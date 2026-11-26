"""Offline tests for the forward-chaining InferenceEngine."""

import pytest

from src.reasoning.engine import SPECIFICITY_RULE_ID, InferenceEngine, _check_operator
from src.reasoning.knowledge_base import KnowledgeBase
from src.reasoning.schema import EngineResult, Facts, Rule

OBSTRUCT_NOTE = (
    "Hành vi chống đối/cản trở người thi hành công vụ không được quy định tại NĐ 168/2024; "
    "có thể bị xử lý theo văn bản khác (lĩnh vực an ninh, trật tự) — ngoài phạm vi hệ thống."
)


@pytest.fixture(scope="module")
def engine() -> InferenceEngine:
    return InferenceEngine()


def citations(result) -> set[str]:
    return {hit.citation_id for hit in result.violations}


def fired(result) -> list[str]:
    return [step.rule_id for step in result.trace]


# --- operator / schema -------------------------------------------------------


@pytest.mark.parametrize("value,expected", [(None, True), (False, True), (True, False)])
def test_not_true_operator(value, expected):
    assert _check_operator("not_true", True, value) is expected


def test_schema_rejects_unknown_operator():
    with pytest.raises(ValueError):
        Rule.model_validate({"id": "X", "type": "derive", "when": {"officer_signal": {"is_falsy": True}}})


def test_schema_accepts_note_type_and_not_true():
    rule = Rule.model_validate(
        {"id": "X", "type": "note", "when": {"officer_signal": {"not_true": True}}, "then": {"add_notes": ["n"]}}
    )
    assert rule.type == "note"


def test_facts_has_passenger_exception_fields():
    facts = Facts()
    assert facts.passenger_exception is None
    assert facts.passenger_helmet_exception is None


# --- 1. hit-and-run ----------------------------------------------------------


def test_accident_and_flee_without_officer_signal_gives_hit_and_run(engine):
    result = engine.infer({"consequence": ["CONS_ACCIDENT"], "resistance": ["RES_FLEE"], "officer_signal": None})
    assert "ACT_HIT_AND_RUN" in result.acts
    assert "R-DER-RES-04" in fired(result)
    assert "ACT_IGNORE_OFFICER" not in result.acts


def test_accident_and_flee_with_officer_signal_false_gives_hit_and_run(engine):
    result = engine.infer(
        {"vehicle_class": "VEH_CAR", "consequence": ["CONS_ACCIDENT"], "resistance": ["RES_FLEE"], "officer_signal": False}
    )
    assert "ACT_HIT_AND_RUN" in result.acts
    assert citations(result) == {"ND168-D6-K8"}


def test_flee_with_officer_signal_true_is_not_hit_and_run(engine):
    result = engine.infer(
        {"vehicle_class": "VEH_MOTORBIKE", "consequence": ["CONS_ACCIDENT"], "resistance": ["RES_FLEE"], "officer_signal": True}
    )
    assert "ACT_HIT_AND_RUN" not in result.acts
    assert "ACT_IGNORE_OFFICER" in result.acts


def test_hit_and_run_motorbike_has_verbatim_legal_text(engine):
    result = engine.infer({"vehicle_class": "VEH_MOTORBIKE", "consequence": ["CONS_ACCIDENT"], "resistance": ["RES_FLEE"]})
    hit = next(h for h in result.violations if h.citation_id == "ND168-D7-K9-Pc")
    assert hit.legal_excerpt in hit.legal_text


# --- 3. ACT_OBSTRUCT_OFFICER note -------------------------------------------


def test_obstruct_only_sets_out_of_scope_with_note(engine):
    result = engine.infer({"vehicle_class": "VEH_MOTORBIKE", "resistance": ["RES_OBSTRUCT"]})
    assert "ACT_OBSTRUCT_OFFICER" in result.acts
    assert result.violations == []
    assert result.notes == [OBSTRUCT_NOTE]
    assert result.status == "out_of_scope"


def test_obstruct_with_other_violation_keeps_status(engine):
    result = engine.infer(
        {"vehicle_class": "VEH_MOTORBIKE", "acts": ["ACT_RED_LIGHT"], "resistance": ["RES_OBSTRUCT"]}
    )
    assert citations(result) == {"ND168-D7-K7-Pc"}
    assert result.notes == [OBSTRUCT_NOTE]
    assert result.status == "answered"


def test_note_runs_after_classify(engine):
    result = engine.infer(
        {"vehicle_class": "VEH_MOTORBIKE", "acts": ["ACT_RED_LIGHT"], "resistance": ["RES_OBSTRUCT"]}
    )
    order = fired(result)
    assert order.index("R-CLS-RED-MOTO") < order.index("R-NOTE-OBSTRUCT")


def test_no_escalate_rule_for_obstruct(engine):
    assert all("OBSTRUCT" not in rule.id for rule in engine.kb.rules_of("escalate"))


# --- 4. passenger exceptions -------------------------------------------------


def test_two_passengers_without_exception_gives_k2_pg(engine):
    result = engine.infer({"vehicle_class": "VEH_MOTORBIKE", "passengers_count": 2})
    assert "ND168-D7-K2-Pg" in citations(result)


