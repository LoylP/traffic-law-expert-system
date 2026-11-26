"""LLMClient, FactExtractor and AnswerWriter with a faked LLM (no network)."""

import json

import pytest
import requests

from src.reasoning import llm_client as module
from src.reasoning.answer_writer import AnswerWriter, check_answer
from src.reasoning.engine import InferenceEngine
from src.reasoning.extractor_llm import PROMPT_TOKEN_BUDGET, FactExtractor, sanitize_facts
from src.reasoning.knowledge_base import get_knowledge_base
from src.reasoning.llm_client import LLMClient, LLMConfig, LLMConnectionError, LLMError
from src.reasoning.pipeline import ConsultOptions, ExpertPipeline

SCHEMA = {"type": "object", "properties": {"a": {"type": "integer"}}, "required": ["a"]}
MESSAGES = [{"role": "user", "content": "q"}]


class FakeResponse:
    def __init__(self, body, status=200):
        self.body, self.status_code, self.text = body, status, json.dumps(body)

    def json(self):
        return self.body


def fake_server(monkeypatch, *replies):
    """Each reply is a content string, a FakeResponse or an exception."""
    queue, payloads = list(replies), []

    def post(url, json=None, timeout=None):
        payloads.append({"url": url, **json})
        reply = queue.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply if isinstance(reply, FakeResponse) else FakeResponse({"message": {"content": reply}})

    monkeypatch.setattr(module.requests, "post", post)
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    return payloads


def test_ollama_request_and_think_stripping(monkeypatch):
    payloads = fake_server(monkeypatch, '<think>{"a": 9}</think>{"a": 1}')
    client = LLMClient(LLMConfig(seed=7))
    assert client.chat_json(MESSAGES, SCHEMA) == {"a": 1}
    sent = payloads[0]
    assert sent["url"] == "http://localhost:11434/api/chat"
    assert sent["format"] == SCHEMA and sent["think"] is False and sent["stream"] is False
    assert sent["options"] == {
        "temperature": 0, "top_p": 1, "presence_penalty": 0, "seed": 7, "num_ctx": 8192
    }
    assert client.last_metadata.mode == "constrained"


@pytest.mark.parametrize(
    "first",
    [FakeResponse({"error": "structured output is unavailable"}, 500), "không phải JSON"],
)
def test_prompt_only_fallback_with_one_retry(monkeypatch, first):
    payloads = fake_server(monkeypatch, first, '{"b": 2}', '```json\n{"a": 2}\n```')
    client = LLMClient(LLMConfig())
    assert client.chat_json(MESSAGES, SCHEMA) == {"a": 2}
    assert client.last_metadata.mode == "prompt_only"
    assert "format" not in payloads[1] and "JSON Schema" in payloads[1]["messages"][0]["content"]
    assert "chưa hợp lệ" in payloads[2]["messages"][-1]["content"]


def test_connection_errors_are_retried_twice(monkeypatch):
    payloads = fake_server(monkeypatch, *[requests.ConnectionError("down")] * 3)
    with pytest.raises(LLMConnectionError):
        LLMClient(LLMConfig()).chat_text(MESSAGES)
    assert len(payloads) == 3


def test_other_server_errors_are_not_retried(monkeypatch):
    payloads = fake_server(monkeypatch, FakeResponse({"error": "model not found"}, 404))
    with pytest.raises(LLMError):
        LLMClient(LLMConfig()).chat_json(MESSAGES, SCHEMA)
    assert len(payloads) == 1


def test_cache_avoids_second_call(monkeypatch, tmp_path):
    payloads = fake_server(monkeypatch, '{"a": 3}')
    client = LLMClient(LLMConfig(cache_dir=str(tmp_path)))
    assert client.chat_json(MESSAGES, SCHEMA) == client.chat_json(MESSAGES, SCHEMA)
    assert len(payloads) == 1 and client.last_metadata.cached


# --- extractor ----------------------------------------------------------------


