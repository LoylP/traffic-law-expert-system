"""LLM FactExtractor (DESIGN §6, problem 2). Extracts facts only: it never
chooses a legal article or a fine."""

from __future__ import annotations

import copy
import json
import logging
import re
from typing import Any

from src.extract.vehicle_mapping import match_user_vehicles
from src.reasoning.extractor_regex import (
    _OFFICER,
    _OFFICER_SIGNAL,
    _RESISTANCE_PATTERNS,
    _ROAD_PATTERNS,
    _TIME_PATTERNS,
    DRANK_PATTERN,
    NUMBER,
    RegexExtractor,
    normalize,
    parse_date,
    to_number,
)
from src.reasoning.knowledge_base import KnowledgeBase, get_knowledge_base
from src.reasoning.llm_client import LLMClient, LLMError
from src.reasoning.schema import ExtractionResult, Facts

logger = logging.getLogger(__name__)

SYNONYMS_PER_ID = 3
PROMPT_TOKEN_BUDGET = 6000
# Filled by other pipeline steps (grounder, follow-up answers), never by the extractor.
EXCLUDED_FIELDS = ("grounded_violations", "speed_band", "alcohol_level", "unknown_slots")
# Hit-and-run needs an accident; small models confuse it with fleeing a police stop.
# "phóng nhanh", "chạy nhanh" do not state that a speed limit was exceeded.
_SPEED_WORDS = re.compile(r"tốc độ(?!\s+cao)|km|cây số|vượt mức")
# Aggravating facts about the past: accepted only with the wording of circumstances.yaml.
_HISTORY_CIRCUMSTANCES = ("CIR_REPEAT", "CIR_MULTIPLE_TIMES")
_ACCIDENT_WORDS = re.compile(r"tai nạn|tông|đâm|va chạm|va quẹt|quẹt (?:vào|trúng|phải)")
# ...and the message must say the driver left or did not stop to help.
_LEFT_SCENE_WORDS = re.compile(
    r"bỏ (?:chạy|trốn|đi|mặc)|(?:chạy|đi) (?:trốn|mất|luôn)|trốn|rời (?:khỏi )?hiện trường|"
    r"không (?:chịu )?(?:dừng|giúp|cứu|giữ(?: nguyên)? hiện trường)"
)
# Numbers decide the fine bracket, so they must be written in the message.
NUMERIC_FIELDS = (
    "speed_limit_kmh",
    "actual_speed_kmh",
    "speed_over_kmh",
    "bac_blood_mg_100ml",
    "bac_breath_mg_l",
)

INSTRUCTIONS = """Bạn là bộ trích xuất dữ kiện cho hệ chuyên gia luật giao thông Việt Nam.
Đọc mô tả của người dùng và trả về DUY NHẤT một đối tượng JSON.

Quy tắc:
1. Chỉ dùng ID có trong các danh mục bên dưới. Không tự tạo ID.
2. Chỉ ghi dữ kiện được NÊU RÕ trong câu. KHÔNG đoán theo thói quen nói, KHÔNG điền giá trị \
"thường gặp". Trường không được nêu rõ thì để null. Cụm chung chung -> null: "chạy xe", "đi xe", \
"lái xe", "về bằng xe" (không biết loại xe); "chạy nhanh", "phóng nhanh" (chưa nói quá tốc độ); \
"ngoài đường" (không biết loại đường); "có uống chút" (chỉ drank_alcohol=true, không có số đo); \
"bị bắt mấy lần rồi", "trước đây bị phạt rồi" (không phải tái phạm: CIR_REPEAT chỉ khi nói rõ \
tái phạm hoặc đã bị xử phạt về chính lỗi này). KHÔNG suy loại xe từ hành vi (mũ bảo hiểm, \
dây an toàn...): hệ chuyên gia tự suy luận.
3. Chỉ chọn ID hành vi khi ĐÚNG hành vi đó. Hành vi vi phạm không khớp ID nào trong danh mục \
(vd: dừng đỗ sai chỗ, không bật đèn, không gương chiếu hậu): KHÔNG chọn ID gần giống, mà chép cụm \
mô tả vào free_behaviors. Đã có trong acts thì không ghi lại vào free_behaviors.
ACT_HIT_AND_RUN chỉ dùng khi có tai nạn; bỏ chạy khi bị ra hiệu dừng xe là ACT_IGNORE_OFFICER.
4. evidence: với mỗi trường đã điền, chép NGUYÊN VĂN đoạn trong câu của người dùng.
5. KHÔNG tự tính speed_over_kmh. Chỉ điền speed_over_kmh khi người dùng nói thẳng số km/h vượt. \
Nếu họ nói tốc độ đang chạy và tốc độ giới hạn thì điền actual_speed_kmh và speed_limit_kmh.
6. Nồng độ cồn: "mg/l" hoặc "khí thở" -> bac_breath_mg_l; "mg/100ml" hoặc "máu" -> bac_blood_mg_100ml. \
Không có số đo thì để null.
7. passengers_count = số người được chở, KHÔNG tính người lái ("kẹp ba" -> 2).
8. officer_signal = true khi người thi hành công vụ ra hiệu lệnh dừng xe hoặc ra hiệu lệnh.
9. circumstances: chỉ khi người dùng nói rõ tình tiết đó về chính người vi phạm.
10. violation_date: chỉ khi người dùng nêu ngày cụ thể (định dạng YYYY-MM-DD).
11. KHÔNG nêu điều luật, KHÔNG nêu mức phạt, KHÔNG tư vấn."""

