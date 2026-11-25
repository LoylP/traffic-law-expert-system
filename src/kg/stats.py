from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from src.kg.build_kg import OUT_EDGES, OUT_NODES


def load_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


def main() -> None:
    nodes = load_jsonl(OUT_NODES)
    edges = load_jsonl(OUT_EDGES)
    node_counts = Counter(node["type"] for node in nodes)
    edge_counts = Counter(edge["relation"] for edge in edges)
    violations = [node for node in nodes if node.get("type") == "Violation"]
    vehicles = Counter(node.get("vehicle_class", "VEH_ANY") for node in violations)

    print("Số node theo loại:")
    for node_type, count in sorted(node_counts.items()):
        print(f"  {node_type}: {count}")
    print("Số cạnh theo loại:")
    for relation, count in sorted(edge_counts.items()):
        print(f"  {relation}: {count}")
    print(f"Số violation theo vehicle_class: {dict(sorted(vehicles.items()))}")
    print(f"Violation có points_deducted: {sum(node.get('points_deducted', 0) > 0 for node in violations)}")
    print(f"Violation có sanctions: {sum(bool(node.get('sanctions')) for node in violations)}")
    print(f"BASED_ON: {edge_counts.get('BASED_ON', 0)}")
    print(f"BASED_ON_UNRESOLVED: {edge_counts.get('BASED_ON_UNRESOLVED', 0)}")


if __name__ == "__main__":
    main()
