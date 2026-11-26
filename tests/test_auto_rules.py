"""Tests for classify_auto generation, grounded matching and the extended KG."""

import json
from pathlib import Path

import pytest
import yaml

from src.reasoning.engine import InferenceEngine
from src.reasoning.gen_auto_rules import build_rules, core_citations

ROOT = Path(__file__).resolve().parents[1]
RULES = ROOT / "data" / "knowledge" / "rules"


def _violations() -> list[dict]:
    path = ROOT / "data" / "structured" / "violations_168_clean.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _rules(name: str) -> list[dict]:
    return yaml.safe_load((RULES / name).read_text(encoding="utf-8"))["rules"]


def _jsonl(name: str) -> list[dict]:
    with (ROOT / "data" / "kg" / name).open(encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


@pytest.fixture(scope="module")
def engine() -> InferenceEngine:
    return InferenceEngine()


def test_auto_file_is_up_to_date_and_complements_core():
    violations = _violations()
    skip = core_citations(_rules("classify_core.yaml"))
    auto = _rules("classify_auto.yaml")
    assert auto == build_rules(violations, skip)
    covered = {rule["then"]["add_violation"] for rule in auto}
    assert covered.isdisjoint(skip)
    assert covered | skip == {item["citation_id"] for item in violations}


def test_auto_priority_is_below_core():
    lowest_core = min(
        rule["priority"] for rule in _rules("classify_core.yaml") if rule["type"] == "classify"
    )
    assert all(rule["priority"] < lowest_core for rule in _rules("classify_auto.yaml"))


@pytest.mark.parametrize(
    "rule_class,vehicle,fires",
    [
        ("VEH_MOTOR", "VEH_CAR", True),
        ("VEH_MOTOR", "VEH_MOTORBIKE", True),
        ("VEH_MOTOR", "VEH_BICYCLE_RUDIMENTARY", False),
        ("VEH_MOTOR", None, False),
        ("VEH_ANY", "VEH_PEDESTRIAN", True),
        ("VEH_ANY", None, True),
        ("VEH_CAR", "VEH_MOTOR", False),
        ("VEH_CAR", "VEH_MOTORBIKE", False),
    ],
)
def test_grounded_violation_respects_vehicle_hierarchy(engine, rule_class, vehicle, fires):
    rule = next(
        r for r in _rules("classify_auto.yaml") if r["when"]["vehicle_class"] == rule_class
    )
    citation = rule["then"]["add_violation"]
    result = engine.infer({"vehicle_class": vehicle, "grounded_violations": [citation]})
    assert (citation in {hit.citation_id for hit in result.violations}) is fires


def test_auto_rules_do_not_fire_without_grounding(engine):
    result = engine.infer({"vehicle_class": "VEH_CAR"})
    assert result.violations == []


def test_kg_has_knowledge_nodes_and_edges():
    nodes = {node["id"]: node for node in _jsonl("kg_nodes.jsonl")}
    edges = _jsonl("kg_edges.jsonl")
    assert {
        "Act", "VehicleClass", "RoadType", "TimeContext", "AlcoholLevel", "SpeedBand",
        "Consequence", "ResistanceBehavior", "Circumstance", "Subject",
    } <= {node["type"] for node in nodes.values()}
    assert all(edge["source"] in nodes and edge["target"] in nodes for edge in edges)

    expected = {
        "INSTANCE_OF_ACT": ("Violation", {"Act"}),
        "REQUIRES_CONTEXT": ("Violation", {"RoadType", "TimeContext", "AlcoholLevel", "SpeedBand"}),
        "ESCALATES_TO": ("Violation", {"Violation"}),
    }
    for relation, (source_type, target_types) in expected.items():
        matching = [edge for edge in edges if edge["relation"] == relation]
        assert matching, relation
        for edge in matching:
            assert nodes[edge["source"]]["type"] == source_type
            assert nodes[edge["target"]]["type"] in target_types
