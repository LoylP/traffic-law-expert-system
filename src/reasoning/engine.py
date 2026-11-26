"""Forward-chaining inference engine (DESIGN §5.3).

Pure Python: no LLM, no network. Phases run in PHASE_ORDER; inside a phase the
engine loops match → resolve → fire until no rule can fire (each rule fires at
most once). Conflict resolution: priority desc → specificity desc → file order.
"""

from __future__ import annotations

import itertools
import json
from datetime import date
from typing import Any, Iterable

from src.reasoning.knowledge_base import KnowledgeBase, get_knowledge_base
from src.reasoning.schema import (
    PHASE_ORDER,
    Branch,
    BranchCondition,
    EngineResult,
    Facts,
    Question,
    Rule,
    TraceStep,
    ViolationHit,
)

_MISSING = object()

# Pseudo rule id of the built-in "specific beats general" exclusion.
SPECIFICITY_RULE_ID = "ENGINE-EXC-SPECIFICITY"
# Answer meaning "I do not know": the slot is not asked again.
UNKNOWN_VALUE = "unknown"
UNKNOWN_LABEL = "Không rõ"
# Phases replayed to see what a value of a missing slot would lead to.
PROBE_PHASES = ("derive", "temporal", "classify", "escalate", "exclude")
# Option keys that change more than the asked slot; such options are not probed.
_EFFECT_KEYS = ("set_facts", "set_acts", "remove_acts")


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
        self.branches: list[Branch] = []
        self.depends_on: list[str] = []
        self.branches_incomplete = False
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
    def __init__(
        self,
        kb: KnowledgeBase | None = None,
        enabled_rule_types: Iterable[str] | None = None,
        disabled_types: Iterable[str] = (),
    ):
        self.kb = kb or get_knowledge_base()
        enabled = set(PHASE_ORDER if enabled_rule_types is None else enabled_rule_types)
        unknown = (enabled | set(disabled_types)) - set(PHASE_ORDER)
        if unknown:
            raise ValueError(f"unknown rule type(s): {sorted(unknown)}")
        self.enabled_types = enabled - set(disabled_types)
        self._order = {rule.id: index for index, rule in enumerate(self.kb.rules)}
        self._by_phase: dict[str, list[Rule]] = {}

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
        if key == "has_circumstance":
            return any(cir in wm.circumstances for cir in _as_list(cond))
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
            elif key == "has_circumstance":
                matched[key] = [c for c in _as_list(rule.when[key]) if c in wm.circumstances]
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

    def _acts_of(self, wm: WorkingMemory, rule: Rule, citation_id: str) -> list[str]:
        """Acts a new hit stands for: the rule's has_act, else the acts.yaml mapping."""
        matched = [a for a in _as_list(rule.when.get("has_act")) if a in wm.acts]
        return matched or list(self.kb.citation_acts.get(citation_id, []))

    def _new_hit(self, rule: Rule, citation_id: str, **extra: Any) -> ViolationHit:
        return ViolationHit(
            citation_id=citation_id,
            rule_id=rule.id,
            legal_excerpt=rule.legal_excerpt,
            legal_text=self.kb.legal_texts.get(citation_id),
            **extra,
        )

    # -- firing ---------------------------------------------------------
    def _fire(self, wm: WorkingMemory, rule: Rule) -> dict[str, Any]:
        then = rule.then
        produced: dict[str, Any] = {}

        if "set_facts" in then:  # derive only fills what is still empty
            filled = {k: v for k, v in then["set_facts"].items() if _is_empty(wm.facts[k])}
            wm.facts.update(filled)
            produced["set_facts"] = filled
        if "add_consequence" in then:
            wm.facts["consequence"] = list(wm.facts["consequence"])
            produced["consequence"] = _add_unique(
                wm.facts["consequence"], _as_list(then["add_consequence"])
            )
        if "add_context_from" in then:
            value = wm.facts[then["add_context_from"]]
            produced["contexts"] = _add_unique(wm.contexts, [value])
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
                wm.violations[cid] = self._new_hit(
                    rule, cid, acts=self._acts_of(wm, rule, cid), priority=rule.priority
                )
            produced["violation"] = cid
        if "escalate_to" in then:
            target = then["escalate_to"]
            sources = [cid for cid in _as_list(rule.when.get("has_violation")) if cid in wm.violations]
            # The escalated hit keeps what it stands for, so the specificity
            # exclusion still applies to it (DESIGN §5.2).
            replaced = [wm.violations.pop(cid) for cid in sources]
            if sources:
                if target not in wm.violations:
                    wm.violations[target] = self._new_hit(rule, target)
                hit = wm.violations[target]
                _add_unique(hit.escalated_from, sources)
                for source_hit in replaced:
                    _add_unique(hit.acts, source_hit.acts)
                    hit.priority = max(hit.priority, source_hit.priority)
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

        return produced

    def _rules(self, wm: WorkingMemory, phase: str) -> list[Rule]:
        """Rules of a phase, without the grounded-only rules that cannot match."""
        if phase not in self._by_phase:
            self._by_phase[phase] = self.kb.rules_of(phase)
        grounded = set(wm.facts["grounded_violations"])
        return [
            rule
            for rule in self._by_phase[phase]
            if "grounded_violation" not in rule.when
            or grounded & set(_as_list(rule.when["grounded_violation"]))
        ]

    def _run_phase(self, wm: WorkingMemory, phase: str, fired: set[tuple[str, str]]) -> None:
        """Match → resolve → fire until no new (rule, binding) pair is left."""
        while True:
            eligible = []
            for rule in self._rules(wm, phase):
                if not self._matches(wm, rule):
                    continue
                matched = self._matched_facts(wm, rule)
                binding = (rule.id, json.dumps(matched, sort_keys=True, default=str))
                if binding not in fired:
                    eligible.append((rule, matched, binding))
            if not eligible:
                return
            rule, matched, binding = min(eligible, key=lambda item: self._rank(item[0]))
            produced = self._fire(wm, rule)
            fired.add(binding)
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

    def _exclude_general_hits(self, wm: WorkingMemory) -> None:
        """Drop a hit when each of its acts has a higher-priority hit."""
        snapshot = list(wm.violations.values())
        for hit in snapshot:
            if not hit.acts:
                continue
            winners: dict[str, str] = {}
            for act in hit.acts:
                better = [o for o in snapshot if act in o.acts and o.priority > hit.priority]
                if better:
                    winners[act] = max(better, key=lambda o: o.priority).citation_id
            if len(winners) != len(hit.acts):
                continue
            del wm.violations[hit.citation_id]
            replaced_by = list(dict.fromkeys(winners.values()))
            wm.trace.append(
                TraceStep(
                    rule_id=SPECIFICITY_RULE_ID,
                    type="exclude",
                    matched_facts={"has_violation": [hit.citation_id, *replaced_by]},
                    produced={"removed_violations": [hit.citation_id]},
                    explain=(
                        f"Bỏ {hit.citation_id}: cùng hành vi đã có quy định cụ thể hơn "
                        f"({', '.join(replaced_by)})."
                    ),
                    source="DESIGN §5.2 (luật exclude)",
                )
            )

    # -- missing slots --------------------------------------------------
    # An ask rule only declares a slot (its question, the options and when it is
    # known). Whether to ask is decided here: a missing slot matters when the
    # classify rules of the current acts read it AND its value changes which
    # citations come out.

    def _slots(self) -> list[Rule]:
        """The primary ask rule of every slot (the one with options), best first."""
        primary = [r for r in self.kb.rules_of("ask") if r.then.get("options")]
        return sorted(primary, key=self._rank)

    @staticmethod
    def _slot_name(rule: Rule) -> str:
        return rule.then.get("slot") or rule.then["ask_field"]

    @staticmethod
    def _probe_options(rule: Rule) -> list[dict[str, Any]]:
        return [o for o in rule.then["options"] if not any(k in o for k in _EFFECT_KEYS)]

    @staticmethod
    def _is_known(facts: dict[str, Any], rule: Rule) -> bool:
        """known_if: the slot is known when every field of any group is stated."""

        def stated(name: str) -> bool:
            value = facts[name]
            return value is not False and not _is_empty(value)

        return any(all(stated(f) for f in group) for group in rule.then["known_if"])

    def _is_relevant(self, wm: WorkingMemory, slot_rule: Rule) -> bool:
        """Does a classify rule for one of the current acts read this slot?"""
        name = slot_rule.then["ask_field"]
        values = {o["value"] for o in self._probe_options(slot_rule)}
        return any(
            set(_as_list(rule.when.get("has_act"))) & set(wm.acts)
            and (name in rule.when or set(_as_list(rule.when.get("has_context"))) & values)
            for rule in self._rules(wm, "classify")
        )

    def _probe(self, facts: Facts) -> dict[str, ViolationHit]:
        wm = WorkingMemory(facts)
        fired: set[tuple[str, str]] = set()
        for phase in PROBE_PHASES:
            if phase not in self.enabled_types:
                continue
            self._run_phase(wm, phase, fired)
            if phase == "exclude":
                self._exclude_general_hits(wm)
            if wm.status == "out_of_scope_temporal":
                break
        return wm.violations

    def _resolve_missing_slots(self, wm: WorkingMemory, facts: Facts, allow_questions: bool) -> None:
        """Ask the first slot that changes the result, or list the branches."""
        slots = [
            rule
            for rule in self._slots()
            if not self._is_known(wm.facts, rule) and self._is_relevant(wm, rule)
        ]
        if not slots:
            return
        # Outcome of every combination of values of the missing slots.
        domains = [[o["value"] for o in self._probe_options(rule)] for rule in slots]
        outcomes = {
            combo: self._probe(
                facts.model_copy(
                    update={r.then["ask_field"]: v for r, v in zip(slots, combo)}, deep=True
                )
            )
            for combo in itertools.product(*domains)
        }
        mattering = []
        for index in range(len(slots)):
            seen: dict[tuple, set[frozenset[str]]] = {}
            for combo, hits in outcomes.items():
                others = combo[:index] + combo[index + 1 :]
                seen.setdefault(others, set()).add(frozenset(hits))
            if any(len(results) > 1 for results in seen.values()):
                mattering.append(index)
        if not mattering:
            return

        # Only what holds whatever the missing values are counts as determined.
        stable = set.intersection(*(set(hits) for hits in outcomes.values()))
        pending = [cid for cid in wm.violations if cid not in stable]
        for cid in pending:
            del wm.violations[cid]

        unknown = set(wm.facts["unknown_slots"])
        askable = [slots[i] for i in mattering if self._slot_name(slots[i]) not in unknown]
        if askable and allow_questions:
            self._ask(wm, askable[0], pending)
        else:
            self._branch(wm, [slots[i] for i in mattering], mattering, outcomes, stable)

    def _question_rule(self, wm: WorkingMemory, slot_rule: Rule) -> Rule:
        """A conditional variant of the slot (ask only the missing half), else the primary."""
        name = self._slot_name(slot_rule)
        for rule in self.kb.rules_of("ask"):
            if rule.when and self._slot_name(rule) == name and self._matches(wm, rule):
                return rule
        return slot_rule

    def _ask(self, wm: WorkingMemory, slot_rule: Rule, pending: list[str]) -> None:
        rule = self._question_rule(wm, slot_rule)
        then = rule.then
        question = Question(
            field=then["ask_field"],
            slot=self._slot_name(rule),
            text=then.get("question_text", ""),
            options=[*then.get("options", []), {"value": UNKNOWN_VALUE, "label": UNKNOWN_LABEL}],
            input_type=then.get("input_type"),
            unit=then.get("unit"),
            number_field=then.get("number_field"),
            number_max=then.get("number_max"),
            rule_id=rule.id,
        )
        wm.questions.append(question)
        produced: dict[str, Any] = {"question": question.field}
        if pending:
            produced["pending_violations"] = pending
        wm.trace.append(
            TraceStep(
                rule_id=rule.id,
                type="ask",
                matched_facts={"missing_slot": question.slot},
                produced=produced,
                explain=rule.explain,
                source=rule.source,
            )
        )

    def _branch(
        self,
        wm: WorkingMemory,
        slots: list[Rule],
        positions: list[int],
        outcomes: dict[tuple, dict[str, ViolationHit]],
        stable: set[str],
    ) -> None:
        projected: dict[tuple, dict[str, ViolationHit]] = {}
        for combo, hits in outcomes.items():
            projected.setdefault(tuple(combo[i] for i in positions), hits)
        groups: dict[tuple[str, ...], list[tuple]] = {}
        for combo, hits in projected.items():
            extra = tuple(cid for cid in hits if cid not in stable)
            if extra:
                groups.setdefault(extra, []).append(combo)
            else:
                wm.branches_incomplete = True
        options = [{o["value"]: o["label"] for o in self._probe_options(r)} for r in slots]
        for extra, combos in groups.items():
            columns = [list(dict.fromkeys(c[i] for c in combos)) for i in range(len(slots))]
            size = 1
            for column in columns:
                size *= len(column)
            # Merge the combinations only when the merged condition says exactly the same.
            rows = [columns] if size == len(combos) else [[[v] for v in c] for c in combos]
            for row in rows:
                conditions = [
                    BranchCondition(
                        slot=self._slot_name(rule),
                        slot_label=rule.then["slot_label"],
                        values=values,
                        labels=[options[i][v] for v in values],
                    )
                    for i, (rule, values) in enumerate(zip(slots, row))
                    if len(values) < len(options[i])
                ]
                wm.branches.append(
                    Branch(conditions=conditions, hits=[projected[combos[0]][c] for c in extra])
                )
        wm.depends_on = [rule.then["slot_label"] for rule in slots]
        for rule in slots:
            wm.trace.append(
                TraceStep(
                    rule_id=rule.id,
                    type="ask",
                    matched_facts={"missing_slot": self._slot_name(rule)},
                    produced={"depends_on": rule.then["slot_label"]},
                    explain=f"Thiếu {rule.then['slot_label']}: không tự chọn, liệt kê các khả năng.",
                    source=rule.source,
                )
            )

    # -- public API -----------------------------------------------------
    def run(self, facts: Facts | dict[str, Any], allow_questions: bool = True) -> EngineResult:
        """`allow_questions=False` (question limit reached) turns every slot that
        would be asked into branches."""
        if not isinstance(facts, Facts):
            facts = Facts.model_validate(facts)
        wm = WorkingMemory(facts)
        fired: set[tuple[str, str]] = set()

        for phase in PHASE_ORDER:
            if phase not in self.enabled_types:
                continue
            if phase == "ask":
                self._resolve_missing_slots(wm, facts, allow_questions)
                continue
            self._run_phase(wm, phase, fired)
            if phase == "exclude":
                self._exclude_general_hits(wm)
            if phase == "temporal" and wm.status == "out_of_scope_temporal":
                break

        return EngineResult(
            status=self._final_status(wm),
            input_facts=facts.model_copy(deep=True),
            facts_final=wm.to_facts(),
            acts=wm.acts,
            contexts=wm.contexts,
            circumstances=wm.circumstances,
            hits=list(wm.violations.values()),
            questions=wm.questions,
            branches=wm.branches,
            depends_on=wm.depends_on,
            branches_incomplete=wm.branches_incomplete,
            notes=wm.notes,
            message=wm.message,
            trace=wm.trace,
        )

    infer = run  # P1 name

    @staticmethod
    def _final_status(wm: WorkingMemory) -> str:
        if wm.status == "out_of_scope_temporal":
            return wm.status
        if wm.questions:
            return "need_info"
        if wm.violations or wm.branches:
            return "answered"
        if wm.status:  # e.g. out_of_scope set by a note rule (only when no violation)
            return wm.status
        return "unknown"

    def apply_answer(self, facts: Facts, field: str, value: Any) -> Facts:
        """Merge the user's answer to a question into facts.

        "Không rõ" fills nothing: the slot is recorded in `unknown_slots`.

        If the matching ask-rule option declares effects (`set_facts`, `set_acts`,
        `remove_acts`) they are applied instead of writing the raw value; e.g.
        R-ASK-ALC-01 option `refuse` → alcohol_test_refused=True, add
        ACT_REFUSE_ALCOHOL_TEST, drop ACT_ALCOHOL.
        """
        data = facts.model_dump()
        if value == UNKNOWN_VALUE:
            slot = next(
                (
                    self._slot_name(r)
                    for r in self.kb.rules_of("ask")
                    if r.then["ask_field"] == field
                ),
                field,
            )
            _add_unique(data["unknown_slots"], [slot])
            return Facts.model_validate(data)
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
