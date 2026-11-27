"""Export the knowledge graph to OWL (DESIGN §5.4). Report only, not part of the runtime.

Usage: python -m src.kg.export_owl [--no-reasoner]

1. Build `data/knowledge/traffic.owl` (asserted axioms only) from the KG and ontology.yaml.
2. Classify it with Pellet (HermiT as fallback) when Java is available.
3. Compare the members of every defined class with direct counts from the KG and the KB,
   and write `data/knowledge/owl_reasoning_report.md`.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import owlready2
from owlready2 import (
    AllDisjoint,
    AnnotationProperty,
    ConstrainedDatatype,
    DataProperty,
    FunctionalProperty,
    ObjectProperty,
    OwlReadyInconsistentOntologyError,
    Thing,
    World,
)

from src.extract.legal_corpus_builder import canonical_citation_id
from src.kg.build_kg import BASE_DIR as ROOT_DIR
from src.kg.build_kg import CIRCUMSTANCE_KINDS, KNOWLEDGE_DIR, OUT_EDGES, OUT_NODES
from src.kg.build_kg import VIOLATIONS_FILE, load_json, load_jsonl, load_yaml, normalize_text
from src.reasoning.explain import citation_label

ONTOLOGY_IRI = "http://traffic-law-expert-system.local/traffic.owl"
OUT_OWL = KNOWLEDGE_DIR / "traffic.owl"
OUT_REPORT = KNOWLEDGE_DIR / "owl_reasoning_report.md"
HIGH_POINT_THRESHOLD = 10
VEHICLE_INDIVIDUAL_SUFFIX = "_individual"

# KG node type -> Vietnamese class label
CLASS_LABELS: dict[str, str] = {
    "VehicleClass": "Loại phương tiện",
    "Act": "Hành vi",
    "RoadType": "Loại đường",
    "TimeContext": "Bối cảnh thời gian",
    "AlcoholLevel": "Mức nồng độ cồn",
    "SpeedBand": "Khoảng vượt tốc độ",
    "Consequence": "Hậu quả",
    "ResistanceBehavior": "Hành vi chống đối",
    "Circumstance": "Tình tiết",
    "Subject": "Chủ thể vi phạm",
    "AdditionalSanction": "Hình thức xử phạt bổ sung, biện pháp khắc phục",
    "Violation": "Vi phạm",
    "LegalProvision": "Quy định pháp luật",
}
# KG type of the legal text nodes -> OWL class name
KG_TYPE_ALIASES = {"LegalUnit": "LegalProvision"}
SANCTION_CLASSES = {
    "revoke_license": ("RevokeLicenseSanction", "Tước quyền sử dụng giấy phép lái xe"),
    "confiscate": ("ConfiscationSanction", "Tịch thu phương tiện"),
    "remedy": ("RemedialMeasure", "Biện pháp khắc phục hậu quả"),
}
# KG relation -> (OWL property, domain, range, label)
OBJECT_PROPERTIES: dict[str, tuple[str, str, tuple[str, ...], str]] = {
    "BASED_ON": ("basedOn", "Violation", ("LegalProvision",), "căn cứ vào"),
    "INSTANCE_OF_ACT": ("instanceOfAct", "Violation", ("Act",), "là thể hiện của hành vi"),
    "REQUIRES_CONTEXT": (
        "requiresContext", "Violation",
        ("RoadType", "TimeContext", "AlcoholLevel", "SpeedBand"), "yêu cầu ngữ cảnh",
    ),
    "ESCALATES_TO": ("escalatesTo", "Violation", ("Violation",), "chuyển khung thành"),
    "EXCLUDES": ("excludes", "Violation", ("Violation",), "loại trừ"),
    "HAS_SANCTION": ("hasSanction", "Violation", ("AdditionalSanction",), "có chế tài bổ sung"),
    "APPLIES_TO": ("appliesToVehicle", "Violation", ("VehicleClass",), "áp dụng cho phương tiện"),
}
# data property -> (python type, label)
DATA_PROPERTIES: dict[str, tuple[type, str]] = {
    "fineMin": (int, "mức phạt tối thiểu (đồng)"),
    "fineMax": (int, "mức phạt tối đa (đồng)"),
    "pointsDeducted": (int, "số điểm giấy phép lái xe bị trừ"),
    "legalExcerpt": (str, "trích nguyên văn quy định"),
}


@dataclass(frozen=True)
class DefinedClass:
    name: str
    label: str
    axiom: str  # description-logic form, for the report


DEFINED_CLASSES: tuple[DefinedClass, ...] = (
    DefinedClass("AlcoholViolation", "Vi phạm nồng độ cồn",
                 "Violation ⊓ ∃instanceOfAct.{ACT_ALCOHOL}"),
    DefinedClass("CarViolation", "Vi phạm của ô tô", "Violation ⊓ ∃appliesToVehicle.VEH_CAR"),
    DefinedClass("MotorVehicleViolation", "Vi phạm của phương tiện cơ giới",
                 "Violation ⊓ ∃appliesToVehicle.VEH_MOTOR"),
    DefinedClass("LicenseRevokingViolation", "Vi phạm bị tước giấy phép lái xe",
                 "Violation ⊓ ∃hasSanction.RevokeLicenseSanction"),
    DefinedClass("EscalatedViolation", "Vi phạm ở khung chuyển nặng",
                 "Violation ⊓ ∃escalatedFrom.Violation (escalatedFrom ≡ escalatesTo⁻)"),
    DefinedClass("HighPointViolation", f"Vi phạm bị trừ từ {HIGH_POINT_THRESHOLD} điểm",
                 f"Violation ⊓ ∃pointsDeducted.xsd:integer[≥ {HIGH_POINT_THRESHOLD}]"),
)


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


def _label(text: str) -> list:
    return [owlready2.locstr(text, "vi")]


def _node_label(node: dict[str, Any]) -> str:
    kind = node["type"]
    if kind == "LegalUnit":
        return citation_label(node)
    if kind == "Violation":
        return f"{node['citation_id']}: {node['description']}"
    if kind == "AdditionalSanction":
        text = SANCTION_CLASSES[node["sanction_type"]][1]
        if node.get("duration_min") is not None:
            text += f" {node['duration_min']}–{node['duration_max']} tháng"
        return text
    return normalize_text(node.get("label") or node["id"])


def build_ontology(
    nodes_path: Path = OUT_NODES,
    edges_path: Path = OUT_EDGES,
    knowledge_dir: Path = KNOWLEDGE_DIR,
) -> tuple[World, Any]:
    """Asserted ontology in its own World. Defined classes get no asserted members."""
    nodes = {node["id"]: node for node in load_jsonl(nodes_path)}
    edges = load_jsonl(edges_path)
    ontology_yaml = load_yaml(knowledge_dir / "ontology.yaml")

    world = World()
    onto = world.get_ontology(ONTOLOGY_IRI)
    with onto:
        classes: dict[str, Any] = {}

        def new_class(name: str, parent: Any, label: str) -> Any:
            cls = type(name, (parent,), {})
            cls.label = _label(label)
            classes[name] = cls
            return cls

        for name, label in CLASS_LABELS.items():
            new_class(name, Thing, label)
        AllDisjoint([classes[name] for name in CLASS_LABELS])

        # Circumstance -> Aggravating | Mitigating
        kinds = [new_class(kind_id, classes["Circumstance"], label)
                 for kind_id, label in CIRCUMSTANCE_KINDS.values()]
        AllDisjoint(kinds)

        for class_name, label in SANCTION_CLASSES.values():
            new_class(class_name, classes["AdditionalSanction"], label)
        AllDisjoint([classes[name] for name, _ in SANCTION_CLASSES.values()])

        # Vehicle hierarchy: every VEH_* is a class (parents come first in the YAML).
        children: dict[str, list[str]] = {}
        for item in ontology_yaml["vehicle_classes"]:
            parent = item.get("parent")
            new_class(item["id"], classes[parent or "VehicleClass"], item["label"])
            if parent:
                children.setdefault(parent, []).append(item["id"])
        for siblings in children.values():
            if len(siblings) > 1:
                AllDisjoint([classes[name] for name in siblings])

        properties: dict[str, Any] = {}
        for relation, (name, domain, ranges, label) in OBJECT_PROPERTIES.items():
            prop = type(name, (ObjectProperty,), {})
            prop.domain = [classes[domain]]
            targets = [classes[r] for r in ranges]
            prop.range = [targets[0] if len(targets) == 1 else owlready2.Or(targets)]
            prop.label = _label(label)
            properties[relation] = prop

        escalated_from = type("escalatedFrom", (ObjectProperty,), {})
        escalated_from.inverse_property = properties["ESCALATES_TO"]
        escalated_from.label = _label("được chuyển khung từ")

        for name, (python_type, label) in DATA_PROPERTIES.items():
            bases = (DataProperty,) if name == "legalExcerpt" else (DataProperty, FunctionalProperty)
            prop = type(name, bases, {})
            prop.range = [python_type]
            if python_type is int:
                prop.domain = [classes["Violation"]]
            prop.label = _label(label)

        # --- individuals -------------------------------------------------
        individuals: dict[str, Any] = {}

        # One representative per vehicle class, the target of appliesToVehicle.
        for item in ontology_yaml["vehicle_classes"]:
            individual = classes[item["id"]](item["id"] + VEHICLE_INDIVIDUAL_SUFFIX)
            individual.label = _label(item["label"])
            individuals[item["id"]] = individual

        for node_id, node in nodes.items():
            kind = KG_TYPE_ALIASES.get(node["type"], node["type"])
            if kind not in CLASS_LABELS or kind == "VehicleClass":
                continue
            if kind == "Circumstance":
                cls = classes[CIRCUMSTANCE_KINDS[node["kind"]][0]]
            elif kind == "AdditionalSanction":
                cls = classes[SANCTION_CLASSES[node["sanction_type"]][0]]
            else:
                cls = classes[kind]
            individual = cls(node_id)
            individual.label = _label(_node_label(node))
            if kind == "LegalProvision":
                individual.legalExcerpt = [node["text"]]
            elif kind == "Violation":
                individual.fineMin = node["fine_min"]
                individual.fineMax = node["fine_max"]
                individual.pointsDeducted = node["points_deducted"]
                individual.legalExcerpt = [node["legal_text"]]
            individuals[node_id] = individual

        for edge in edges:
            prop = properties.get(edge["relation"])
            if prop is None:
                continue
            values = getattr(individuals[edge["source"]], prop.python_name)
            target = individuals[edge["target"]]
            if target not in values:
                values.append(target)

        # --- defined classes ---------------------------------------------
        violation = classes["Violation"]
        restrictions: dict[str, Any] = {
            "AlcoholViolation": properties["INSTANCE_OF_ACT"].value(individuals["ACT_ALCOHOL"]),
            "CarViolation": properties["APPLIES_TO"].some(classes["VEH_CAR"]),
            "MotorVehicleViolation": properties["APPLIES_TO"].some(classes["VEH_MOTOR"]),
            "LicenseRevokingViolation": properties["HAS_SANCTION"].some(
                classes["RevokeLicenseSanction"]
            ),
            "EscalatedViolation": escalated_from.some(violation),
            "HighPointViolation": onto.pointsDeducted.some(
                ConstrainedDatatype(int, min_inclusive=HIGH_POINT_THRESHOLD)
            ),
        }
        for spec in DEFINED_CLASSES:
            cls = type(spec.name, (Thing,), {})
            cls.label = _label(spec.label)
            cls.comment = _label(spec.axiom)
            cls.equivalent_to = [violation & restrictions[spec.name]]

    return world, onto


def export_owl(out_path: Path = OUT_OWL, **build_args: Any) -> tuple[World, Any]:
    world, onto = build_ontology(**build_args)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    onto.save(file=str(out_path), format="rdfxml")
    return world, onto


# ---------------------------------------------------------------------------
# Direct counts (independent of the OWL builder)
# ---------------------------------------------------------------------------


def _descendants(root: str, parent_of: dict[str, str | None]) -> set[str]:
    found = {root}
    while True:
        extra = {child for child, parent in parent_of.items() if parent in found} - found
        if not extra:
            return found
        found |= extra


def count_from_kg(nodes_path: Path = OUT_NODES, edges_path: Path = OUT_EDGES) -> dict[str, set[str]]:
    """Members (citation_id) of each defined class, read from the KG files."""
    nodes = {node["id"]: node for node in load_jsonl(nodes_path)}
    edges = load_jsonl(edges_path)
    violations = {k: v for k, v in nodes.items() if v["type"] == "Violation"}

    def pairs(relation: str) -> list[tuple[str, str]]:
        return [(e["source"], e["target"]) for e in edges if e["relation"] == relation]

    parent_of = {s: t for s, t in pairs("SUBCLASS_OF")}

    def cite(ids: set[str]) -> set[str]:
        return {violations[i]["citation_id"] for i in ids if i in violations}

    def applies_to(root: str) -> set[str]:
        wanted = _descendants(root, parent_of)
        return cite({s for s, t in pairs("APPLIES_TO") if t in wanted})

    return {
        "AlcoholViolation": cite({s for s, t in pairs("INSTANCE_OF_ACT") if t == "ACT_ALCOHOL"}),
        "CarViolation": applies_to("VEH_CAR"),
        "MotorVehicleViolation": applies_to("VEH_MOTOR"),
        "LicenseRevokingViolation": cite(
            {s for s, t in pairs("HAS_SANCTION") if nodes[t]["sanction_type"] == "revoke_license"}
        ),
        "EscalatedViolation": cite({t for _, t in pairs("ESCALATES_TO")}),
        "HighPointViolation": cite(
            {i for i, n in violations.items() if n["points_deducted"] >= HIGH_POINT_THRESHOLD}
        ),
    }


def count_from_kb(
    violations_path: Path = VIOLATIONS_FILE, knowledge_dir: Path = KNOWLEDGE_DIR
) -> dict[str, set[str]]:
    """Same sets, read from the violation table and the hand-written YAML knowledge."""
    rows = {canonical_citation_id(r["citation_id"]): r for r in load_json(violations_path)}
    ontology = load_yaml(knowledge_dir / "ontology.yaml")
    parent_of = {i["id"]: i["parent"] for i in ontology["vehicle_classes"]}
    acts = {a["id"]: a for a in load_yaml(knowledge_dir / "acts.yaml")["acts"]}

    def where(predicate: Callable[[dict], bool]) -> set[str]:
        return {cid for cid, row in rows.items() if predicate(row)}

    def applies_to(root: str) -> set[str]:
        wanted = _descendants(root, parent_of)
        return where(lambda r: r["vehicle_class"] in wanted)

    escalated: set[str] = set()
    for rule in load_yaml(knowledge_dir / "rules" / "escalate.yaml")["rules"]:
        if rule["when"].get("has_violation"):
            escalated.add(canonical_citation_id(rule["then"]["escalate_to"]))

    return {
        "AlcoholViolation": {
            canonical_citation_id(c) for c in acts["ACT_ALCOHOL"]["related_violations"]
        },
        "CarViolation": applies_to("VEH_CAR"),
        "MotorVehicleViolation": applies_to("VEH_MOTOR"),
        "LicenseRevokingViolation": where(
            lambda r: any(s["type"] == "revoke_license" for s in r["sanctions"])
        ),
        "EscalatedViolation": escalated,
        "HighPointViolation": where(lambda r: r["points_deducted"] >= HIGH_POINT_THRESHOLD),
    }


# ---------------------------------------------------------------------------
# Reasoning
# ---------------------------------------------------------------------------


@dataclass
class ReasoningResult:
    reasoner: str | None = None
    consistent: bool | None = None  # None = not checked
    seconds: float | None = None
    members: dict[str, set[str]] = field(default_factory=dict)
    unsatisfiable: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)  # reasoners that crashed


def java_version() -> str | None:
    """First line of `java -version`, or None. macOS ships a stub that only fails."""
    try:
        done = subprocess.run(
            [owlready2.JAVA_EXE, "-version"], capture_output=True, text=True, timeout=30
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    lines = (done.stderr or done.stdout).splitlines()
    return lines[0] if done.returncode == 0 and lines else None


def run_reasoner(owl_path: Path) -> ReasoningResult:
    """Classify the saved file (so the exported .owl itself is what gets checked)."""
    result = ReasoningResult()
    reasoners = (("Pellet", owlready2.sync_reasoner_pellet), ("HermiT", owlready2.sync_reasoner_hermit))
    for name, sync in reasoners:
        world = World()
        onto = world.get_ontology(owl_path.resolve().as_uri()).load()
        started = time.perf_counter()
        try:
            with onto:
                sync(world, debug=0)
        except OwlReadyInconsistentOntologyError:
            result.reasoner, result.consistent = name, False
            result.seconds = time.perf_counter() - started
            return result
        except Exception as error:  # reasoner crash: try the next one
            result.failures.append(f"{name}: {type(error).__name__}: {str(error).strip()[-600:]}")
            continue
        result.reasoner, result.consistent = name, True
        result.seconds = time.perf_counter() - started
        result.unsatisfiable = sorted(c.name for c in world.inconsistent_classes())
        for spec in DEFINED_CLASSES:
            # A LegalProvision individual is named by its citation_id.
            result.members[spec.name] = {
                i.basedOn[0].name for i in onto[spec.name].instances()
            }
        return result
    return result


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

PROTEGE_STEPS = """Mở bằng Protégé (có sẵn Java đi kèm):
  1. File → Open… → chọn data/knowledge/traffic.owl
  2. Menu Reasoner → HermiT → Start reasoner
  3. Tab Entities → Classes → chọn defined class (vd CarViolation), bật chế độ Inferred
     và xem mục Instances (hoặc dùng tab DL Query)."""


def ontology_stats(onto: Any) -> dict[str, int]:
    names = ("Violation", "Act", "Circumstance", "LegalProvision")
    stats = {name: len(onto[name].instances()) for name in names}
    stats["Lớp"] = len(list(onto.classes()))
    stats["Object property"] = len(list(onto.object_properties()))
    stats["Data property"] = len(list(onto.data_properties()))
    stats["Tổng số cá thể"] = len(list(onto.individuals()))
    return stats


def compare(
    reasoning: ReasoningResult, kg: dict[str, set[str]], kb: dict[str, set[str]]
) -> list[tuple[str, int | None, int, int, bool | None]]:
    """(class, inferred, KG, KB, match). Match compares the member sets, not just sizes."""
    rows = []
    for spec in DEFINED_CLASSES:
        inferred = reasoning.members.get(spec.name)
        in_kg, in_kb = kg[spec.name], kb[spec.name]
        match = None if inferred is None else inferred == in_kg == in_kb
        rows.append((spec.name, None if inferred is None else len(inferred), len(in_kg), len(in_kb), match))
    return rows


def _mark(match: bool | None) -> str:
    return {True: "khớp", False: "LỆCH", None: "chưa đối chiếu"}[match]


def table_lines(rows: list[tuple[str, int | None, int, int, bool | None]]) -> list[str]:
    lines = ["| Defined class | Reasoner | Đếm từ KG | Đếm từ KB | So tập citation_id |",
             "|---|---:|---:|---:|---|"]
    for name, inferred, in_kg, in_kb, match in rows:
        shown = "–" if inferred is None else str(inferred)
        lines.append(f"| {name} | {shown} | {in_kg} | {in_kb} | {_mark(match)} |")
    return lines


def render_report(
    stats: dict[str, int],
    reasoning: ReasoningResult,
    rows: list[tuple[str, int | None, int, int, bool | None]],
    java: str | None,
    kb: dict[str, set[str]],
    unmapped_alcohol: list[str],
) -> str:
    status = {True: "NHẤT QUÁN", False: "KHÔNG NHẤT QUÁN", None: "chưa kiểm tra"}
    lines = [
        "# Báo cáo suy luận OWL",
        "",
        "Sinh tự động bởi `python -m src.kg.export_owl` (`make owl`). Không sửa tay.",
        "",
        "## Ontology đã xuất (`traffic.owl`, chỉ gồm tiên đề khẳng định)",
        "",
        "| Thành phần | Số lượng |",
        "|---|---:|",
        *[f"| {k} | {v} |" for k, v in stats.items()],
        "",
        "## Kết quả suy luận",
        "",
        f"- Java: {java or 'không tìm thấy'}",
        f"- Reasoner: {reasoning.reasoner or 'không chạy được'} (owlready2 {owlready2.VERSION})",
        f"- Tính nhất quán: **{status[reasoning.consistent]}**",
    ]
    if reasoning.seconds is not None:
        lines.append(f"- Thời gian suy luận (gồm khởi động JVM): {reasoning.seconds:.2f} giây")
    if reasoning.consistent:
        lines.append(f"- Lớp không thỏa được: {', '.join(reasoning.unsatisfiable) or 'không có'}")
    lines += [f"- Reasoner lỗi: {failure}" for failure in reasoning.failures]
    if reasoning.consistent is None:
        lines += ["", "```", PROTEGE_STEPS, "```"]

    lines += ["", "## Defined classes", "", "| Lớp | Định nghĩa |", "|---|---|",
              *[f"| {s.name} | {s.axiom} |" for s in DEFINED_CLASSES]]
    lines += ["", "## Đối chiếu số cá thể được phân lớp", "", *table_lines(rows), "",
              "- **Đếm từ KG**: đọc trực tiếp `kg_nodes.jsonl`, `kg_edges.jsonl`.",
              "- **Đếm từ KB**: đọc `violations_168_clean.json`, `ontology.yaml`, `acts.yaml`, "
              "`rules/escalate.yaml` (không qua KG).",
              "- OWL được dựng từ KG nên cột KB là phép kiểm tra độc lập hơn.",
              "", "## Thành viên các lớp nhỏ (≤ 20, theo KB)", ""]
    for spec in DEFINED_CLASSES:
        if len(kb[spec.name]) <= 20:
            lines.append(f"- **{spec.name}**: {', '.join(sorted(kb[spec.name]))}")

    lines += [
        "",
        "## Giới hạn khi đọc kết quả",
        "",
        "- Khớp số liệu chứng tỏ phép phân lớp OWL tái lập đúng KG/KB; nó **không** chứng minh "
        "KG/KB đúng với văn bản luật.",
        f"- `AlcoholViolation` chỉ gồm vi phạm được `acts.yaml` gắn với `ACT_ALCOHOL`. Còn "
        f"{len(unmapped_alcohol)} vi phạm có chữ “nồng độ cồn” trong mô tả nhưng không có cạnh này "
        f"(có thể gồm cả hành vi chỉ nhắc đến, không phải hành vi uống rượu, bia khi điều khiển xe): "
        f"{', '.join(unmapped_alcohol) or 'không có'}.",
        "- `CarViolation` chỉ gồm vi phạm gắn với `VEH_CAR` hoặc lớp con. Vi phạm gắn `VEH_ANY` / "
        "`VEH_MOTOR` có thể áp dụng cho ô tô nhưng không được suy ra là riêng của ô tô.",
        "- Mỗi lớp `VEH_*` có một cá thể đại diện `VEH_*_individual` làm đích của `appliesToVehicle`; "
        "phân cấp xe nằm ở quan hệ lớp con.",
        "- `HighPointViolation` chỉ tính `pointsDeducted`, không tính mức trừ điểm có điều kiện.",
        "- `requiresContext` không giữ được ngữ nghĩa “một trong các ngữ cảnh” (`any_of`) và "
        "`escalatesTo` không giữ hậu quả kích hoạt; luật suy luận đầy đủ nằm ở `rules/*.yaml`.",
        "- Giả định thế giới mở: chỉ định nghĩa lớp bằng điều kiện tồn tại (∃), không dùng phủ định.",
        "",
    ]
    return "\n".join(lines)


def unmapped_alcohol_violations(
    members: set[str], violations_path: Path = VIOLATIONS_FILE
) -> list[str]:
    return sorted(
        row["citation_id"] for row in load_json(violations_path)
        if "nồng độ cồn" in row["description"].lower() and row["citation_id"] not in members
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Export the knowledge graph to OWL")
    parser.add_argument("--no-reasoner", action="store_true", help="only write the .owl file")
    args = parser.parse_args(argv)

    _, onto = export_owl()
    stats = ontology_stats(onto)
    print(f"Saved OWL: {OUT_OWL} ({OUT_OWL.stat().st_size / 1e6:.1f} MB)")
    for key, value in stats.items():
        print(f"  {key}: {value}")

    java = java_version()
    reasoning = ReasoningResult()
    if args.no_reasoner:
        print("Bỏ qua reasoner (--no-reasoner).")
    elif java is None:
        print("Không tìm thấy Java: đã xuất .owl nhưng không chạy reasoner.")
        print(PROTEGE_STEPS)
    else:
        print(f"Java: {java}")
        reasoning = run_reasoner(OUT_OWL)
        for failure in reasoning.failures:
            print(f"Reasoner lỗi -> {failure}")
        if reasoning.reasoner:
            verdict = "NHẤT QUÁN" if reasoning.consistent else "KHÔNG NHẤT QUÁN"
            print(f"Reasoner: {reasoning.reasoner} | {verdict} | {reasoning.seconds:.2f} s")
        else:
            print(PROTEGE_STEPS)

    kg, kb = count_from_kg(), count_from_kb()
    rows = compare(reasoning, kg, kb)
    print("\n".join(table_lines(rows)))
    report = render_report(
        stats, reasoning, rows, java, kb, unmapped_alcohol_violations(kb["AlcoholViolation"])
    )
    OUT_REPORT.write_text(report, encoding="utf-8")
    print(f"Saved report: {OUT_REPORT}")

    ran_but_failed = bool(java) and not args.no_reasoner and not reasoning.consistent
    if ran_but_failed or any(row[4] is False for row in rows) or kg != kb:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
