import json
from pathlib import Path

from src.extract.legal_corpus_builder import canonical_citation_id

ROOT = Path(__file__).resolve().parents[1]
STRUCTURED = ROOT / "data/structured"
KG = ROOT / "data/kg"


def _read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


def test_citation_ids_normalize_optional_year() -> None:
    assert canonical_citation_id("ND168_2024-D7-K7-Pc") == "ND168-D7-K7-Pc"
    assert canonical_citation_id("ND168-D7-K7-Pc") == "ND168-D7-K7-Pc"


def test_every_violation_has_a_resolved_legal_unit() -> None:
    violations = json.loads(
        (STRUCTURED / "violations_168_clean.json").read_text(encoding="utf-8")
    )
    nodes = _read_jsonl(KG / "kg_nodes.jsonl")
    edges = _read_jsonl(KG / "kg_edges.jsonl")
    legal_ids = {
        node["citation_id"] for node in nodes if node.get("type") == "LegalUnit"
    }
    violation_nodes = {
        node["id"] for node in nodes if node.get("type") == "Violation"
    }
    based_on = [edge for edge in edges if edge["relation"] == "BASED_ON"]

    assert len(based_on) == len(violations)
    assert {edge["source"] for edge in based_on} == violation_nodes
    assert not any(edge["relation"] == "BASED_ON_UNRESOLVED" for edge in edges)
    assert all(edge["target"] in legal_ids for edge in based_on)


def test_violation_citations_and_legal_text_are_integral() -> None:
    violations = json.loads(
        (STRUCTURED / "violations_168_clean.json").read_text(encoding="utf-8")
    )
    law_ids = {
        canonical_citation_id(row["citation_id"])
        for row in _read_jsonl(STRUCTURED / "law_corpus.jsonl")
    }

    for violation in violations:
        citation_id = canonical_citation_id(violation["citation_id"])
        assert citation_id in law_ids
        assert violation["legal_text"].strip()
        if violation["article"] == 6:
            assert violation["vehicle_class"] == "VEH_CAR"
        elif violation["article"] == 7:
            assert violation["vehicle_class"] == "VEH_MOTORBIKE"
        elif violation["article"] == 8:
            assert violation["vehicle_class"] == "VEH_SPECIAL"


def test_fines_are_positive_and_ordered() -> None:
    violations = json.loads(
        (STRUCTURED / "violations_168_clean.json").read_text(encoding="utf-8")
    )
    for violation in violations:
        assert violation["fine_min"] > 0
        assert violation["fine_max"] > 0
        assert violation["fine_min"] <= violation["fine_max"]
        if violation["fine_org_min"] is not None:
            assert violation["fine_org_min"] >= violation["fine_min"]
            assert violation["fine_org_max"] is not None
            assert violation["fine_org_max"] >= violation["fine_org_min"]


def test_red_light_motorbike_spot_check() -> None:
    violations = json.loads(
        (STRUCTURED / "violations_168_clean.json").read_text(encoding="utf-8")
    )
    violation = next(
        row for row in violations if row["citation_id"] == "ND168-D7-K7-Pc"
    )
    assert violation["vehicle_class"] == "VEH_MOTORBIKE"
    assert "đèn tín hiệu" in violation["description"].lower()