def test_prompt_stays_in_budget():
    assert FactExtractor(LLMClient(LLMConfig())).prompt_tokens < PROMPT_TOKEN_BUDGET


def test_sanitize_drops_unbacked_values():
    message = "Đi xe máy, CSGT thổi còi thì tôi bỏ chạy"
    facts, warnings = sanitize_facts(
        {
            "vehicle_class": "VEH_SPACESHIP",
            "acts": ["ACT_IGNORE_OFFICER", "ACT_MADE_UP", "ACT_HIT_AND_RUN", "ACT_SPEEDING"],
            "bac_breath_mg_l": 0.5,
            "speed_over_kmh": 15,
            "violation_date": "2024-01-01",
            "grounded_violations": ["ND168-D6-K1-Pa"],
            "evidence": {"acts": "tôi bỏ chạy", "officer_signal": "không có trong câu"},
            "officer_signal": True,
        },
        message,
        get_knowledge_base(),
    )
    assert facts.vehicle_class is None
    assert facts.acts == ["ACT_IGNORE_OFFICER"]
    assert facts.bac_breath_mg_l is None and facts.speed_over_kmh is None
    assert facts.violation_date is None and facts.grounded_violations == []
    assert facts.evidence == {"acts": "tôi bỏ chạy"}
    assert warnings


def test_extractor_falls_back_to_regex(monkeypatch):
    fake_server(monkeypatch, *[requests.Timeout("slow")] * 3)
    result = FactExtractor(LLMClient(LLMConfig())).extract("xe máy vượt đèn đỏ")
    assert result.source == "regex" and result.facts.acts == ["ACT_RED_LIGHT"]


# --- answer writer ------------------------------------------------------------


@pytest.fixture(scope="module")
def decided():
    pipeline = ExpertPipeline()
    options = ConsultOptions(use_llm_extractor=False, use_llm_writer=False)
    result = pipeline.consult("Tôi đi xe máy vượt đèn đỏ", options=options)
    hits = InferenceEngine(pipeline.kb).run(result.facts).hits
    return result, pipeline.penalty.decide_hits(hits)


GOOD = (
    "Theo Điều 7 Khoản 7 Điểm c NĐ 168/2024, mức phạt đề xuất là 5.000.000 đồng "
    "(khung 4 đến 6 triệu đồng), trừ 4 điểm giấy phép lái xe."
)


def test_writer_accepts_faithful_text(decided):
    result, penalty = decided
    assert check_answer(GOOD, AnswerWriter.payload(result, penalty)) == []


@pytest.mark.parametrize(
    "bad",
    [
        "Bạn bị phạt 8.000.000 đồng.",
        "Bạn bị phạt 8 triệu đồng.",
        "Bạn bị phạt tám triệu đồng.",
        "Bạn bị phạt 5000001 đồng.",
        "Căn cứ Điều 99, phạt 5.000.000 đồng.",
        "Bạn bị trừ 10 điểm giấy phép lái xe.",
        "Bạn bị tước bằng 22 tháng.",
        "Bạn bị phạt cảnh cáo và 5.000.000 đồng.",
        "Phương tiện sẽ bị tịch thu.",
        "từ " * 160,
    ],
)
def test_writer_rejects_invented_content(decided, bad):
    result, penalty = decided
    assert check_answer(bad, AnswerWriter.payload(result, penalty))


def test_writer_falls_back_to_template(monkeypatch, decided):
    result, penalty = decided
    writer = AnswerWriter(LLMClient(LLMConfig()))
    fake_server(monkeypatch, "Phạt 9.999.000 đồng theo Điều 99.", GOOD)
    text, source = writer.write(result, penalty)
    assert source == "template" and "9.999.000" not in text and "5.000.000" in text
    text, source = writer.write(result, penalty, remarks=["Ghi chú X"])
    assert source == "llm" and text.startswith(GOOD) and "Ghi chú X" in text