FEW_SHOT: tuple[tuple[str, dict[str, Any]], ...] = (
    # Contrast pairs: vague wording -> null, explicit wording -> value.
    (
        "Nhậu xong chạy xe về, ngoài đường phóng nhanh, trước giờ bị bắt mấy lần rồi.",
        {"drank_alcohol": True, "evidence": {"drank_alcohol": "Nhậu xong"}},
    ),
    (
        "Lái ô tô trên cao tốc, thổi được 0,3 mg/l khí thở.",
        {
            "vehicle_class": "VEH_CAR",
            "acts": ["ACT_ALCOHOL"],
            "bac_breath_mg_l": 0.3,
            "road_type": "ROAD_EXPRESSWAY",
            "evidence": {
                "vehicle_class": "ô tô",
                "acts": "thổi được 0,3 mg/l",
                "bac_breath_mg_l": "0,3 mg/l",
                "road_type": "cao tốc",
            },
        },
    ),
    (
        "Đi xe không thắt dây an toàn, trước đây bị phạt rồi.",
        {"acts": ["ACT_NO_SEATBELT"], "evidence": {"acts": "không thắt dây an toàn"}},
    ),
    (
        "Tôi đi xe máy vượt đèn đỏ thì sao?",
        {
            "vehicle_class": "VEH_MOTORBIKE",
            "acts": ["ACT_RED_LIGHT"],
            "free_behaviors": [],
            "evidence": {"vehicle_class": "xe máy", "acts": "vượt đèn đỏ"},
        },
    ),
    (
        "Lái ô tô, thấy CSGT vẫy gậy yêu cầu dừng xe nhưng tôi đạp ga chạy luôn.",
        {
            "vehicle_class": "VEH_CAR",
            "acts": ["ACT_IGNORE_OFFICER"],
            "free_behaviors": [],
            "officer_signal": True,
            "resistance": ["RES_FLEE"],
            "evidence": {
                "vehicle_class": "ô tô",
                "acts": "đạp ga chạy luôn",
                "officer_signal": "CSGT vẫy gậy yêu cầu dừng xe",
                "resistance": "đạp ga chạy luôn",
            },
        },
    ),
    (
        "Tối qua nhậu xong tôi chạy xe gắn máy 72 km/h ở đoạn giới hạn 50, kẹp ba, "
        "đầu không đội nón, còn vừa chạy vừa tháo biển số.",
        {
            "vehicle_class": "VEH_MOTORBIKE",
            "acts": ["ACT_SPEEDING", "ACT_OVERLOAD_PASSENGER", "ACT_NO_HELMET"],
            "free_behaviors": ["vừa chạy vừa tháo biển số"],
            "actual_speed_kmh": 72,
            "speed_limit_kmh": 50,
            "drank_alcohol": True,
            "time_context": "TIME_NIGHT",
            "passengers_count": 2,
            "no_helmet_who": "driver",
            "evidence": {
                "acts": "72 km/h; kẹp ba; đầu không đội nón",
                "drank_alcohol": "nhậu xong",
                "actual_speed_kmh": "72 km/h",
                "speed_limit_kmh": "giới hạn 50",
                "passengers_count": "kẹp ba",
                "no_helmet_who": "đầu không đội nón",
                "time_context": "Tối qua",
            },
        },
    ),
    (
        "Công ty tôi cho xe tải chạy quá tốc độ 15 km/h gây tai nạn, đây là lần tái phạm "
        "nhưng đã tự nguyện bồi thường thiệt hại.",
        {
            "vehicle_class": "VEH_CAR",
            "acts": ["ACT_SPEEDING"],
            "free_behaviors": [],
            "speed_over_kmh": 15,
            "consequence": ["CONS_ACCIDENT"],
            "subject": "SUBJ_ORGANIZATION",
            "circumstances": ["CIR_REPEAT", "CIR_PREVENT_HARM"],
            "evidence": {
                "vehicle_class": "xe tải",
                "acts": "chạy quá tốc độ 15 km/h",
                "speed_over_kmh": "quá tốc độ 15 km/h",
                "consequence": "gây tai nạn",
                "subject": "Công ty tôi",
                "circumstances": "lần tái phạm; tự nguyện bồi thường thiệt hại",
            },
        },
    ),
)


