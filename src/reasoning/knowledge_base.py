"""Load the explicit knowledge base (YAML rules + legal corpus) for the engine."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from src.reasoning.schema import Rule

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_DIR = ROOT / "data" / "knowledge"
RULES_DIR = KNOWLEDGE_DIR / "rules"
ONTOLOGY_PATH = KNOWLEDGE_DIR / "ontology.yaml"
ACTS_PATH = KNOWLEDGE_DIR / "acts.yaml"
CIRCUMSTANCES_PATH = KNOWLEDGE_DIR / "circumstances.yaml"
CORPUS_PATH = ROOT / "data" / "structured" / "law_corpus.jsonl"
VIOLATIONS_PATH = ROOT / "data" / "structured" / "violations_168_clean.json"

# Rule files in load order (order inside the list = tie-breaker "rule order").
RULE_FILES: tuple[str, ...] = (
    "derive.yaml",
    "temporal.yaml",
    "classify_core.yaml",
    "classify_auto.yaml",
    "escalate.yaml",
    "note.yaml",
    "ask.yaml",
)


def _read_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


@dataclass
class KnowledgeBase:
    rules: list[Rule]
    legal_texts: dict[str, str] = field(default_factory=dict)
    vehicle_parents: dict[str, str | None] = field(default_factory=dict)
    ontology: dict[str, Any] = field(default_factory=dict)
    acts: dict[str, dict[str, Any]] = field(default_factory=dict)
    circumstances: dict[str, dict[str, Any]] = field(default_factory=dict)
    # circumstance id -> violations whose constituent behaviour it duplicates
    circumstance_overlaps: dict[str, dict[str, Any]] = field(default_factory=dict)
    violations: dict[str, dict[str, Any]] = field(default_factory=dict)
    legal_units: dict[str, dict[str, Any]] = field(default_factory=dict)
    citation_acts: dict[str, list[str]] = field(default_factory=dict)
    include_unverified: bool = True

    @classmethod
    def load(
        cls,
        rules_dir: Path = RULES_DIR,
        corpus_path: Path | None = CORPUS_PATH,
        include_unverified: bool = True,
    ) -> "KnowledgeBase":
        unverified: list[str] = []

        def keep(item_id: str, verified: bool) -> bool:
            if verified:
                return True
            unverified.append(item_id)
            return include_unverified

        rules: list[Rule] = []
        for name in RULE_FILES:
            path = rules_dir / name
            if not path.exists():
                continue
            for raw in _read_yaml(path).get("rules", []):
                rule = Rule.model_validate(raw)
                if keep(rule.id, rule.verified):
                    rules.append(rule)

        legal_units: dict[str, dict[str, Any]] = {}
        if corpus_path is not None and corpus_path.exists():
            with corpus_path.open(encoding="utf-8") as file:
                for line in file:
                    if line.strip():
                        row = json.loads(line)
                        legal_units[row["citation_id"]] = row

        ontology = _read_yaml(ONTOLOGY_PATH)
        acts = {
            item["id"]: item
            for item in _read_yaml(ACTS_PATH).get("acts", [])
            if keep(item["id"], item.get("verified", False))
        }
        circumstance_data = _read_yaml(CIRCUMSTANCES_PATH)
        circumstances = {
            item["id"]: item
            for group in ("mitigating_circumstances", "aggravating_circumstances")
            for item in circumstance_data.get(group, [])
            if keep(item["id"], item.get("verified", False))
        }
        overlaps = {
            item["circumstance"]: item
            for item in circumstance_data.get("violation_overlaps", [])
            if keep(f"overlap:{item['circumstance']}", item.get("verified", False))
        }
        citation_acts: dict[str, list[str]] = {}
        for act_id, act in acts.items():
            for citation_id in act.get("related_violations") or []:
                citation_acts.setdefault(citation_id, []).append(act_id)

        violations: dict[str, dict[str, Any]] = {}
        if VIOLATIONS_PATH.exists():
            rows = json.loads(VIOLATIONS_PATH.read_text(encoding="utf-8"))
            violations = {row["citation_id"]: row for row in rows}

        if unverified:
            logger.warning(
                "%d knowledge item(s) not verified (%s): %s",
                len(unverified),
                "included" if include_unverified else "excluded",
                ", ".join(unverified[:10]),
            )

        return cls(
            rules=rules,
            legal_texts={cid: row["text"] for cid, row in legal_units.items()},
            vehicle_parents={item["id"]: item["parent"] for item in ontology["vehicle_classes"]},
            ontology=ontology,
            acts=acts,
            circumstances=circumstances,
            circumstance_overlaps=overlaps,
            violations=violations,
            legal_units=legal_units,
            citation_acts=citation_acts,
            include_unverified=include_unverified,
        )

    def rules_of(self, rule_type: str) -> list[Rule]:
        return [rule for rule in self.rules if rule.type == rule_type]


@lru_cache(maxsize=None)
def get_knowledge_base(include_unverified: bool = True) -> KnowledgeBase:
    """Process-wide cached instance. Treat it as read-only."""
    return KnowledgeBase.load(include_unverified=include_unverified)
