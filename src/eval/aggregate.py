"""Collect data/eval/results/ into tables and charts under data/eval/report/.

Only reads summary.json files written by run_eval.py: no metric is computed here
and no interpretation is written.

    python -m src.eval.aggregate
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

from src.eval import cases as C  # noqa: E402
from src.eval.run_eval import CONFIGS, DEFAULT_OUT, NO_LLM_CONFIGS, NO_LLM_DIR, model_slug

DEFAULT_REPORT = DEFAULT_OUT.parent / "report"
MAIN_MODEL = "qwen3.5:4b-q4_K_M"
SMALL_TIER = ("qwen3.5:4b-q4_K_M", "gemma4:e4b", "llama3.2:3b")
LARGE_TIER = ("qwen3.5:9b-q4_K_M", "gemma4:12b", "llama3.1:8b")
SMALL_TIER_MAX_BILLIONS = 6.0  # fallback for models outside the two lists

# column -> path inside summary["metrics"]["overall"]
COLUMNS: dict[str, tuple[str, ...]] = {
    "slot_f1": ("extraction", "slot", "f1"),
    "acts_f1": ("extraction", "acts", "f1"),
    "halluc_slot": ("extraction", "hallucinated_slot_rate"),
    "violation_p": ("reasoning", "violation", "precision"),
    "violation_r": ("reasoning", "violation", "recall"),
    "violation_f1": ("reasoning", "violation", "f1"),
    "exact_set": ("reasoning", "exact_set_match"),
    "citation_acc": ("reasoning", "citation_accuracy"),
    "citation_exists": ("reasoning", "citation_exists_rate"),
    "fine_range": ("reasoning", "fine_range_accuracy"),
    "fine_exact": ("reasoning", "recommended_fine_exact"),
    "points_acc": ("reasoning", "points_accuracy"),
    "sanctions_f1": ("reasoning", "sanctions", "f1"),
    "aggravating": ("reasoning", "aggravating_exact"),
    "mitigating": ("reasoning", "mitigating_exact"),
    "first_status": ("dialog", "first_status_accuracy"),
    "first_ask_slot": ("dialog", "first_ask_slot_accuracy"),
    "status": ("dialog", "status_accuracy"),
    "avg_questions": ("dialog", "avg_question_turns"),
    "end_to_end": ("end_to_end_accuracy",),
}
MAIN_METRICS = ("slot_f1", "violation_f1", "exact_set", "fine_exact", "status", "end_to_end")
GROUP_METRICS = ("slot_f1", "violation_f1", "exact_set", "status", "end_to_end")
STEPS = ("extract", "ground", "engine", "write")

# Reference palette of the dataviz method, light surface, fixed categorical order.
SERIES = ("#257de0", "#f47230", "#00b894", "#f2a600", "#ee7fac", "#008a17")
SEQUENTIAL = ("#ffffff", "#257de0")
SURFACE, INK, MUTED, GRID = "#ffffff", "#191919", "#666666", "#e5e5e5"


def dig(data: Any, path: tuple[str, ...]) -> Any:
    for key in path:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


def load_summaries(results: Path) -> list[dict[str, Any]]:
    summaries = []
    for path in sorted(Path(results).glob("*/*/summary.json")):
        summary = json.loads(path.read_text(encoding="utf-8"))
        summary["slug"] = path.parent.parent.name
        summaries.append(summary)
    return summaries


def model_name(summary: dict[str, Any]) -> str:
    return dig(summary, ("env", "model", "name")) or summary["slug"]


def tier(summary: dict[str, Any]) -> str:
    name = model_name(summary)
    if name in SMALL_TIER or name in LARGE_TIER:
        return "nhỏ" if name in SMALL_TIER else "lớn"
    size = str(dig(summary, ("env", "model", "parameter_size")) or "")
    try:
        billions = float(size.rstrip("Bb"))
    except ValueError:
        return "chưa rõ"
    return "nhỏ" if billions <= SMALL_TIER_MAX_BILLIONS else "lớn"


def table_row(summary: dict[str, Any], **leading: Any) -> dict[str, Any]:
    overall = summary["metrics"]["overall"]
    row = {**leading, "n": overall["n_cases"]}
    row.update({name: dig(overall, path) for name, path in COLUMNS.items()})
    row["total_p50_ms"] = dig(summary, ("system", "latency_ms", "total", "p50"))
    row["total_p95_ms"] = dig(summary, ("system", "latency_ms", "total", "p95"))
    row["invalid_json"] = dig(summary, ("system", "llm", "invalid_json_rate"))
    row["fallback_regex"] = dig(summary, ("system", "llm", "fallback_to_regex_rate"))
    row["llm_unfaithful"] = dig(summary, ("system", "faithfulness", "llm_unfaithful_rate"))
    row["template_fallback"] = dig(summary, ("system", "faithfulness", "template_fallback_rate"))
    return row


def ablation_summaries(summaries: list[dict], main_model: str) -> dict[str, dict]:
    """config -> summary of the main model (or of the runs without an LLM)."""
    slug = model_slug(main_model)
    found = {s["config"]: s for s in summaries if s["slug"] in (slug, NO_LLM_DIR)}
    return {config: found[config] for config in CONFIGS if config in found}


def model_summaries(summaries: list[dict]) -> list[dict]:
    """Baselines first, then every model × full and llm_only, small tier first."""
    baselines = [
        s for c in ("oracle_facts", "regex_extractor") for s in summaries
        if s["slug"] == NO_LLM_DIR and s["config"] == c
    ]
    order = [*SMALL_TIER, *LARGE_TIER]
    runs = [s for s in summaries if s["slug"] != NO_LLM_DIR and s["config"] in ("full", "llm_only")]
    runs.sort(
        key=lambda s: (
            {"nhỏ": 0, "lớn": 1}.get(tier(s), 2),
            order.index(model_name(s)) if model_name(s) in order else len(order),
            model_name(s),
            CONFIGS.index(s["config"]),
        )
    )
    return baselines + runs


def warnings_of(summaries: list[dict]) -> list[str]:
    """Facts that make runs not comparable. No interpretation of the numbers."""
    warnings = []
    llm_runs = [s for s in summaries if s["config"] not in NO_LLM_CONFIGS]
    gpus: dict[str, set[str]] = {}
    for summary in llm_runs:
        for gpu in summary["env"].get("gpus", []):
            gpus.setdefault(gpu, set()).add(model_name(summary))
    if len(gpus) > 1:
        detail = "; ".join(f"{gpu}: {', '.join(sorted(m))}" for gpu, m in sorted(gpus.items()))
        warnings.append(f"Các model chạy trên GPU khác nhau, không so sánh độ trễ được — {detail}")
    if len({s["env"].get("case_ids_sha1") for s in summaries}) > 1:
        counts = ", ".join(
            sorted({f"{model_name(s)}/{s['config']}={s['env'].get('n_cases')}" for s in summaries})
        )
        warnings.append(f"Các lần chạy không cùng tập case — {counts}")
    shas = {dig(s, ("env", "git", "sha")) for s in summaries}
    if len(shas) > 1:
        warnings.append(f"Các lần chạy dùng {len(shas)} commit khác nhau.")
    if any(dig(s, ("env", "git", "dirty")) for s in summaries):
        warnings.append("Có lần chạy khi mã nguồn đã sửa nhưng chưa commit.")
    unverified = max((s["env"].get("n_unverified_cases", 0) for s in summaries), default=0)
    if unverified:
        warnings.append(f"Tập case còn {unverified} case chưa verified.")
    spilled = sorted({
        model_name(s) for s in llm_runs
        if (dig(s, ("env", "model", "vram_fraction")) or 1.0) < 0.999
    })
    if spilled:
        warnings.append(f"Model không nằm trọn trong VRAM (một phần chạy CPU): {', '.join(spilled)}")
    return warnings


# -- tables ----------------------------------------------------------------
def markdown_table(frame: pd.DataFrame) -> str:
    def cell(value: Any) -> str:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return "—"
        if isinstance(value, float):
            return f"{value:.0f}" if abs(value) >= 100 else f"{value:.3f}"
        return str(value)

    lines = ["| " + " | ".join(frame.columns) + " |", "|" + "---|" * len(frame.columns)]
    lines += ["| " + " | ".join(cell(v) for v in row) + " |" for row in frame.astype(object).values]
    return "\n".join(lines)


def write_table(report: Path, name: str, title: str, frame: pd.DataFrame, warnings: list[str]):
    with pd.ExcelWriter(report / f"{name}.xlsx") as writer:
        frame.to_excel(writer, index=False, sheet_name=name)
        if warnings:
            pd.DataFrame({"cảnh báo": warnings}).to_excel(writer, index=False, sheet_name="warnings")
    lines = [f"# {title}", ""]
    lines += [f"> CẢNH BÁO: {w}" for w in warnings]
    lines += [""] if warnings else []
    lines += [markdown_table(frame), ""]
    (report / f"{name}.md").write_text("\n".join(lines), encoding="utf-8")


# -- charts ----------------------------------------------------------------
def _style(ax) -> None:
    ax.set_facecolor(SURFACE)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=MUTED, length=0)


def grouped_bars(ax, categories: list[str], series: dict[str, list[float | None]]) -> None:
    """One axis, fixed hue order, a gap between adjacent bars, values labelled."""
    width = 0.8 / max(len(series), 1)
    for index, (name, values) in enumerate(series.items()):
        positions = [x - 0.4 + width * (index + 0.5) for x in range(len(categories))]
        bars = ax.bar(
            positions, [v or 0 for v in values], width, label=name,
            color=SERIES[index % len(SERIES)], edgecolor=SURFACE, linewidth=1.5,
        )
        labels = ["n/a" if v is None else f"{v:.2f}" for v in values]
        ax.bar_label(bars, labels=labels, padding=2, fontsize=6.5, color=INK, rotation=90)
    ax.set_xticks(range(len(categories)), categories)
    ax.set_ylim(0, 1.18)
    ax.set_yticks([0, 0.25, 0.5, 0.75, 1.0])
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    _style(ax)


def _save(figure, path: Path) -> Path:
    figure.savefig(path, dpi=200, bbox_inches="tight", facecolor=SURFACE)
    plt.close(figure)
    return path


def chart_by_metric(path: Path, title: str, panels: list[tuple[str, dict[str, dict]]]) -> Path:
    """panels = [(panel title, {series label: summary})]; categories = main metrics.
    At most six series per panel (the size of the fixed hue order)."""
    figure, axes = plt.subplots(
        len(panels), 1, figsize=(11, 4.2 * len(panels)), squeeze=False, layout="constrained"
    )
    for ax, (panel, runs) in zip(axes[:, 0], panels):
        series = {
            label: [dig(s["metrics"]["overall"], COLUMNS[m]) for m in MAIN_METRICS]
            for label, s in runs.items()
        }
        grouped_bars(ax, list(MAIN_METRICS), series)
        ax.set_title(panel, color=INK, loc="left", fontsize=11)
        ax.legend(loc="upper left", bbox_to_anchor=(1.0, 1.0), frameon=False, fontsize=8)
    figure.suptitle(title, color=INK)
    return _save(figure, path)


def chart_groups(path: Path, summary: dict) -> Path:
    by_group = summary["metrics"]["by_group"]
    groups = [g for g in C.GROUPS if g in by_group]
    series = {m: [dig(by_group[g], COLUMNS[m]) for g in groups] for m in GROUP_METRICS}
    figure, ax = plt.subplots(figsize=(11, 4.5), layout="constrained")
    grouped_bars(ax, [f"{g} (n={by_group[g]['n_cases']})" for g in groups], series)
    ax.set_title(f"full — {model_name(summary)}: theo nhóm case", color=INK, loc="left")
    ax.legend(loc="upper left", bbox_to_anchor=(1.0, 1.0), frameon=False, fontsize=8)
    return _save(figure, path)


def chart_latency(path: Path, runs: dict[str, dict]) -> Path | None:
    """Mean milliseconds per step, stacked; each step averages its own real calls."""
    labels = [
        label for label, s in runs.items()
        if any(dig(s, ("system", "latency_ms", step, "mean")) for step in STEPS)
    ]
    if not labels:
        return None
    figure, ax = plt.subplots(figsize=(11, 1.4 + 0.5 * len(labels)), layout="constrained")
    left = [0.0] * len(labels)
    for index, step in enumerate(STEPS):
        values = [dig(runs[l], ("system", "latency_ms", step, "mean")) or 0 for l in labels]
        ax.barh(
            labels, values, 0.6, left=left, label=step,
            color=SERIES[index], edgecolor=SURFACE, linewidth=1.5,
        )
        left = [a + b for a, b in zip(left, values)]
    for row, total in enumerate(left):
        ax.annotate(f" {total:,.0f} ms", (total, row), va="center", fontsize=8, color=INK)
    ax.invert_yaxis()
    ax.set_xlim(0, max(left) * 1.15)
    ax.set_xlabel(
        "ms trung bình (write = answer writer LLM, đo trên mẫu)\n"
        "ground + engine < 10 ms, không hiển thị được ở thang này",
        color=MUTED,
    )
    ax.xaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    _style(ax)
    ax.set_title("Độ trễ theo bước", color=INK, loc="left")
    ax.legend(loc="upper left", bbox_to_anchor=(1.0, 1.0), frameon=False, fontsize=8)
    return _save(figure, path)


def chart_full_vs_llm(path: Path, summaries: list[dict]) -> Path | None:
    """end_to_end accuracy per model, bars grouped by config: full vs llm_only."""
    configs = ("full", "llm_only")
    names: list[str] = []
    values: dict[str, dict[str, float | None]] = {c: {} for c in configs}
    for s in summaries:
        if s["slug"] == NO_LLM_DIR or s["config"] not in configs:
            continue
        name = model_name(s)
        if name not in names:
            names.append(name)
        values[s["config"]][name] = dig(s["metrics"]["overall"], COLUMNS["end_to_end"])
    if not names:
        return None
    series = {c: [values[c].get(n) for n in names] for c in configs}
    figure, ax = plt.subplots(figsize=(11, 4.5), layout="constrained")
    grouped_bars(ax, names, series)
    ax.set_title("end_to_end: full so với llm_only, theo model", color=INK, loc="left")
    ax.legend(loc="upper left", bbox_to_anchor=(1.0, 1.0), frameon=False, fontsize=8)
    return _save(figure, path)


def chart_confusion(path: Path, summary: dict) -> Path | None:
    matrix = dig(summary["metrics"]["overall"], ("dialog", "first_status_confusion"))
    if not matrix:
        return None
    values = [[matrix[t][p] for p in C.STATUSES] for t in C.STATUSES]
    top = max(max(row) for row in values) or 1
    figure, ax = plt.subplots(figsize=(5.2, 4.4), layout="constrained")
    ax.imshow(values, cmap=LinearSegmentedColormap.from_list("blue", SEQUENTIAL), vmin=0, vmax=top)
    for row, line in enumerate(values):
        for column, value in enumerate(line):
            ax.text(column, row, str(value), ha="center", va="center",
                    color=SURFACE if value > top * 0.6 else INK)
    ax.set_xticks(range(len(C.STATUSES)), C.STATUSES)
    ax.set_yticks(range(len(C.STATUSES)), C.STATUSES)
    ax.set_xlabel("dự đoán", color=MUTED)
    ax.set_ylabel("ground truth", color=MUTED)
    ax.tick_params(colors=MUTED, length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.set_title(f"first_status — {model_name(summary)} / {summary['config']}", color=INK, fontsize=10)
    return _save(figure, path)


def build_report(results: Path, report: Path, main_model: str = MAIN_MODEL) -> list[Path]:
    summaries = load_summaries(results)
    if not summaries:
        raise SystemExit(f"Không tìm thấy summary.json nào trong {results}")
    report.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    ablation = ablation_summaries(summaries, main_model)
    if ablation:
        frame = pd.DataFrame([table_row(s, config=c) for c, s in ablation.items()])
        write_table(report, "ablation", f"Ablation — {main_model}", frame,
                    warnings_of(list(ablation.values())))
        written += [report / "ablation.xlsx", report / "ablation.md"]

    models = model_summaries(summaries)
    if models:
        frame = pd.DataFrame([
            table_row(
                s,
                model="(không LLM)" if s["slug"] == NO_LLM_DIR else model_name(s),
                tier="mốc" if s["slug"] == NO_LLM_DIR else tier(s),
                config=s["config"],
                gpu=", ".join(dict.fromkeys(s["env"].get("gpus", []))),
            )
            for s in models
        ])
        write_table(report, "models", "So sánh model", frame, warnings_of(models))
        written += [report / "models.xlsx", report / "models.md"]

    if ablation:
        # Two panels so that no panel needs more than the six fixed hues.
        configs = list(ablation)
        panels = [
            ("Ablation", {c: ablation[c] for c in configs if c in (
                "full", "no_derive", "no_circumstance", "no_grounder")}),
            ("Mốc và baseline", {c: ablation[c] for c in configs if c in (
                "full", "regex_extractor", "oracle_facts", "llm_only")}),
        ]
        written.append(chart_by_metric(
            report / "metrics_by_config.png", f"Chỉ số chính theo config — {main_model}",
            [p for p in panels if p[1]],
        ))

    full_runs = {model_name(s): s for s in models if s["config"] == "full" and s["slug"] != NO_LLM_DIR}
    if full_runs:
        labelled = {f"{n} ({tier(s)})": s for n, s in full_runs.items()}
        written.append(chart_by_metric(
            report / "metrics_by_model.png", "Chỉ số chính theo model (config full)",
            [("Tất cả model", labelled)],
        ))
        written.append(chart_full_vs_llm(report / "full_vs_llm_only.png", models))
    if "full" in ablation:
        written.append(chart_groups(report / "full_by_group.png", ablation["full"]))
        written.append(chart_confusion(report / "confusion_status.png", ablation["full"]))

    latency_runs = {f"{n} / full": s for n, s in full_runs.items()}
    latency_runs.update({
        f"{c}": s for c, s in ablation.items() if c in ("regex_extractor", "oracle_facts")
    })
    written.append(chart_latency(report / "latency_by_step.png", latency_runs))

    for warning in warnings_of(summaries):
        print(f"CẢNH BÁO: {warning}")
    return [path for path in written if path is not None]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--out", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--main-model", default=MAIN_MODEL)
    args = parser.parse_args(argv)
    for path in build_report(args.results, args.out, args.main_model):
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
