"""Metric functions of run_eval.py on made-up data (no LLM, no retriever)."""

import pytest

from src.eval import cases as C
from src.eval.run_eval import (
    aggregate_scores,
    confusion_matrix,
    fact_items,
    latency_stats,
    prf,
    score_case,
    system_metrics,
)
from src.reasoning.knowledge_base import get_knowledge_base

RANGE = {"X-D1-K1-Pa": (100, 200)}


def make_case(case_id="A-001", group="A", **truth):
    ground_truth = {
        "facts": {"vehicle_class": "VEH_CAR", "acts": ["ACT_RED_LIGHT"]},
        "first_status": "answered",
        "first_ask_slot": None,
        "status": "answered",
        "violations": ["X-D1-K1-Pa"],
        "recommended_fine_total": 150,
        "points_deducted_total": 4,
        "sanctions": [],
        "aggravating": [],
        "mitigating": [],
    }
    ground_truth.update(truth)
    return {"id": case_id, "group": group, "ground_truth": ground_truth}


def make_pred(**changes):
    pred = {
        "facts": {"vehicle_class": "VEH_CAR", "acts": ["ACT_RED_LIGHT"]},
        "first_status": "answered",
        "first_ask_slot": None,
        "reports_ask_slot": True,
        "status": "answered",
        "question_turns": 0,
        "violations": ["X-D1-K1-Pa"],
        "fine_ranges": {"X-D1-K1-Pa": [100, 200]},
        "recommended_fine_total": 150,
        "points_deducted_total": 4,
        "sanctions": [],
        "aggravating": [],
        "mitigating": [],
    }
    pred.update(changes)
    return pred


def test_prf_micro_and_empty():
    result = prf([(2, 1, 0), (1, 0, 2)])
    assert result["precision"] == pytest.approx(3 / 4)
    assert result["recall"] == pytest.approx(3 / 5)
    assert result["f1"] == pytest.approx(6 / 9)
    assert prf([(0, 0, 0)])["f1"] is None
    assert prf([(0, 2, 0)])["precision"] == 0 and prf([(0, 2, 0)])["recall"] is None


def test_fact_items_ignores_unfilled_values_and_normalizes_numbers():
    items = fact_items({
        "vehicle_class": None, "officer_signal": False, "acts": [], "subject": "SUBJ_INDIVIDUAL",
        "speed_over_kmh": 15.0, "free_behaviors": ["abc"], "evidence": {"acts": "x"},
    })
    assert items == {"speed_over_kmh": {"15"}}
    assert fact_items({"passengers_count": 2}) == fact_items({"passengers_count": 2.0})


def test_slot_scores_and_hallucinated_rate():
    pred = make_pred(facts={
        "vehicle_class": "VEH_MOTORBIKE",           # wrong value: 1 FP + 1 FN
        "acts": ["ACT_RED_LIGHT", "ACT_NO_HELMET"],  # 1 TP + 1 FP
        "road_type": "ROAD_TUNNEL",                  # hallucinated slot
    })
    score = score_case(make_case(), pred, RANGE)
    assert score["slots"]["vehicle_class"] == (0, 1, 1)
    assert score["slots"]["acts"] == (1, 1, 0)
    assert (score["filled_slots"], score["hallucinated_slots"]) == (3, 1)
    extraction = aggregate_scores([score])["extraction"]
    assert extraction["slot"]["precision"] == pytest.approx(1 / 4)
    assert extraction["slot"]["recall"] == pytest.approx(1 / 2)
    assert extraction["acts"]["f1"] == pytest.approx(2 / 3)
    assert extraction["hallucinated_slot_rate"] == pytest.approx(1 / 3)


def test_violation_set_and_citation_metrics():
    pred = make_pred(violations=["X-D1-K1-Pb", "X-D9-K9-Pz"])
    score = score_case(make_case(), pred, RANGE, known_citations={"X-D1-K1-Pa", "X-D1-K1-Pb"})
    assert score["violations"] == (0, 2, 1)
    assert not score["exact_set"]
    reasoning = aggregate_scores([score])["reasoning"]
    assert reasoning["violation"]["f1"] == 0
    assert reasoning["citation_accuracy"] == 1  # right Điều-Khoản, wrong Điểm
    assert reasoning["citation_exists_rate"] == pytest.approx(1 / 2)


def test_confusion_matrix_skips_missing_predictions():
    matrix = confusion_matrix([
        ("answered", "answered"), ("answered", "need_info"), ("unknown", "unknown"),
        ("need_info", None),
    ])
    assert matrix["answered"] == {"answered": 1, "need_info": 1, "unknown": 0}
    assert matrix["unknown"]["unknown"] == 1
    assert sum(matrix["need_info"].values()) == 0


