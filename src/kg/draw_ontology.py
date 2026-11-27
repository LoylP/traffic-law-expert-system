"""Report figures: ontology schema, KG example, KB statistics, one inference chain.

Usage: python -m src.kg.draw_ontology   (writes PNGs to docs_img/)
Read-only on the knowledge base; the inference chain comes from the engine's trace.
"""

from __future__ import annotations

import json
import textwrap
from collections import Counter
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

from src.kg.build_kg import KNOWLEDGE_DIR, OUT_EDGES, OUT_NODES, load_jsonl, load_yaml
from src.kg.export_owl import DATA_PROPERTIES, DEFINED_CLASSES, OBJECT_PROPERTIES, ROOT_DIR
from src.reasoning.engine import InferenceEngine
from src.reasoning.explain import Explainer, citation_label
from src.reasoning.knowledge_base import get_knowledge_base
from src.reasoning.penalty import PenaltyDecider, format_money
from src.reasoning.schema import Facts

OUT_DIR = ROOT_DIR / "docs_img"
CASES_FILE = ROOT_DIR / "data" / "eval" / "test_cases.jsonl"
SAMPLE_CASE = "C-005"
DPI = 200

INK, MUTED, EDGE, SURFACE = "#191919", "#555555", "#6b6b6b", "#ffffff"
# (border, fill) per role. Every box also carries a text label, so colour is never alone.
BLUE = ("#257de0", "#e8f1fc")
ORANGE = ("#f47230", "#fef0e8")
AQUA = ("#00a383", "#e3f6f2")
VIOLET = ("#6a4ce2", "#eeeafc")
GRAY = ("#8a8a8a", "#f3f3f3")

plt.rcParams.update({"font.family": "DejaVu Sans", "text.color": INK})


# ---------------------------------------------------------------------------
# Drawing helpers (data units are inches)
# ---------------------------------------------------------------------------


class Box:
    def __init__(self, x: float, y: float, w: float, h: float):
        self.x, self.y, self.w, self.h = x, y, w, h  # lower-left corner

    @property
    def left(self) -> tuple[float, float]:
        return self.x, self.y + self.h / 2

    @property
    def right(self) -> tuple[float, float]:
        return self.x + self.w, self.y + self.h / 2

    @property
    def top(self) -> tuple[float, float]:
        return self.x + self.w / 2, self.y + self.h

    @property
    def bottom(self) -> tuple[float, float]:
        return self.x + self.w / 2, self.y


def canvas(width: float, height: float) -> tuple[Any, Any]:
    fig = plt.figure(figsize=(width, height), facecolor=SURFACE)
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_xlim(0, width)
    ax.set_ylim(0, height)
    ax.axis("off")
    return fig, ax


def box(
    ax: Any, x: float, y: float, w: float, h: float, title: str, body: str = "",
    colors: tuple[str, str] = GRAY, title_size: float = 10, body_size: float = 8.5,
) -> Box:
    ax.add_patch(FancyBboxPatch(
        (x, y), w, h, boxstyle="round,pad=0,rounding_size=0.08",
        linewidth=1.4, edgecolor=colors[0], facecolor=colors[1], zorder=2,
    ))
    if body:
        ax.text(x + w / 2, y + h - 0.1, title, ha="center", va="top",
                fontsize=title_size, fontweight="bold", zorder=3, linespacing=1.25)
        offset = 0.12 + (title.count("\n") + 1) * title_size * 1.4 / 72
        ax.text(x + w / 2, y + h - offset, body, ha="center", va="top",
                fontsize=body_size, color=INK, zorder=3, linespacing=1.35)
    else:
        ax.text(x + w / 2, y + h / 2, title, ha="center", va="center",
                fontsize=title_size, fontweight="bold", zorder=3, linespacing=1.3)
    return Box(x, y, w, h)