def test_two_passengers_with_exception_no_k2_pg(engine):
    result = engine.infer({"vehicle_class": "VEH_MOTORBIKE", "passengers_count": 2, "passenger_exception": True})
    assert "ND168-D7-K2-Pg" not in citations(result)


def test_passenger_no_helmet_with_exception_no_k2_pi(engine):
    base = {"vehicle_class": "VEH_MOTORBIKE", "no_helmet_who": "passenger"}
    assert "ND168-D7-K2-Pi" in citations(engine.infer(base))
    result = engine.infer({**base, "passenger_helmet_exception": True})
    assert "ND168-D7-K2-Pi" not in citations(result)


# --- 5. speed ask rules ------------------------------------------------------


def test_no_speed_question_when_speed_over_known(engine):
    result = engine.infer({"vehicle_class": "VEH_CAR", "acts": ["ACT_SPEEDING"], "speed_over_kmh": 15})
    assert [q.field for q in result.questions] == []
    assert "ND168-D6-K5-Pđ" in citations(result)


def test_speed_questions_when_nothing_known(engine):
    result = engine.infer({"vehicle_class": "VEH_CAR", "acts": ["ACT_SPEEDING"]})
    assert result.status == "need_info"
    assert {q.field for q in result.questions} == {"actual_speed_kmh", "speed_limit_kmh"}


# --- 6. alcohol ask options + refuse ----------------------------------------


def test_alcohol_question_options(engine):
    result = engine.infer({"vehicle_class": "VEH_MOTORBIKE", "acts": ["ACT_ALCOHOL"]})
    question = next(q for q in result.questions if q.field == "bac_breath_mg_l")
    assert [(o.label, o.value) for o in question.options] == [
        ("Đến 0,25 mg/l", 0.2),
        ("Trên 0,25 đến 0,4 mg/l", 0.3),
        ("Trên 0,4 mg/l", 0.5),
        ("Từ chối kiểm tra nồng độ cồn", "refuse"),
    ]


@pytest.mark.parametrize("value,level", [(0.2, "BAC_L1"), (0.3, "BAC_L2"), (0.5, "BAC_L3")])
def test_alcohol_option_values_map_to_levels(engine, value, level):
    facts = engine.infer({"vehicle_class": "VEH_MOTORBIKE", "acts": ["ACT_ALCOHOL"]}).facts
    result = engine.infer(engine.apply_answer(facts, "bac_breath_mg_l", value))
    assert level in result.contexts
    assert result.status == "answered"


@pytest.mark.parametrize("vehicle,citation", [("VEH_MOTORBIKE", "ND168-D7-K9-Pđ"), ("VEH_CAR", "ND168-D6-K11-Pb")])
def test_refuse_answer_sets_refuse_alcohol_act(engine, vehicle, citation):
    first = engine.infer({"vehicle_class": vehicle, "acts": ["ACT_ALCOHOL"]})
    assert first.status == "need_info"
    facts = engine.apply_answer(first.facts, "bac_breath_mg_l", "refuse")
    assert facts.bac_breath_mg_l is None
    assert facts.alcohol_test_refused is True
    assert "ACT_REFUSE_ALCOHOL_TEST" in facts.acts
    result = engine.infer(facts)
    assert result.questions == []
    assert citations(result) == {citation}
    assert result.status == "answered"


# --- general behaviour -------------------------------------------------------


def test_temporal_out_of_scope_stops_classification(engine):
    result = engine.infer({"vehicle_class": "VEH_MOTORBIKE", "acts": ["ACT_RED_LIGHT"], "violation_date": "2024-06-01"})
    assert result.status == "out_of_scope_temporal"
    assert result.violations == []


def test_escalate_replaces_base_violation(engine):
    result = engine.infer(
        {"vehicle_class": "VEH_MOTORBIKE", "acts": ["ACT_RED_LIGHT"], "consequence": ["CONS_ACCIDENT"]}
    )
    assert citations(result) == {"ND168-D7-K10-Pb"}
    assert result.violations[0].escalated_from == ["ND168-D7-K7-Pc"]


def test_empty_facts_unknown(engine):
    result = engine.infer({})
    assert result.status == "unknown"
    assert result.questions == []


# --- P2: engine core ---------------------------------------------------------


def synthetic(*rules: dict) -> InferenceEngine:
    return InferenceEngine(KnowledgeBase(rules=[Rule.model_validate(r) for r in rules]))


def rule(rule_id: str, rule_type: str, when: dict, then: dict, priority: int = 0) -> dict:
    return {"id": rule_id, "type": rule_type, "priority": priority, "when": when, "then": then}


def test_conflict_resolution_priority_then_specificity_then_file_order():
    engine = synthetic(
        rule("LOW", "derive", {"officer_signal": True}, {"add_acts": ["A1"]}, 1),
        rule("TIE-FIRST", "derive", {"officer_signal": True}, {"add_acts": ["A2"]}, 5),
        rule("TIE-SECOND", "derive", {"officer_signal": True}, {"add_acts": ["A3"]}, 5),
        rule(
            "SPECIFIC", "derive",
            {"officer_signal": True, "vehicle_class": {"is_null": True}}, {"add_acts": ["A4"]}, 5,
        ),
        rule("HIGH", "derive", {"officer_signal": True}, {"add_acts": ["A5"]}, 9),
    )
    result = engine.run({"officer_signal": True})
    assert fired(result) == ["HIGH", "SPECIFIC", "TIE-FIRST", "TIE-SECOND", "LOW"]