def test_end_to_end():
    assert score_case(make_case(), make_pred(), RANGE)["end_to_end"]
    for change in (
        {"violations": []},
        {"recommended_fine_total": 151},
        {"points_deducted_total": 0},
        {"status": "unknown"},
    ):
        assert not score_case(make_case(), make_pred(**change), RANGE)["end_to_end"], change
    # sanctions are reported on their own, not part of end-to-end
    assert score_case(make_case(), make_pred(sanctions=["confiscate"]), RANGE)["end_to_end"]
    # when the expected status is not "answered", only the status counts
    case = make_case(status="unknown", violations=[], recommended_fine_total=0)
    score = score_case(case, make_pred(status="unknown", violations=[]), {})
    assert score["end_to_end"] and score["fine_ok"] is None


def test_unsupported_outputs_are_not_counted():
    pred = make_pred(
        facts=None, fine_ranges=None, aggravating=None, mitigating=None, first_status=None
    )
    metrics = aggregate_scores([score_case(make_case(), pred, RANGE)])
    assert metrics["extraction"] is None
    assert metrics["reasoning"]["fine_range_accuracy"] is None
    assert metrics["reasoning"]["aggravating_exact"] is None
    assert metrics["dialog"]["first_status_accuracy"] is None
    assert metrics["dialog"]["first_status_confusion"] is None
    assert metrics["end_to_end_accuracy"] == 1


def test_ask_slot_and_error_types():
    case = make_case(first_status="need_info", first_ask_slot="vehicle")
    pred = make_pred(first_status="need_info", first_ask_slot="alcohol")
    score = score_case(case, pred, RANGE)
    assert score["first_ask_slot_ok"] is False and score["error_types"] == ["dialog"]

    assert score_case(make_case(), make_pred(), RANGE)["error_types"] == []
    wrong_rule = make_pred(violations=[])
    assert score_case(make_case(), wrong_rule, RANGE)["error_types"] == ["rule"]
    wrong_fine = make_pred(recommended_fine_total=1)
    assert score_case(make_case(), wrong_fine, RANGE)["error_types"] == ["penalty"]
    missed_act = make_pred(facts={"vehicle_class": "VEH_CAR"}, violations=[], status="unknown")
    assert score_case(make_case(), missed_act, RANGE)["error_types"] == ["extract"]
    grounded = make_pred(
        facts={"vehicle_class": "VEH_CAR", "acts": ["ACT_RED_LIGHT", "ACT_WRONG_LANE"]},
        grounded={"acts": ["ACT_WRONG_LANE"], "violations": []},
        violations=["X-D1-K1-Pa", "X-D2-K1-Pa"],
    )
    assert score_case(make_case(), grounded, RANGE)["error_types"] == ["ground"]


def test_metrics_by_group_and_latency():
    scores = [
        score_case(make_case("A-001", "A"), make_pred(), RANGE),
        score_case(make_case("B-001", "B"), make_pred(violations=[]), RANGE),
    ]
    assert aggregate_scores(scores)["end_to_end_accuracy"] == 0.5
    assert aggregate_scores(scores[1:])["end_to_end_accuracy"] == 0
    assert latency_stats([]) is None
    stats = latency_stats([1.0, 2.0, 3.0, 4.0, 100.0])
    assert stats["p50"] == 3.0 and stats["mean"] == 22.0 and stats["p95"] > 4


def test_replayed_cases_give_no_total_latency():
    def record(cached):
        call = {"cached": cached, "invalid_json": False, "error": None}
        return {"turns": [
            {"latency_ms": {"engine": 1.0, **({} if cached else {"total": 900.0})},
             "llm_calls": [call]},
            {"latency_ms": {"engine": 1.0, "total": 2.0}, "llm_calls": []},
        ]}

    replayed = system_metrics([record(True)])
    assert "total" not in replayed["latency_ms"] and replayed["latency_ms"]["engine"]["n"] == 2
    assert system_metrics([record(False)])["latency_ms"]["total"]["n"] == 2


# -- case files -------------------------------------------------------------
@pytest.mark.parametrize("path", [C.DRAFT_PATH, C.SMOKE_PATH])
def test_committed_case_files_are_valid(path):
    assert C.validate_cases(C.load_cases(path), get_knowledge_base()) == []


def test_validate_case_rejects_bad_input():
    kb = get_knowledge_base()
    case = C.load_cases(C.SMOKE_PATH)[0]
    assert C.validate_cases([case, case], kb) == [f"{case['id']}: id trùng"]
    broken = {**case, "group": "E", "ground_truth": {**case["ground_truth"]}}
    broken["ground_truth"].update(violations=["ND168-KHONG-CO"], aggravating=["CIR_KHONG_CO"])
    errors = " ".join(C.validate_case(broken, kb))
    assert "citation không có trong KB" in errors
    assert "tình tiết không có trong KB" in errors
    assert "nhóm E" in errors


def test_facts_roundtrip_through_the_verify_sheet():
    facts = {
        "vehicle_class": "VEH_CAR", "acts": ["ACT_ALCOHOL", "ACT_RED_LIGHT"],
        "bac_breath_mg_l": 0.3, "passengers_count": 2, "officer_signal": True,
        "violation_date": "2024-10-20",
    }
    assert C.decode_facts(C.encode_facts(facts)) == facts
    with pytest.raises(ValueError):
        C.decode_facts("khong_co=1")