def arrow(
    ax: Any, start: tuple[float, float], end: tuple[float, float], label: str = "",
    at: float = 0.5, offset: tuple[float, float] = (0, 0), dashed: bool = False,
    inherit: bool = False, curve: float = 0.0, size: float = 8,
) -> None:
    """`inherit=True` draws the UML hollow triangle (subclass -> superclass)."""
    ax.add_patch(FancyArrowPatch(
        start, end,
        arrowstyle="-|>", mutation_scale=15 if inherit else 11,
        linewidth=1.1, linestyle=(0, (4, 3)) if dashed else "solid",
        edgecolor=EDGE, facecolor=SURFACE if inherit else EDGE,
        connectionstyle=f"arc3,rad={curve}", shrinkA=0, shrinkB=0, zorder=1,
    ))
    if label:
        x = start[0] + (end[0] - start[0]) * at + offset[0]
        y = start[1] + (end[1] - start[1]) * at + offset[1]
        ax.text(x, y, label, ha="center", va="center", fontsize=size, color=INK, zorder=4,
                bbox={"boxstyle": "round,pad=0.18", "fc": SURFACE, "ec": "none"})


def wrap(text: str, width: int, lines: int = 0) -> str:
    wrapped = textwrap.wrap(text, width)
    if lines and len(wrapped) > lines:
        wrapped = wrapped[:lines]
        wrapped[-1] = wrapped[-1].rstrip(" ,;") + " …"
    return "\n".join(wrapped)


def heading(ax: Any, x: float, y: float, title: str, subtitle: str = "") -> None:
    ax.text(x, y, title, fontsize=15, fontweight="bold", va="top")
    if subtitle:
        ax.text(x, y - 0.36, subtitle, fontsize=9, color=MUTED, va="top")


