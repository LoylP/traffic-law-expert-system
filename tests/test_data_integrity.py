import json
from pathlib import Path

import pytest

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


def _violations_by_citation() -> dict[str, dict]:
    path = STRUCTURED / "violations_168_clean.json"
    return {row["citation_id"]: row for row in json.loads(path.read_text(encoding="utf-8"))}


@pytest.mark.parametrize(
    ("citation_id", "points"),
    [
        ("ND168-D6-K6-Pa", 4),  # D6-K16-Pb: "khoản 6"
        ("ND168-D6-K10-Pa", 10),  # D6-K16-Pd: "khoản 10"
        ("ND168-D6-K10-Pb", 10),
        ("ND168-D6-K8", 6),  # D6-K16-Pc: "khoản 8"
        ("ND168-D7-K5-Pa", 2),  # D7-K13-Pa: "khoản 5"
        ("ND168-D7-K10-Pa", 10),  # D7-K13-Pd: "khoản 10"
        ("ND168-D7-K2-Ph", 0),  # not referenced by D7-K13
    ],
)
def test_points_deducted_including_whole_clause_references(
    citation_id: str, points: int
) -> None:
    assert _violations_by_citation()[citation_id]["points_deducted"] == points


@pytest.mark.parametrize(
    ("article", "clause", "expected"),
    [
        # Điều 12 khoản 15: "hành vi quy định tại khoản 14 Điều này ... hình thức
        # xử phạt bổ sung tước quyền sử dụng GPLX từ 22 tháng đến 24 tháng".
        (12, "14", {"type": "revoke_license", "duration_min": 22, "duration_max": 24}),
        # Điều 13 khoản 11 điểm a: "khoản 1; khoản 2; ... Điều này buộc lắp đầy đủ
        # thiết bị ..." (biện pháp khắc phục hậu quả).
        (13, "2", {"type": "remedy"}),
        # Điều 38 khoản 3: "Tịch thu phương tiện ... tái phạm hành vi quy định tại
        # khoản 1, khoản 2 Điều này". Điều 38 khoản 4 uses the same references.
        (38, "1", {"type": "confiscate"}),
        (38, "2", {"type": "remedy"}),
    ],
)
def test_whole_clause_sanction_reference_covers_every_point(
    article: int, clause: str, expected: dict
) -> None:
    members = [
        row
        for row in _violations_by_citation().values()
        if row["article"] == article and row["clause"] == clause
    ]
    assert len(members) > 1
    assert all(expected in row["sanctions"] for row in members)


@pytest.mark.parametrize(
    "citation_id",
    [
        "ND168-D18-K2-Pb",  # "bảo hiểm bắt buộc" is not a remedial measure
        "ND168-D20-K3-Pđ",  # "chằng buộc hành lý"
        "ND168-D32-K7-Pb",  # only in "(trừ trường hợp bị tịch thu phương tiện)"
    ],
)
def test_wording_and_carve_outs_do_not_create_sanctions(citation_id: str) -> None:
    sanctions = _violations_by_citation()[citation_id]["sanctions"]
    forbidden = "confiscate" if citation_id.startswith("ND168-D32") else "remedy"
    assert forbidden not in {item["type"] for item in sanctions}


@pytest.mark.parametrize(
    "citation_id,duration",
    [
        # Alcohol level 3, car (Điều 6 khoản 15 điểm c) and motorbike (Điều 7 khoản 12 điểm c).
        ("ND168-D6-K11-Pa", (22, 24)),
        ("ND168-D7-K9-Pd", (22, 24)),
        # Whole-point list, Điều 7 khoản 12 điểm b.
        ("ND168-D7-K9-Pa", (10, 12)),
    ],
)
def test_license_revocation_months_match_the_text(
    citation_id: str, duration: tuple[int, int]
) -> None:
    sanctions = _violations_by_citation()[citation_id]["sanctions"]
    revoke = [item for item in sanctions if item["type"] == "revoke_license"]
    assert revoke == [
        {"type": "revoke_license", "duration_min": duration[0], "duration_max": duration[1]}
    ]


@pytest.mark.parametrize(
    "citation_id",
    [
        "ND168-D6-K4-Pa",  # polluted by "buộc phải dừng xe" in a sibling point
        "ND168-D8-K6-Pc",  # same, alcohol level 1 for non-motor vehicles
        "ND168-D18-K2-Pc",  # "bảo hiểm bắt buộc"
        "ND168-D20-K3-Pa",  # "chằng buộc"
    ],
)
def test_buoc_in_behaviour_wording_is_not_a_remedy(citation_id: str) -> None:
    assert _violations_by_citation()[citation_id]["sanctions"] == []


@pytest.mark.parametrize(
    "citation_id,source,base_source",
    [
        ("ND168-D20-K2", "ND168-D20-K10-Pd", "ND168-D20-K10-Pb"),
        ("ND168-D20-K4", "ND168-D20-K10-Pd", "ND168-D20-K10-Pb"),
        ("ND168-D32-K5", "ND168-D32-K21-Ph", "ND168-D32-K21-Pd"),
        ("ND168-D32-K6", "ND168-D32-K21-Ph", "ND168-D32-K21-Pd"),
    ],
)
def test_conditional_points_keep_the_base_value(
    citation_id: str, source: str, base_source: str
) -> None:
    row = _violations_by_citation()[citation_id]
    assert row["points_deducted"] == 4
    [item] = row["points_conditional"]
    assert (item["points"], item["source"]) == (10, source)
    assert "vượt trên 100% số người" in item["condition"]
    assert base_source != item["source"]
    corpus = [
        json.loads(line)
        for line in (ROOT / "data/structured/law_corpus.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    [unit] = [unit for unit in corpus if unit["citation_id"] == source]
    assert item["condition"] in unit["text"]


def test_only_those_rows_have_conditional_points() -> None:
    conditional = {
        cid for cid, row in _violations_by_citation().items() if row["points_conditional"]
    }
    assert conditional == {"ND168-D20-K2", "ND168-D20-K4", "ND168-D32-K5", "ND168-D32-K6"}
