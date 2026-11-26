"""Nothing is filled in that the user did not say; missing slots that change the
result are asked one at a time (offline: RegexExtractor + template answer)."""

import pytest

from src.reasoning.engine import InferenceEngine
from src.reasoning.extractor_llm import FEW_SHOT, build_schema, sanitize_facts
from src.reasoning.extractor_regex import RegexExtractor
from src.reasoning.knowledge_base import get_knowledge_base
from src.reasoning.pipeline import MAX_QUESTION_ROUNDS, ConsultOptions, ExpertPipeline

OFFLINE = ConsultOptions(use_llm_extractor=False, use_llm_writer=False)


@pytest.fixture(scope="module")
def pipeline():
    return ExpertPipeline()


def consult(pipeline, *turns):
    result = None
    for message in turns:
        session = result.session_id if result else None
        result = pipeline.consult(message, session, OFFLINE)
    return result


def citations(violations):
    return [v.citation_id for v in violations]


# (message, status, first asked slot, determined citations)
CASES = [
    ("nhậu xong chạy xe về", "need_info", "vehicle_class", []),
    ("nhậu xong chạy xe máy về", "need_info", "alcohol_level", []),
    ("lái ô tô đo được 0,3 mg/l", "answered", None, ["ND168-D6-K9-Pa"]),
    ("chạy xe quá tốc độ", "need_info", "vehicle_class", []),
    ("ô tô chạy quá tốc độ", "need_info", "speed_band", []),
    ("ô tô chạy 80 km/h ở đoạn giới hạn 60", "answered", None, ["ND168-D6-K5-Pđ"]),
    ("không thắt dây an toàn", "answered", None, ["ND168-D6-K3-Pk"]),
    ("không đội mũ bảo hiểm", "answered", None, ["ND168-D7-K2-Ph"]),
    ("vượt đèn đỏ", "need_info", "vehicle_class", []),
    ("đi xe máy ngược chiều trên cao tốc", "answered", None, ["ND168-D7-K7-Pa"]),
    # The road changes the article for a car, so it is asked.
    ("ô tô đi ngược chiều", "need_info", "road_type", []),
    ("xe máy vượt đèn đỏ, trước đây bị phạt rồi", "answered", None, ["ND168-D7-K7-Pc"]),
]


@pytest.mark.parametrize("message,status,slot,expected", CASES)
def test_case(pipeline, message, status, slot, expected):
    result = consult(pipeline, message)
    assert result.status == status
    assert citations(result.violations) == expected
    assert result.branches == []
    if slot is None:
        assert result.questions == []
    else:
        assert [q.slot for q in result.questions] == [slot]  # one question per turn
        assert result.questions[0].options[-1].label == "Không rõ"


@pytest.mark.parametrize(
    "message",
    [
        "nhậu xong chạy xe về",
        "đi xe ngoài đường phóng nhanh",
        "lái xe chạy nhanh quá",
        "tôi có uống chút rồi về bằng xe",
        "bị bắt mấy lần rồi",
        "xe máy vượt đèn đỏ, trước đây bị phạt rồi",
    ],
)
def test_generic_wording_fills_nothing_it_does_not_say(message):
    facts = RegexExtractor().extract(message).facts
    if "xe máy" not in message:
        assert facts.vehicle_class is None
    assert "ACT_SPEEDING" not in facts.acts and facts.speed_over_kmh is None
    assert facts.road_type is None and facts.time_context is None
    assert facts.bac_breath_mg_l is None and facts.alcohol_level is None
    assert facts.circumstances == [] and facts.consequence == [] and facts.resistance == []


def test_a_little_drink_is_only_drinking():
    facts = RegexExtractor().extract("tôi có uống chút rồi lái ô tô").facts
    assert facts.drank_alcohol is True and facts.acts == []


@pytest.mark.parametrize(
    "message", ["đây là lần tái phạm", "tôi đã bị phạt lỗi này, nay đi xe máy vượt đèn đỏ"]
)
def test_explicit_repeat_is_kept(message):
    assert "CIR_REPEAT" in RegexExtractor().extract(message).facts.circumstances