def save(fig: Any, name: str, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / name
    fig.savefig(path, dpi=DPI, facecolor=SURFACE)
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------
# 1. Ontology schema
# ---------------------------------------------------------------------------


def draw_schema(out_dir: Path = OUT_DIR) -> Path:
    fig, ax = canvas(17, 11.4)
    heading(ax, 0.3, 11.15, "Lược đồ ontology (traffic.owl)",
            "Chỉ vẽ lớp và quan hệ, không vẽ cá thể.  Mũi tên đầu rỗng: lớp con ⊑ lớp cha.  "
            "Nét đứt: defined class do reasoner tự phân lớp.")
    prop = {name: name for name, *_ in OBJECT_PROPERTIES.values()}

    data = "\n".join(f"{name}: xsd:{'integer' if t is int else 'string'}"
                     for name, (t, _) in DATA_PROPERTIES.items())
    violation = box(ax, 6.7, 5.7, 3.6, 1.9, "Violation\nVi phạm", data, BLUE, 11.5, 9)
    legal = box(ax, 6.7, 9.0, 3.6, 1.1, "LegalProvision\nQuy định pháp luật",
                "legalExcerpt: xsd:string", AQUA)
    act = box(ax, 0.9, 7.1, 2.9, 0.85, "Act\nHành vi", colors=ORANGE)
    sanction = box(ax, 13.1, 7.1, 3.2, 0.85,
                   "AdditionalSanction\nXử phạt bổ sung, khắc phục", colors=VIOLET, title_size=9.5)

    arrow(ax, violation.top, legal.bottom, prop["basedOn"])
    arrow(ax, (6.7, 7.25), act.right, prop["instanceOfAct"])
    arrow(ax, (10.3, 7.25), sanction.left, prop["hasSanction"])

    # self relations
    arrow(ax, (10.3, 6.65), (10.3, 5.9), curve=-1.5)
    ax.text(11.65, 6.28, f"{prop['escalatesTo']}\n(nghịch đảo: escalatedFrom)",
            fontsize=8, ha="left", va="center")
    arrow(ax, (6.7, 5.9), (6.7, 6.65), curve=-1.5)
    ax.text(5.35, 6.28, prop["excludes"], fontsize=8, ha="right", va="center")

    sanction_children = (("RevokeLicense\nSanction", 12.35), ("Confiscation\nSanction", 13.9),
                         ("Remedial\nMeasure", 15.45))
    for name, x in sanction_children:
        child = box(ax, x, 8.65, 1.42, 0.65, name, colors=VIOLET, title_size=7.8)
        arrow(ax, child.bottom, sanction.top, inherit=True)

    # context union (range of requiresContext)
    box(ax, 0.5, 3.45, 3.7, 2.25, "", colors=GRAY)
    ax.text(2.35, 5.55, "Ngữ cảnh (range = hợp 4 lớp)", ha="center", va="top",
            fontsize=9, fontweight="bold", zorder=3)
    for index, name in enumerate(("RoadType · Loại đường", "TimeContext · Thời gian",
                                  "AlcoholLevel · Mức nồng độ cồn",
                                  "SpeedBand · Khoảng vượt tốc độ")):
        box(ax, 0.7, 4.76 - index * 0.41, 3.3, 0.34, name, colors=ORANGE, title_size=8)
    arrow(ax, (6.7, 5.75), (4.2, 5.0), prop["requiresContext"])

    # vehicle hierarchy
    vehicle = box(ax, 6.95, 3.95, 3.1, 0.7, "VehicleClass\nLoại phương tiện", colors=AQUA)
    arrow(ax, violation.bottom, vehicle.top, prop["appliesToVehicle"])
    root = box(ax, 7.55, 2.9, 1.9, 0.55, "VEH_ANY", colors=AQUA, title_size=9)
    arrow(ax, root.top, vehicle.bottom, inherit=True)
    level2 = {}
    for name, label, x, w in (
        ("VEH_MOTOR", "Cơ giới", 4.3, 2.0),
        ("VEH_SPECIAL", "Xe máy chuyên dùng", 6.45, 1.9),
        ("VEH_BICYCLE_\nRUDIMENTARY", "Xe đạp, thô sơ", 8.5, 1.9),
        ("VEH_PEDESTRIAN", "Người đi bộ", 10.5, 1.85),
    ):
        level2[name] = box(ax, x, 1.65, w, 0.8, name, label, AQUA, 8.2, 7.8)
        arrow(ax, level2[name].top, root.bottom, inherit=True)
    for name, label, x in (("VEH_CAR", "Ô tô", 4.15), ("VEH_MOTORBIKE", "Mô tô, xe gắn máy", 6.4)):
        child = box(ax, x, 0.45, 2.0, 0.75, name, label, AQUA, 8.5, 7.8)
        arrow(ax, child.top, level2["VEH_MOTOR"].bottom, inherit=True)

    # defined classes
    box(ax, 12.55, 0.4, 4.15, 5.35, "", colors=BLUE)
    ax.text(14.62, 5.58, "Defined classes (≡) ⊑ Violation", ha="center", va="top",
            fontsize=9.5, fontweight="bold", zorder=3)
    for index, spec in enumerate(DEFINED_CLASSES):
        condition = spec.axiom.removeprefix("Violation ⊓ ").split(" (")[0]
        y = 4.48 - index * 0.8
        ax.add_patch(FancyBboxPatch(
            (12.72, y), 3.81, 0.66, boxstyle="round,pad=0,rounding_size=0.06",
            linewidth=1.1, linestyle=(0, (4, 3)), edgecolor=BLUE[0], facecolor=SURFACE, zorder=2.5,
        ))
        ax.text(14.62, y + 0.45, spec.name, ha="center", va="center", fontsize=8.8,
                fontweight="bold", zorder=3)
        ax.text(14.62, y + 0.18, condition, ha="center", va="center", fontsize=7.4, zorder=3)
    arrow(ax, (12.55, 4.9), (10.3, 5.75), dashed=True, inherit=True)

    # classes without an OWL object property
    ax.text(0.35, 2.95, "Lớp chưa có object property trong OWL", fontsize=9,
            fontweight="bold", color=MUTED)
    circumstance = box(ax, 0.35, 1.9, 2.7, 0.75, "Circumstance\nTình tiết",
                       colors=GRAY, title_size=9)
    for name, x in (("Aggravating\nTăng nặng", 0.35), ("Mitigating\nGiảm nhẹ", 1.75)):
        child = box(ax, x, 0.8, 1.3, 0.65, name, colors=GRAY, title_size=8)
        arrow(ax, child.top, circumstance.bottom, inherit=True)
    for name, x, width in (("Consequence", 0.35, 1.05), ("ResistanceBehavior", 1.48, 1.45),
                           ("Subject", 3.01, 0.75)):
        box(ax, x, 0.2, width, 0.4, name, colors=GRAY, title_size=7.4)
    return save(fig, "ontology_schema.png", out_dir)


# ---------------------------------------------------------------------------
# 2. KG example: ACT_RED_LIGHT
# ---------------------------------------------------------------------------


def kg_subgraph(act_id: str) -> dict[str, Any]:
    nodes = {node["id"]: node for node in load_jsonl(OUT_NODES)}
    edges = load_jsonl(OUT_EDGES)

    def out(source: str, relation: str) -> list[dict]:
        return [e for e in edges if e["source"] == source and e["relation"] == relation]

    def describe(node_id: str) -> dict[str, Any]:
        return {
            "node": nodes[node_id],
            "legal": nodes[out(node_id, "BASED_ON")[0]["target"]],
            "sanctions": [nodes[e["target"]] for e in out(node_id, "HAS_SANCTION")],
        }

    rows = []
    for edge in edges:
        if edge["relation"] == "INSTANCE_OF_ACT" and edge["target"] == act_id:
            row = describe(edge["source"])
            row["escalations"] = [
                {**describe(e["target"]), "edge": e} for e in out(edge["source"], "ESCALATES_TO")
            ]
            rows.append(row)
    rows.sort(key=lambda r: r["node"]["article"])
    return {"act": nodes[act_id], "rows": rows}


def _violation_body(item: dict[str, Any]) -> str:
    node = item["node"]
    points = node["points_deducted"]
    lines = [
        f"Phạt {format_money(node['fine_min'])} – {format_money(node['fine_max'])}",
        f"Trừ {points} điểm GPLX" if points else "Không có mức trừ điểm trong KG",
    ]
    for sanction in item["sanctions"]:
        text = sanction["sanction_type"]
        if sanction.get("duration_min") is not None:
            text += f" {sanction['duration_min']}–{sanction['duration_max']} tháng"
        lines.append(f"hasSanction: {text}")
    return "\n".join(lines)


def draw_red_light(out_dir: Path = OUT_DIR) -> Path:
    graph = kg_subgraph("ACT_RED_LIGHT")
    kb = get_knowledge_base()
    vehicles = {i["id"]: i["label"] for i in kb.ontology["vehicle_classes"]}
    row_h = 2.3
    height = 1.5 + row_h * len(graph["rows"])
    fig, ax = canvas(17.5, height)
    heading(ax, 0.3, height - 0.2, "Đồ thị tri thức quanh ACT_RED_LIGHT",
            "Act → Violation theo loại xe → LegalProvision (basedOn); escalatesTo khi gây tai nạn. "
            "Mũi tên instanceOfAct vẽ theo chiều đọc (cạnh gốc: Violation → Act).")

    middle = (height - 1.1) / 2
    act = box(ax, 0.3, middle - 0.75, 2.6, 1.5, "ACT_RED_LIGHT",
              wrap(graph["act"]["label"], 28), ORANGE, 10.5, 8.8)

    def legal_box(item: dict, x: float, y: float) -> Box:
        unit = item["legal"]
        # the corpus text is "Điều X\n<point text>": show the point text, truncated
        excerpt = unit["text"].split("\n", 1)[-1]
        return box(ax, x, y, 3.2, 1.62, citation_label(unit).replace(", ", ",\n"),
                   wrap(f"“{excerpt}”", 40, 4), AQUA, 8.8, 7.8)

    any_sanction = False
    for index, row in enumerate(graph["rows"]):
        y = height - 1.3 - row_h * (index + 1) + 0.35
        node = row["node"]
        violation = box(ax, 3.9, y + 0.17, 2.9, 1.3,
                        f"{node['violation_id']} · {node['vehicle_class']}",
                        f"{vehicles[node['vehicle_class']]}\n{_violation_body(row)}",
                        BLUE, 8.8, 8)
        arrow(ax, act.right, violation.left)
        provision = legal_box(row, 8.0, y)
        arrow(ax, violation.right, provision.left, "basedOn")
        any_sanction |= bool(row["sanctions"])
        for escalation in row["escalations"]:
            target = escalation["node"]
            consequence = ", ".join(escalation["edge"].get("consequence", []))
            escalated = box(ax, 11.85, y + 0.17, 2.1, 1.3, target["violation_id"],
                            _violation_body(escalation).replace(" – ", " –\n"), VIOLET, 8.8, 7.8)
            target_legal = legal_box(escalation, 14.1, y)
            arrow(ax, escalated.right, target_legal.left)
            # routed above the provision box of the source violation
            start = (violation.x + violation.w * 0.75, violation.y + violation.h)
            lane = y + 1.92
            ax.plot([start[0], start[0], 11.5, 11.5], [start[1], lane, lane, escalated.left[1]],
                    color=EDGE, linewidth=1.1, zorder=1)
            arrow(ax, (11.5, escalated.left[1]), escalated.left)
            ax.text(9.2, lane, f"escalatesTo khi {consequence}  ({escalation['edge']['rule_id']})",
                    ha="center", va="center", fontsize=7.8, zorder=4,
                    bbox={"boxstyle": "round,pad=0.2", "fc": SURFACE, "ec": "none"})
            any_sanction |= bool(escalation["sanctions"])
        if not row["escalations"]:
            ax.text(11.85, y + 0.82, "Không có cạnh escalatesTo trong KG",
                    fontsize=8.5, color=MUTED, va="center")
    if not any_sanction:
        ax.text(0.3, 0.18, "Không vi phạm nào trong đồ thị con này có cạnh hasSanction trong KG.",
                fontsize=9, color=MUTED)
    return save(fig, "kg_example_red_light.png", out_dir)


# ---------------------------------------------------------------------------
# 3. KB statistics
# ---------------------------------------------------------------------------


def kb_counts(knowledge_dir: Path = KNOWLEDGE_DIR) -> tuple[dict[str, int], dict[str, int]]:
    """Counts every item in the YAML files, verified or not."""
    counts: Counter = Counter()
    for path in sorted((knowledge_dir / "rules").glob("*.yaml")):
        for rule in load_yaml(path)["rules"]:
            key = rule["type"]
            if key == "classify":
                key = "classify core" if path.stem == "classify_core" else "classify auto"
            counts[key] += 1
    order = ("derive", "classify core", "classify auto", "escalate", "exclude", "ask",
             "temporal", "note")
    unknown = set(counts) - set(order)
    if unknown:
        raise ValueError(f"unplotted rule type(s): {sorted(unknown)}")
    circumstances = load_yaml(knowledge_dir / "circumstances.yaml")
    others = {
        "Hành vi (Act)": len(load_yaml(knowledge_dir / "acts.yaml")["acts"]),
        "Tình tiết tăng nặng": len(circumstances["aggravating_circumstances"]),
        "Tình tiết giảm nhẹ": len(circumstances["mitigating_circumstances"]),
    }
    return {name: counts[name] for name in order}, others


def draw_kb_stats(out_dir: Path = OUT_DIR) -> Path:
    rules, others = kb_counts()
    fig, axes = plt.subplots(
        2, 1, figsize=(10, 6.6), facecolor=SURFACE,
        gridspec_kw={"height_ratios": [len(rules), len(others)]},
    )
    panels = (
        (axes[0], rules, f"Số luật theo loại (tổng {sum(rules.values())})"),
        (axes[1], others, "Hành vi và tình tiết"),
    )
    for ax, values, title in panels:
        bars = ax.barh(list(values), list(values.values()), color=BLUE[0], height=0.68)
        ax.bar_label(bars, padding=4, fontsize=9.5, color=INK)
        ax.invert_yaxis()
        ax.set_title(title, loc="left", fontsize=12, fontweight="bold")
        ax.set_xlim(0, max(values.values()) * 1.1)
        ax.set_xticks([])
        ax.tick_params(axis="y", length=0, labelsize=9.5, labelcolor=INK)
        for side in ("top", "right", "bottom"):
            ax.spines[side].set_visible(False)
        ax.spines["left"].set_color(EDGE)
    fig.text(0.02, 0.015, "Đếm trong data/knowledge/*.yaml, gồm cả mục chưa verified. "
             "Hai khung dùng thang đo riêng.", fontsize=8.5, color=MUTED)
    fig.tight_layout(rect=(0, 0.04, 1, 1), h_pad=2)
    return save(fig, "kb_stats.png", out_dir)


# ---------------------------------------------------------------------------
# 4. Inference example
# ---------------------------------------------------------------------------


def load_case(case_id: str, path: Path = CASES_FILE) -> dict[str, Any]:
    for case in load_jsonl(path):
        if case["id"] == case_id:
            return case
    raise ValueError(f"case {case_id} not found in {path}")


def inference_lanes(case: dict[str, Any]) -> dict[str, Any]:
    """Run the engine on the case's labelled facts and group its trace by violation."""
    kb = get_knowledge_base()
    facts = Facts.model_validate(case["ground_truth"]["facts"])
    result = InferenceEngine(kb).run(facts)
    penalty = PenaltyDecider(kb).decide(result)
    rules = {rule.id: rule for rule in kb.rules}
    derives = [step for step in result.trace if step.type == "derive"]

    lanes, used = [], set()
    for step in (s for s in result.trace if s.type == "classify"):
        acts = set(step.matched_facts.get("has_act", []))
        contexts = set(step.matched_facts.get("has_context", []))
        # a derive step feeds a lane through the acts its rule adds or the context it produced
        feeding = [
            d for d in derives
            if acts & set(rules[d.rule_id].then.get("add_acts", []))
            or contexts & set(d.produced.get("contexts", []))
        ]
        used |= {d.rule_id for d in feeding}
        citation = step.produced["violation"]
        decision = next(d for d in penalty.decisions if d.citation_id == citation)
        lanes.append({"classify": step, "derive": feeding, "decision": decision})
    other = [s.rule_id for s in result.trace if s.type not in ("derive", "classify")]
    unplaced = [d.rule_id for d in derives if d.rule_id not in used] + other
    if unplaced:
        raise ValueError(f"trace steps missing from the figure: {unplaced}")
    return {"lanes": lanes, "result": result, "penalty": penalty,
            "facts": facts.model_dump(exclude_defaults=True), "explainer": Explainer(kb)}


def _pairs(values: dict[str, Any]) -> list[str]:
    lines = []
    for key, value in values.items():
        if value in (None, [], {}):
            continue
        shown = ", ".join(map(str, value)) if isinstance(value, list) else value
        lines.append(f"{key} = {shown}")
    return lines


def _fact_lines(lane: dict[str, Any], facts: dict[str, Any]) -> list[str]:
    acts = lane["classify"].matched_facts.get("has_act", [])
    keys = {k for step in lane["derive"] for k, v in step.matched_facts.items()
            if v is not None and k in facts}
    return [f"acts ∋ {act}" for act in acts] + _pairs({k: facts[k] for k in facts if k in keys})


def _derive_text(step: Any) -> str:
    produced = _pairs({k: v for k, v in step.produced.items() if k != "set_facts"})
    produced += _pairs(step.produced.get("set_facts", {}))
    outcome = "; ".join(produced) or "không thêm mới (đã có sẵn)"
    return f"{outcome}\nkhớp: {', '.join(k for k, v in step.matched_facts.items() if v is not None)}"


def draw_inference(out_dir: Path = OUT_DIR, case_id: str = SAMPLE_CASE) -> Path:
    case = load_case(case_id)
    data = inference_lanes(case)
    penalty, explainer = data["penalty"], data["explainer"]
    step_h, gap = 0.98, 0.14
    heights = [max(1.85, len(l["derive"]) * (step_h + gap) - gap) for l in data["lanes"]]
    height = 2.3 + sum(heights) + 0.4 * len(heights) + 1.45
    fig, ax = canvas(17, height)
    heading(ax, 0.3, height - 0.2, f"Chuỗi suy luận của case {case_id}",
            "Đầu vào: facts gán nhãn của bộ test (không qua LLM). Mỗi bước lấy từ TraceStep "
            "của InferenceEngine; mức phạt từ PenaltyDecider.")
    ax.text(0.3, height - 0.95, wrap(f"“{case['query']}”", 170), fontsize=10,
            style="italic", va="top")
    ax.text(0.3, height - 1.4,
            f"Fact dùng chung cho mọi luật classify: vehicle_class = "
            f"{data['facts']['vehicle_class']}", fontsize=9.5, va="top")

    columns = ((0.3, 3.0, "1. Facts"), (3.9, 4.1, "2. derive"),
               (8.6, 3.8, "3. classify"), (13.0, 3.7, "4. penalty"))
    for x, width, title in columns:
        ax.text(x + width / 2, height - 1.95, title, ha="center", fontsize=11.5, fontweight="bold")

    top = height - 2.25
    for lane, lane_h in zip(data["lanes"], heights):
        step, decision = lane["classify"], lane["decision"]
        middle = top - lane_h / 2
        facts = box(ax, 0.3, middle - 0.55, 3.0, 1.1,
                    "\n".join(_fact_lines(lane, data["facts"])), colors=GRAY, title_size=8)
        classified = box(
            ax, 8.6, middle - 0.9, 3.8, 1.8, step.rule_id,
            f"→ {step.produced['violation']}\n"
            f"khi: {', '.join(step.matched_facts.get('has_act', []))}"
            + (f" ∧ {', '.join(step.matched_facts['has_context'])}"
               if step.matched_facts.get("has_context") else "")
            + f"\n\nCăn cứ: {wrap(step.source or '—', 44)}",
            BLUE, 9.2, 8.4)

        derive_total = len(lane["derive"]) * (step_h + gap) - gap
        y = middle + derive_total / 2
        for derived in lane["derive"]:
            y -= step_h
            item = box(ax, 3.9, y, 4.1, step_h, derived.rule_id,
                       "\n".join(wrap(line, 56) for line in _derive_text(derived).split("\n"))
                       + f"\nnguồn: {wrap(derived.source or '—', 60, 1)}",
                       ORANGE, 8.8, 7.4)
            arrow(ax, facts.right, item.left)
            arrow(ax, item.right, classified.left)
            y -= gap
        if not lane["derive"]:
            arrow(ax, facts.right, classified.left, "không cần luật derive", size=8.5)

        low, high = decision.fine_range
        decided = box(
            ax, 13.0, middle - 0.9, 3.7, 1.8, explainer.label_of(decision.citation_id),
            f"Khung: {format_money(low)} –\n{format_money(high)}\n"
            f"Đề xuất: {format_money(decision.recommended_fine)}\n"
            f"Điểm GPLX theo quy định: {decision.points_deducted}",
            AQUA, 8.8, 8.6)
        arrow(ax, classified.right, decided.left)
        top -= lane_h + 0.4

    summary = (
        f"Kết luận ({data['result'].status}): tổng tiền phạt đề xuất "
        f"{format_money(penalty.total_recommended_fine)}; điểm GPLX bị trừ "
        f"{penalty.total_points_deducted}; tăng nặng {len(penalty.aggravating)}, "
        f"giảm nhẹ {len(penalty.mitigating)}"
    )
    notes = "\n".join(wrap(line, 175) for line in penalty.reasoning[1:])
    box(ax, 0.3, 0.2, 16.4, 1.15, summary, notes, GRAY, 11, 9)
    return save(fig, "inference_example.png", out_dir)


def main() -> None:
    for draw in (draw_schema, draw_red_light, draw_kb_stats, draw_inference):
        print(f"Saved {draw().relative_to(ROOT_DIR)}")


if __name__ == "__main__":
    main()
