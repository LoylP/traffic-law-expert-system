"""OntologyGrounder (DESIGN §2 step 2, problem 2): map free-text behaviour
phrases onto Act / Violation nodes with the existing hybrid retriever.

The hybrid score is min-max scaled over the candidates, so the best candidate
scores about 1.0 even for an unrelated sentence. Score and margin therefore only
say the winner is *distinct*; the raw embedding cosine (`min_cosine`) is the
absolute check that it is *related*.
"""

from __future__ import annotations

import os
from typing import Any, Protocol

from src.reasoning.extractor_regex import RegexExtractor
from src.reasoning.knowledge_base import KnowledgeBase, get_knowledge_base
from src.reasoning.schema import Facts, TraceStep

GROUND_RULE_ID = "GROUND-ONTOLOGY"
DEFAULT_THRESHOLD = 0.75
DEFAULT_MARGIN = 0.05
# Calibrated on a handful of phrases with multilingual-e5-large; tune on the P4 set.
DEFAULT_MIN_COSINE = 0.84
TOP_K = 3


class Retriever(Protocol):
    def search(self, query: str, top_k: int = ..., **kwargs: Any) -> list[dict[str, Any]]: ...


def _env_float(name: str, default: float) -> float:
    return float(os.getenv(name) or default)


class OntologyGrounder:
    def __init__(
        self,
        retriever: Retriever,
        kb: KnowledgeBase | None = None,
        threshold: float | None = None,
        margin: float = DEFAULT_MARGIN,
        min_cosine: float | None = None,
    ):
        self.retriever = retriever
        self.kb = kb or get_knowledge_base()
        self.threshold = (
            _env_float("GROUND_THRESHOLD", DEFAULT_THRESHOLD) if threshold is None else threshold
        )
        self.margin = margin
        self.min_cosine = (
            _env_float("GROUND_MIN_COSINE", DEFAULT_MIN_COSINE) if min_cosine is None else min_cosine
        )
        self._lexical = RegexExtractor(self.kb)
        # acts.yaml mapping, completed by the core rules (a few violations they
        # produce are not listed under any Act and have no classify_auto rule).
        self.acts_by_citation: dict[str, list[str]] = {}
        for rule in self.kb.rules_of("classify"):
            citation_id = rule.then.get("add_violation")
            if citation_id and isinstance(rule.when.get("has_act"), str):
                self.acts_by_citation[citation_id] = [rule.when["has_act"]]
        self.acts_by_citation.update(self.kb.citation_acts)

    def vehicle_family(self, vehicle_class: str) -> set[str]:
        """The class, its ancestors and its descendants (never its siblings)."""
        parents = self.kb.vehicle_parents

        def lineage(item: str | None) -> list[str]:
            chain = []
            while item is not None:
                chain.append(item)
                item = parents.get(item)
            return chain

        descendants = {item for item in parents if vehicle_class in lineage(item)}
        return set(lineage(vehicle_class)) | descendants

    def ground(self, facts: Facts) -> tuple[Facts, list[TraceStep]]:
        """Return a copy of the facts with grounded acts/violations, plus trace."""
        grounded = facts.model_copy(deep=True)
        steps: list[TraceStep] = []
        # Without a vehicle the same phrase matches several articles: do not guess.
        if facts.vehicle_class is None:
            return grounded, steps
        family = self.vehicle_family(facts.vehicle_class)

        for behaviour in facts.free_behaviors:
            known = self._lexical.extract(behaviour).facts.acts
            if known and set(known) <= set(grounded.acts):
                continue  # already covered by an extracted act
            results = self.retriever.search(behaviour, top_k=TOP_K, vehicle_classes=family)
            if not results:
                continue
            steps.append(self._decide(grounded, behaviour, results))
        return grounded, steps

    def _decide(self, facts: Facts, behaviour: str, results: list[dict[str, Any]]) -> TraceStep:
        candidates = [
            {
                "citation_id": r["raw_node"]["citation_id"],
                "hybrid": round(r["scores"]["hybrid"], 4),
                "cosine": round(r["scores"]["embedding"], 4),
            }
            for r in results
        ]
        top = candidates[0]
        gap = top["hybrid"] - (candidates[1]["hybrid"] if len(candidates) > 1 else 0.0)
        failed = []
        if top["hybrid"] < self.threshold:
            failed.append(f"điểm hybrid {top['hybrid']:.2f} < {self.threshold}")
        if gap < self.margin - 1e-9:
            failed.append(f"cách ứng viên thứ hai {gap:.2f} < {self.margin}")
        if top["cosine"] < self.min_cosine:
            failed.append(f"độ tương đồng ngữ nghĩa {top['cosine']:.3f} < {self.min_cosine}")

        produced: dict[str, Any] = {}
        if failed:
            explain = f"Không ánh xạ “{behaviour}”: {'; '.join(failed)}."
        else:
            citation_id = top["citation_id"]
            acts = self.acts_by_citation.get(citation_id)
            if acts:
                # Violations with an Act are classified by the core rules, which
                # still check context (speed band, alcohol level...).
                added = [a for a in acts if a not in facts.acts]
                facts.acts.extend(added)
                produced["acts"] = added
                target = ", ".join(acts)
            else:
                if citation_id not in facts.grounded_violations:
                    facts.grounded_violations.append(citation_id)
                produced["grounded_violations"] = [citation_id]
                target = citation_id
            explain = (
                f"Ánh xạ “{behaviour}” → {target} (hybrid {top['hybrid']:.2f}, "
                f"cách ứng viên kế tiếp {gap:.2f}, cosine {top['cosine']:.3f})."
            )
        return TraceStep(
            rule_id=GROUND_RULE_ID,
            type="ground",
            matched_facts={"free_behavior": behaviour, "candidates": candidates},
            produced=produced,
            explain=explain,
            source="OntologyGrounder (BM25 + E5)",
        )