@pytest.mark.parametrize(
    "message,rule_id,vehicle",
    [
        ("không thắt dây an toàn", "R-DER-VEH-01", "VEH_CAR"),
        ("không đội mũ bảo hiểm", "R-DER-VEH-02", "VEH_MOTORBIKE"),
    ],
)
def test_vehicle_comes_from_a_derive_rule_not_the_extractor(pipeline, message, rule_id, vehicle):
    assert RegexExtractor().extract(message).facts.vehicle_class is None
    result = consult(pipeline, message)
    assert result.facts.vehicle_class == vehicle
    step = next(s for s in result.explanation.chain if s.rule_id == rule_id)
    assert step.type == "derive" and step.source
    assert step.produced["set_facts"] == {"vehicle_class": vehicle}
    entry = next(f for f in result.explanation.facts_used if f.field == "vehicle_class")
    assert entry.origin == "derived" and rule_id in entry.derived_from
    assert any("suy ra" in note for note in result.notes)


def test_stated_vehicle_is_never_overridden(pipeline):
    result = consult(pipeline, "đi xe đạp không đội mũ bảo hiểm")
    assert result.facts.vehicle_class == "VEH_BICYCLE_RUDIMENTARY"


def test_recorded_facts_are_stated_or_derived(pipeline):
    result = consult(pipeline, "nhậu xong chạy xe về")
    stated = {f.field for f in result.explanation.facts_used if f.origin == "user"}
    assert stated == {"drank_alcohol"}
    derived = [f for f in result.explanation.facts_used if f.origin == "derived"]
    assert [(f.field, f.value) for f in derived] == [("acts", ["ACT_ALCOHOL"])]
    assert "uống rượu" in derived[0].derived_from


def test_unknown_alcohol_level_lists_three_branches(pipeline):
    first = consult(pipeline, "lái ô tô có nồng độ cồn")
    assert [q.slot for q in first.questions] == ["alcohol_level"]
    result = pipeline.consult("Không rõ", first.session_id, OFFLINE)
    assert result.status == "answered"
    assert result.questions == [] and result.violations == []
    assert result.total_recommended_fine == 0
    assert result.depends_on == ["mức nồng độ cồn"]
    assert [citations(b.violations) for b in result.branches] == [
        ["ND168-D6-K6-Pc"],
        ["ND168-D6-K9-Pa"],
        ["ND168-D6-K11-Pa"],
    ]
    assert all(v.fine_range and v.legal_text for b in result.branches for v in b.violations)
    assert [b.conditions[0].values for b in result.branches] == [["BAC_L1"], ["BAC_L2"], ["BAC_L3"]]
    assert "phụ thuộc vào mức nồng độ cồn" in result.answer_text
    assert result.facts.alcohol_level is None and result.facts.bac_breath_mg_l is None


def test_unknown_vehicle_is_not_asked_again_and_keeps_asking_the_rest(pipeline):
    result = consult(pipeline, "chạy xe quá tốc độ", "Không rõ")
    assert [q.slot for q in result.questions] == ["speed_band"]
    result = pipeline.consult("không biết", result.session_id, OFFLINE)
    assert result.status == "answered"
    assert set(result.depends_on) == {"loại phương tiện", "mức vượt tốc độ"}
    cited = {c for b in result.branches for c in citations(b.violations)}
    assert {"ND168-D6-K3-Pa", "ND168-D7-K2-Pb"} <= cited


def test_determined_violation_stays_outside_the_branches(pipeline):
    result = consult(pipeline, "ô tô vượt đèn đỏ rồi đi ngược chiều", "Không rõ")
    assert citations(result.violations) == ["ND168-D6-K9-Pb"]
    assert [citations(b.violations) for b in result.branches] == [
        ["ND168-D6-K11-Pđ"],
        ["ND168-D6-K9-Pd"],
    ]


def test_range_answer_records_no_measured_value(pipeline):
    result = consult(pipeline, "ô tô chạy quá tốc độ", "Vượt trên 20 đến 35 km/h")
    assert citations(result.violations) == ["ND168-D6-K6-Pa"]
    assert result.facts.speed_band == "SPEED_20_35" and result.facts.speed_over_kmh is None


