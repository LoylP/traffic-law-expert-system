"""Generate classify_auto.yaml: one classify rule per violation not covered by core rules.

Auto rules fire only when the grounder puts the citation_id into
`Facts.grounded_violations` (DESIGN §5.2).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
VIOLATIONS_FILE = ROOT / "data" / "structured" / "violations_168_clean.json"
CORE_RULES_FILE = ROOT / "data" / "knowledge" / "rules" / "classify_core.yaml"
OUTPUT_FILE = ROOT / "data" / "knowledge" / "rules" / "classify_auto.yaml"

AUTO_PRIORITY = 10
HEADER = (
    "# FILE TỰ SINH bởi src/reasoning/gen_auto_rules.py (make data). KHÔNG sửa tay.\n"
    "# Nguồn: data/structured/violations_168_clean.json; bỏ qua citation đã có trong classify_core.yaml\n\n"
)


def core_citations(core_rules: list[dict[str, Any]]) -> set[str]:
    return {
        rule["then"]["add_violation"]
        for rule in core_rules
        if "add_violation" in rule.get("then", {})
    }


def build_rules(violations: list[dict[str, Any]], skip: set[str]) -> list[dict[str, Any]]:
    return [
        {
            "id": f"R-AUTO-{item['citation_id']}",
            "type": "classify",
            "priority": AUTO_PRIORITY,
            "when": {
                "vehicle_class": item["vehicle_class"],
                "grounded_violation": item["citation_id"],
            },
            "then": {"add_violation": item["citation_id"]},
            "source": "auto",
            "verified": True,  # sinh máy móc từ văn bản
        }
        for item in violations
        if item["citation_id"] not in skip
    ]


def main() -> None:
    violations = json.loads(VIOLATIONS_FILE.read_text(encoding="utf-8"))
    core = yaml.safe_load(CORE_RULES_FILE.read_text(encoding="utf-8"))["rules"]
    skip = core_citations(core)
    rules = build_rules(violations, skip)
    body = yaml.safe_dump({"rules": rules}, allow_unicode=True, sort_keys=False)
    OUTPUT_FILE.write_text(HEADER + body, encoding="utf-8")
    print(
        f"Đã sinh {len(rules)} luật classify_auto "
        f"(bỏ qua {len(violations) - len(rules)} violation đã có trong classify_core) -> {OUTPUT_FILE}"
    )


if __name__ == "__main__":
    main()
