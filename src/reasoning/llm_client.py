"""Single entry point for every LLM call in the project (DESIGN §12).

Providers: ``ollama`` (default, native /api/chat), ``openai_compatible``
(LM Studio...) and ``gemini`` (optional). Configuration comes from ``.env``.
The LLM only reads and writes language: it never decides violations or fines.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

import requests
from dotenv import load_dotenv
from pydantic import BaseModel

logger = logging.getLogger(__name__)

PROVIDERS = ("ollama", "openai_compatible", "gemini")
DEFAULT_BASE_URL = "http://localhost:11434/v1"
DEFAULT_MODEL = "qwen3.5:4b-q4_K_M"
NUM_CTX = 8192
CONNECTION_RETRIES = 2

MODE_CONSTRAINED = "constrained"
MODE_PROMPT_ONLY = "prompt_only"
MODE_TEXT = "text"

Message = dict[str, str]

_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.S | re.I)
_SCHEMA_UNSUPPORTED = re.compile(
    r"structured output|response_format|json_schema|failed to parse grammar|"
    r"invalid (json )?schema|invalid format",
    re.I,
)


class LLMError(RuntimeError):
    """The LLM could not produce a usable answer."""


class LLMConnectionError(LLMError):
    """Server unreachable or too slow (retried)."""


class LLMSchemaUnsupported(LLMError):
    """The server refuses the structured-output request."""


class LLMOutputError(LLMError):
    """The output is not the requested JSON."""


@dataclass(frozen=True)
class LLMConfig:
    provider: str = "ollama"
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    seed: int = 42
    disable_thinking: bool = True
    timeout: float = 120.0
    cache_dir: str | None = None
    api_key: str | None = None  # gemini only

    @classmethod
    def from_env(cls) -> "LLMConfig":
        load_dotenv()

        def env(name: str, default: str) -> str:
            return (os.getenv(name) or "").strip() or default

        return cls(
            provider=env("LLM_PROVIDER", "ollama").lower(),
            base_url=env("LLM_BASE_URL", DEFAULT_BASE_URL),
            model=env("LLM_MODEL", DEFAULT_MODEL),
            seed=int(env("LLM_SEED", "42")),
            disable_thinking=env("LLM_DISABLE_THINKING", "true").lower()
            in ("1", "true", "yes", "on"),
            timeout=float(env("LLM_TIMEOUT", "120")),
            cache_dir=env("LLM_CACHE_DIR", "") or None,
            api_key=env("GOOGLE_API_KEY", "") or None,
        )


@dataclass
class CallMetadata:
    provider: str
    model: str
    mode: str  # constrained | prompt_only | text
    cached: bool = False
    attempts: int = 1
    latency_ms: float = 0.0
    prompt_tokens: int | None = None
    output_tokens: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def strip_think(text: str) -> str:
    """Remove <think> blocks, including an unopened or unclosed one."""
    text = _THINK_BLOCK.sub("", text)
    if "</think>" in text:
        text = text.rsplit("</think>", 1)[1]
    return text.split("<think>", 1)[0].strip()


def parse_json_object(text: str) -> dict[str, Any]:
    """Parse the first JSON object in the text (tolerates code fences)."""
    start = text.find("{")
    if start < 0:
        raise LLMOutputError("Không tìm thấy đối tượng JSON trong câu trả lời.")
    try:
        data, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError as error:
        raise LLMOutputError(f"JSON không hợp lệ: {error}") from error
    if not isinstance(data, dict):
        raise LLMOutputError("Câu trả lời không phải đối tượng JSON.")
    return data


def _check_shape(data: dict[str, Any], schema: dict[str, Any]) -> None:
    """Minimal check for raw dict schemas: required keys and no foreign object."""
    missing = [key for key in schema.get("required", []) if key not in data]
    if missing:
        raise LLMOutputError(f"Thiếu trường bắt buộc: {', '.join(missing)}")
    properties = schema.get("properties")
    if properties and data and not set(data) & set(properties):
        raise LLMOutputError("JSON không có trường nào đúng theo schema.")


class LLMClient:
    def __init__(self, config: LLMConfig | None = None):
        self.config = config or LLMConfig.from_env()
        if self.config.provider not in PROVIDERS:
            raise ValueError(f"LLM_PROVIDER must be one of {PROVIDERS}")
        self._local = threading.local()
        # Set once the server refuses structured output, to skip useless calls.
        self._schema_unsupported = False

    @property
    def last_metadata(self) -> CallMetadata | None:
        """Metadata of the latest call made by the current thread."""
        return getattr(self._local, "metadata", None)

    # -- public API -----------------------------------------------------
    def chat_json(
        self,
        messages: list[Message],
        json_schema: dict[str, Any] | type[BaseModel],
        temperature: float = 0,
        validator: Callable[[dict[str, Any]], Any] | None = None,
    ) -> dict[str, Any]:
        """Return a JSON object following `json_schema`.

        Constrained decoding first; if the server refuses or ignores the schema,
        fall back to prompt-only JSON with one retry that quotes the error.
        `validator` raises ValueError to reject an output.
        """
        if isinstance(json_schema, type) and issubclass(json_schema, BaseModel):
            model_class, schema = json_schema, json_schema.model_json_schema()
            validator = validator or model_class.model_validate
        else:
            schema = json_schema

        def check(text: str) -> dict[str, Any]:
            data = parse_json_object(text)
            _check_shape(data, schema)
            if validator is not None:
                try:
                    validator(data)
                except ValueError as error:  # includes pydantic.ValidationError
                    raise LLMOutputError(str(error)) from error
            return data

        key = self._cache_key(messages, schema, temperature)
        cached = self._cache_read(key)
        if cached is not None:
            self._record(cached["mode"], cached=True)
            return cached["value"]

        started = time.perf_counter()
        attempts = 0
        if not self._schema_unsupported:
            attempts += 1
            try:
                text, usage = self._complete(messages, schema, temperature)
                data = check(text)
                self._record(MODE_CONSTRAINED, started=started, attempts=attempts, **usage)
                self._cache_write(key, MODE_CONSTRAINED, data)
                return data
            except LLMSchemaUnsupported as error:
                self._schema_unsupported = True
                logger.warning("Structured output unavailable, using prompt-only JSON: %s", error)
            except LLMOutputError as error:
                logger.warning("Schema ignored by the model, using prompt-only JSON: %s", error)

        conversation = self._with_schema_instruction(messages, schema)
        last_error: LLMOutputError | None = None
        for _ in range(2):  # first try + 1 retry with the validation error
            attempts += 1
            text, usage = self._complete(conversation, None, temperature)
            try:
                data = check(text)
                self._record(MODE_PROMPT_ONLY, started=started, attempts=attempts, **usage)
                self._cache_write(key, MODE_PROMPT_ONLY, data)
                return data
            except LLMOutputError as error:
                last_error = error
                conversation = conversation + [
                    {"role": "assistant", "content": text},
                    {
                        "role": "user",
                        "content": f"JSON chưa hợp lệ: {str(error)[:500]}\n"
                        "Hãy trả lại DUY NHẤT một đối tượng JSON đúng schema.",
                    },
                ]
        self._record(MODE_PROMPT_ONLY, started=started, attempts=attempts)
        raise LLMOutputError(f"Model không trả về JSON hợp lệ: {last_error}")

    def chat_text(self, messages: list[Message], temperature: float = 0) -> str:
        key = self._cache_key(messages, None, temperature)
        cached = self._cache_read(key)
        if cached is not None:
            self._record(MODE_TEXT, cached=True)
            return cached["value"]
        started = time.perf_counter()
        text, usage = self._complete(messages, None, temperature)
        self._record(MODE_TEXT, started=started, **usage)
        self._cache_write(key, MODE_TEXT, text)
        return text

    # -- transport ------------------------------------------------------
    def _complete(
        self, messages: list[Message], schema: dict[str, Any] | None, temperature: float
    ) -> tuple[str, dict[str, Any]]:
        backend = {
            "ollama": self._ollama,
            "openai_compatible": self._openai_compatible,
            "gemini": self._gemini,
        }[self.config.provider]
        for attempt in range(CONNECTION_RETRIES + 1):
            try:
                text, usage = backend(messages, schema, temperature)
                break
            except LLMConnectionError as error:
                if attempt == CONNECTION_RETRIES:
                    raise
                logger.warning("LLM connection error (retry %d): %s", attempt + 1, error)
                time.sleep(attempt + 1)
        if self.config.disable_thinking:
            text = strip_think(text)
        return text.strip(), usage

    def ollama_url(self) -> str:
        base = self.config.base_url.rstrip("/")
        return base.removesuffix("/v1").rstrip("/") + "/api/chat"

    def ollama_payload(
        self, messages: list[Message], schema: dict[str, Any] | None, temperature: float
    ) -> dict[str, Any]:
        # Explicit options override model defaults (Qwen3.5 ships temperature 1
        # and presence_penalty 1.5).
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "top_p": 1,
                "presence_penalty": 0,
                "seed": self.config.seed,
                "num_ctx": NUM_CTX,
            },
        }
        if schema is not None:
            payload["format"] = schema
        if self.config.disable_thinking:
            payload["think"] = False
        return payload

    def _ollama(
        self, messages: list[Message], schema: dict[str, Any] | None, temperature: float
    ) -> tuple[str, dict[str, Any]]:
        try:
            response = requests.post(
                self.ollama_url(),
                json=self.ollama_payload(messages, schema, temperature),
                timeout=self.config.timeout,
            )
        except (requests.ConnectionError, requests.Timeout) as error:
            raise LLMConnectionError(str(error)) from error
        try:
            body = response.json()
        except ValueError:
            body = {"error": response.text[:300]}
        if response.status_code >= 400 or body.get("error"):
            message = str(body.get("error") or response.status_code)
            if schema is not None and _SCHEMA_UNSUPPORTED.search(message):
                raise LLMSchemaUnsupported(message)
            raise LLMError(f"Ollama: {message}")
        usage = {
            "prompt_tokens": body.get("prompt_eval_count"),
            "output_tokens": body.get("eval_count"),
        }
        return body.get("message", {}).get("content", ""), usage

    def _openai_compatible(
        self, messages: list[Message], schema: dict[str, Any] | None, temperature: float
    ) -> tuple[str, dict[str, Any]]:
        import openai

        client = openai.OpenAI(
            base_url=self.config.base_url,
            api_key="local",
            timeout=self.config.timeout,
            max_retries=0,
        )
        formats: list[dict[str, Any] | None] = [None]
        if schema is not None:
            formats = [
                {"type": "json_schema", "json_schema": {"name": "output", "schema": schema}},
                {"type": "json_object"},
            ]
        for index, response_format in enumerate(formats):
            kwargs: dict[str, Any] = {
                "model": self.config.model,
                "messages": messages,
                "temperature": temperature,
                "seed": self.config.seed,
            }
            if response_format is not None:
                kwargs["response_format"] = response_format
            try:
                response = client.chat.completions.create(**kwargs)
            except (openai.APIConnectionError, openai.APITimeoutError) as error:
                raise LLMConnectionError(str(error)) from error
            except openai.APIError as error:
                if schema is not None and _SCHEMA_UNSUPPORTED.search(str(error)):
                    if index + 1 < len(formats):
                        continue
                    raise LLMSchemaUnsupported(str(error)) from error
                raise LLMError(f"OpenAI-compatible server: {error}") from error
            usage = getattr(response, "usage", None)
            return response.choices[0].message.content or "", {
                "prompt_tokens": getattr(usage, "prompt_tokens", None),
                "output_tokens": getattr(usage, "completion_tokens", None),
            }
        raise LLMError("unreachable")

    def _gemini(
        self, messages: list[Message], schema: dict[str, Any] | None, temperature: float
    ) -> tuple[str, dict[str, Any]]:
        if not self.config.api_key:
            raise LLMError("Vui lòng cấu hình GOOGLE_API_KEY trong file .env")
        import google.generativeai as genai
        from google.api_core import exceptions as google_errors

        genai.configure(api_key=self.config.api_key)
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        contents = [
            {"role": "model" if m["role"] == "assistant" else "user", "parts": [m["content"]]}
            for m in messages
            if m["role"] != "system"
        ]
        generation: dict[str, Any] = {"temperature": temperature}
        if schema is not None:
            generation["response_mime_type"] = "application/json"
            # Gemini accepts only a subset of JSON Schema, so send it as text.
            system = f"{system}\n\n{self._schema_text(schema)}".strip()
        model = genai.GenerativeModel(self.config.model, system_instruction=system or None)
        try:
            response = model.generate_content(
                contents,
                generation_config=generation,
                request_options={"timeout": self.config.timeout},
            )
            return response.text, {}
        except (google_errors.ServiceUnavailable, google_errors.DeadlineExceeded) as error:
            raise LLMConnectionError(str(error)) from error
        except Exception as error:  # SDK raises many unrelated types
            raise LLMError(f"Gemini: {error}") from error

    # -- helpers --------------------------------------------------------
    @staticmethod
    def _schema_text(schema: dict[str, Any]) -> str:
        return (
            "Chỉ trả về DUY NHẤT một đối tượng JSON, không markdown, không giải thích, "
            "đúng JSON Schema sau:\n"
            + json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
        )

    def _with_schema_instruction(
        self, messages: list[Message], schema: dict[str, Any]
    ) -> list[Message]:
        instruction = self._schema_text(schema)
        if messages and messages[0]["role"] == "system":
            first = {"role": "system", "content": f"{messages[0]['content']}\n\n{instruction}"}
            return [first, *messages[1:]]
        return [{"role": "system", "content": instruction}, *messages]

    def _record(
        self,
        mode: str,
        *,
        started: float | None = None,
        cached: bool = False,
        attempts: int = 1,
        prompt_tokens: int | None = None,
        output_tokens: int | None = None,
    ) -> None:
        metadata = CallMetadata(
            provider=self.config.provider,
            model=self.config.model,
            mode=mode,
            cached=cached,
            attempts=attempts,
            latency_ms=0.0 if started is None else (time.perf_counter() - started) * 1000,
            prompt_tokens=prompt_tokens,
            output_tokens=output_tokens,
        )
        self._local.metadata = metadata
        logger.info("LLM call: %s", metadata.as_dict())

    # -- cache ----------------------------------------------------------
    def _cache_key(
        self, messages: list[Message], schema: dict[str, Any] | None, temperature: float
    ) -> str:
        # Schema, seed and temperature change the output, so they are part of the key.
        material = [self.config.provider, self.config.model, messages, schema, temperature, self.config.seed]
        blob = json.dumps(material, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def _cache_read(self, key: str) -> dict[str, Any] | None:
        if not self.config.cache_dir:
            return None
        path = Path(self.config.cache_dir) / f"{key}.json"
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _cache_write(self, key: str, mode: str, value: Any) -> None:
        if not self.config.cache_dir:
            return
        directory = Path(self.config.cache_dir)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{key}.json").write_text(
            json.dumps({"mode": mode, "value": value}, ensure_ascii=False), encoding="utf-8"
        )
