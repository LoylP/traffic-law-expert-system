"""Run the evaluation (DESIGN §11). All metric logic lives in this module.

    python -m src.eval.run_eval --cases data/eval/test_cases.jsonl --config all \
        --model qwen3.5:4b-q4_K_M --resume

Output: <out>/<model_slug>/<config>/ (configs without an LLM: <out>/_no_llm/<config>/)
with per_case.jsonl (appended after every case), per_case.csv, errors.csv and
summary.json.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import os
import platform
import random
import re
import subprocess
import sys
import time
import uuid
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import requests

from src.eval import cases as C
from src.eval.llm_only import LLMOnlyBaseline
from src.reasoning.answer_writer import DISCLAIMER, AnswerWriter, check_answer
from src.reasoning.knowledge_base import ROOT, KnowledgeBase, get_knowledge_base
from src.reasoning.llm_client import (
    MODE_PROMPT_ONLY,
    LLMClient,
    LLMConfig,
    LLMConnectionError,
    LLMError,
    LLMOutputError,
)
from src.reasoning.penalty import PenaltyDecider
from src.reasoning.pipeline import ConsultOptions, ExpertPipeline
from src.reasoning.schema import PHASE_ORDER, ConsultResult, Facts, PenaltySummary, ViolationHit

CONFIGS = (
    "full",  # first: the ablations reuse its cached extractions
    "no_derive",
    "no_circumstance",
    "no_grounder",
    "regex_extractor",
    "oracle_facts",
    "llm_only",
)
NO_LLM_CONFIGS = ("regex_extractor", "oracle_facts")
NO_LLM_DIR = "_no_llm"
DEFAULT_OUT = ROOT / "data" / "eval" / "results"
DEFAULT_CACHE = "data/eval/cache"
MIN_LLM_TIMEOUT = 300.0

# Facts slots compared with the ground truth. free_behaviors is free text (it is
# measured through the acts the grounder maps it to).
SCORED_SLOTS = tuple(
    name
    for name in Facts.model_fields
    if name not in ("evidence", "grounded_violations", "unknown_slots", "free_behaviors")
)
LATENCY_STEPS = ("extract", "ground", "engine", "write", "retrieve", "llm", "total")
ERROR_ORDER = ("ground", "extract", "rule", "penalty", "dialog")
# check_answer() reasons that mean "a number or citation outside the payload".
UNFAITHFUL_MARK = "không có trong dữ liệu"


def model_slug(model: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", model).strip("-")


def output_dir(out: Path, model: str, config: str) -> Path:
    return Path(out) / (NO_LLM_DIR if config in NO_LLM_CONFIGS else model_slug(model)) / config


def input_hash(case: dict[str, Any], config: str) -> str:
    """Changes when what the system receives changes (a resumed record is then redone).
    Ground truth edits only change scores, which are recomputed from the records."""
    material: list[Any] = [case["query"], case.get("followups") or []]
    if config == "oracle_facts":
        material.append(case["ground_truth"]["facts"])
    blob = json.dumps(material, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Metrics (pure functions)
# ---------------------------------------------------------------------------


def _norm_value(value: Any) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float)):
        return f"{float(value):g}"
    return str(value)


def fact_items(facts: dict[str, Any]) -> dict[str, set[str]]:
    """Filled slots -> set of values. None, False, empty and the default subject
    mean "not filled"; list slots contribute one item per element."""
    default = Facts().model_dump(mode="json")
    items: dict[str, set[str]] = {}
    for slot in SCORED_SLOTS:
        value = facts.get(slot)
        if value is None or value is False or value == [] or value == default[slot]:
            continue
        values = value if isinstance(value, list) else [value]
        items[slot] = {_norm_value(v) for v in values}
    return items


def count_sets(truth: Iterable[Any], predicted: Iterable[Any]) -> tuple[int, int, int]:
    """(true positives, false positives, false negatives)."""
    truth, predicted = set(truth), set(predicted)
    return len(truth & predicted), len(predicted - truth), len(truth - predicted)


def prf(counts: Iterable[tuple[int, int, int]]) -> dict[str, Any]:
    """Micro precision / recall / F1. None where there is nothing to measure."""
    tp = fp = fn = 0
    for a, b, c in counts:
        tp, fp, fn = tp + a, fp + b, fn + c
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = 2 * tp / (2 * tp + fp + fn) if tp + fp + fn else None
    return {"precision": precision, "recall": recall, "f1": f1, "tp": tp, "fp": fp, "fn": fn}


def rate(values: Iterable[bool | None]) -> float | None:
    """Share of True among the applicable (not None) values."""
    applicable = [v for v in values if v is not None]
    return sum(applicable) / len(applicable) if applicable else None


def clause_of(citation_id: str) -> str:
    """Điều + Khoản of a citation id (drops the Điểm)."""
    return re.sub(r"-P[^-]+$", "", citation_id)


def score_case(
    case: dict[str, Any],
    pred: dict[str, Any],
    gt_fine_ranges: dict[str, Any],
    known_citations: set[str] | None = None,
) -> dict[str, Any]:
    """Compare one prediction with the ground truth. A prediction value of None
    means the configuration does not produce it (not counted)."""
    truth = case["ground_truth"]
    answered = truth["status"] == "answered"
    score: dict[str, Any] = {"id": case["id"], "group": case["group"]}

    # problem 2: extraction -> ontology
    if pred.get("facts") is None:
        score.update(slots=None, filled_slots=0, hallucinated_slots=0)
    else:
        expected, actual = fact_items(truth["facts"]), fact_items(pred["facts"])
        score["slots"] = {
            slot: count_sets(expected.get(slot, ()), actual.get(slot, ()))
            for slot in set(expected) | set(actual)
        }
        score["filled_slots"] = len(actual)
        score["hallucinated_slots"] = len(set(actual) - set(expected))

    # problem 1: reasoning
    predicted = set(pred["violations"])
    expected_set = set(truth["violations"])
    score["violations"] = count_sets(expected_set, predicted)
    score["exact_set"] = predicted == expected_set
    clauses = {clause_of(c) for c in predicted}
    score["citations_found"] = (sum(clause_of(c) in clauses for c in expected_set), len(expected_set))
    score["citations_exist"] = (
        None
        if known_citations is None
        else (sum(c in known_citations for c in predicted), len(predicted))
    )

    ranges = pred.get("fine_ranges")
    score["fine_range_ok"] = None
    if answered and ranges is not None:
        score["fine_range_ok"] = {k: list(v) if v else None for k, v in ranges.items()} == {
            k: list(v) if v else None for k, v in gt_fine_ranges.items()
        }
    score["fine_ok"] = (
        pred["recommended_fine_total"] == truth["recommended_fine_total"] if answered else None
    )
    score["points_ok"] = (
        pred["points_deducted_total"] == truth["points_deducted_total"] if answered else None
    )
    score["sanctions"] = count_sets(truth["sanctions"], pred["sanctions"])
    for kind in ("aggravating", "mitigating"):
        value = pred.get(kind)
        score[f"{kind}_ok"] = (
            set(value) == set(truth[kind]) if answered and value is not None else None
        )

    # dialogue
    first = pred.get("first_status")
    score["first_status"] = (truth["first_status"], first)
    score["first_status_ok"] = None if first is None else first == truth["first_status"]
    # Only systems that name the slot they ask for are scored on it.
    score["first_ask_slot_ok"] = None
    if truth["first_status"] == "need_info" and first is not None and pred.get("reports_ask_slot"):
        score["first_ask_slot_ok"] = pred.get("first_ask_slot") == truth["first_ask_slot"]
    score["status_ok"] = pred["status"] == truth["status"]
    score["question_turns"] = pred.get("question_turns")
    score["followup_mismatches"] = len(pred.get("followup_mismatches") or [])
    score["end_to_end"] = bool(
        score["status_ok"]
        and (not answered or (score["exact_set"] and score["fine_ok"] and score["points_ok"]))
    )
    score["error_types"] = error_types(truth, pred, score)
    return score


def is_wrong(score: dict[str, Any]) -> bool:
    checks = ("fine_ok", "points_ok", "aggravating_ok", "mitigating_ok")
    return (
        not score["end_to_end"]
        or not score["exact_set"]
        or any(score[name] is False for name in checks)
        or any(score["sanctions"][1:])
        or score["first_status_ok"] is False
        or score["first_ask_slot_ok"] is False
    )


def error_types(truth: dict[str, Any], pred: dict[str, Any], score: dict[str, Any]) -> list[str]:
    """Where a wrong case went wrong, primary cause first. Empty for a correct case."""
    if not is_wrong(score):
        return []
    found = set()
    grounded = pred.get("grounded") or {}
    wrong_acts = set(grounded.get("acts", [])) - set(truth["facts"].get("acts", []))
    wrong_ids = set(grounded.get("violations", [])) - set(truth["violations"])
    if wrong_acts or wrong_ids:
        found.add("ground")
    for slot, (_, false_pos, false_neg) in (score["slots"] or {}).items():
        # An act the grounder added wrongly is its error, not the extractor's.
        if slot == "acts":
            false_pos -= len(wrong_acts)
        if false_pos > 0 or false_neg > 0:
            found.add("extract")
    if (
        score["first_status_ok"] is False
        or score["first_ask_slot_ok"] is False
        or score["followup_mismatches"]
    ):
        found.add("dialog")
    if not found & {"ground", "extract"}:
        if not score["exact_set"] or not score["status_ok"]:
            found.add("rule")
        elif (
            any(score[n] is False for n in ("fine_ok", "points_ok", "aggravating_ok", "mitigating_ok"))
            or any(score["sanctions"][1:])
        ):
            found.add("penalty")
    return [name for name in ERROR_ORDER if name in found] or ["rule"]


def confusion_matrix(pairs: Iterable[tuple[str, str | None]]) -> dict[str, dict[str, int]]:
    """Rows = ground truth, columns = prediction; pairs without prediction are skipped."""
    matrix = {t: {p: 0 for p in C.STATUSES} for t in C.STATUSES}
    for truth, predicted in pairs:
        if predicted is not None:
            matrix[truth][predicted] += 1
    return matrix


def aggregate_scores(scores: list[dict[str, Any]]) -> dict[str, Any]:
    extraction = None
    with_facts = [s for s in scores if s["slots"] is not None]
    if with_facts:
        per_slot: dict[str, list[tuple[int, int, int]]] = {}
        for item in with_facts:
            for slot, counts in item["slots"].items():
                per_slot.setdefault(slot, []).append(counts)
        filled = sum(s["filled_slots"] for s in with_facts)
        extraction = {
            "slot": prf(c for values in per_slot.values() for c in values),
            "per_slot": {slot: prf(per_slot[slot]) for slot in sorted(per_slot)},
            "acts": prf(per_slot.get("acts", [])),
            "hallucinated_slot_rate": (
                sum(s["hallucinated_slots"] for s in with_facts) / filled if filled else None
            ),
        }

    def share(name: str) -> float | None:
        pairs = [s[name] for s in scores if s[name] is not None]
        total = sum(n for _, n in pairs)
        return sum(a for a, _ in pairs) / total if total else None

    turns = [s["question_turns"] for s in scores if s["question_turns"] is not None]
    has_dialog = any(s["first_status_ok"] is not None for s in scores)
    return {
        "n_cases": len(scores),
        "extraction": extraction,
        "reasoning": {
            "violation": prf(s["violations"] for s in scores),
            "exact_set_match": rate(s["exact_set"] for s in scores),
            "citation_accuracy": share("citations_found"),
            "citation_exists_rate": share("citations_exist"),
            "fine_range_accuracy": rate(s["fine_range_ok"] for s in scores),
            "recommended_fine_exact": rate(s["fine_ok"] for s in scores),
            "points_accuracy": rate(s["points_ok"] for s in scores),
            "sanctions": prf(s["sanctions"] for s in scores),
            "aggravating_exact": rate(s["aggravating_ok"] for s in scores),
            "mitigating_exact": rate(s["mitigating_ok"] for s in scores),
            "n_answered": sum(s["fine_ok"] is not None for s in scores),
        },
        "dialog": {
            "first_status_accuracy": rate(s["first_status_ok"] for s in scores),
            "first_status_confusion": (
                confusion_matrix(s["first_status"] for s in scores) if has_dialog else None
            ),
            "first_ask_slot_accuracy": rate(s["first_ask_slot_ok"] for s in scores),
            "status_accuracy": rate(s["status_ok"] for s in scores),
            "avg_question_turns": sum(turns) / len(turns) if turns else None,
            "followup_mismatches": sum(s["followup_mismatches"] for s in scores),
        },
        "end_to_end_accuracy": rate(s["end_to_end"] for s in scores),
    }


def latency_stats(samples: list[float]) -> dict[str, Any] | None:
    if not samples:
        return None
    return {
        "n": len(samples),
        "mean": round(float(np.mean(samples)), 2),
        "p50": round(float(np.percentile(samples, 50)), 2),
        "p95": round(float(np.percentile(samples, 95)), 2),
    }


def system_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Latency (real calls only), LLM errors and answer-writer faithfulness."""
    samples: dict[str, list[float]] = {step: [] for step in LATENCY_STEPS}
    calls = cache_hits = json_errors = fallbacks = call_errors = 0
    writers = []
    for record in records:
        # A case replayed from the cache gives no end-to-end timing at all: its
        # turns without an LLM call alone would not represent a request.
        replayed = any(c["cached"] for t in record["turns"] for c in t.get("llm_calls", []))
        for turn in record["turns"]:
            for step, value in turn["latency_ms"].items():
                if not (replayed and step == "total"):
                    samples[step].append(value)
            for call in turn.get("llm_calls", []):
                calls += 1
                cache_hits += call["cached"]
                json_errors += call["invalid_json"]
                call_errors += call["error"] is not None
                fallbacks += call.get("fallback", False)
        if record.get("writer"):
            writers.append(record["writer"])
            if record["writer"]["latency_ms"] is not None:
                samples["write"].append(record["writer"]["latency_ms"])

    llm = None
    if calls:
        llm = {
            "calls": calls,
            "cache_hits": cache_hits,
            "invalid_json_rate": json_errors / calls,
            "fallback_to_regex_rate": fallbacks / calls,
            "call_errors": call_errors,
        }
    faithfulness = None
    if writers:
        answered = [w for w in writers if w["raw_text"] is not None]
        faithfulness = {
            "n_samples": len(writers),
            "llm_unfaithful_rate": rate(
                any(UNFAITHFUL_MARK in p for p in w["problems"]) for w in answered
            ),
            "llm_rejected_rate": rate(bool(w["problems"]) for w in answered),
            "template_fallback_rate": rate(w["writer"] == "template" for w in writers),
            "final_unfaithful_rate": rate(w["final_unfaithful"] for w in writers),
        }
    return {
        "latency_ms": {s: latency_stats(v) for s, v in samples.items() if v},
        "llm": llm,
        "faithfulness": faithfulness,
    }


