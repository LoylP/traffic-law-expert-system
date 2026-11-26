"""PenaltyDecider (DESIGN §7). Pure Python: no LLM, no network."""

from __future__ import annotations

from typing import Iterable

from src.reasoning.knowledge_base import KnowledgeBase, get_knowledge_base
from src.reasoning.schema import (
    ConditionalPoints,
    EngineResult,
    PenaltyDecision,
    PenaltySummary,
    Sanction,
    ViolationHit,
)

LEGAL_PRINCIPLE_REF = (
    "Luật XLVPHC (sửa đổi 2025), Điều 9–10, Điều 23; "
    "NĐ 118/2021/NĐ-CP sửa đổi bởi NĐ 68/2025/NĐ-CP"
)
SUBJECT_ORGANIZATION = "SUBJ_ORGANIZATION"
ORG_MULTIPLIER = 2


def round_to_thousand(value: float) -> int:
    """Round half up to the nearest 1.000 đồng."""
    return int((value + 500) // 1000) * 1000


def format_money(value: float) -> str:
    return f"{int(value):,}".replace(",", ".") + " đồng"


def apply_net(fine_min: int, fine_max: int, net: int) -> tuple[int, tuple[int, int], str]:
    """Return (recommended fine, allowed range, Vietnamese explanation) for a net score."""
    mid = (fine_min + fine_max) / 2
    mid_rounded = round_to_thousand(mid)
    if net == 0:
        return (
            mid_rounded,
            (mid_rounded, mid_rounded),
            "Không còn tình tiết tăng nặng/giảm nhẹ sau bù trừ: áp dụng mức trung bình "
            "của khung (điểm a khoản 1 Điều 9 NĐ 118/2021).",
        )
    if net >= 2:
        return (
            fine_max,
            (fine_max, fine_max),
            "Còn từ 02 tình tiết tăng nặng: áp dụng mức tối đa của khung "
            "(điểm c khoản 1 Điều 9 NĐ 118/2021).",
        )
    if net <= -2:
        return (
            fine_min,
            (fine_min, fine_min),
            "Còn từ 02 tình tiết giảm nhẹ: áp dụng mức tối thiểu của khung "
            "(điểm b khoản 1 Điều 9 NĐ 118/2021).",
        )
    if net == 1:
        return (
            round_to_thousand((mid + fine_max) / 2),
            (mid_rounded, fine_max),
            "Còn 01 tình tiết tăng nặng: mức phạt từ trên mức trung bình đến dưới mức tối đa "
            "(điểm c khoản 1 Điều 9 NĐ 118/2021); đề xuất giá trị giữa khoảng.",
        )
    return (
        round_to_thousand((fine_min + mid) / 2),
        (fine_min, mid_rounded),
        "Còn 01 tình tiết giảm nhẹ: mức phạt từ trên mức tối thiểu đến dưới mức trung bình "
        "(điểm b khoản 1 Điều 9 NĐ 118/2021); đề xuất giá trị giữa khoảng.",
    )


class PenaltyDecider:
    def __init__(self, kb: KnowledgeBase | None = None):
        self.kb = kb or get_knowledge_base()

    def decide(self, result: EngineResult) -> PenaltySummary:
        return self.decide_hits(result.hits, result.circumstances, result.facts_final.subject)

    def decide_hits(
        self,
        hits: Iterable[ViolationHit],
        circumstances: Iterable[str] = (),
        subject: str = "SUBJ_INDIVIDUAL",
    ) -> PenaltySummary:
        hits = list(hits)
        summary = PenaltySummary(legal_principle_ref=LEGAL_PRINCIPLE_REF)
        self._weigh_circumstances(summary, hits, list(dict.fromkeys(circumstances)))
        summary.decisions = [self._decide_one(hit, summary.net, subject) for hit in hits]
        self._aggregate(summary)
        return summary

    # -- circumstances ----------------------------------------------------
    def _weigh_circumstances(
        self, summary: PenaltySummary, hits: list[ViolationHit], circumstances: list[str]
    ) -> None:
        cited = {hit.citation_id for hit in hits}
        for cid in circumstances:
            item = self.kb.circumstances.get(cid)
            if item is None:
                reason = "Không có trong danh mục tình tiết nên không được tính."
                summary.excluded_circumstances[cid] = reason
                summary.reasoning.append(f"Bỏ qua {cid}: {reason}")
                continue
            overlap = self.kb.circumstance_overlaps.get(cid, {})
            duplicated = sorted(cited & set(overlap.get("violations", [])))
            if item["kind"] == "aggravating" and duplicated:
                reason = (
                    f"Trùng với hành vi đã bị xử phạt trong cùng lần ({', '.join(duplicated)}) "
                    "nên không coi là tình tiết tăng nặng (khoản 2 Điều 10 Luật XLVPHC)."
                )
                summary.excluded_circumstances[cid] = reason
                summary.reasoning.append(f"Không tính “{item['label']}”: {reason}")
                continue
            target = summary.aggravating if item["kind"] == "aggravating" else summary.mitigating
            target.append(cid)
            kind = "tăng nặng" if item["kind"] == "aggravating" else "giảm nhẹ"
            summary.reasoning.append(
                f"Tình tiết {kind}: {item['label']} ({item.get('legal_ref', '')})."
            )

        aggravating, mitigating = len(summary.aggravating), len(summary.mitigating)
        summary.net = aggravating - mitigating
        line = f"Số tình tiết tăng nặng A = {aggravating}, giảm nhẹ M = {mitigating}"
        if aggravating and mitigating:
            line += (
                f"; bù trừ một tăng nặng với một giảm nhẹ ({min(aggravating, mitigating)} cặp, "
                "điểm d khoản 1 Điều 9 NĐ 118/2021)"
            )
        summary.reasoning.append(f"{line}; net = {summary.net:+d}.")

    # -- one violation ----------------------------------------------------
    def _decide_one(self, hit: ViolationHit, net: int, subject: str) -> PenaltyDecision:
        row = self.kb.violations.get(hit.citation_id)
        if row is None:
            raise KeyError(f"{hit.citation_id} not found in violations_168_clean.json")
        decision = PenaltyDecision(
            citation_id=hit.citation_id,
            points_deducted=row.get("points_deducted") or 0,
            points_conditional=[
                ConditionalPoints.model_validate(item)
                for item in row.get("points_conditional") or []
            ],
            sanctions=[Sanction.model_validate(s) for s in row.get("sanctions") or []],
        )
        for item in decision.points_conditional:
            decision.reasoning.append(
                f"Trừ điểm có điều kiện: trừ {item.points} điểm GPLX nếu “{item.condition}” "
                f"(căn cứ {item.source}). Hệ thống chưa tự áp mức này, chỉ tính "
                f"{decision.points_deducted} điểm; cần đối chiếu điều kiện với vụ việc."
            )
        fine_min, fine_max = row.get("fine_min"), row.get("fine_max")
        if subject == SUBJECT_ORGANIZATION:
            if row.get("fine_org_min") is not None and row.get("fine_org_max") is not None:
                fine_min, fine_max = row["fine_org_min"], row["fine_org_max"]
                decision.reasoning.append("Chủ thể là tổ chức: dùng khung phạt đối với tổ chức.")
            elif fine_min is not None and fine_max is not None:
                fine_min, fine_max = fine_min * ORG_MULTIPLIER, fine_max * ORG_MULTIPLIER
                decision.org_rule_applied = True
                decision.reasoning.append(
                    "Chủ thể là tổ chức nhưng dữ liệu chưa có khung riêng: tạm tính bằng "
                    "02 lần khung đối với cá nhân (cần đối chiếu với NĐ 168/2024)."
                )
        if fine_min is None or fine_max is None:
            decision.reasoning.append("Dữ liệu không có khung phạt tiền cho vi phạm này.")
            return decision

        recommended, allowed, why = apply_net(fine_min, fine_max, net)
        decision.fine_range = (fine_min, fine_max)
        decision.recommended_fine = recommended
        decision.allowed_range_after_circumstances = allowed
        decision.reasoning += [
            f"Khung phạt: {format_money(fine_min)} – {format_money(fine_max)}; "
            f"mức trung bình {format_money((fine_min + fine_max) / 2)}.",
            why,
            f"Mức phạt đề xuất: {format_money(recommended)}.",
        ]
        return decision

    # -- all violations ---------------------------------------------------
    def _aggregate(self, summary: PenaltySummary) -> None:
        if not summary.decisions:
            summary.reasoning.append("Không có vi phạm nào để tính mức phạt.")
            return
        summary.total_recommended_fine = sum(d.recommended_fine for d in summary.decisions)
        summary.reasoning.append(
            f"Xử phạt từng hành vi và cộng lại: {len(summary.decisions)} hành vi, "
            f"tổng {format_money(summary.total_recommended_fine)}."
        )

        deducting = [d for d in summary.decisions if d.points_deducted > 0]
        if deducting:
            top = max(deducting, key=lambda d: d.points_deducted)
            summary.total_points_deducted = top.points_deducted
            summary.points_from = top.citation_id
            if len(deducting) > 1:
                summary.reasoning.append(
                    f"Có {len(deducting)} hành vi bị trừ điểm GPLX: chỉ trừ theo hành vi bị trừ "
                    f"nhiều điểm nhất ({top.citation_id}: {top.points_deducted} điểm), không cộng "
                    "dồn (điểm b khoản 1 Điều 50 NĐ 168/2024)."
                )
            else:
                summary.reasoning.append(
                    f"Trừ {top.points_deducted} điểm GPLX ({top.citation_id})."
                )

        for decision in summary.decisions:
            for sanction in decision.sanctions:
                if sanction not in summary.sanctions:
                    summary.sanctions.append(sanction)
