"""Driving-licence acts (NĐ 168 Điều 18) and signal rules for Điều 9, 10."""

import re
from pathlib import Path

import pytest

from src.reasoning.engine import InferenceEngine
from src.reasoning.extractor_llm import sanitize_facts
from src.reasoning.extractor_regex import RegexExtractor
from src.reasoning.knowledge_base import get_knowledge_base

PROCESSED = Path(__file__).resolve().parents[1] / "data" / "processed" / "nghi_dinh_168.txt"
LICENSE_ACTS = (
    "ACT_NO_LICENSE", "ACT_LICENSE_MISMATCH", "ACT_LICENSE_EXPIRED", "ACT_LICENSE_NOT_CARRIED",
)
NEW_CLASSIFY = re.compile(r"R-CLS-(LIC-|RED-BIKE|RED-PED)")


@pytest.fixture(scope="module")
def kb():
    return get_knowledge_base()


def test_new_excerpts_are_verbatim(kb):
    source = PROCESSED.read_text(encoding="utf-8")
    rules = [r for r in kb.rules if NEW_CLASSIFY.match(r.id) or r.id == "R-NOTE-LIC-PRIVATE"]
    assert len(rules) == 13
    for rule in rules:
        assert rule.legal_excerpt in source, rule.id
        if rule.type == "classify":
            assert rule.legal_excerpt in kb.legal_texts[rule.then["add_violation"]], rule.id


@pytest.mark.parametrize(
    "facts,expected",
    [
        ({"vehicle_class": "VEH_BICYCLE_RUDIMENTARY", "acts": ["ACT_RED_LIGHT"]}, "ND168-D9-K2-Pđ"),
        ({"vehicle_class": "VEH_PEDESTRIAN", "acts": ["ACT_RED_LIGHT"]}, "ND168-D10-K1-Pb"),
        *[
            ({"vehicle_class": "VEH_MOTORBIKE", "acts": [act], **slots}, citation)
            for act, slots, citation in (
                ("ACT_NO_LICENSE", {"engine_capacity_cc": 125}, "ND168-D18-K5-Pa"),
                ("ACT_NO_LICENSE", {"engine_capacity_cc": 126}, "ND168-D18-K7-Pb"),
                ("ACT_NO_LICENSE", {"motor_power_kw": 11}, "ND168-D18-K5-Pa"),
                ("ACT_LICENSE_MISMATCH", {"motorbike_type": "MOTO_UP_TO_125"}, "ND168-D18-K5-Pa"),
                ("ACT_LICENSE_MISMATCH", {"motorbike_type": "MOTO_OVER_125"}, "ND168-D18-K7-Pa"),
                ("ACT_LICENSE_NOT_CARRIED",
                 {"motorbike_type": "MOTO_OVER_125", "transport_use": "TRANSPORT_COMMERCIAL"},
                 "ND168-D18-K2-Pd"),
            )
        ],
        *[
            ({"vehicle_class": "VEH_CAR", "acts": [act], **slots}, citation)
            for act, slots, citation in (
                ("ACT_NO_LICENSE", {}, "ND168-D18-K9-Pb"),
                ("ACT_LICENSE_MISMATCH", {}, "ND168-D18-K9-Pa"),
                ("ACT_LICENSE_EXPIRED", {"license_expired_months": 11}, "ND168-D18-K8-Pa"),
                ("ACT_LICENSE_EXPIRED", {"license_expired_months": 12}, "ND168-D18-K9-Pa"),
                ("ACT_LICENSE_NOT_CARRIED", {"transport_use": "TRANSPORT_COMMERCIAL"},
                 "ND168-D18-K3-Pa"),
            )
        ],
    ],
)
def test_classification(kb, facts, expected):
    result = InferenceEngine(kb).run(facts)
    assert result.status == "answered"
    assert [hit.citation_id for hit in result.hits] == [expected]


@pytest.mark.parametrize(
    "act,vehicle,slot",
    [
        ("ACT_NO_LICENSE", "VEH_MOTORBIKE", "motorbike_type"),
        ("ACT_LICENSE_EXPIRED", "VEH_CAR", "license_expiry"),
        ("ACT_LICENSE_NOT_CARRIED", "VEH_CAR", "transport_use"),
    ],
)
def test_missing_slot_is_asked(kb, act, vehicle, slot):
    result = InferenceEngine(kb).run({"vehicle_class": vehicle, "acts": [act]})
    assert result.status == "need_info"
    assert result.questions[0].slot == slot


@pytest.mark.parametrize(
    "facts",
    [
        {"vehicle_class": "VEH_MOTORBIKE", "acts": ["ACT_NO_LICENSE"], "motorbike_type": "MOTO_MOPED"},
        {"vehicle_class": "VEH_CAR", "acts": ["ACT_LICENSE_NOT_CARRIED"],
         "transport_use": "TRANSPORT_PRIVATE"},
        {"vehicle_class": "VEH_MOTORBIKE", "acts": ["ACT_LICENSE_EXPIRED"]},
    ],
)
def test_no_provision_gives_a_note_and_no_violation(kb, facts):
    result = InferenceEngine(kb).run(facts)
    assert result.status == "unknown" and not result.hits and result.notes


@pytest.mark.parametrize(
    "message,slot,value",
    [
        ("xe máy 150 phân khối không có bằng lái", "engine_capacity_cc", 150),
        ("xe mô tô trên 125 cm3 không có bằng lái", "motorbike_type", "MOTO_OVER_125"),
        ("ô tô, bằng lái hết hạn chưa đến 1 năm", "license_expiry", "LIC_EXPIRED_UNDER_1Y"),
        ("ô tô, bằng lái hết hạn 2 năm", "license_expired_months", 24),
        ("tôi không kinh doanh vận tải, quên mang bằng lái", "transport_use", "TRANSPORT_PRIVATE"),
    ],
)
def test_regex_reads_license_slots(kb, message, slot, value):
    facts = RegexExtractor(kb).extract(message).facts
    assert getattr(facts, slot) == value
    assert facts.actual_speed_kmh is None


def test_license_slots_are_never_taken_from_the_llm(kb):
    guessed = {
        "vehicle_class": "VEH_MOTORBIKE", "acts": ["ACT_NO_LICENSE"],
        "motorbike_type": "MOTO_UP_TO_125", "engine_capacity_cc": 110,
        "transport_use": "TRANSPORT_PRIVATE",
    }
    facts, _ = sanitize_facts(guessed, "đi xe máy không có bằng lái", kb)
    assert facts.motorbike_type is None
    assert facts.engine_capacity_cc is None and facts.transport_use is None


def test_every_license_act_has_a_draft_case():
    text = (PROCESSED.parents[1] / "eval" / "test_cases.draft.jsonl").read_text(encoding="utf-8")
    for act in LICENSE_ACTS:
        assert act in text
