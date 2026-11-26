"""Offline tests for PenaltyDecider, Explainer and the CLI."""

import re
import subprocess
import sys
import unicodedata
from pathlib import Path

import pytest
import yaml

from src.reasoning import cli, knowledge_base
from src.reasoning.engine import InferenceEngine
from src.reasoning.explain import Explainer, render_markdown
from src.reasoning.knowledge_base import KnowledgeBase, get_knowledge_base
from src.reasoning.penalty import PenaltyDecider, apply_net, round_to_thousand
from src.reasoning.schema import ViolationHit

ROOT = Path(__file__).resolve().parents[1]
RED_MOTO = "ND168-D7-K7-Pc"  # 4tr–6tr, 4 points
ALC_CAR_L2 = "ND168-D6-K9-Pa"  # 18tr–20tr, 10 points
HELMET = "ND168-D7-K2-Ph"  # 400k–600k, 0 points
OVERLOAD = "ND168-D7-K3-Pb"  # 600k–800k, 2 points
INSULT_VIOLATION = "ND168-D12-K14-Pa"

AGG = ["CIR_REPEAT", "CIR_ORGANIZED", "CIR_CONCEAL"]
MIT = ["CIR_VOLUNTARY_CONFESS", "CIR_PREVENT_HARM", "CIR_HARDSHIP"]


@pytest.fixture(scope="module")
def decider() -> PenaltyDecider:
    return PenaltyDecider()


def hits(*citation_ids: str) -> list[ViolationHit]:
    return [ViolationHit(citation_id=cid, rule_id="TEST") for cid in citation_ids]


@pytest.mark.parametrize(
    "circumstances,net,recommended,allowed",
    [
        ([], 0, 5_000_000, (5_000_000, 5_000_000)),
        (AGG[:1], 1, 5_500_000, (5_000_000, 6_000_000)),
        (MIT[:1], -1, 4_500_000, (4_000_000, 5_000_000)),
        (AGG[:2], 2, 6_000_000, (6_000_000, 6_000_000)),
        (MIT[:2], -2, 4_000_000, (4_000_000, 4_000_000)),
        (AGG, 3, 6_000_000, (6_000_000, 6_000_000)),
        (MIT, -3, 4_000_000, (4_000_000, 4_000_000)),
        (AGG[:2] + MIT[:1], 1, 5_500_000, (5_000_000, 6_000_000)),
        (AGG[:1] + MIT[:1], 0, 5_000_000, (5_000_000, 5_000_000)),
    ],
)
def test_net_circumstances(decider, circumstances, net, recommended, allowed):
    summary = decider.decide_hits(hits(RED_MOTO), circumstances)
    decision = summary.decisions[0]
    assert summary.net == net
    assert decision.fine_range == (4_000_000, 6_000_000)
    assert decision.recommended_fine == recommended
    assert decision.allowed_range_after_circumstances == allowed


def test_offsetting_is_explained(decider):
    summary = decider.decide_hits(hits(RED_MOTO), AGG[:2] + MIT[:1])
    assert any("bù trừ" in line for line in summary.reasoning)


@pytest.mark.parametrize("value,expected", [(1_499, 1_000), (1_500, 2_000), (2_000, 2_000)])
def test_round_to_thousand(value, expected):
    assert round_to_thousand(value) == expected


def test_recommended_fine_is_rounded():
    recommended, _, _ = apply_net(100_000, 201_000, 1)  # midpoint 175.750
    assert recommended == 176_000


def test_organization_uses_data_range_when_available(decider):
    decision = decider.decide_hits(hits("ND168-D12-K10"), subject="SUBJ_ORGANIZATION").decisions[0]
    assert decision.fine_range == (8_000_000, 12_000_000)
    assert decision.org_rule_applied is False


def test_organization_without_data_doubles_and_flags(decider):
    decision = decider.decide_hits(hits(RED_MOTO), subject="SUBJ_ORGANIZATION").decisions[0]
    assert decision.fine_range == (8_000_000, 12_000_000)
    assert decision.recommended_fine == 10_000_000
    assert decision.org_rule_applied is True


def test_multiple_violations_sum_fines(decider):
    summary = decider.decide_hits(hits(HELMET, OVERLOAD), ["CIR_REPEAT"])
    assert [d.recommended_fine for d in summary.decisions] == [550_000, 750_000]
    assert summary.total_recommended_fine == 1_300_000


def test_points_take_largest_value_only(decider):
    summary = decider.decide_hits(hits(RED_MOTO, OVERLOAD, HELMET))
    assert summary.total_points_deducted == 4
    assert summary.points_from == RED_MOTO
    assert any("Điều 50" in line for line in summary.reasoning)
    assert [d.points_deducted for d in summary.decisions] == [4, 2, 0]


def test_sanctions_are_returned_with_duration(decider):
    summary = decider.decide_hits(hits("ND168-D6-K11-Pa"))
    sanction = summary.sanctions[0]
    assert (sanction.type, sanction.duration_min, sanction.duration_max) == ("revoke_license", 22, 24)


def test_insult_not_counted_when_it_is_a_sanctioned_violation(decider):
    summary = decider.decide_hits(hits(RED_MOTO, INSULT_VIOLATION), ["CIR_INSULT_OFFICER"])
    assert summary.net == 0
    assert "CIR_INSULT_OFFICER" in summary.excluded_circumstances
    assert any("khoản 2 Điều 10" in line for line in summary.reasoning)
    assert summary.decisions[0].recommended_fine == 5_000_000


