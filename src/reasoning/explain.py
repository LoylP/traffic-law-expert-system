"""Explainer (DESIGN §8). Pure Python: no LLM, no network."""

from __future__ import annotations

import json
import re
from typing import Any

from src.reasoning.engine import SPECIFICITY_RULE_ID
from src.reasoning.knowledge_base import KnowledgeBase, get_knowledge_base
from src.reasoning.schema import (
    EngineResult,
    Explanation,
    Facts,
    FactUsed,
    LegalCitation,
    PenaltySummary,
)


# Fields a derive rule can match, as named in "suy ra từ ...".
FIELD_NAMES = {
    "vehicle_class": "phương tiện",
    "actual_speed_kmh": "tốc độ thực tế (km/h)",
    "speed_limit_kmh": "tốc độ cho phép (km/h)",
    "speed_over_kmh": "số km/h vượt",
    "speed_band": "khoảng vượt tốc độ",
    "alcohol_level": "mức nồng độ cồn",
    "bac_blood_mg_100ml": "nồng độ cồn trong máu",
    "bac_breath_mg_l": "nồng độ cồn trong khí thở",
    "drank_alcohol": "có uống rượu, bia",
    "alcohol_test_refused": "từ chối kiểm tra nồng độ cồn",
    "passengers_count": "số người được chở",
    "no_helmet_who": "người không đội mũ",
    "resistance": "phản ứng với người thi hành công vụ",
    "officer_signal": "có hiệu lệnh của người thi hành công vụ",
    "consequence": "hậu quả",
    "free_behaviors": "mô tả",
}


def full_heading(citation_id: str, text: str) -> str:
    """Display form of a verbatim excerpt: law_corpus heads it with the bare
    "Điều X", so add the clause. `LegalCitation.text` itself stays untouched."""
    match = re.search(r"-D(\d+)-K(\d+)", citation_id)
    if not match:
        return text
    article, clause = match.groups()
    return re.sub(rf"\AĐiều {article}$", f"Điều {article} khoản {clause}", text, flags=re.M)


def citation_label(unit: dict[str, Any]) -> str:
    """e.g. "NĐ 168/2024, Điều 7 Khoản 7 Điểm c"."""
    decree = {"100": "NĐ 100/2019", "123": "NĐ 123/2021", "168": "NĐ 168/2024"}
    parts = [f"Điều {unit['article']}"]
    if unit.get("clause"):
        parts.append(f"Khoản {unit['clause']}")
    if unit.get("point"):
        parts.append(f"Điểm {unit['point']}")
    name = decree.get(str(unit.get("decree_id")), f"NĐ {unit.get('decree_id')}")
    return f"{name}, {' '.join(parts)}"


