"""Forward-chaining inference engine (DESIGN §5.3).

Pure Python: no LLM, no network. Phases run in PHASE_ORDER; inside a phase the
engine loops match → resolve → fire until no rule can fire (each rule fires at
most once). Conflict resolution: priority desc → specificity desc → file order.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Iterable

from src.reasoning.knowledge_base import KnowledgeBase
from src.reasoning.schema import (
    PHASE_ORDER,
    Facts,
    InferenceResult,
    Question,
    Rule,
    TraceStep,
    ViolationHit,
)

_MISSING = object()


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set, frozenset)):
        return list(value)
    return [value]


def _is_empty(value: Any) -> bool:
    return value is None or (isinstance(value, (list, tuple, set, dict, str)) and len(value) == 0)


def _to_date(value: Any) -> date:
    if value is None:
        return date.today()  # DESIGN §6: violation_date null = hôm nay
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _check_operator(op: str, arg: Any, value: Any) -> bool:
    if op == "is_null":
        return _is_empty(value) == bool(arg)
    if op == "not_null":
        return (not _is_empty(value)) == bool(arg)
    if op == "not_true":
        return (value is not True) == bool(arg)
    if op == "not_empty":
        return (not _is_empty(value)) == bool(arg)
    if op == "eq":
        return value == arg
    if op == "in":
        return value in _as_list(arg)
    if op in ("gt", "gte", "lt", "lte"):
        if value is None or isinstance(value, bool):
            return False
        try:
            number = float(value)
        except (TypeError, ValueError):
            return False
        return {
            "gt": number > arg,
            "gte": number >= arg,
            "lt": number < arg,
            "lte": number <= arg,
        }[op]
    if op == "before":
        return _to_date(value) < _to_date(arg)
    if op == "from":
        return _to_date(value) >= _to_date(arg)
    raise ValueError(f"unknown operator {op}")


class WorkingMemory:
    def __init__(self, facts: Facts):
        self.facts: dict[str, Any] = facts.model_dump()
        self.acts: list[str] = list(dict.fromkeys(facts.acts))
        self.contexts: list[str] = [c for c in (facts.road_type, facts.time_context) if c]
        self.circumstances: list[str] = list(dict.fromkeys(facts.circumstances))
        self.violations: dict[str, ViolationHit] = {}
        self.questions: list[Question] = []
        self.notes: list[str] = []
        self.status: str | None = None
        self.message: str | None = None
        self.trace: list[TraceStep] = []

    # -- lookup ---------------------------------------------------------
    def value_of(self, key: str) -> Any:
        if key == "acts":
            return list(self.acts)
        if key == "circumstances":
            return list(self.circumstances)
        return self.facts.get(key, _MISSING)

    def to_facts(self) -> Facts:
        data = dict(self.facts)
        data["acts"] = list(self.acts)
        data["circumstances"] = list(self.circumstances)
        return Facts.model_validate(data)


def _add_unique(target: list[str], items: Iterable[str]) -> list[str]:
    added = []
    for item in items:
        if item not in target:
            target.append(item)
            added.append(item)
    return added


class InferenceEngine:
    def __init__(self, kb: KnowledgeBase | None = None, disabled_types: Iterable[str] = ()):
        self.kb = kb or KnowledgeBase.load()
        self.disabled_types = set(disabled_types)
        self._order = {rule.id: index for index, rule in enumerate(self.kb.rules)}

    # -- matching -------------------------------------------------------
    def _vehicle_matches(self, value: str | None, cond: Any) -> bool:
        """A rule's class also covers its subclasses; VEH_ANY covers unknown too."""
        wanted = set(_as_list(cond))
        if "VEH_ANY" in wanted:
            return True
        while value is not None:
            if value in wanted:
                return True
            value = self.kb.vehicle_parents.get(value)
        return False

    def _condition_holds(self, wm: WorkingMemory, key: str, cond: Any) -> bool:
        if key == "has_act":
            return any(act in wm.acts for act in _as_list(cond))
        if key == "has_context":
            return any(ctx in wm.contexts for ctx in _as_list(cond))
        if key in ("has_violation", "also_has_violation"):
            return any(cid in wm.violations for cid in _as_list(cond))
        if key == "grounded_violation":
            return any(cid in wm.facts["grounded_violations"] for cid in _as_list(cond))
        if key == "vehicle_class" and not isinstance(cond, dict):
            return self._vehicle_matches(wm.facts["vehicle_class"], cond)

        value = wm.value_of(key)
        if value is _MISSING:
            value = None
        if isinstance(cond, dict):
            return all(_check_operator(op, arg, value) for op, arg in cond.items())
        if isinstance(cond, list):  # OR over listed values
            return any(v in cond for v in _as_list(value))
        if isinstance(value, list):
            return cond in value
        return value == cond

    def _matches(self, wm: WorkingMemory, rule: Rule) -> bool:
        return all(self._condition_holds(wm, key, cond) for key, cond in rule.when.items())

    def _matched_facts(self, wm: WorkingMemory, rule: Rule) -> dict[str, Any]:
        matched: dict[str, Any] = {}
        for key in rule.when:
            if key == "has_act":
                matched[key] = [a for a in _as_list(rule.when[key]) if a in wm.acts]
            elif key == "has_context":
                matched[key] = [c for c in _as_list(rule.when[key]) if c in wm.contexts]
            elif key in ("has_violation", "also_has_violation"):
                matched[key] = [v for v in _as_list(rule.when[key]) if v in wm.violations]
            elif key == "grounded_violation":
                matched[key] = [
                    v for v in _as_list(rule.when[key]) if v in wm.facts["grounded_violations"]
                ]
            else:
                value = wm.value_of(key)
                matched[key] = None if value is _MISSING else value
        return matched

    def _rank(self, rule: Rule) -> tuple[int, int, int]:
        return (-rule.priority, -rule.specificity, self._order[rule.id])

    # -- firing ---------------------------------------------------------
    def _fire(self, wm: WorkingMemory, rule: Rule) -> dict[str, Any]:
        then = rule.then
        produced: dict[str, Any] = {}

        if then.get("compute_speed_over"):
            over = float(wm.facts["actual_speed_kmh"]) - float(wm.facts["speed_limit_kmh"])
            wm.facts["speed_over_kmh"] = over
            produced["speed_over_kmh"] = over
        if "add_context" in then:
            produced["contexts"] = _add_unique(wm.contexts, _as_list(then["add_context"]))
        if "add_acts" in then:
            produced["acts"] = _add_unique(wm.acts, _as_list(then["add_acts"]))
        if "add_circumstances" in then:
            produced["circumstances"] = _add_unique(wm.circumstances, _as_list(then["add_circumstances"]))

        if "add_violation" in then:
            cid = then["add_violation"]
            if cid not in wm.violations:
                wm.violations[cid] = ViolationHit(
                    citation_id=cid,
                    rule_id=rule.id,
                    legal_excerpt=rule.legal_excerpt,
                    legal_text=self.kb.legal_texts.get(cid),
                )
            produced["violation"] = cid
        if "escalate_to" in then:
            target = then["escalate_to"]
            sources = [cid for cid in _as_list(rule.when.get("has_violation")) if cid in wm.violations]
            for cid in sources:
                del wm.violations[cid]
            if target in wm.violations:
                wm.violations[target].escalated_from.extend(sources)
            else:
                wm.violations[target] = ViolationHit(
                    citation_id=target,
                    rule_id=rule.id,
                    legal_excerpt=rule.legal_excerpt,
                    legal_text=self.kb.legal_texts.get(target),
                    escalated_from=sources,
                )
            produced["escalated"] = {"from": sources, "to": target}
        if "remove_violation" in then:
            removed = [cid for cid in _as_list(then["remove_violation"]) if wm.violations.pop(cid, None)]
            produced["removed_violations"] = removed

        if "set_status" in then:
            wm.status = then["set_status"]
            wm.message = then.get("message")
            produced["status"] = wm.status
        if "add_notes" in then:
            produced["notes"] = _add_unique(wm.notes, _as_list(then["add_notes"]))
        if "set_status_if_no_violation" in then and not wm.violations:
            wm.status = then["set_status_if_no_violation"]
            produced["status"] = wm.status

        if "ask_field" in then:
            question = Question(
                field=then["ask_field"],
                text=then.get("question_text", ""),
                options=then.get("options", []),
                input_type=then.get("input_type"),
                unit=then.get("unit"),
                rule_id=rule.id,
            )
            wm.questions.append(question)
            produced["question"] = question.field
        return produced

    def _run_phase(self, wm: WorkingMemory, phase: str, fired: set[str]) -> None:
        candidates = [r for r in self.kb.rules_of(phase) if r.id not in fired]
        while True:
            eligible = [r for r in candidates if r.id not in fired and self._matches(wm, r)]
            if not eligible:
                return
            rule = min(eligible, key=self._rank)
            matched = self._matched_facts(wm, rule)
            produced = self._fire(wm, rule)
            fired.add(rule.id)
            wm.trace.append(
                TraceStep(
                    rule_id=rule.id,
                    type=rule.type,
                    matched_facts=matched,
                    produced=produced,
                    explain=rule.explain,
                    source=rule.source,
                )
            )

    # -- public API -----------------------------------------------------
    def infer(self, facts: Facts | dict[str, Any]) -> InferenceResult:
        if not isinstance(facts, Facts):
            facts = Facts.model_validate(facts)
        wm = WorkingMemory(facts)
        fired: set[str] = set()

        for phase in PHASE_ORDER:
            if phase in self.disabled_types:
                continue
            self._run_phase(wm, phase, fired)
            if phase == "temporal" and wm.status == "out_of_scope_temporal":
                break

        return InferenceResult(
            status=self._final_status(wm),
            facts=wm.to_facts(),
            acts=wm.acts,
            contexts=wm.contexts,
            circumstances=wm.circumstances,
            violations=list(wm.violations.values()),
            questions=wm.questions,
            notes=wm.notes,
            message=wm.message,
            trace=wm.trace,
        )

    @staticmethod
    def _final_status(wm: WorkingMemory) -> str:
        if wm.status == "out_of_scope_temporal":
            return wm.status
        if wm.questions:
            return "need_info"
        if wm.violations:
            return "answered"
        if wm.status:  # e.g. out_of_scope set by a note rule (only when no violation)
            return wm.status
        return "unknown"

    def apply_answer(self, facts: Facts, field: str, value: Any) -> Facts:
        """Merge the user's answer to a question into facts.

        If the matching ask-rule option declares effects (`set_facts`, `set_acts`,
        `remove_acts`) they are applied instead of writing the raw value; e.g.
        R-ASK-ALC-01 option `refuse` → alcohol_test_refused=True, add
        ACT_REFUSE_ALCOHOL_TEST, drop ACT_ALCOHOL.
        """
        data = facts.model_dump()
        option = self._find_option(field, value)
        effects = {k: option[k] for k in ("set_facts", "set_acts", "remove_acts") if option and k in option}
        if effects:
            data.update(effects.get("set_facts", {}))
            acts = [a for a in data["acts"] if a not in set(effects.get("remove_acts", []))]
            _add_unique(acts, effects.get("set_acts", []))
            data["acts"] = acts
        else:
            data[field] = value
        return Facts.model_validate(data)

    def _find_option(self, field: str, value: Any) -> dict[str, Any] | None:
        for rule in self.kb.rules_of("ask"):
            if rule.then.get("ask_field") != field:
                continue
            for option in rule.then.get("options", []):
                if option.get("value") == value or str(option.get("value")) == str(value):
                    return option
        return None