def test_insult_counted_without_that_violation(decider):
    summary = decider.decide_hits(hits(RED_MOTO), ["CIR_INSULT_OFFICER"])
    assert summary.net == 1


def test_overlap_excluded_when_unverified_knowledge_disabled(tmp_path, monkeypatch):
    kb = get_knowledge_base(include_unverified=False)
    assert all(rule.verified for rule in kb.rules)
    assert "CIR_INSULT_OFFICER" in kb.circumstance_overlaps  # verified overlap is kept

    data = yaml.safe_load(knowledge_base.CIRCUMSTANCES_PATH.read_text(encoding="utf-8"))
    for overlap in data["violation_overlaps"]:
        overlap["verified"] = False
    path = tmp_path / "circumstances.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr(knowledge_base, "CIRCUMSTANCES_PATH", path)

    strict = KnowledgeBase.load(include_unverified=False)
    assert "CIR_INSULT_OFFICER" not in strict.circumstance_overlaps


def test_unknown_and_duplicate_circumstances(decider):
    summary = decider.decide_hits(hits(RED_MOTO), ["CIR_NOPE", "CIR_REPEAT", "CIR_REPEAT"])
    assert summary.net == 1
    assert "CIR_NOPE" in summary.excluded_circumstances


def test_no_hits(decider):
    summary = decider.decide_hits([])
    assert summary.total_recommended_fine == 0
    assert summary.total_points_deducted == 0


def test_knowledge_base_is_cached_and_overlap_excerpt_is_verbatim():
    kb = get_knowledge_base()
    assert kb is get_knowledge_base()
    assert isinstance(kb, KnowledgeBase)
    for overlap in kb.circumstance_overlaps.values():
        assert any(overlap["legal_excerpt"] in kb.legal_texts[cid] for cid in overlap["violations"])


def test_explanation_is_faithful_with_verbatim_citation():
    result = InferenceEngine().run(
        {"vehicle_class": "VEH_MOTORBIKE", "acts": ["ACT_RED_LIGHT"], "evidence": {"acts": "vượt đèn đỏ"}}
    )
    explainer = Explainer()
    explanation = explainer.explain(result, PenaltyDecider().decide(result))
    citation = explanation.legal_citations[0]
    assert citation.label == "NĐ 168/2024, Điều 7 Khoản 7 Điểm c"
    assert citation.text == explainer.kb.legal_texts[RED_MOTO]
    assert explanation.faithfulness_ok
    assert next(f for f in explanation.facts_used if f.field == "acts").evidence == "vượt đèn đỏ"
    markdown = render_markdown(explanation)
    assert "R-CLS-RED-MOTO" in markdown and "5.000.000 đồng" in markdown


def test_explanation_flags_penalty_outside_inferred_set():
    result = InferenceEngine().run({"vehicle_class": "VEH_MOTORBIKE", "acts": ["ACT_RED_LIGHT"]})
    foreign = PenaltyDecider().decide_hits(hits(HELMET))
    assert not Explainer().explain(result, foreign).faithfulness_ok


@pytest.mark.parametrize("path", sorted((ROOT / "examples").glob("facts_*.json")), ids=lambda p: p.stem)
def test_cli_examples(path, capsys):
    cli.main(["--facts", str(path)])
    out = capsys.readouterr().out
    assert "# Kết quả: answered" in out
    assert "Kiểm tra trung thành trích dẫn: đạt" in out


def test_core_runs_without_network_or_llm_library():
    # `socket` itself is pulled in by the standard library, so connections are blocked instead.
    code = """
import socket, sys

def blocked(*args, **kwargs):
    raise RuntimeError("network access")

socket.socket.connect = socket.create_connection = socket.getaddrinfo = blocked

from src.reasoning.engine import InferenceEngine
from src.reasoning.explain import Explainer, render_markdown
from src.reasoning.penalty import PenaltyDecider

result = InferenceEngine().run({"vehicle_class": "VEH_CAR", "speed_over_kmh": 15})
render_markdown(Explainer().explain(result, PenaltyDecider().decide(result)))
banned = ("requests", "httpx", "urllib.request", "http.client", "openai", "google.genai",
          "sentence_transformers", "torch")
print([m for m in banned if m in sys.modules])
"""
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[]"


def test_conditional_points_are_explained_not_applied(decider):
    summary = decider.decide_hits(hits("ND168-D20-K2"))
    decision = summary.decisions[0]
    assert decision.points_deducted == summary.total_points_deducted == 4
    [item] = decision.points_conditional
    line = next(s for s in decision.reasoning if "có điều kiện" in s)
    assert item.condition in line and "10 điểm" in line and "chưa tự áp" in line


# Words seen glued to the previous one; no Vietnamese word ends right before them.
GLUED_RE = re.compile(r"[a-zà-ỹ](?:vượt|đúng|khoản)|điểm[ab] ?khoản|điểm bkhoản")


@pytest.mark.parametrize("path", sorted((ROOT / "examples").glob("*.json")), ids=lambda p: p.stem)
def test_example_output_has_no_glued_words(path, capsys):
    cli.main(["--facts", str(path)])  # result block + render_markdown
    output = unicodedata.normalize("NFC", capsys.readouterr().out)
    assert GLUED_RE.findall(output) == []