class Explainer:
    def __init__(self, kb: KnowledgeBase | None = None):
        self.kb = kb or get_knowledge_base()

    def label_of(self, citation_id: str) -> str:
        unit = self.kb.legal_units.get(citation_id)
        return citation_label(unit) if unit else citation_id

    def explain(
        self,
        result: EngineResult,
        penalty: PenaltySummary | None = None,
        user_facts: Facts | None = None,
    ) -> Explanation:
        """`user_facts` = what the user stated, before grounding (default: the input)."""
        citations = [
            LegalCitation(
                citation_id=hit.citation_id,
                label=self.label_of(hit.citation_id),
                text=self.kb.legal_texts.get(hit.citation_id),
            )
            for hit in result.hits
        ]
        return Explanation(
            facts_used=self._facts_used(user_facts or result.input_facts)
            + self._derived_facts(result),
            chain=list(result.trace),
            legal_citations=citations,
            penalty_calc=self._penalty_calc(penalty),
            faithfulness_ok=self._is_faithful(result, citations, penalty),
        )

    @staticmethod
    def _facts_used(facts: Facts) -> list[FactUsed]:
        """Facts supplied by the user."""
        defaults = Facts().model_dump(mode="json")
        return [
            FactUsed(field=name, value=value, evidence=facts.evidence.get(name))
            for name, value in facts.model_dump(mode="json").items()
            if name not in ("evidence", "unknown_slots") and value != defaults[name]
        ]

    def _derived_facts(self, result: EngineResult) -> list[FactUsed]:
        """Facts added by derive rules or the grounder, each with where it came from."""
        derived: list[FactUsed] = []
        for step in result.trace:
            if step.type == "ground":
                source = f"cụm “{step.matched_facts['free_behavior']}” (ánh xạ ngữ nghĩa)"
            elif step.type == "derive":
                source = f"{self._origin_of(step.matched_facts)} (luật {step.rule_id})"
            else:
                continue
            items = dict(step.produced.get("set_facts") or {})
            for name in ("acts", "grounded_violations", "circumstances", "consequence",
                         "contexts", "speed_over_kmh"):
                if step.produced.get(name) not in (None, []):
                    items[name] = step.produced[name]
            derived += [
                FactUsed(field=name, value=value, origin="derived", derived_from=source)
                for name, value in items.items()
            ]
        return derived

    def _name_of(self, value: Any) -> str:
        """Vietnamese label of an ontology / act / circumstance ID."""
        for items in (self.kb.acts, self.kb.circumstances):
            if value in items:
                return items[value]["label"]
        for group in self.kb.ontology.values():
            if isinstance(group, list):
                for item in group:
                    if isinstance(item, dict) and item.get("id") == value:
                        return item.get("label", value)
        return str(value)

    def _origin_of(self, matched: dict[str, Any]) -> str:
        """The facts a derive rule matched, in words."""
        parts = []
        for key, value in matched.items():
            if value in (None, [], False):  # "is_null"-style conditions
                continue
            values = value if isinstance(value, list) else [value]
            if key == "has_act":
                parts += [f"hành vi “{self._name_of(v)}”" for v in values]
            elif key == "has_context":
                parts += [f"mức “{self._name_of(v)}”" for v in values]
            else:
                shown = "có" if value is True else ", ".join(self._name_of(v) for v in values)
                parts.append(f"{FIELD_NAMES.get(key, key)}: {shown}")
        return "; ".join(parts)

    def _penalty_calc(self, penalty: PenaltySummary | None) -> list[str]:
        if penalty is None:
            return []
        lines = list(penalty.reasoning)
        for decision in penalty.decisions:
            lines += [f"[{self.label_of(decision.citation_id)}] {s}" for s in decision.reasoning]
        if penalty.decisions:
            lines.append(f"Căn cứ nguyên tắc: {penalty.legal_principle_ref}.")
        return lines

    @staticmethod
    def _is_faithful(
        result: EngineResult,
        citations: list[LegalCitation],
        penalty: PenaltySummary | None,
    ) -> bool:
        """Every citation was produced by a traced rule, has verbatim text and
        the penalty covers no violation outside the inferred set."""
        produced: set[str] = set()
        for step in result.trace:
            if step.rule_id == SPECIFICITY_RULE_ID:
                continue
            if "violation" in step.produced:
                produced.add(step.produced["violation"])
            if "escalated" in step.produced:
                produced.add(step.produced["escalated"]["to"])
        cited = {c.citation_id for c in citations}
        decided = {d.citation_id for d in penalty.decisions} if penalty else set()
        return cited <= produced and decided <= cited and all(c.text for c in citations)


def _short(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def render_markdown(explanation: Explanation) -> str:
    lines = ["## Giải thích", "", "### 1. Dữ kiện đã ghi nhận"]
    for fact in explanation.facts_used:
        evidence = f" — “{fact.evidence}”" if fact.evidence else ""
        if fact.origin == "derived":
            evidence = f" — suy ra từ {fact.derived_from}"
        lines.append(f"- `{fact.field}` = {_short(fact.value)}{evidence}")
    if not explanation.facts_used:
        lines.append("- (không có)")

    lines += ["", "### 2. Chuỗi suy luận"]
    for index, step in enumerate(explanation.chain, 1):
        description = step.explain or step.source or ""
        produced = {k: v for k, v in step.produced.items() if v not in (None, [], "")}
        lines.append(f"{index}. **{step.rule_id}** ({step.type}) {description}".rstrip())
        lines.append(f"   - khớp: {_short(step.matched_facts)}")
        if produced:
            lines.append(f"   - kết quả: {_short(produced)}")
    if not explanation.chain:
        lines.append("- (không có luật nào được kích hoạt)")

    lines += ["", "### 3. Căn cứ pháp lý"]
    for citation in explanation.legal_citations:
        lines.append(f"- **{citation.label}** (`{citation.citation_id}`)")
        excerpt = full_heading(citation.citation_id, citation.text or "(thiếu nguyên văn)")
        lines += [f"  > {part}" for part in excerpt.splitlines()]
    if not explanation.legal_citations:
        lines.append("- (không có)")

    lines += ["", "### 4. Tính mức phạt"]
    lines += [f"- {line}" for line in explanation.penalty_calc] or ["- (không có)"]
    check = "đạt" if explanation.faithfulness_ok else "KHÔNG đạt"
    lines += ["", f"Kiểm tra trung thành trích dẫn: {check}"]
    return "\n".join(lines)
