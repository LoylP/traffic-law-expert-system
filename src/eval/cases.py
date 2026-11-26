"""Test-case format (DESIGN §11): I/O, validation, and conclusions computed by
the engine from hand-written facts. No metric lives here (see run_eval.py) and
nothing here runs the extractor, the grounder or an LLM.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from src.reasoning.engine import InferenceEngine
from src.reasoning.knowledge_base import ROOT, KnowledgeBase
from src.reasoning.penalty import PenaltyDecider
from src.reasoning.pipeline import MAX_QUESTION_ROUNDS
from src.reasoning.schema import Facts

EVAL_DIR = ROOT / "data" / "eval"
DRAFT_PATH = EVAL_DIR / "test_cases.draft.jsonl"
TEST_PATH = EVAL_DIR / "test_cases.jsonl"
SMOKE_PATH = EVAL_DIR / "smoke_cases.jsonl"
VERIFY_PATH = EVAL_DIR / "verify_cases.csv"
MANUAL_PATH = EVAL_DIR / "manual_cases.csv"

GROUPS = ("A", "B", "C", "D", "E")
GROUP_MINIMUM = {"A": 15, "B": 20, "C": 15, "D": 20, "E": 10}
SOURCES = ("draft", "manual")
STATUSES = ("answered", "need_info", "unknown")
MAX_FOLLOWUPS = 3

# Slot names used in case files -> slot names of the engine's questions.
SLOT_ALIASES = {
    "vehicle": "vehicle_class",
    "alcohol": "alcohol_level",
    "speed": "speed_band",
    "passengers": "passengers_count",
    "road": "road_type",
    "license_class": "motorbike_type",
    "transport": "transport_use",
    "license_expiry": "license_expiry",
}
_SHORT_SLOTS = {engine: short for short, engine in SLOT_ALIASES.items()}
ASK_SLOTS = tuple(SLOT_ALIASES)

CASE_FIELDS = ("id", "group", "source", "query", "ground_truth", "verified", "notes")
LIST_CONCLUSIONS = ("violations", "sanctions", "aggravating", "mitigating")
INT_CONCLUSIONS = ("recommended_fine_total", "points_deducted_total")
GROUND_TRUTH_FIELDS = (
    "facts",
    "first_status",
    "first_ask_slot",
    "status",
    *LIST_CONCLUSIONS,
    *INT_CONCLUSIONS,
)

# Facts fields that are not something a user states.
_INTERNAL_FACTS = ("evidence", "grounded_violations", "unknown_slots")


def short_slot(slot: str | None) -> str | None:
    return None if slot is None else _SHORT_SLOTS.get(slot, slot)


def normalize_status(status: str) -> str:
    """Case files use three statuses: "out of scope" counts as unknown."""
    return "unknown" if status in ("out_of_scope", "out_of_scope_temporal") else status


# -- I/O -----------------------------------------------------------------
def load_cases(path: Path) -> list[dict[str, Any]]:
    cases = []
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            cases.append(json.loads(line))
        except json.JSONDecodeError as error:
            raise ValueError(f"{path}:{number}: JSON không hợp lệ: {error}") from error
    return cases


def save_cases(path: Path, cases: Iterable[dict[str, Any]]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(case, ensure_ascii=False) + "\n" for case in cases)
    path.write_text(text, encoding="utf-8")


def compact_facts(facts: Facts) -> dict[str, Any]:
    """Only the stated slots: no empty values, defaults or internal fields."""
    data = facts.model_dump(mode="json")
    default = Facts().model_dump(mode="json")
    return {
        name: value
        for name, value in data.items()
        if name not in _INTERNAL_FACTS
        and value not in (None, [], {}, False)
        and value != default[name]
    }


# -- conclusions from facts (never from the extraction pipeline) ----------
class Concluder:
    """Engine + PenaltyDecider on given facts: the oracle used to draft ground
    truth and by the `oracle_facts` configuration."""

    def __init__(self, kb: KnowledgeBase):
        self.kb = kb
        self.engine = InferenceEngine(kb)
        self.penalty = PenaltyDecider(kb)

    def conclude(self, facts: Facts, asked: int = 0) -> dict[str, Any]:
        result = self.engine.run(facts, allow_questions=asked < MAX_QUESTION_ROUNDS)
        penalty = self.penalty.decide_hits(
            result.hits, result.circumstances, result.facts_final.subject
        )
        return {
            "status": normalize_status(result.status),
            "ask_slot": short_slot(result.questions[0].slot) if result.questions else None,
            "ask_field": result.questions[0].field if result.questions else None,
            "violations": sorted(hit.citation_id for hit in result.hits),
            "fine_ranges": {
                d.citation_id: list(d.fine_range) if d.fine_range else None
                for d in penalty.decisions
            },
            "recommended_fine_total": penalty.total_recommended_fine,
            "points_deducted_total": penalty.total_points_deducted,
            "sanctions": sorted({s.type for s in penalty.sanctions}),
            "aggravating": sorted(penalty.aggravating),
            "mitigating": sorted(penalty.mitigating),
        }

    def ground_truth(
        self, first_facts: dict[str, Any], turns: Iterable[tuple[str, str, Any]] = ()
    ) -> dict[str, Any]:
        """`turns` = (expected slot, field filled by the reply, value) per follow-up."""
        facts = Facts.model_validate(first_facts)
        outcome = first = self.conclude(facts)
        asked = 0
        for expected_slot, field, value in turns:
            if outcome["status"] != "need_info":
                raise ValueError(f"follow-up '{expected_slot}' nhưng engine không hỏi thêm")
            if outcome["ask_slot"] != expected_slot:
                raise ValueError(
                    f"engine hỏi '{outcome['ask_slot']}', case ghi '{expected_slot}'"
                )
            facts = self.engine.apply_answer(facts, field, value)
            asked += 1
            outcome = self.conclude(facts, asked)
        return {
            "facts": compact_facts(facts),
            "first_status": first["status"],
            "first_ask_slot": first["ask_slot"],
            "status": outcome["status"],
            **{key: outcome[key] for key in ("violations", *INT_CONCLUSIONS)},
            **{key: outcome[key] for key in ("sanctions", "aggravating", "mitigating")},
        }


# -- validation -----------------------------------------------------------
def validate_case(case: dict[str, Any], kb: KnowledgeBase) -> list[str]:
    errors = [f"thiếu trường '{name}'" for name in CASE_FIELDS if name not in case]
    if errors:
        return errors
    if case["group"] not in GROUPS:
        errors.append(f"group không hợp lệ: {case['group']!r}")
    if case["source"] not in SOURCES:
        errors.append(f"source không hợp lệ: {case['source']!r}")
    if not str(case["query"]).strip():
        errors.append("query rỗng")
    if not isinstance(case["verified"], bool):
        errors.append("verified phải là true/false")

    followups = case.get("followups") or []
    if len(followups) > MAX_FOLLOWUPS:
        errors.append(f"quá {MAX_FOLLOWUPS} followups")
    for index, item in enumerate(followups):
        if item.get("expect_ask_slot") not in ASK_SLOTS:
            errors.append(f"followups[{index}].expect_ask_slot không hợp lệ")
        if not str(item.get("answer", "")).strip():
            errors.append(f"followups[{index}].answer rỗng")

    truth = case["ground_truth"]
    missing = [name for name in GROUND_TRUTH_FIELDS if name not in truth]
    if missing:
        return errors + [f"ground_truth thiếu trường: {', '.join(missing)}"]
    for name in ("first_status", "status"):
        if truth[name] not in STATUSES:
            errors.append(f"ground_truth.{name} không hợp lệ: {truth[name]!r}")
    slot = truth["first_ask_slot"]
    if slot is not None and slot not in ASK_SLOTS:
        errors.append(f"first_ask_slot không hợp lệ: {slot!r}")
    if (truth["first_status"] == "need_info") != (slot is not None):
        errors.append("first_ask_slot phải có giá trị khi và chỉ khi first_status = need_info")
    if followups:
        if truth["first_status"] != "need_info":
            errors.append("có followups nhưng first_status không phải need_info")
        elif followups[0].get("expect_ask_slot") != slot:
            errors.append("followups[0].expect_ask_slot khác first_ask_slot")
    elif truth["status"] != truth["first_status"]:
        errors.append("không có followups nên status phải bằng first_status")
    for name in INT_CONCLUSIONS:
        if not isinstance(truth[name], int) or truth[name] < 0:
            errors.append(f"ground_truth.{name} phải là số nguyên không âm")

    for citation_id in truth["violations"]:
        if citation_id not in kb.violations:
            errors.append(f"citation không có trong KB: {citation_id}")
    cited = [*truth["aggravating"], *truth["mitigating"], *truth["facts"].get("circumstances", [])]
    for circumstance in dict.fromkeys(cited):
        if circumstance not in kb.circumstances:
            errors.append(f"tình tiết không có trong KB: {circumstance}")
    for kind in ("aggravating", "mitigating"):
        for circumstance in truth[kind]:
            actual = kb.circumstances.get(circumstance, {}).get("kind")
            if actual and actual != kind:
                errors.append(f"{circumstance} là tình tiết {actual}, ghi ở {kind}")

    unknown = set(truth["facts"]) - (set(Facts.model_fields) - set(_INTERNAL_FACTS))
    if unknown:
        errors.append(f"ground_truth.facts có slot lạ: {sorted(unknown)}")
    else:
        try:
            Facts.model_validate(truth["facts"])
        except ValueError as error:
            errors.append(f"ground_truth.facts sai kiểu: {str(error)[:200]}")
    for act in truth["facts"].get("acts", []):
        if act not in kb.acts:
            errors.append(f"act không có trong KB: {act}")

    if case["group"] == "E" and truth["first_status"] == "answered":
        errors.append("nhóm E phải có first_status khác answered")
    return errors


def validate_cases(cases: list[dict[str, Any]], kb: KnowledgeBase) -> list[str]:
    errors, seen = [], set()
    for index, case in enumerate(cases, 1):
        case_id = case.get("id") or f"dòng {index}"
        if case_id in seen:
            errors.append(f"{case_id}: id trùng")
        seen.add(case_id)
        errors += [f"{case_id}: {message}" for message in validate_case(case, kb)]
    return errors


def group_shortfalls(cases: list[dict[str, Any]]) -> dict[str, int]:
    counts = {group: 0 for group in GROUPS}
    for case in cases:
        if case.get("group") in counts:
            counts[case["group"]] += 1
    return {g: GROUP_MINIMUM[g] - n for g, n in counts.items() if n < GROUP_MINIMUM[g]}


# -- verify sheet encoding ------------------------------------------------
LIST_SEPARATOR = "|"


def encode_list(values: Iterable[str]) -> str:
    return LIST_SEPARATOR.join(values)


def decode_list(text: str) -> list[str]:
    return [item.strip() for item in (text or "").split(LIST_SEPARATOR) if item.strip()]


def encode_facts(facts: dict[str, Any]) -> str:
    """`slot=value; list_slot=a|b` — readable and editable in a spreadsheet."""
    parts = []
    for name, value in facts.items():
        if isinstance(value, list):
            value = encode_list(value)
        elif isinstance(value, bool):
            value = "true" if value else "false"
        elif isinstance(value, float) and value.is_integer():
            value = int(value)
        parts.append(f"{name}={value}")
    return "; ".join(parts)


def decode_facts(text: str) -> dict[str, Any]:
    list_fields = {n for n, v in Facts().model_dump().items() if isinstance(v, list)}
    data: dict[str, Any] = {}
    for part in (text or "").split(";"):
        if not part.strip():
            continue
        name, separator, value = part.partition("=")
        name, value = name.strip(), value.strip()
        if not separator or name not in Facts.model_fields or name in _INTERNAL_FACTS:
            raise ValueError(f"facts: mục không hợp lệ '{part.strip()}'")
        data[name] = decode_list(value) if name in list_fields else value
    # Pydantic coerces "0.3", "true", "2" and dates to the declared types.
    dumped = Facts.model_validate(data).model_dump(mode="json")
    return {name: dumped[name] for name in data}
