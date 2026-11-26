"""ExpertPipeline without LLM or network (RegexExtractor + template answer)."""

import pytest

from src.reasoning.grounder import GROUND_RULE_ID, OntologyGrounder
from src.reasoning.knowledge_base import get_knowledge_base
from src.reasoning.pipeline import ConsultOptions, ExpertPipeline, SessionStore

OFFLINE = ConsultOptions(use_llm_extractor=False, use_llm_writer=False)


class FakeRetriever:
    """Returns canned candidates per phrase: (citation_id, hybrid, cosine)."""

    def __init__(self, answers=None):
        self.answers = answers or {}
        self.calls = []

    def search(self, query, top_k=5, **kwargs):
        self.calls.append((query, kwargs))
        return [
            {"raw_node": {"citation_id": cid}, "scores": {"hybrid": hybrid, "embedding": cosine}}
            for cid, hybrid, cosine in self.answers.get(query, [])
        ][:top_k]


@pytest.fixture(scope="module")
def pipeline():
    return ExpertPipeline(retriever=FakeRetriever())


def consult(pipeline, message, **kwargs):
    kwargs.setdefault("options", OFFLINE)
    return pipeline.consult(message, **kwargs)


# 7 single-turn samples; the 8th (need_info -> answered) follows.
SAMPLES = [
    ("Tôi đi xe máy vượt đèn đỏ", "answered", {"ND168-D7-K7-Pc"}),
    (
        "Xe máy chạy 75 km/h ở đoạn giới hạn 50 km/h, người lái không đội mũ bảo hiểm",
        "answered",
        {"ND168-D7-K8-Pa", "ND168-D7-K2-Ph"},
    ),
    (
        "Đi xe máy, CSGT ra hiệu dừng xe nhưng tôi bỏ chạy và chửi bới CSGT",
        "answered",
        {"ND168-D7-K7-Pd"},
    ),
    (
        "Đi xe máy kẹp ba, người ngồi sau không đội mũ bảo hiểm",
        "answered",
        {"ND168-D7-K2-Pg", "ND168-D7-K2-Pi"},
    ),
    ("Ngày 15/06/2024 tôi lái ô tô vượt đèn đỏ", "out_of_scope", set()),
    ("xe máy chống đối CSGT", "out_of_scope", set()),
    ("Hôm nay trời đẹp quá", "unknown", set()),
]


@pytest.mark.parametrize("message,status,citations", SAMPLES)
def test_sample(pipeline, message, status, citations):
    result = consult(pipeline, message)
    assert result.status == status
    assert {v.citation_id for v in result.violations} == citations
    assert result.total_recommended_fine == sum(v.recommended_fine for v in result.violations)
    assert result.answer_text
    assert result.explanation.faithfulness_ok
    assert all(v.legal_text for v in result.violations)
    assert set(result.latency_ms) == {"extract", "ground", "reason", "write", "total"}


def test_need_info_then_answer_in_same_session(pipeline):
    first = consult(pipeline, "Tôi uống rượu rồi lái ô tô")
    assert first.status == "need_info"
    assert [q.field for q in first.questions] == ["alcohol_level"]
    assert first.session_id

    outcome = pipeline.consult_detailed("0,3 mg/l", first.session_id, OFFLINE)
    assert outcome.extractor == "answer"
    second = outcome.result
    assert second.status == "answered"
    assert second.session_id == first.session_id
    assert [v.citation_id for v in second.violations] == ["ND168-D6-K9-Pa"]
    assert second.facts.bac_breath_mg_l == 0.3


def test_refuse_option_switches_violation(pipeline):
    first = consult(pipeline, "Tôi uống rượu rồi đi xe máy")
    second = consult(pipeline, "Từ chối kiểm tra nồng độ cồn", session_id=first.session_id)
    assert [v.citation_id for v in second.violations] == ["ND168-D7-K9-Pđ"]


def test_free_text_follow_up_is_merged(pipeline):
    first = consult(pipeline, "Tôi vượt đèn đỏ")
    assert [q.field for q in first.questions] == ["vehicle_class"]
    second = consult(pipeline, "tôi đi xe máy nhé", session_id=first.session_id)
    assert second.status == "answered"
    assert [v.citation_id for v in second.violations] == ["ND168-D7-K7-Pc"]


def test_answered_turn_does_not_leak_into_next_turn(pipeline):
    first = consult(pipeline, "uống bia lái ô tô 0,3 mg/l, đã từng bị phạt lỗi này")
    assert first.status == "answered"
    assert "CIR_REPEAT" in first.facts.circumstances
    second = consult(pipeline, "lái ô tô đo được 0,1 mg/l", session_id=first.session_id)
    assert second.session_id == first.session_id
    assert second.status == "answered"
    assert "CIR_REPEAT" not in second.facts.circumstances
    assert second.total_recommended_fine == 7_000_000


@pytest.mark.parametrize(
    "message,status",
    [("Hôm nay trời đẹp quá", "unknown"), ("Ngày 15/06/2024 tôi lái ô tô vượt đèn đỏ", "out_of_scope")],
)
def test_unknown_or_out_of_scope_turn_starts_over(pipeline, message, status):
    first = consult(pipeline, message)
    assert first.status == status
    second = consult(pipeline, "Tôi đi xe máy vượt đèn đỏ", session_id=first.session_id)
    assert second.status == "answered"
    assert second.facts.violation_date is None
    assert [v.citation_id for v in second.violations] == ["ND168-D7-K7-Pc"]


