"""Load the explicit knowledge base (YAML rules + legal corpus) for the engine."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from src.reasoning.schema import Rule

ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_DIR = ROOT / "data" / "knowledge"
RULES_DIR = KNOWLEDGE_DIR / "rules"
CORPUS_PATH = ROOT / "data" / "structured" / "law_corpus.jsonl"

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


@dataclass
class KnowledgeBase:
    rules: list[Rule]
    legal_texts: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, rules_dir: Path = RULES_DIR, corpus_path: Path | None = CORPUS_PATH) -> "KnowledgeBase":
        rules: list[Rule] = []
        for name in RULE_FILES:
            path = rules_dir / name
            if not path.exists():
                continue
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            rules.extend(Rule.model_validate(raw) for raw in data.get("rules", []))
        legal_texts: dict[str, str] = {}
        if corpus_path is not None and corpus_path.exists():
            with corpus_path.open(encoding="utf-8") as file:
                for line in file:
                    if line.strip():
                        row = json.loads(line)
                        legal_texts[row["citation_id"]] = row["text"]
        return cls(rules=rules, legal_texts=legal_texts)

    def rules_of(self, rule_type: str) -> list[Rule]:
        return [rule for rule in self.rules if rule.type == rule_type]