def estimate_tokens(text: str) -> int:
    """Rough token count for Vietnamese text (about 3 characters per token)."""
    return len(text) // 3 + 1


def allowed_ids(kb: KnowledgeBase) -> dict[str, dict[str, str]]:
    """Facts field -> {valid ID: label}, taken from the knowledge base."""

    def from_ontology(key: str) -> dict[str, str]:
        return {item["id"]: item["label"] for item in kb.ontology[key]}

    return {
        "vehicle_class": from_ontology("vehicle_classes"),
        "road_type": from_ontology("road_types"),
        "time_context": from_ontology("time_contexts"),
        "resistance": from_ontology("resistance_behaviors"),
        "consequence": from_ontology("consequences"),
        "subject": from_ontology("subjects"),
        "acts": {item_id: item["label"] for item_id, item in kb.acts.items()},
        "circumstances": {item_id: item["label"] for item_id, item in kb.circumstances.items()},
    }


def build_schema(kb: KnowledgeBase) -> dict[str, Any]:
    """JSON schema derived from `Facts`, with enums restricted to known IDs."""
    schema = copy.deepcopy(Facts.model_json_schema())
    properties = {
        name: spec for name, spec in schema["properties"].items() if name not in EXCLUDED_FIELDS
    }
    for spec in properties.values():
        spec.pop("title", None)
        spec.pop("default", None)
        for branch in spec.get("anyOf", []):
            branch.pop("format", None)  # grammar converters reject some formats
    for name, ids in allowed_ids(kb).items():
        spec = properties[name]
        if spec.get("type") == "array":
            spec["items"] = {"type": "string", "enum": list(ids)}
        elif "anyOf" in spec:
            spec["anyOf"] = [{"type": "string", "enum": list(ids)}, {"type": "null"}]
        else:
            spec["enum"] = list(ids)
    properties["subject"] = {"type": "string", "enum": list(allowed_ids(kb)["subject"])}
    properties["evidence"] = {
        "type": "object",
        "properties": {n: {"type": "string"} for n in properties if n != "evidence"},
        "additionalProperties": False,
    }
    for name, spec in properties.items():
        if {"type": "null"} not in spec.get("anyOf", []):
            properties[name] = {"anyOf": [spec, {"type": "null"}]}
    return {
        "type": "object",
        "properties": properties,
        # All required (null allowed): small models skip optional properties.
        "required": list(properties),
        "additionalProperties": False,
    }


def build_system_prompt(kb: KnowledgeBase) -> str:
    ids = allowed_ids(kb)
    sources = {**kb.acts, **kb.circumstances}
    titles = {
        "vehicle_class": "vehicle_class (chỉ khi câu nêu rõ loại xe: \"xe máy\" là VEH_MOTORBIKE; "
        "ô tô, xe tải, xe khách là VEH_CAR; chỉ nói \"xe\" thì null)",
        "acts": "acts (hành vi)",
        "circumstances": "circumstances (tình tiết)",
        "road_type": "road_type",
        "time_context": "time_context",
        "resistance": "resistance (phản ứng với người thi hành công vụ)",
        "consequence": "consequence",
        "subject": "subject",
    }
    blocks = [INSTRUCTIONS]
    for field, title in titles.items():
        lines = [f"## {title}"]
        for item_id, label in ids[field].items():
            synonyms = (sources.get(item_id) or {}).get("synonyms") or []
            hint = f" (vd: {'; '.join(synonyms[:SYNONYMS_PER_ID])})" if synonyms else ""
            lines.append(f"- {item_id}: {label}{hint}")
        blocks.append("\n".join(lines))
    blocks.append("## no_helmet_who: driver | passenger | both")
    return "\n\n".join(blocks)