def gt_fine_ranges(
    case: dict[str, Any], decider: PenaltyDecider
) -> dict[str, tuple[int, int] | None]:
    """Fine ranges of the ground-truth violations, looked up in the knowledge base."""
    hits = [
        ViolationHit(citation_id=c, rule_id="ground_truth")
        for c in case["ground_truth"]["violations"]
        if c in decider.kb.violations
    ]
    subject = case["ground_truth"]["facts"].get("subject", "SUBJ_INDIVIDUAL")
    return {d.citation_id: d.fine_range for d in decider.decide_hits(hits, [], subject).decisions}


def evaluate(
    cases: list[dict[str, Any]], records: dict[str, dict[str, Any]], kb: KnowledgeBase
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Per-case scores and the metrics block of summary.json (total and by group)."""
    decider = PenaltyDecider(kb)
    known = set(kb.violations) | set(kb.legal_units)
    scores = [
        score_case(case, records[case["id"]]["prediction"], gt_fine_ranges(case, decider), known)
        for case in cases
        if case["id"] in records
    ]
    by_group = {
        group: aggregate_scores([s for s in scores if s["group"] == group])
        for group in C.GROUPS
        if any(s["group"] == group for s in scores)
    }
    return scores, {"overall": aggregate_scores(scores), "by_group": by_group}


# ---------------------------------------------------------------------------
# LLM client wrapper
# ---------------------------------------------------------------------------


class EvalLLMClient(LLMClient):
    """Records every call, and also caches invalid-output failures so that the
    ablations replay exactly what `full` got without calling the model again."""

    def __init__(self, config: LLMConfig):
        super().__init__(config)
        self.events: list[dict[str, Any]] = []

    def _sidecar(self, key: str, suffix: str) -> Path | None:
        return Path(self.config.cache_dir) / f"{key}.{suffix}" if self.config.cache_dir else None

    def _event(self, **values: Any) -> None:
        event = {"kind": "json", "cached": False, "invalid_json": False, "error": None,
                 "connection_error": False, **values}
        self.events.append(event)

    def chat_json(self, messages, json_schema, temperature=0, validator=None):
        key = self._cache_key(messages, json_schema, temperature)
        meta, failure = self._sidecar(key, "meta"), self._sidecar(key, "fail")
        if failure is not None and failure.exists():
            self._record(MODE_PROMPT_ONLY, cached=True)
            message = failure.read_text(encoding="utf-8")
            self._event(cached=True, invalid_json=True, error=message)
            raise LLMOutputError(message)
        try:
            data = super().chat_json(messages, json_schema, temperature, validator)
        except LLMError as error:
            invalid = isinstance(error, LLMOutputError)
            if invalid and failure is not None:
                failure.parent.mkdir(parents=True, exist_ok=True)
                failure.write_text(str(error)[:500], encoding="utf-8")
            self._event(
                invalid_json=invalid,
                error=str(error)[:500],
                connection_error=isinstance(error, LLMConnectionError),
            )
            raise
        metadata = self.last_metadata
        attempts = metadata.attempts
        if meta is not None:
            if metadata.cached and meta.exists():
                attempts = json.loads(meta.read_text(encoding="utf-8"))["attempts"]
            elif not metadata.cached:
                meta.write_text(json.dumps({"attempts": attempts}), encoding="utf-8")
        # More than one attempt = the first output was not valid JSON for the schema.
        self._event(cached=metadata.cached, invalid_json=attempts > 1)
        return data

    def chat_text(self, messages, temperature=0):
        try:
            text = super().chat_text(messages, temperature)
        except LLMError as error:
            self._event(
                kind="text",
                error=str(error)[:500],
                connection_error=isinstance(error, LLMConnectionError),
            )
            raise
        metadata = self.last_metadata
        self._event(
            kind="text", cached=metadata.cached, text=text, latency_ms=metadata.latency_ms
        )
        return text


def _api(config: LLMConfig, path: str) -> str:
    return config.base_url.rstrip("/").removesuffix("/v1").rstrip("/") + path


def server_alive(config: LLMConfig) -> bool:
    if config.provider != "ollama":
        return False
    try:
        return requests.get(_api(config, "/api/version"), timeout=10).ok
    except requests.RequestException:
        return False


def check_connection(client: EvalLLMClient, events: list[dict[str, Any]]) -> None:
    """A dead server must stop the run: otherwise the pipeline silently falls back
    to regex and the results would be reported under the model's name."""
    if any(e["connection_error"] for e in events) and not server_alive(client.config):
        raise SystemExit(
            f"Mất kết nối tới LLM tại {client.config.base_url}. Case đang chạy chưa được ghi; "
            "khởi động lại server rồi chạy lại với --resume."
        )


# ---------------------------------------------------------------------------
# Running the configurations
# ---------------------------------------------------------------------------


def pipeline_options(config: str) -> ConsultOptions:
    options = ConsultOptions(use_llm_writer=False)  # the writer is sampled separately
    if config == "no_derive":
        options.enabled_rule_types = [t for t in PHASE_ORDER if t != "derive"]
    elif config == "no_circumstance":
        options.use_circumstances = False
    elif config == "no_grounder":
        options.use_grounder = False
    elif config == "regex_extractor":
        options.use_llm_extractor = False
    return options


def run_oracle(case: dict[str, Any], concluder: C.Concluder) -> dict[str, Any]:
    """Ground-truth facts straight into the engine: the ceiling of the reasoning.
    There is no conversation, so the dialogue metrics do not apply."""
    facts = Facts.model_validate(case["ground_truth"]["facts"])
    started = time.perf_counter()
    outcome = concluder.conclude(facts, asked=len(case.get("followups") or []))
    elapsed = round((time.perf_counter() - started) * 1000, 2)
    prediction = {
        key: outcome[key]
        for key in (
            "status", "violations", "fine_ranges", "recommended_fine_total",
            "points_deducted_total", "sanctions", "aggravating", "mitigating",
        )
    }
    prediction.update(facts=None, first_status=None, first_ask_slot=None, question_turns=None)
    turn = {"message": None, "status": outcome["status"],
            "latency_ms": {"engine": elapsed, "total": elapsed}, "llm_calls": []}
    return {"prediction": prediction, "turns": [turn], "writer": None}


def _replies(case: dict[str, Any]) -> list[dict[str, str]]:
    return (case.get("followups") or [])[: C.MAX_FOLLOWUPS]


def run_pipeline(
    case: dict[str, Any], config: str, pipeline: ExpertPipeline, client: EvalLLMClient | None
) -> tuple[dict[str, Any], ConsultResult]:
    options = pipeline_options(config)
    uses_llm = config not in NO_LLM_CONFIGS
    session_id = f"eval-{case['id']}-{uuid.uuid4().hex}"
    pending = _replies(case)
    message, turns, mismatches = case["query"], [], []
    first: dict[str, Any] = {}
    question_turns = 0
    while True:
        seen = len(client.events) if client else 0
        outcome = pipeline.consult_detailed(message, session_id, options)
        events = client.events[seen:] if client else []
        if client:
            check_connection(client, events)
        result = outcome.result
        status = C.normalize_status(result.status)
        ask_slot = C.short_slot(result.questions[0].slot) if result.questions else None
        cached = any(e["cached"] for e in events)
        latency = {"ground": result.latency_ms["ground"], "engine": result.latency_ms["reason"]}
        # A reply read by parse_answer runs no extractor; cache hits are not timed.
        if outcome.extractor != "answer" and not cached:
            latency["extract"] = result.latency_ms["extract"]
        if not cached:
            latency["total"] = result.latency_ms["total"]
        calls = [dict(e) for e in events]
        for call in calls:
            call["fallback"] = uses_llm and outcome.extractor == "regex"
        turns.append({
            "message": message, "status": result.status, "ask_slot": ask_slot,
            "extractor": outcome.extractor, "latency_ms": latency, "llm_calls": calls,
            "warnings": outcome.warnings,
        })
        if not first:
            first = {"first_status": status, "first_ask_slot": ask_slot}
        question_turns += status == "need_info"
        if status != "need_info" or not pending:
            break
        reply = pending.pop(0)
        if reply["expect_ask_slot"] != ask_slot:
            mismatches.append({"expected": reply["expect_ask_slot"], "asked": ask_slot})
        message = reply["answer"]

    # What was understood from the user: session facts plus what the grounder mapped.
    facts = C.compact_facts(pipeline.sessions.get(session_id).facts)
    grounded: dict[str, list[str]] = {"acts": [], "violations": []}
    for step in result.explanation.chain:
        if step.type == "ground":
            grounded["acts"] += step.produced.get("acts", [])
            grounded["violations"] += step.produced.get("grounded_violations", [])
    if grounded["acts"]:
        facts["acts"] = list(dict.fromkeys([*facts.get("acts", []), *grounded["acts"]]))
    prediction = {
        **first,
        "reports_ask_slot": True,
        "status": C.normalize_status(result.status),
        "raw_status": result.status,
        "question_turns": question_turns,
        "followup_mismatches": mismatches,
        "facts": facts,
        "grounded": grounded,
        "violations": sorted(v.citation_id for v in result.violations),
        "fine_ranges": {
            v.citation_id: list(v.fine_range) if v.fine_range else None for v in result.violations
        },
        "recommended_fine_total": result.total_recommended_fine,
        "points_deducted_total": result.total_points_deducted,
        "sanctions": sorted({s.type for s in result.sanctions}),
        "aggravating": sorted(result.aggravating),
        "mitigating": sorted(result.mitigating),
    }
    return {"prediction": prediction, "turns": turns, "writer": None}, result


def sample_writer(
    result: ConsultResult, writer: AnswerWriter, client: EvalLLMClient
) -> dict[str, Any]:
    """Run the LLM answer writer on a decided result and check its raw output."""
    # The writer payload only reads these fields of the penalty summary.
    penalty = PenaltySummary(
        legal_principle_ref="",
        total_points_deducted=result.total_points_deducted,
        aggravating=result.aggravating,
        mitigating=result.mitigating,
    )
    payload = AnswerWriter.payload(result, penalty)
    seen = len(client.events)
    text, source = writer.write(result, penalty, result.notes, use_llm=True)
    events = client.events[seen:]
    check_connection(client, events)
    call = next((e for e in events if e["kind"] == "text"), {})
    raw = call.get("text")
    final_unfaithful = False
    if source == "llm":
        body = text.removesuffix("\n".join(["", *result.notes, DISCLAIMER]))
        final_unfaithful = any(UNFAITHFUL_MARK in p for p in check_answer(body, payload))
    return {
        "writer": source,
        "raw_text": raw,
        "problems": [] if raw is None else check_answer(raw, payload),
        "final_unfaithful": final_unfaithful,
        "latency_ms": None if raw is None or call["cached"] else round(call["latency_ms"], 2),
        "error": call.get("error"),
    }


def run_llm_only(
    case: dict[str, Any], baseline: LLMOnlyBaseline, client: EvalLLMClient
) -> dict[str, Any]:
    baseline.reset()
    pending = _replies(case)
    message, turns = case["query"], []
    first_status, question_turns = None, 0
    while True:
        seen = len(client.events)
        started = time.perf_counter()
        candidates = baseline.retrieve(message)
        retrieved = time.perf_counter()
        try:
            data = baseline.ask(message, candidates)
        except LLMError:
            data = None
        finished = time.perf_counter()
        events = client.events[seen:]
        check_connection(client, events)
        failed = data is None
        data = data or {"status": "unknown", "violations": [], "recommended_fine_total": 0,
                        "points_deducted_total": 0, "sanctions": []}
        latency = {"retrieve": round((retrieved - started) * 1000, 2)}
        if not any(e["cached"] for e in events):
            latency["llm"] = round((finished - retrieved) * 1000, 2)
            latency["total"] = round((finished - started) * 1000, 2)
        turns.append({"message": message, "status": data["status"], "latency_ms": latency,
                      "llm_calls": [dict(e) for e in events], "llm_failed": failed})
        first_status = first_status or data["status"]
        question_turns += data["status"] == "need_info"
        if data["status"] != "need_info" or not pending:
            break
        message = pending.pop(0)["answer"]
    prediction = {
        "first_status": first_status,
        "first_ask_slot": None,
        "reports_ask_slot": False,
        "status": data["status"],
        "question_turns": question_turns,
        "facts": None,
        "violations": sorted(set(data["violations"])),
        "fine_ranges": None,
        "recommended_fine_total": data["recommended_fine_total"],
        "points_deducted_total": data["points_deducted_total"],
        "sanctions": sorted(set(data["sanctions"])),
        "aggravating": None,
        "mitigating": None,
    }
    return {"prediction": prediction, "turns": turns, "writer": None}


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------


def _command(*args: str) -> str | None:
    try:
        done = subprocess.run(args, capture_output=True, text=True, cwd=ROOT, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def gpu_name() -> str:
    names = _command("nvidia-smi", "--query-gpu=name", "--format=csv,noheader")
    if names:
        return ", ".join(names.splitlines())
    if platform.system() == "Darwin":
        chip = _command("sysctl", "-n", "machdep.cpu.brand_string")
        if chip:
            return f"{chip} (Apple GPU)"
    return "không có GPU được phát hiện"


def git_info() -> dict[str, Any]:
    status = _command("git", "status", "--porcelain", "--untracked-files=no")
    return {
        "sha": _command("git", "rev-parse", "HEAD"),
        "tag": _command("git", "describe", "--tags", "--exact-match"),
        "dirty": None if status is None else bool(status),
    }


def model_info(config: LLMConfig) -> dict[str, Any]:
    """Same data as `ollama show` / `ollama ps`, read from the server API."""
    info: dict[str, Any] = {"name": config.model, "provider": config.provider}
    if config.provider != "ollama":
        return info
    try:
        show = requests.post(_api(config, "/api/show"), json={"model": config.model}, timeout=30)
        details = show.json().get("details", {})
        info["parameter_size"] = details.get("parameter_size")
        info["quantization"] = details.get("quantization_level")
        for entry in requests.get(_api(config, "/api/tags"), timeout=30).json().get("models", []):
            if config.model in (entry.get("name"), entry.get("model")):
                info["digest"] = entry.get("digest")
        info["ollama_version"] = requests.get(_api(config, "/api/version"), timeout=30).json()[
            "version"
        ]
        for entry in requests.get(_api(config, "/api/ps"), timeout=30).json().get("models", []):
            if config.model in (entry.get("name"), entry.get("model")) and entry.get("size"):
                info["vram_fraction"] = round(entry.get("size_vram", 0) / entry["size"], 3)
    except (requests.RequestException, ValueError, KeyError) as error:
        info["error"] = str(error)[:200]
    return info


# ---------------------------------------------------------------------------
# Records and reports
# ---------------------------------------------------------------------------


def read_records(path: Path) -> dict[str, dict[str, Any]]:
    """Last record per id; a line cut off by a lost connection is ignored."""
    records: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return records
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        records[record["id"]] = record
    return records


def valid_records(
    cases: list[dict[str, Any]], directory: Path, config: str
) -> dict[str, dict[str, Any]]:
    stored = read_records(directory / "per_case.jsonl")
    return {
        case["id"]: stored[case["id"]]
        for case in cases
        if case["id"] in stored and stored[case["id"]]["input_hash"] == input_hash(case, config)
    }


def _write_csv(path: Path, columns: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def write_reports(
    directory: Path,
    cases: list[dict[str, Any]],
    records: dict[str, dict[str, Any]],
    scores: list[dict[str, Any]],
) -> None:
    by_id = {case["id"]: case for case in cases}
    rows, errors = [], []
    for score in scores:
        case, record = by_id[score["id"]], records[score["id"]]
        truth, pred = case["ground_truth"], record["prediction"]
        row = {
            "id": case["id"],
            "group": case["group"],
            "query": case["query"],
            "gt_first_status": truth["first_status"],
            "first_status": pred.get("first_status"),
            "gt_first_ask_slot": truth["first_ask_slot"],
            "first_ask_slot": pred.get("first_ask_slot"),
            "gt_status": truth["status"],
            "status": pred["status"],
            "gt_violations": C.encode_list(truth["violations"]),
            "violations": C.encode_list(pred["violations"]),
            "gt_fine": truth["recommended_fine_total"],
            "fine": pred["recommended_fine_total"],
            "gt_points": truth["points_deducted_total"],
            "points": pred["points_deducted_total"],
            "gt_sanctions": C.encode_list(truth["sanctions"]),
            "sanctions": C.encode_list(pred["sanctions"]),
            "exact_set": score["exact_set"],
            "end_to_end": score["end_to_end"],
            "error_types": C.encode_list(score["error_types"]),
        }
        rows.append(row)
        if score["error_types"]:
            facts = pred.get("facts")
            errors.append({
                **row,
                "primary_error": score["error_types"][0],
                "gt_facts": C.encode_facts(truth["facts"]),
                "facts": "" if facts is None else C.encode_facts(facts),
            })
    columns = list(rows[0]) if rows else ["id"]
    _write_csv(directory / "per_case.csv", columns, rows)
    _write_csv(
        directory / "errors.csv",
        [*columns, "primary_error", "gt_facts", "facts"],
        errors,
    )


class Runner:
    """Shared, lazily built resources: the retriever (E5) is loaded at most once."""

    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.kb = get_knowledge_base()
        base = LLMConfig.from_env()  # also loads .env
        model = args.model or base.model
        cache = Path(base.cache_dir or DEFAULT_CACHE)
        cache = cache if cache.is_absolute() else ROOT / cache
        self.llm_config = replace(
            base,
            model=model,
            seed=args.seed,
            cache_dir=str(cache / model_slug(model)),
            timeout=max(base.timeout, MIN_LLM_TIMEOUT),
        )
        self._retriever = None
        self._warmed_up = False

    @property
    def retriever(self):
        if self._retriever is None:
            from src.kg.hybrid_search import LegalRetriever  # heavy import

            self._retriever = LegalRetriever(
                ROOT / "data" / "kg" / "kg_nodes.jsonl", ROOT / "data" / "kg" / "embedding_cache"
            )
            self._retriever.search("khởi động", top_k=1)  # keep it out of the latency
        return self._retriever

    def warm_up(self) -> None:
        """Load the model once (not timed, not cached) and fail early if it cannot run."""
        if self._warmed_up:
            return
        try:
            LLMClient(replace(self.llm_config, cache_dir=None)).chat_text(
                [{"role": "user", "content": "Trả lời đúng một chữ: ok"}]
            )
        except LLMError as error:
            raise SystemExit(f"Không gọi được model {self.llm_config.model}: {error}") from error
        self._warmed_up = True

    def run_config(self, config: str, cases: list[dict[str, Any]]) -> dict[str, Any]:
        model = self.llm_config.model
        directory = output_dir(self.args.out, model, config)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "per_case.jsonl"
        if not self.args.resume and path.exists():
            path.unlink()
        records = valid_records(cases, directory, config)
        pending = [case for case in cases if case["id"] not in records]
        uses_llm = config not in NO_LLM_CONFIGS
        label = f"{model if uses_llm else NO_LLM_DIR} | {config}"
        print(f"[{label}] {len(records)}/{len(cases)} đã có, còn {len(pending)} case", flush=True)

        started = time.perf_counter()
        if pending:
            client = pipeline = baseline = concluder = None
            if uses_llm:
                self.warm_up()
                client = EvalLLMClient(self.llm_config)
            if config == "oracle_facts":
                concluder = C.Concluder(self.kb)
            elif config == "llm_only":
                baseline = LLMOnlyBaseline(self.retriever, client)
            else:
                pipeline = ExpertPipeline(
                    retriever=None if config == "no_grounder" else self.retriever,
                    kb=self.kb,
                    llm_client=client,
                )
            if config != "no_grounder" and config != "oracle_facts":
                _ = self.retriever  # load before timing the cases
            gpu = gpu_name()
            loop_started = time.perf_counter()
            sampled = sum(bool(r.get("writer")) for r in records.values())
            with path.open("a", encoding="utf-8") as file:
                if path.stat().st_size and not path.read_bytes().endswith(b"\n"):
                    file.write("\n")  # isolate a line cut off by a lost connection
                for number, case in enumerate(pending, 1):
                    case_started = time.perf_counter()
                    if config == "oracle_facts":
                        record = run_oracle(case, concluder)
                    elif config == "llm_only":
                        record = run_llm_only(case, baseline, client)
                    else:
                        record, result = run_pipeline(case, config, pipeline, client)
                        if (
                            config == "full"
                            and sampled < self.args.writer_sample
                            and result.status == "answered"
                            and not result.branches
                        ):
                            record["writer"] = sample_writer(result, pipeline.writer, client)
                            sampled += 1
                    record = {
                        "id": case["id"],
                        "input_hash": input_hash(case, config),
                        "gpu": gpu,
                        "wall_s": round(time.perf_counter() - case_started, 3),
                        **record,
                    }
                    file.write(json.dumps(record, ensure_ascii=False) + "\n")
                    file.flush()
                    records[case["id"]] = record
                    elapsed = time.perf_counter() - loop_started
                    remaining = elapsed / number * (len(pending) - number)
                    print(
                        f"[{label}] {len(records)}/{len(cases)} {case['id']} "
                        f"({record['wall_s']:.1f}s) còn khoảng {remaining / 60:.1f} phút",
                        flush=True,
                    )
        return self.summarize(config, cases, records, directory, bool(pending),
                              time.perf_counter() - started)

    def summarize(self, config, cases, records, directory, ran, duration) -> dict[str, Any]:
        scores, metrics = evaluate(cases, records, self.kb)
        write_reports(directory, cases, records, scores)
        uses_llm = config not in NO_LLM_CONFIGS
        summary_path = directory / "summary.json"
        previous = {}
        if summary_path.exists():
            previous = json.loads(summary_path.read_text(encoding="utf-8")).get("env", {})
        # Re-scoring finished runs needs no server: keep what was recorded then.
        model = None
        if uses_llm:
            model = model_info(self.llm_config) if ran or not previous else previous.get("model")
        env = {
            "git": git_info() if ran or not previous else previous.get("git"),
            "model": model,
            "gpus": sorted({r["gpu"] for r in records.values()}),
            "seed": self.args.seed,
            "n_cases": len(records),
            "cases_file": str(self.args.cases),
            "case_ids_sha1": hashlib.sha1(" ".join(sorted(records)).encode()).hexdigest(),
            "n_unverified_cases": sum(not c["verified"] for c in cases),
            "limit": self.args.limit,
            "last_run_duration_s": round(duration, 1) if ran else previous.get("last_run_duration_s"),
            "total_case_time_s": round(sum(r["wall_s"] for r in records.values()), 1),
            "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        system = system_metrics(list(records.values()))
        summary = {
            "config": config,
            "env": env,
            "metrics": metrics,
            "system": system,
            "error_counts": dict(Counter(s["error_types"][0] for s in scores if s["error_types"])),
            "notes": [
                "Độ trễ chỉ lấy từ lần gọi thật: bước/lượt trúng cache LLM không được tính "
                "(xem system.latency_ms.*.n và system.llm.cache_hits).",
                "latency_ms.write là LLM answer writer, chỉ đo trên mẫu writer (config full); "
                "không nằm trong latency_ms.total.",
                "Trạng thái out_of_scope được quy về unknown khi so với ground truth.",
            ],
        }
        if config == "oracle_facts":
            summary["notes"].append(
                "oracle_facts bỏ qua trích xuất và hội thoại: không có chỉ số extraction/first_status."
            )
        summary_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return summary


def _show(value: float | None) -> str:
    return "—" if value is None else f"{value:.3f}"


def headline(summary: dict[str, Any]) -> str:
    overall = summary["metrics"]["overall"]
    extraction = overall["extraction"] or {"slot": {"f1": None}}
    return (
        f"  => n={overall['n_cases']} slot_f1={_show(extraction['slot']['f1'])} "
        f"violation_f1={_show(overall['reasoning']['violation']['f1'])} "
        f"exact_set={_show(overall['reasoning']['exact_set_match'])} "
        f"fine_exact={_show(overall['reasoning']['recommended_fine_exact'])} "
        f"first_status={_show(overall['dialog']['first_status_accuracy'])} "
        f"status={_show(overall['dialog']['status_accuracy'])} "
        f"end_to_end={_show(overall['end_to_end_accuracy'])} "
        f"lỗi={summary['error_counts']}"
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate the expert system (DESIGN §11)")
    parser.add_argument("--cases", type=Path, default=C.TEST_PATH)
    parser.add_argument(
        "--config", nargs="+", choices=[*CONFIGS, "all"], default=["full"],
        help="one or more configurations, or `all`",
    )
    parser.add_argument("--model", help="default: LLM_MODEL from .env")
    parser.add_argument("--limit", type=int, help="only the first N cases")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--resume", action="store_true", help="skip cases already recorded")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--writer-sample", type=int, default=20)
    parser.add_argument(
        "--check-complete", action="store_true",
        help="run nothing; exit 0 when every case of the configs is already recorded",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.ERROR)
    random.seed(args.seed)
    np.random.seed(args.seed)
    if not args.cases.exists():
        print(
            f"Không có {args.cases}. Tạo bằng scripts/apply_verification.py "
            "sau khi kiểm tra verify sheet.", file=sys.stderr,
        )
        return 2
    cases = C.load_cases(args.cases)
    errors = C.validate_cases(cases, get_knowledge_base())
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 2
    cases = cases[: args.limit] if args.limit is not None else cases
    configs = CONFIGS if "all" in args.config else tuple(dict.fromkeys(args.config))

    runner = Runner(args)
    if args.check_complete:
        missing = 0
        for config in configs:
            directory = output_dir(args.out, runner.llm_config.model, config)
            missing += len(cases) - len(valid_records(cases, directory, config))
        print(f"còn thiếu {missing} case")
        return 1 if missing else 0

    unverified = sum(not c["verified"] for c in cases)
    if unverified:
        print(
            f"CẢNH BÁO: {unverified}/{len(cases)} case chưa verified — kết quả chỉ để chạy thử."
        )
    for config in configs:
        print(headline(runner.run_config(config, cases)), flush=True)
    return 0


if __name__ == "__main__":
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    sys.exit(main())
