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
    {
        "has_act",
        "has_context",
        "has_circumstance",
        "has_violation",
        "also_has_violation",
        "grounded_violation",
    }
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
    # citation_id do OntologyGrounder ánh xạ trực tiếp (DESIGN §5.2, luật classify_auto)
    grounded_violations: list[str] = Field(default_factory=list)
    speed_limit_kmh: float | None = None
    actual_speed_kmh: float | None = None
    speed_over_kmh: float | None = None
    drank_alcohol: bool | None = None
    bac_blood_mg_100ml: float | None = None
    bac_breath_mg_l: float | None = None
    alcohol_test_refused: bool | None = None
    # Ranges the user picks when there is no measured value (no number is made up).
    speed_band: str | None = None
    alcohol_level: str | None = None
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
    # Slots the user answered "Không rõ" to: never asked again, reported as branches.
    unknown_slots: list[str] = Field(default_factory=list)
    evidence: dict[str, str] = Field(default_factory=dict)


class ExtractionResult(BaseModel):
    facts: Facts
    source: Literal["llm", "regex", "answer"]
    warnings: list[str] = Field(default_factory=list)
    llm: dict[str, Any] | None = None  # CallMetadata of the LLM call


# ---------------------------------------------------------------------------
# Engine output
# ---------------------------------------------------------------------------


class TraceStep(BaseModel):
    rule_id: str
    type: RuleType | Literal["ground"]  # "ground" = OntologyGrounder, not a rule
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
    # Used by the engine's "specific beats general" exclusion.
    acts: list[str] = Field(default_factory=list)
    priority: int = 0


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
    slot: str = ""
    # A typed number fills this field (e.g. a measured value instead of a range).
    number_field: str | None = None
    number_max: float | None = None


class BranchCondition(BaseModel):
    slot: str
    slot_label: str
    values: list[Any]
    labels: list[str]


class Branch(BaseModel):
    """One possible outcome while some slots stay unknown."""

    conditions: list[BranchCondition]
    hits: list[ViolationHit]


Status = Literal["answered", "need_info", "unknown", "out_of_scope", "out_of_scope_temporal"]


class EngineResult(BaseModel):
    status: Status
    input_facts: Facts = Field(default_factory=Facts)
    facts_final: Facts
    acts: list[str] = Field(default_factory=list)
    contexts: list[str] = Field(default_factory=list)
    circumstances: list[str] = Field(default_factory=list)
    hits: list[ViolationHit] = Field(default_factory=list)
    questions: list[Question] = Field(default_factory=list)
    branches: list[Branch] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)  # slot labels behind the branches
    branches_incomplete: bool = False  # some values of those slots lead to no known rule
    notes: list[str] = Field(default_factory=list)
    message: str | None = None
    trace: list[TraceStep] = Field(default_factory=list)

    # P1 names, kept for backward compatibility.
    @property
    def facts(self) -> Facts:
        return self.facts_final

    @property
    def violations(self) -> list[ViolationHit]:
        return self.hits


InferenceResult = EngineResult


# ---------------------------------------------------------------------------
# Penalty (DESIGN §7)
# ---------------------------------------------------------------------------


class Sanction(BaseModel):
    type: str
    duration_min: int | None = None  # months
    duration_max: int | None = None


class ConditionalPoints(BaseModel):
    """A higher deduction that only applies under a condition (never auto-applied)."""

    points: int
    condition: str  # verbatim wording of the deduction clause
    source: str  # citation_id of that clause


class PenaltyDecision(BaseModel):
    """Decision for a single violation."""

    citation_id: str
    fine_range: tuple[int, int] | None = None
    recommended_fine: int = 0
    # Bounds produced by the circumstances; for net = ±1 both ends are exclusive.
    allowed_range_after_circumstances: tuple[int, int] | None = None
    points_deducted: int = 0  # statutory value of this violation
    points_conditional: list[ConditionalPoints] = Field(default_factory=list)
    sanctions: list[Sanction] = Field(default_factory=list)
    org_rule_applied: bool = False
    reasoning: list[str] = Field(default_factory=list)


class PenaltySummary(BaseModel):
    """All violations handled in the same decision."""

    decisions: list[PenaltyDecision] = Field(default_factory=list)
    total_recommended_fine: int = 0
    total_points_deducted: int = 0  # largest single value, never summed
    points_from: str | None = None
    sanctions: list[Sanction] = Field(default_factory=list)
    aggravating: list[str] = Field(default_factory=list)
    mitigating: list[str] = Field(default_factory=list)
    excluded_circumstances: dict[str, str] = Field(default_factory=dict)
    net: int = 0
    reasoning: list[str] = Field(default_factory=list)
    legal_principle_ref: str


# ---------------------------------------------------------------------------
# Explanation (DESIGN §8)
# ---------------------------------------------------------------------------


class FactUsed(BaseModel):
    field: str
    value: Any
    evidence: str | None = None
    origin: Literal["user", "derived"] = "user"
    derived_from: str | None = None  # set when origin == "derived"


class LegalCitation(BaseModel):
    citation_id: str
    label: str
    text: str | None = None  # verbatim LegalUnit text


class Explanation(BaseModel):
    facts_used: list[FactUsed] = Field(default_factory=list)
    chain: list[TraceStep] = Field(default_factory=list)
    legal_citations: list[LegalCitation] = Field(default_factory=list)
    penalty_calc: list[str] = Field(default_factory=list)
    faithfulness_ok: bool = False


# ---------------------------------------------------------------------------
# API response (DESIGN §9)
# ---------------------------------------------------------------------------


class ConsultViolation(BaseModel):
    citation_id: str
    label: str
    description: str
    fine_range: tuple[int, int] | None = None
    recommended_fine: int = 0
    points_deducted: int = 0
    sanctions: list[Sanction] = Field(default_factory=list)
    legal_text: str | None = None
    # Display data copied from PenaltyDecision (the UI must not recompute it).
    allowed_range_after_circumstances: tuple[int, int] | None = None
    points_conditional: list[ConditionalPoints] = Field(default_factory=list)
    org_rule_applied: bool = False


class ConsultBranch(BaseModel):
    conditions: list[BranchCondition]
    violations: list[ConsultViolation]


class ConsultResult(BaseModel):
    session_id: str | None = None
    status: Literal["answered", "need_info", "unknown", "out_of_scope"]
    facts: Facts
    violations: list[ConsultViolation] = Field(default_factory=list)
    total_recommended_fine: int = 0
    questions: list[Question] = Field(default_factory=list)
    branches: list[ConsultBranch] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    explanation: Explanation = Field(default_factory=Explanation)
    answer_text: str = ""
    # answer_text split into its parts, plus the decision totals from PenaltySummary.
    summary_text: str = ""
    notes: list[str] = Field(default_factory=list)
    total_points_deducted: int = 0
    sanctions: list[Sanction] = Field(default_factory=list)
    aggravating: list[str] = Field(default_factory=list)
    mitigating: list[str] = Field(default_factory=list)
    latency_ms: dict[str, float] = Field(default_factory=dict)