def full_answer(partial: dict[str, Any]) -> dict[str, Any]:
    """Few-shot answers list every field, matching the constrained output."""
    empty = Facts().model_dump(mode="json", exclude=set(EXCLUDED_FIELDS))
    return {name: partial.get(name, default) for name, default in empty.items()}


def clean_raw(data: dict[str, Any]) -> dict[str, Any]:
    """Drop placeholders so Pydantic defaults apply."""
    return {
        key: value
        for key, value in data.items()
        if key not in EXCLUDED_FIELDS and value not in (None, "", "null", "None")
    }


def sanitize_facts(
    data: dict[str, Any], message: str, kb: KnowledgeBase
) -> tuple[Facts, list[str]]:
    """Validate LLM output and remove what the message or ontology cannot back."""
    data = clean_raw(data)
    warnings: list[str] = []

    for field, ids in allowed_ids(kb).items():
        value = data.get(field)
        if isinstance(value, list):
            unknown = [v for v in value if v not in ids]
            data[field] = list(dict.fromkeys(v for v in value if v in ids))
        elif value is not None and value not in ids:
            unknown = [data.pop(field)]
        else:
            continue
        if unknown:
            warnings.append(f"{field}: bỏ ID không hợp lệ {unknown}")

    facts = Facts.model_validate(data)
    updates: dict[str, Any] = {}
    text = normalize(message)

    written = {to_number(n) for n in re.findall(NUMBER, text)}
    for field in NUMERIC_FIELDS:
        value = getattr(facts, field)
        if value is not None and value not in written:
            updates[field] = None
            warnings.append(f"{field}={value}: bỏ vì con số này không có trong câu")
    has_pair = all(
        updates.get(f, getattr(facts, f)) is not None
        for f in ("actual_speed_kmh", "speed_limit_kmh")
    )
    if has_pair and facts.speed_over_kmh is not None:
        updates["speed_over_kmh"] = None  # the derive rule computes it

    stated = parse_date(text)
    if stated:
        updates["violation_date"] = stated
    elif facts.violation_date and str(facts.violation_date.year) not in text:
        updates["violation_date"] = None
        warnings.append("violation_date: bỏ vì câu không nêu ngày cụ thể")

    evidence = {}
    for field, span in facts.evidence.items():
        value = updates.get(field, getattr(facts, field, None))
        if value in (None, []):
            continue
        parts = [p.strip() for p in span.split(";") if p.strip()]
        if parts and all(normalize(p) in text for p in parts):
            evidence[field] = span
        elif parts:
            warnings.append(f"evidence.{field}: bỏ vì không phải nguyên văn")
    updates["evidence"] = evidence
    updates["free_behaviors"] = list(dict.fromkeys(b.strip() for b in facts.free_behaviors if b.strip()))

    _drop_unstated(facts, updates, evidence, message, text, kb, warnings)

    acts = list(facts.acts)
    has_speed = any(updates.get(f, getattr(facts, f)) is not None for f in NUMERIC_FIELDS[:3])
    if "ACT_SPEEDING" in acts and not has_speed and not _SPEED_WORDS.search(text):
        acts.remove("ACT_SPEEDING")
        warnings.append("ACT_SPEEDING: bỏ vì câu không nói đến tốc độ")
    if "ACT_HIT_AND_RUN" in acts and not _ACCIDENT_WORDS.search(text):
        acts.remove("ACT_HIT_AND_RUN")
        warnings.append("ACT_HIT_AND_RUN: bỏ vì câu không nói đến tai nạn")
    elif "ACT_HIT_AND_RUN" in acts and not _LEFT_SCENE_WORDS.search(text):
        acts.remove("ACT_HIT_AND_RUN")
        warnings.append("ACT_HIT_AND_RUN: bỏ vì câu không nói người lái bỏ đi hoặc không dừng lại")
    # Refusing the test is not a measured level. Everything else that follows from
    # a fact (drank -> alcohol act, refusal <-> act) is left to the derive rules.
    refused = facts.alcohol_test_refused is True or "ACT_REFUSE_ALCOHOL_TEST" in acts
    measured = any(
        (updates.get(f, getattr(facts, f)) or 0) > 0
        for f in ("bac_blood_mg_100ml", "bac_breath_mg_l")
    )
    if refused and not measured and "ACT_ALCOHOL" in acts:
        acts.remove("ACT_ALCOHOL")
    updates["acts"] = acts

    return facts.model_copy(update=updates), warnings


