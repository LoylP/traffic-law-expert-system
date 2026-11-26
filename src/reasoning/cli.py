"""Run the offline reasoning core on a Facts JSON file.

    python -m src.reasoning.cli --facts examples/facts_red_light.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.reasoning.engine import InferenceEngine
from src.reasoning.explain import Explainer, render_markdown
from src.reasoning.knowledge_base import get_knowledge_base
from src.reasoning.penalty import PenaltyDecider, format_money
from src.reasoning.schema import EngineResult, Facts, PenaltySummary, Sanction

SANCTION_LABELS = {
    "revoke_license": "Tước quyền sử dụng GPLX",
    "confiscate": "Tịch thu",
    "remedy": "Biện pháp khắc phục hậu quả",
}


def _sanction_text(sanction: Sanction) -> str:
    text = SANCTION_LABELS.get(sanction.type, sanction.type)
    if sanction.duration_min is not None:
        text += f" {sanction.duration_min}–{sanction.duration_max} tháng"
    return text


def render_result(result: EngineResult, penalty: PenaltySummary, explainer: Explainer) -> str:
    lines = [f"# Kết quả: {result.status}"]
    if result.message:
        lines.append(result.message)
    lines += [f"Ghi chú: {note}" for note in result.notes]

    lines += ["", "## Vi phạm và mức phạt"]
    decisions = {d.citation_id: d for d in penalty.decisions}
    for hit in result.hits:
        decision = decisions[hit.citation_id]
        row = explainer.kb.violations[hit.citation_id]
        lines.append(f"- **{explainer.label_of(hit.citation_id)}** (`{hit.citation_id}`)")
        lines.append(f"  - Hành vi: {row['description']}")
        if hit.escalated_from:
            lines.append(f"  - Chuyển khung từ: {', '.join(hit.escalated_from)}")
        if decision.fine_range:
            low, high = decision.fine_range
            lines.append(f"  - Khung phạt: {format_money(low)} – {format_money(high)}")
            lines.append(f"  - Đề xuất: {format_money(decision.recommended_fine)}")
        lines.append(f"  - Điểm GPLX theo quy định: {decision.points_deducted}")
        for item in decision.points_conditional:
            lines.append(
                f"  - Chưa tự áp: trừ {item.points} điểm nếu “{item.condition}” ({item.source})"
            )
        if decision.sanctions:
            lines.append(f"  - Bổ sung: {'; '.join(map(_sanction_text, decision.sanctions))}")
    if result.hits:
        lines += [
            "",
            f"**Tổng tiền phạt đề xuất: {format_money(penalty.total_recommended_fine)}**",
            f"**Điểm GPLX bị trừ: {penalty.total_points_deducted}**",
        ]
    elif not result.branches:
        lines.append("- (chưa xác định được vi phạm)")

    if result.branches:
        lines += ["", f"## Các khả năng (phụ thuộc vào {', '.join(result.depends_on)})"]
        for branch in result.branches:
            when = "; ".join(f"{c.slot_label}: {' hoặc '.join(c.labels)}" for c in branch.conditions)
            cited = ", ".join(explainer.label_of(h.citation_id) for h in branch.hits)
            lines.append(f"- {when} → {cited}")

    if result.questions:
        lines += ["", "## Câu hỏi bổ sung"]
        for question in result.questions:
            lines.append(f"- ({question.field}) {question.text}")
            lines += [f"  - {o.value}: {o.label}" for o in question.options]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Offline traffic-law reasoning CLI")
    parser.add_argument("--facts", required=True, type=Path, help="Facts JSON file")
    args = parser.parse_args(argv)

    facts = Facts.model_validate(json.loads(args.facts.read_text(encoding="utf-8")))
    kb = get_knowledge_base()
    result = InferenceEngine(kb).run(facts)
    penalty = PenaltyDecider(kb).decide(result)
    explainer = Explainer(kb)
    print(render_result(result, penalty, explainer))
    print()
    print(render_markdown(explainer.explain(result, penalty)))


if __name__ == "__main__":
    main()