def test_phase_loops_to_fixed_point_and_fires_once_per_binding():
    engine = synthetic(
        rule("C", "derive", {"has_act": "B"}, {"add_acts": ["C"]}, 9),
        rule("B", "derive", {"has_act": "A"}, {"add_acts": ["B"]}, 5),
        rule("A", "derive", {"officer_signal": True}, {"add_acts": ["A"]}, 1),
    )
    result = engine.run({"officer_signal": True})
    assert result.acts == ["A", "B", "C"]
    assert fired(result) == ["A", "B", "C"]


def test_has_circumstance_and_matched_facts_limited_to_when_keys():
    engine = synthetic(
        rule("CIR", "derive", {"has_circumstance": ["CIR_REPEAT"]}, {"add_acts": ["A"]}),
    )
    result = engine.run({"circumstances": ["CIR_REPEAT"], "vehicle_class": "VEH_CAR"})
    assert result.acts == ["A"]
    assert result.trace[0].matched_facts == {"has_circumstance": ["CIR_REPEAT"]}


def test_eq_and_in_operators():
    assert _check_operator("eq", 2, 2)
    assert _check_operator("in", ["a", "b"], "a")
    assert not _check_operator("in", ["a", "b"], None)


def test_enabled_rule_types_disables_derive():
    engine = InferenceEngine(enabled_rule_types=["temporal", "classify", "escalate", "exclude", "note", "ask"])
    result = engine.run({"vehicle_class": "VEH_MOTORBIKE", "no_helmet_who": "driver"})
    assert result.hits == []
    assert result.status == "unknown"


def test_enabled_rule_types_rejects_unknown_type():
    with pytest.raises(ValueError):
        InferenceEngine(enabled_rule_types=["clasify"])


def test_run_returns_engine_result_and_keeps_input_facts(engine):
    result = engine.run({"vehicle_class": "VEH_MOTORBIKE", "no_helmet_who": "driver"})
    assert isinstance(result, EngineResult)
    assert result.facts_final.acts == ["ACT_NO_HELMET"]
    assert result.input_facts.acts == []
    assert citations(result) == {"ND168-D7-K2-Ph"}


def test_missing_bac_is_need_info(engine):
    result = engine.run({"vehicle_class": "VEH_CAR", "acts": ["ACT_ALCOHOL"]})
    assert result.status == "need_info"
    assert [q.field for q in result.questions] == ["bac_breath_mg_l"]


def test_no_act_is_unknown(engine):
    assert engine.run({"vehicle_class": "VEH_CAR"}).status == "unknown"


def test_multiple_violations(engine):
    result = engine.run({"vehicle_class": "VEH_MOTORBIKE", "passengers_count": 3, "no_helmet_who": "both"})
    assert citations(result) == {"ND168-D7-K3-Pb", "ND168-D7-K2-Ph", "ND168-D7-K2-Pi"}


def test_specific_hit_removes_general_hit_for_same_act(engine):
    facts = {"vehicle_class": "VEH_CAR", "acts": ["ACT_WRONG_WAY"], "road_type": "ROAD_EXPRESSWAY"}
    assert citations(engine.run(facts)) == {"ND168-D6-K11-Pđ"}


def test_generic_exclusion_applies_without_explicit_exclude_rule():
    engine = synthetic(
        rule("GEN", "classify", {"has_act": "A"}, {"add_violation": "X-GENERAL"}, 10),
        rule("SPEC", "classify", {"has_act": "A"}, {"add_violation": "X-SPECIFIC"}, 40),
        rule("OTHER", "classify", {"has_act": "B"}, {"add_violation": "X-OTHER"}, 10),
    )
    result = engine.run({"acts": ["A", "B"]})
    assert citations(result) == {"X-SPECIFIC", "X-OTHER"}
    assert result.trace[-1].rule_id == SPECIFICITY_RULE_ID


def test_escalated_general_hit_does_not_double_count_against_specific_hit(engine):
    result = engine.run(
        {
            "vehicle_class": "VEH_CAR", "acts": ["ACT_WRONG_WAY"],
            "road_type": "ROAD_EXPRESSWAY", "consequence": ["CONS_ACCIDENT"],
        }
    )
    assert citations(result) == {"ND168-D6-K11-Pđ"}


@pytest.mark.parametrize(
    "vehicle,target", [("VEH_CAR", "ND168-D6-K10-Pa"), ("VEH_MOTORBIKE", "ND168-D7-K10-Pa")]
)
def test_accident_escalates_speeding(engine, vehicle, target):
    result = engine.run({"vehicle_class": vehicle, "speed_over_kmh": 15, "consequence": ["CONS_ACCIDENT"]})
    assert citations(result) == {target}
    assert result.hits[0].acts == ["ACT_SPEEDING"]