def test_typed_number_answers_a_range_question(pipeline):
    result = consult(pipeline, "ô tô chạy quá tốc độ", "15 km/h")
    assert result.facts.speed_over_kmh == 15
    assert citations(result.violations) == ["ND168-D6-K5-Pđ"]


@pytest.mark.parametrize(
    "message,field",
    [
        ("ô tô chạy 80 km/h, quá tốc độ", "speed_limit_kmh"),
        ("ô tô chạy quá tốc độ ở đoạn giới hạn 60 km/h", "actual_speed_kmh"),
    ],
)
def test_only_the_missing_half_of_the_speed_is_asked(pipeline, message, field):
    result = consult(pipeline, message)
    assert [(q.slot, q.field) for q in result.questions] == [("speed_band", field)]


def test_question_limit_turns_remaining_slots_into_branches(pipeline):
    result = consult(pipeline, "chạy xe quá tốc độ")
    for _ in range(MAX_QUESTION_ROUNDS - 1):
        result = pipeline.consult("hmm", result.session_id, OFFLINE)
        assert result.status == "need_info"
    result = pipeline.consult("hmm", result.session_id, OFFLINE)
    assert result.status == "answered" and result.questions == [] and result.branches


def test_slot_that_does_not_change_the_result_is_not_asked():
    engine = InferenceEngine()
    motorbike = engine.run({"vehicle_class": "VEH_MOTORBIKE", "acts": ["ACT_WRONG_WAY"]})
    assert motorbike.status == "answered" and motorbike.questions == []
    red_light = engine.run({"vehicle_class": "VEH_CAR", "acts": ["ACT_RED_LIGHT"]})
    assert red_light.questions == []  # speed, alcohol, road are irrelevant


def test_every_classify_condition_is_a_slot_or_deliberately_not_asked():
    """A new condition in classify_core must get an ask slot or be listed here."""
    kb = get_knowledge_base()
    slots = [r for r in kb.rules_of("ask") if r.then.get("options")]
    fields = {r.then["ask_field"] for r in slots}
    values = {o["value"] for r in slots for o in r.then["options"]}
    not_asked = {"has_act", "passenger_exception", "passenger_helmet_exception", "grounded_violation"}
    for rule in kb.rules_of("classify"):
        for key, condition in rule.when.items():
            if key == "has_context":
                assert set(condition if isinstance(condition, list) else [condition]) <= values
            else:
                assert key in fields | not_asked, (rule.id, key)


# --- LLM extractor (no network) -----------------------------------------------


def test_schema_allows_null_everywhere():
    for name, spec in build_schema(get_knowledge_base())["properties"].items():
        assert {"type": "null"} in spec["anyOf"], name


def test_few_shots_contrast_vague_and_explicit_wording():
    vague = FEW_SHOT[0][1]
    assert "vehicle_class" not in vague and "road_type" not in vague and "circumstances" not in vague
    assert FEW_SHOT[1][1]["vehicle_class"] == "VEH_CAR"
    assert "vehicle_class" not in FEW_SHOT[2][1]


def test_sanitize_removes_guesses_from_a_vague_message():
    guessed = {
        "vehicle_class": "VEH_MOTORBIKE",
        "acts": ["ACT_SPEEDING"],
        "road_type": "ROAD_NORMAL",
        "time_context": "TIME_NIGHT",
        "consequence": ["CONS_ACCIDENT"],
        "resistance": ["RES_FLEE"],
        "officer_signal": True,
        "circumstances": ["CIR_REPEAT", "CIR_MULTIPLE_TIMES"],
        "passenger_exception": True,
    }
    facts, _ = sanitize_facts(
        guessed, "chạy xe ngoài đường phóng nhanh, bị bắt mấy lần rồi", get_knowledge_base()
    )
    assert facts.model_dump(exclude_defaults=True) == {}


def test_sanitize_adds_no_inferred_fact():
    facts, _ = sanitize_facts(
        {"drank_alcohol": True}, "nhậu xong chạy xe về", get_knowledge_base()
    )
    assert facts.acts == [] and facts.vehicle_class is None
