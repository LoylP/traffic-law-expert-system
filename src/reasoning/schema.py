"""Pydantic schemas for the reasoning layer (DESIGN §5, §6, §9)."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Rule schema
# ---------------------------------------------------------------------------

RuleType = Literal["derive", "temporal", "classify", "escalate", "exclude", "note", "ask"]

# Execution order of rule phases (DESIGN §5.3). `note` runs after classify
# (and after escalate/exclude, so it sees the final violation set) and before ask.
PHASE_ORDER: tuple[str, ...] = (
    "derive",
    "temporal",
    "classify",
    "escalate",
    "exclude",
    "note",
    "ask",
)

# Operators allowed inside a dict-valued condition, e.g. `speed_over_kmh: {gte: 5, lt: 10}`.
#   not_null / is_null : value is (not) None / empty list
#   not_true           : value is not True  (None or False both match)
#   not_empty          : list/collection non-empty
#   gt / gte / lt / lte: numeric comparison (None never matches)
#   eq / in            : equality / membership
#   before / from      : ISO date comparison (violation_date None = today)
CONDITION_OPERATORS: frozenset[str] = frozenset(
    {
        "not_null",
        "is_null",
        "not_true",
        "not_empty",
        "gt",
        "gte",
        "lt",
        "lte",
        "eq",
        "in",
        "before",
        "from",
    }
)

# Condition keys that read working memory rather than a Facts field.
SPECIAL_CONDITION_KEYS: frozenset[str] = frozenset(
    {"has_act", "has_context", "has_violation", "also_has_violation"}
)


class Rule(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    type: RuleType
    priority: int = 0
    when: dict[str, Any] = Field(default_factory=dict)
    then: dict[str, Any] = Field(default_factory=dict)
    explain: str | None = None
    source: str | None = None
    legal_excerpt: str | None = None
    verified: bool = False

    @field_validator("when")
    @classmethod
    def _check_operators(cls, when: dict[str, Any]) -> dict[str, Any]:
        for key, cond in when.items():
            if isinstance(cond, dict):
                unknown = set(cond) - CONDITION_OPERATORS
                if unknown:
                    raise ValueError(f"unknown operator(s) {sorted(unknown)} in condition '{key}'")
        return when

    @model_validator(mode="after")
    def _check_field_names(self) -> "Rule":
        allowed = set(Facts.model_fields) | SPECIAL_CONDITION_KEYS
        unknown = set(self.when) - allowed
        if unknown:
            raise ValueError(f"rule {self.id}: unknown condition key(s) {sorted(unknown)}")
        return self

    @property
    def specificity(self) -> int:
        return len(self.when)


# ---------------------------------------------------------------------------
# Facts (output of FactExtractor, DESIGN §6)
# ---------------------------------------------------------------------------


class Facts(BaseModel):
    model_config = ConfigDict(extra="ignore")

    vehicle_class: str | None = None
    acts: list[str] = Field(default_factory=list)
    free_behaviors: list[str] = Field(default_factory=list)
    speed_limit_kmh: float | None = None
    actual_speed_kmh: float | None = None
    speed_over_kmh: float | None = None
    drank_alcohol: bool | None = None
    bac_blood_mg_100ml: float | None = None
    bac_breath_mg_l: float | None = None
    alcohol_test_refused: bool | None = None
    road_type: str | None = None
    time_context: str | None = None
    violation_date: date | None = None
    officer_signal: bool | None = None
    resistance: list[str] = Field(default_factory=list)
    consequence: list[str] = Field(default_factory=list)
    passengers_count: int | None = None
    # Ngoại lệ NĐ 168 Điều 7 khoản 2 điểm g: chở người bệnh đi cấp cứu, trẻ em dưới 12 tuổi,
    # người già yếu hoặc người khuyết tật, áp giải người có hành vi vi phạm pháp luật.
    passenger_exception: bool | None = None
    # Ngoại lệ NĐ 168 Điều 7 khoản 2 điểm i: chở người bệnh đi cấp cứu, trẻ em dưới 06 tuổi,
    # áp giải người có hành vi vi phạm pháp luật.
    passenger_helmet_exception: bool | None = None
    no_helmet_who: Literal["driver", "passenger", "both"] | None = None
    subject: str = "SUBJ_INDIVIDUAL"
    circumstances: list[str] = Field(default_factory=list)
    evidence: dict[str, str] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------


class TraceStep(BaseModel):
    rule_id: str
    type: RuleType
    matched_facts: dict[str, Any] = Field(default_factory=dict)
    produced: dict[str, Any] = Field(default_factory=dict)
    explain: str | None = None
    source: str | None = None


class ViolationHit(BaseModel):
    citation_id: str
    rule_id: str
    legal_excerpt: str | None = None
    legal_text: str | None = None
    escalated_from: list[str] = Field(default_factory=list)


class QuestionOption(BaseModel):
    model_config = ConfigDict(extra="allow")

    value: Any
    label: str


class Question(BaseModel):
    field: str
    text: str
    options: list[QuestionOption] = Field(default_factory=list)
    input_type: str | None = None
    unit: str | None = None
    rule_id: str


Status = Literal["answered", "need_info", "unknown", "out_of_scope", "out_of_scope_temporal"]


class InferenceResult(BaseModel):
    status: Status
    facts: Facts
    acts: list[str] = Field(default_factory=list)
    contexts: list[str] = Field(default_factory=list)
    circumstances: list[str] = Field(default_factory=list)
    violations: list[ViolationHit] = Field(default_factory=list)
    questions: list[Question] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    message: str | None = None
    trace: list[TraceStep] = Field(default_factory=list)