def test_follow_up_keeps_facts_then_next_turn_starts_over(pipeline):
    first = consult(pipeline, "uống bia lái ô tô, đã từng bị phạt lỗi này")
    assert first.status == "need_info"
    second = consult(pipeline, "0,3 mg/l", session_id=first.session_id)
    assert second.status == "answered"
    assert "CIR_REPEAT" in second.facts.circumstances
    assert [v.citation_id for v in second.violations] == ["ND168-D6-K9-Pa"]
    third = consult(pipeline, "Tôi đi xe máy vượt đèn đỏ", session_id=first.session_id)
    assert third.facts.circumstances == [] and third.facts.bac_breath_mg_l is None
    assert [v.citation_id for v in third.violations] == ["ND168-D7-K7-Pc"]


def test_session_expires():
    now = [0.0]
    pipeline = ExpertPipeline(sessions=SessionStore(ttl=1800, clock=lambda: now[0]))
    first = consult(pipeline, "Tôi uống rượu rồi lái ô tô")
    now[0] = 1801
    assert consult(pipeline, "0,3", session_id=first.session_id).status == "unknown"


@pytest.mark.parametrize(
    "message",
    ["Xe máy không vượt đèn đỏ", "Đi xe máy, tôi không uống rượu bia"],
)
def test_negated_behaviour_is_not_extracted(pipeline, message):
    assert consult(pipeline, message).violations == []


def test_refusing_the_test_is_not_a_measured_level(pipeline):
    result = consult(pipeline, "Tôi từ chối thổi nồng độ cồn khi đi xe máy")
    assert [v.citation_id for v in result.violations] == ["ND168-D7-K9-Pđ"]


def test_ablation_without_circumstances(pipeline):
    message = "Tôi lái ô tô chạy quá tốc độ 25 km/h và tự nguyện khai báo"
    mitigated = consult(pipeline, message)
    flat = consult(
        pipeline, message, options=OFFLINE.model_copy(update={"use_circumstances": False})
    )
    assert mitigated.total_recommended_fine < flat.total_recommended_fine
    low, high = flat.violations[0].fine_range
    assert flat.total_recommended_fine == (low + high) // 2


def test_ablation_without_derive_rules(pipeline):
    types = ["temporal", "classify", "escalate", "exclude", "note", "ask"]
    result = consult(
        pipeline,
        "Xe máy chạy 75 km/h ở đoạn giới hạn 50 km/h",
        options=OFFLINE.model_copy(update={"enabled_rule_types": types}),
    )
    assert result.violations == []


# --- grounder -----------------------------------------------------------------

PHRASE = "Ô tô của tôi dừng ngay trên cầu"


def grounded(candidates, **options):
    retriever = FakeRetriever({PHRASE: candidates})
    pipeline = ExpertPipeline(retriever=retriever)
    result = consult(pipeline, PHRASE, options=OFFLINE.model_copy(update=options))
    return retriever, result


def citation_without_act():
    """A violation without an Act, i.e. reachable only through classify_auto."""
    kb = get_knowledge_base()
    return next(
        cid
        for cid, row in kb.violations.items()
        if row["vehicle_class"] == "VEH_CAR" and cid not in kb.citation_acts
    )


def test_every_violation_without_act_has_a_grounding_rule():
    kb = get_knowledge_base()
    covered = {rule.when.get("grounded_violation") for rule in kb.rules}
    acts_by_citation = OntologyGrounder(FakeRetriever(), kb).acts_by_citation
    assert set(kb.violations) - set(acts_by_citation) <= covered


def test_grounder_accepts_clear_candidate_and_traces_scores():
    cid = citation_without_act()
    retriever, result = grounded([(cid, 1.0, 0.9), ("ND168-D6-K1-Pa", 0.6, 0.8)])
    assert [v.citation_id for v in result.violations] == [cid]
    step = result.explanation.chain[0]
    assert (step.rule_id, step.type) == (GROUND_RULE_ID, "ground")
    assert step.matched_facts["candidates"][0] == {"citation_id": cid, "hybrid": 1.0, "cosine": 0.9}
    assert "ánh xạ tự động" in result.answer_text
    assert result.explanation.faithfulness_ok
    family = retriever.calls[0][1]["vehicle_classes"]
    assert family == {"VEH_CAR", "VEH_MOTOR", "VEH_ANY"}


@pytest.mark.parametrize(
    "top,second",
    [
        ((0.7, 0.9), (0.2, 0.8)),  # below GROUND_THRESHOLD
        ((1.0, 0.9), (0.97, 0.9)),  # margin below 0.05
        ((1.0, 0.8), (0.5, 0.7)),  # distinct but not semantically close
    ],
)
def test_grounder_rejects_weak_candidate(top, second):
    cid = citation_without_act()
    _, result = grounded([(cid, *top), ("ND168-D6-K1-Pa", *second)])
    assert result.status == "unknown"
    assert result.explanation.chain[0].produced == {}


def test_grounder_maps_core_violation_to_its_act():
    _, result = grounded([("ND168-D6-K6-Pc", 1.0, 0.9)])
    # The alcohol level is still unknown, so the engine asks instead of guessing.
    assert result.status == "need_info"
    assert result.violations == []
    assert "ACT_ALCOHOL" in result.facts.acts


def test_grounder_can_be_disabled():
    retriever, result = grounded([(citation_without_act(), 1.0, 0.9)], use_grounder=False)
    assert retriever.calls == [] and result.status == "unknown"