def _drop_unstated(
    facts: Facts,
    updates: dict[str, Any],
    evidence: dict[str, str],
    message: str,
    text: str,
    kb: KnowledgeBase,
    warnings: list[str],
) -> None:
    """Deterministic guard for "never fill what was not said": small models guess
    even when told not to. A value survives only if the message backs it."""

    def drop(field: str, value: Any, empty: Any = None) -> None:
        updates[field] = empty
        evidence.pop(field, None)
        warnings.append(f"{field}={value}: bỏ vì câu không nêu rõ")

    # vehicle: only a class the message names (vehicle_mapping.py)
    named = list(dict.fromkeys(c for c, _ in match_user_vehicles(text)))
    if facts.vehicle_class and facts.vehicle_class not in named:
        # A wrong class is replaced only when the message names exactly one.
        drop("vehicle_class", facts.vehicle_class, named[0] if len(named) == 1 else None)

    for field, patterns in (("road_type", _ROAD_PATTERNS), ("time_context", _TIME_PATTERNS)):
        value = getattr(facts, field)
        if value and not any(v == value and re.search(p, text) for v, p in patterns):
            drop(field, value)

    if facts.consequence and not _ACCIDENT_WORDS.search(text):
        drop("consequence", facts.consequence, [])

    # evidence (already checked to be verbatim) or a known wording
    if facts.officer_signal and not (
        re.search(_OFFICER_SIGNAL, text)
        or re.search(_OFFICER, normalize(evidence.get("officer_signal", "")))
    ):
        drop("officer_signal", True)
    if facts.resistance and "resistance" not in evidence:
        kept = [r for r in facts.resistance if re.search(_RESISTANCE_PATTERNS[r], text)]
        if kept != facts.resistance:
            drop("resistance", facts.resistance, kept)
    if facts.drank_alcohol and "drank_alcohol" not in evidence and not re.search(DRANK_PATTERN, text):
        drop("drank_alcohol", True)
    for field in ("passenger_exception", "passenger_helmet_exception"):
        if getattr(facts, field) and field not in evidence:
            drop(field, True)

    history = [c for c in facts.circumstances if c in _HISTORY_CIRCUMSTANCES]
    if history:
        stated = set(RegexExtractor(kb).extract(message).facts.circumstances)
        kept = [c for c in facts.circumstances if c not in history or c in stated]
        if kept != facts.circumstances:
            drop("circumstances", sorted(set(facts.circumstances) - set(kept)), kept)


class FactExtractor:
    name = "llm"

    def __init__(
        self,
        client: LLMClient | None = None,
        kb: KnowledgeBase | None = None,
        fallback: RegexExtractor | None = None,
    ):
        self.kb = kb or get_knowledge_base()
        self.client = client or LLMClient()
        self.fallback = fallback or RegexExtractor(self.kb)
        self.schema = build_schema(self.kb)
        self.system_prompt = build_system_prompt(self.kb)
        self.prompt_tokens = estimate_tokens(
            json.dumps(self.messages(""), ensure_ascii=False)
        )
        message = f"FactExtractor prompt: ~{self.prompt_tokens} token (ước lượng)"
        print(message)
        if self.prompt_tokens > PROMPT_TOKEN_BUDGET:
            logger.warning("%s vượt ngân sách %d token", message, PROMPT_TOKEN_BUDGET)

    def messages(self, user_message: str) -> list[dict[str, str]]:
        messages = [{"role": "system", "content": self.system_prompt}]
        for question, answer in FEW_SHOT:
            messages.append({"role": "user", "content": question})
            messages.append(
                {"role": "assistant", "content": json.dumps(full_answer(answer), ensure_ascii=False)}
            )
        messages.append({"role": "user", "content": user_message})
        return messages

    def extract(self, message: str) -> ExtractionResult:
        try:
            data = self.client.chat_json(
                self.messages(message),
                self.schema,
                temperature=0,
                validator=lambda raw: Facts.model_validate(clean_raw(raw)),
            )
            facts, warnings = sanitize_facts(data, message, self.kb)
        except (LLMError, ValueError) as error:
            logger.warning("LLM extraction failed, using RegexExtractor: %s", error)
            result = self.fallback.extract(message)
            result.warnings.append(f"LLM lỗi, dùng RegexExtractor: {str(error)[:200]}")
            return result
        for warning in warnings:
            logger.warning("FactExtractor: %s", warning)
        metadata = self.client.last_metadata
        return ExtractionResult(
            facts=facts,
            source=self.name,
            warnings=warnings,
            llm=metadata.as_dict() if metadata else None,
        )
