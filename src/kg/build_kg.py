from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Any

import yaml

from src.extract.legal_corpus_builder import canonical_citation_id

# =========================
# PATH CONFIG
# =========================
BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
STRUCTURED_DIR = DATA_DIR / "structured"
KG_DIR = DATA_DIR / "kg"
KNOWLEDGE_DIR = DATA_DIR / "knowledge"
KG_DIR.mkdir(parents=True, exist_ok=True)

LAW_CORPUS_FILE = STRUCTURED_DIR / "law_corpus.jsonl"
VIOLATIONS_FILE = STRUCTURED_DIR / "violations_168_clean.json"

OUT_NODES = KG_DIR / "kg_nodes.jsonl"
OUT_EDGES = KG_DIR / "kg_edges.jsonl"


# =========================
# HELPERS
# =========================
def load_jsonl(path: Path) -> List[dict]:
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_jsonl(path: Path, rows: List[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def normalize_text(text: Any) -> str:
    if text is None:
        return ""
    text = str(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def slugify(text: str) -> str:
    text = normalize_text(text).lower()
    text = text.replace("đ", "d")
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "unknown"


def add_node(nodes: Dict[str, dict], node_id: str, node_type: str, **attrs):
    if node_id not in nodes:
        nodes[node_id] = {
            "id": node_id,
            "type": node_type,
            **attrs
        }
    else:
        for k, v in attrs.items():
            if k not in nodes[node_id] or nodes[node_id][k] in (None, "", []):
                nodes[node_id][k] = v


def add_edge(edges: List[dict], source: str, relation: str, target: str, **attrs):
    edges.append({
        "source": source,
        "relation": relation,
        "target": target,
        **attrs
    })


def dedup_edges(edges: List[dict]) -> List[dict]:
    seen = set()
    out = []
    for e in edges:
        key = json.dumps(e, ensure_ascii=False, sort_keys=True)
        if key not in seen:
            seen.add(key)
            out.append(e)
    return out


# =========================
# KNOWLEDGE (YAML) -> NODES / EDGES
# =========================
# ontology.yaml section -> node type
ONTOLOGY_NODE_TYPES = {
    "vehicle_classes": "VehicleClass",
    "road_types": "RoadType",
    "time_contexts": "TimeContext",
    "alcohol_levels": "AlcoholLevel",
    "speed_bands": "SpeedBand",
    "consequences": "Consequence",
    "resistance_behaviors": "ResistanceBehavior",
    "subjects": "Subject",
}
# DESIGN §4.2: Circumstance SUBCLASS_OF (Aggravating | Mitigating)
CIRCUMSTANCE_KINDS = {
    "aggravating": ("Aggravating", "Tình tiết tăng nặng"),
    "mitigating": ("Mitigating", "Tình tiết giảm nhẹ"),
}


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def add_ontology_nodes(nodes: Dict[str, dict], edges: List[dict], knowledge_dir: Path) -> None:
    ontology = load_yaml(knowledge_dir / "ontology.yaml")
    for section, node_type in ONTOLOGY_NODE_TYPES.items():
        for item in ontology[section]:
            attrs = {k: v for k, v in item.items() if k != "id"}
            add_node(nodes, item["id"], node_type, **attrs)
            if item.get("parent"):
                add_edge(edges, item["id"], "SUBCLASS_OF", item["parent"])

    for act in load_yaml(knowledge_dir / "acts.yaml")["acts"]:
        # related_violations is materialised as INSTANCE_OF_ACT edges
        attrs = {k: v for k, v in act.items() if k not in ("id", "related_violations")}
        add_node(nodes, act["id"], "Act", **attrs)

    for kind_id, label in CIRCUMSTANCE_KINDS.values():
        add_node(nodes, kind_id, "CircumstanceKind", label=label)
    circumstances = load_yaml(knowledge_dir / "circumstances.yaml")
    for item in circumstances["mitigating_circumstances"] + circumstances["aggravating_circumstances"]:
        attrs = {k: v for k, v in item.items() if k != "id"}
        add_node(nodes, item["id"], "Circumstance", **attrs)
        add_edge(edges, item["id"], "SUBCLASS_OF", CIRCUMSTANCE_KINDS[item["kind"]][0])


def add_knowledge_edges(
    nodes: Dict[str, dict],
    edges: List[dict],
    violations_by_citation: Dict[str, List[str]],
    knowledge_dir: Path,
) -> List[str]:
    """INSTANCE_OF_ACT, REQUIRES_CONTEXT, ESCALATES_TO. Returns unresolved references."""
    unresolved: List[str] = []

    def violation_nodes(citation_id: str, origin: str) -> List[str]:
        found = violations_by_citation.get(canonical_citation_id(citation_id), [])
        if not found:
            unresolved.append(f"{origin}: không tìm thấy Violation {citation_id}")
        return found

    def as_list(value: Any) -> list:
        return value if isinstance(value, list) else [value]

    for act in load_yaml(knowledge_dir / "acts.yaml")["acts"]:
        for citation_id in act.get("related_violations", []):
            for source in violation_nodes(citation_id, act["id"]):
                add_edge(edges, source, "INSTANCE_OF_ACT", act["id"])

    rules_dir = knowledge_dir / "rules"
    for rule in load_yaml(rules_dir / "classify_core.yaml")["rules"]:
        citation_id = rule["then"].get("add_violation")
        if not citation_id:
            continue
        for key in ("has_context", "road_type", "time_context"):
            if key not in rule["when"]:
                continue
            targets = as_list(rule["when"][key])
            for target in targets:
                if target not in nodes:
                    unresolved.append(f"{rule['id']}: không tìm thấy ngữ cảnh {target}")
                    continue
                for source in violation_nodes(citation_id, rule["id"]):
                    # any_of: the rule accepts any one of several contexts (OR)
                    add_edge(
                        edges, source, "REQUIRES_CONTEXT", target,
                        rule_id=rule["id"], any_of=len(targets) > 1,
                    )

    for rule in load_yaml(rules_dir / "escalate.yaml")["rules"]:
        targets = violation_nodes(rule["then"]["escalate_to"], rule["id"])
        for citation_id in as_list(rule["when"]["has_violation"]):
            for source in violation_nodes(citation_id, rule["id"]):
                for target in targets:
                    add_edge(
                        edges, source, "ESCALATES_TO", target,
                        rule_id=rule["id"], consequence=rule["when"].get("consequence", []),
                    )
    return unresolved


# =========================
# BUILD KG
# =========================
def build_kg(
    law_corpus_path: Path = LAW_CORPUS_FILE,
    violations_path: Path = VIOLATIONS_FILE,
    out_nodes_path: Path = OUT_NODES,
    out_edges_path: Path = OUT_EDGES,
    knowledge_dir: Path = KNOWLEDGE_DIR,
):
    law_units = load_jsonl(law_corpus_path)
    violations = load_json(violations_path)

    nodes: Dict[str, dict] = {}
    edges: List[dict] = []

    # =========================
    # 1) LEGAL NODES
    # =========================
    for row in law_units:
        citation_id = canonical_citation_id(row["citation_id"])
        decree_id = str(row.get("decree_id", "")).strip()
        decree_no = row.get("decree_no", "")
        chapter_no = row.get("chapter_no")
        chapter_title = row.get("chapter_title", "")
        article = row.get("article")
        article_title = row.get("article_title", "")
        clause = row.get("clause")
        point = row.get("point")
        text = row.get("text", "")
        effective_from = row.get("effective_from")
        issue_date = row.get("issue_date")
        status = row.get("status", "unknown")
        source = row.get("source", row.get("source_file", ""))

        add_node(
            nodes,
            citation_id,
            "LegalUnit",
            citation_id=citation_id,
            decree_id=decree_id,
            decree_no=decree_no,
            chapter_no=chapter_no,
            chapter_title=chapter_title,
            article=article,
            article_title=article_title,
            clause=clause,
            point=point,
            text=text,
            effective_from=effective_from,
            issue_date=issue_date,
            status=status,
            source=source,
            page_start=row.get("page_start"),
            page_end=row.get("page_end"),
        )

        decree_node_id = f"DECREE_{decree_id}"
        add_node(
            nodes,
            decree_node_id,
            "Decree",
            decree_id=decree_id,
            decree_no=decree_no,
            issue_date=issue_date,
            effective_from=effective_from,
            source=source,
        )
        add_edge(edges, citation_id, "BELONGS_TO_DECREE", decree_node_id)

        if chapter_no is not None:
            chapter_node_id = f"{decree_node_id}_CH{chapter_no}"
            add_node(
                nodes,
                chapter_node_id,
                "Chapter",
                decree_id=decree_id,
                chapter_no=chapter_no,
                chapter_title=chapter_title,
                decree_no=decree_no,
            )
            add_edge(edges, citation_id, "IN_CHAPTER", chapter_node_id)

        amended_by = row.get("amended_by", [])
        if amended_by:
            for idx, amend in enumerate(amended_by, start=1):
                amd_id = str(amend.get("amending_decree_id", "")).strip()
                amd_no = amend.get("amending_decree_no", "")
                amd_issue_date = amend.get("amending_issue_date")
                amd_effective = amend.get("amending_effective_from")
                amd_article = amend.get("amending_article")
                action = amend.get("action", "")
                note = amend.get("note", "")

                if amd_id:
                    amend_decree_node = f"DECREE_{amd_id}"
                    add_node(
                        nodes,
                        amend_decree_node,
                        "Decree",
                        decree_id=amd_id,
                        decree_no=amd_no,
                        issue_date=amd_issue_date,
                        effective_from=amd_effective,
                    )
                    add_edge(
                        edges,
                        citation_id,
                        "AMENDED_BY_DECREE",
                        amend_decree_node,
                        action=action,
                        note=note,
                        amending_article=amd_article,
                    )

                amend_event_id = (
                    f"{citation_id}__AMEND__{idx}__"
                    f"{slugify((amd_no or amd_id) + '_' + str(amd_article) + '_' + action)}"
                )
                add_node(
                    nodes,
                    amend_event_id,
                    "AmendmentEvent",
                    amending_decree_id=amd_id,
                    amending_decree_no=amd_no,
                    amending_issue_date=amd_issue_date,
                    amending_effective_from=amd_effective,
                    amending_article=amd_article,
                    action=action,
                    note=note,
                    target_citation_id=citation_id,
                )
                add_edge(edges, citation_id, "AMENDED_BY", amend_event_id)
                if amd_id:
                    add_edge(edges, amend_event_id, "RECORDED_IN_DECREE", f"DECREE_{amd_id}")

    # =========================
    # 2) ONTOLOGY NODES (data/knowledge/*.yaml)
    # =========================
    add_ontology_nodes(nodes, edges, knowledge_dir)

    # =========================
    # 3) VIOLATION NODES
    # =========================
    law_ids = {
        node["citation_id"]: node_id
        for node_id, node in nodes.items()
        if node.get("type") == "LegalUnit"
    }
    violations_by_citation: Dict[str, List[str]] = {}
    unresolved: List[str] = []
    for item in violations:
        violation_id = str(item.get("violation_id", "")).strip()
        citation_id = canonical_citation_id(item.get("citation_id", ""))
        if not violation_id or not citation_id:
            unresolved.append(f"{violation_id or '<missing id>'}: citation_id rỗng")
            continue

        violation_node_id = f"VIOLATION_{violation_id}"
        description = normalize_text(item.get("description", ""))
        vehicle_class = item.get("vehicle_class", "VEH_ANY")
        vehicle = nodes.get(vehicle_class)
        if vehicle is None or vehicle.get("type") != "VehicleClass":
            unresolved.append(f"{violation_id}: vehicle_class không hợp lệ ({vehicle_class})")
            continue
        legal_unit_id = law_ids.get(citation_id)
        if legal_unit_id is None:
            unresolved.append(f"{violation_id}: không tìm thấy LegalUnit {citation_id}")
            continue

        legal_basis = (
            f"{item.get('source', '')}, Điều {item.get('article')} "
            f"Khoản {item.get('clause')}"
            + (f" Điểm {item['point']}" if item.get("point") else "")
        )
        sanctions = item.get("sanctions", [])
        add_node(
            nodes,
            violation_node_id,
            "Violation",
            violation_id=violation_id,
            citation_id=citation_id,
            article=item.get("article"),
            clause=item.get("clause"),
            point=item.get("point"),
            description=description,
            description_full=normalize_text(item.get("description_full", "")),
            vehicle_class=vehicle_class,
            fine_min=item.get("fine_min"),
            fine_max=item.get("fine_max"),
            fine_org_min=item.get("fine_org_min"),
            fine_org_max=item.get("fine_org_max"),
            points_deducted=item.get("points_deducted", 0),
            sanctions=sanctions,
            consequence_accident=item.get("consequence_accident", False),
            refers_to=item.get("refers_to", []),
            excludes=item.get("excludes", []),
            legal_text=item.get("legal_text", ""),
            source=item.get("source", ""),
            description_natural=description,
            normalized_violation=description,
            vehicle_type=vehicle.get("label", vehicle_class),
            context_condition="",
            additional_sanctions=sanctions,
            legal_basis=legal_basis,
            confidence_label="",
        )
        add_edge(edges, violation_node_id, "BASED_ON", legal_unit_id)
        add_edge(edges, violation_node_id, "APPLIES_TO", vehicle_class)
        violations_by_citation.setdefault(citation_id, []).append(violation_node_id)

        for sanction in sanctions:
            sanction_type = str(sanction.get("type", ""))
            sanction_id = "SANCTION_" + slugify(
                f"{sanction_type}_{sanction.get('duration_min', '')}_{sanction.get('duration_max', '')}"
            )
            add_node(
                nodes,
                sanction_id,
                "AdditionalSanction",
                sanction_type=sanction_type,
                type_name=sanction_type,
                duration_min=sanction.get("duration_min"),
                duration_max=sanction.get("duration_max"),
            )
            add_edge(edges, violation_node_id, "HAS_SANCTION", sanction_id)

    for item in violations:
        violation_node_id = f"VIOLATION_{item.get('violation_id', '')}"
        if violation_node_id not in nodes:
            continue
        for excluded_id in item.get("excludes", []):
            target_citation = canonical_citation_id(excluded_id)
            for target in violations_by_citation.get(target_citation, []):
                add_edge(edges, violation_node_id, "EXCLUDES", target)

    unresolved.extend(
        add_knowledge_edges(nodes, edges, violations_by_citation, knowledge_dir)
    )

    if unresolved:
        print("Không resolve được các tham chiếu:")
        for failure in unresolved:
            print(f"- {failure}")
        raise SystemExit(1)

    resolved_count = len(violations)
    if resolved_count != len(
        [edge for edge in edges if edge["relation"] == "BASED_ON"]
    ):
        raise AssertionError("Số cạnh BASED_ON không bằng số violation")

    edges = dedup_edges(edges)

    # =========================
    # 4) EXPORT
    # =========================
    node_rows = list(nodes.values())
    edge_rows = edges

    save_jsonl(out_nodes_path, node_rows)
    save_jsonl(out_edges_path, edge_rows)

    print(f"Saved nodes: {out_nodes_path} | count = {len(node_rows)}")
    print(f"Saved edges: {out_edges_path} | count = {len(edge_rows)}")
    print(f"Resolved legal basis: {resolved_count}")
    print("Unresolved legal basis: 0")
    print(f"BASED_ON edges: {resolved_count}")


if __name__ == "__main__":
    build_kg()