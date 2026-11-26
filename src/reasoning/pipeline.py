"""ExpertPipeline: DESIGN §2 steps 1→7.

extract → ground → working memory → inference → penalty → explanation → answer.
The LLM is used only in the first and last step.
"""

from __future__ import annotations

import logging
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import BaseModel

from src.reasoning.answer_writer import AnswerWriter
from src.reasoning.engine import UNKNOWN_VALUE, InferenceEngine
from src.reasoning.explain import Explainer
from src.reasoning.extractor_llm import FactExtractor
from src.reasoning.extractor_regex import NUMBER, RegexExtractor, normalize, to_number
from src.reasoning.grounder import OntologyGrounder, Retriever
from src.reasoning.knowledge_base import KnowledgeBase, get_knowledge_base
from src.reasoning.llm_client import LLMClient
from src.reasoning.penalty import PenaltyDecider
from src.reasoning.schema import (
    ConsultBranch,
    ConsultResult,
    ConsultViolation,
    EngineResult,
    ExtractionResult,
    Facts,
    PenaltySummary,
    Question,
    TraceStep,
    ViolationHit,
)

logger = logging.getLogger(__name__)

SESSION_TTL_SECONDS = 30 * 60
GROUNDED_WARNING = (
    "Lưu ý: có hành vi được ánh xạ tự động bằng tìm kiếm ngữ nghĩa ({ids}); "
    "hãy đối chiếu nguyên văn điều luật với thực tế."
)
# Questions per incident; after that the missing slots become branches.
MAX_QUESTION_ROUNDS = 3
UNKNOWN_REPLIES = ("không biết", "không nhớ", "không rõ lắm", "chưa rõ")
# Spellings accepted for the unit of a numeric question (spaces removed).
UNIT_ALIASES = {"km/h": ("km", "kmh", "km/giờ"), "mg/l": ("mg/lítkhíthở", "mg/lkhíthở")}


class ConsultOptions(BaseModel):
    """Switches for the API and for ablation (DESIGN §11)."""

    use_llm_extractor: bool = True
    use_grounder: bool = True
    enabled_rule_types: list[str] | None = None  # None = all
    use_circumstances: bool = True
    use_llm_writer: bool = True


@dataclass
class Session:
    status: str
    facts: Facts
    questions: list[Question]
    expires_at: float
    asked: int = 0  # question rounds used for this incident


class SessionStore:
    """In-memory facts per session with a sliding TTL."""

    def __init__(self, ttl: float = SESSION_TTL_SECONDS, clock: Callable[[], float] = time.monotonic):
        self.ttl = ttl
        self.clock = clock
        self._items: dict[str, Session] = {}
        self._lock = threading.Lock()

    def get(self, session_id: str) -> Session | None:
        with self._lock:
            self._purge()
            return self._items.get(session_id)

    def put(
        self, session_id: str, status: str, facts: Facts, questions: list[Question], asked: int = 0
    ) -> None:
        with self._lock:
            self._purge()
            self._items[session_id] = Session(
                status, facts, questions, self.clock() + self.ttl, asked
            )

    def _purge(self) -> None:
        now = self.clock()
        for key in [k for k, s in self._items.items() if s.expires_at <= now]:
            del self._items[key]


@dataclass
class ConsultOutcome:
    """The API response plus what is worth logging for reports."""

    result: ConsultResult
    extractor: str  # llm | regex | answer
    writer: str  # llm | template
    llm_calls: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def merge_facts(old: Facts, new: Facts) -> Facts:
    """Add a follow-up turn to the session facts: lists are united, new values win."""
    data = old.model_dump()
    defaults = Facts().model_dump()
    for name, value in new.model_dump().items():
        if name == "evidence":
            data[name] = {**data[name], **value}
        elif isinstance(value, list):
            data[name] = list(dict.fromkeys([*data[name], *value]))
        elif value != defaults[name]:
            data[name] = value
    measured = data["bac_blood_mg_100ml"] or data["bac_breath_mg_l"]
    refused = data["alcohol_test_refused"] or "ACT_REFUSE_ALCOHOL_TEST" in data["acts"]
    if refused and not measured:
        data["acts"] = [a for a in data["acts"] if a != "ACT_ALCOHOL"]
    return Facts.model_validate(data)


def parse_answer(message: str, questions: list[Question]) -> tuple[str, Any] | None:
    """Read a short reply to a pending question: an option (value or label) or a
    number with an optional matching unit. Anything else goes to the extractor."""
    reply = normalize(message).strip(" .!?")
    for question in questions:
        if reply in UNKNOWN_REPLIES:
            return question.field, UNKNOWN_VALUE
        for option in question.options:
            label = normalize(option.label)
            accepted = {str(option.value).lower(), label, label.split(" (")[0]}
            if reply in accepted:
                return question.field, option.value

    found = re.fullmatch(rf"(?:khoảng|tầm)?\s*({NUMBER})\s*(.*)", reply)
    if not found:
        return None
    number, unit = to_number(found.group(1)), found.group(2).replace(" ", "")
    for question in questions:
        if question.input_type != "number":
            continue
        expected = (question.unit or "").lower()
        if unit not in ("", expected, *UNIT_ALIASES.get(expected, ())):
            continue
        if question.number_max is None or 0 <= number <= question.number_max:
            return question.number_field or question.field, number
    return None


class ExpertPipeline:
    def __init__(
        self,
        retriever: Retriever | None = None,
        kb: KnowledgeBase | None = None,
        llm_client: LLMClient | None = None,
        sessions: SessionStore | None = None,
    ):
        self.kb = kb or get_knowledge_base()
        self.llm_client = llm_client
        self.sessions = sessions or SessionStore()
        self.regex_extractor = RegexExtractor(self.kb)
        self.llm_extractor = (
            FactExtractor(llm_client, self.kb, self.regex_extractor) if llm_client else None
        )
        self.grounder = OntologyGrounder(retriever, self.kb) if retriever else None
        self.penalty = PenaltyDecider(self.kb)
        self.explainer = Explainer(self.kb)
        self.writer = AnswerWriter(llm_client)

    def consult(
        self,
        message: str,
        session_id: str | None = None,
        options: ConsultOptions | None = None,
    ) -> ConsultResult:
        return self.consult_detailed(message, session_id, options).result

    def consult_detailed(
        self,
        message: str,
        session_id: str | None = None,
        options: ConsultOptions | None = None,
    ) -> ConsultOutcome:
        options = options or ConsultOptions()
        session_id = session_id or uuid.uuid4().hex
        latency: dict[str, float] = {}
        llm_calls: list[dict[str, Any]] = []
        started = mark = time.perf_counter()

        def lap(step: str) -> None:
            nonlocal mark
            now = time.perf_counter()
            latency[step] = round((now - mark) * 1000, 2)
            mark = now

        engine = InferenceEngine(self.kb, enabled_rule_types=options.enabled_rule_types)

        # [1] facts of this turn, merged with the session
        facts, extraction, asked = self._collect_facts(message, session_id, options, engine)
        if extraction.llm:
            llm_calls.append({"step": "extract", **extraction.llm})
        lap("extract")

        # [2] grounding (re-run every turn on the stored phrases)
        working, ground_steps = facts, []
        if options.use_grounder and self.grounder:
            working, ground_steps = self.grounder.ground(facts)
        lap("ground")

        # [3]-[6] inference, penalty, explanation
        inferred = engine.run(working, allow_questions=asked < MAX_QUESTION_ROUNDS)
        inferred.trace[:0] = ground_steps
        circumstances = inferred.circumstances if options.use_circumstances else []
        penalty = self.penalty.decide_hits(inferred.hits, circumstances, inferred.facts_final.subject)
        result = self._build_result(session_id, inferred, penalty, circumstances, facts)
        asked += bool(inferred.questions)
        self.sessions.put(session_id, result.status, facts, inferred.questions, asked)
        lap("reason")

        # [7] answer
        remarks = self._remarks(inferred, penalty, ground_steps)
        use_llm_writer = options.use_llm_writer and self.llm_client is not None
        result.answer_text, writer = self.writer.write(result, penalty, remarks, use_llm_writer)
        result.notes = remarks
        result.summary_text = self.writer.summary(result, remarks, writer)
        if use_llm_writer and result.status == "answered" and self.llm_client.last_metadata:
            if writer == "llm":
                llm_calls.append({"step": "write", **self.llm_client.last_metadata.as_dict()})
        lap("write")

        latency["total"] = round((time.perf_counter() - started) * 1000, 2)
        result.latency_ms = latency
        return ConsultOutcome(
            result=result,
            extractor=extraction.source,
            writer=writer,
            llm_calls=llm_calls,
            warnings=extraction.warnings,
        )

    # -- steps ------------------------------------------------------------
    def _collect_facts(
        self, message: str, session_id: str, options: ConsultOptions, engine: InferenceEngine
    ) -> tuple[Facts, ExtractionResult, int]:
        """Facts of the incident so far, this turn's extraction, questions already asked."""
        session = self.sessions.get(session_id)
        # Only a reply to a follow-up question continues the previous facts; after
        # any other status the same session_id starts a new incident.
        if session and session.status != "need_info":
            session = None
        if session:
            answer = parse_answer(message, session.questions)
            if answer:
                name, value = answer
                facts = engine.apply_answer(session.facts, name, value)
                before, after = session.facts.model_dump(), facts.model_dump()
                for field_name, current in after.items():
                    if field_name in ("evidence", "unknown_slots") or current == before[field_name]:
                        continue
                    facts.evidence.setdefault(field_name, message.strip())
                return facts, ExtractionResult(facts=facts, source="answer"), session.asked

        use_llm = options.use_llm_extractor and self.llm_extractor is not None
        extractor = self.llm_extractor if use_llm else self.regex_extractor
        extraction = extractor.extract(message)
        if session is None:
            return extraction.facts, extraction, 0
        new = extraction.facts
        # A reply that fills an asked slot is not a new behaviour to ground.
        if any(
            getattr(new, name) is not None
            for q in session.questions
            for name in (q.field, q.number_field)
            if name
        ):
            new = new.model_copy(update={"free_behaviors": []})
        return merge_facts(session.facts, new), extraction, session.asked

    def _violations(
        self, hits: list[ViolationHit], penalty: PenaltySummary
    ) -> list[ConsultViolation]:
        decisions = {d.citation_id: d for d in penalty.decisions}
        violations = []
        for hit in hits:
            decision = decisions[hit.citation_id]
            violations.append(
                ConsultViolation(
                    citation_id=hit.citation_id,
                    label=self.explainer.label_of(hit.citation_id),
                    description=self.kb.violations[hit.citation_id]["description"],
                    fine_range=decision.fine_range,
                    recommended_fine=decision.recommended_fine,
                    points_deducted=decision.points_deducted,
                    sanctions=decision.sanctions,
                    legal_text=self.kb.legal_texts.get(hit.citation_id),
                    allowed_range_after_circumstances=decision.allowed_range_after_circumstances,
                    points_conditional=decision.points_conditional,
                    org_rule_applied=decision.org_rule_applied,
                )
            )
        return violations

    def _build_result(
        self,
        session_id: str,
        inferred: EngineResult,
        penalty: PenaltySummary,
        circumstances: list[str],
        user_facts: Facts,
    ) -> ConsultResult:
        subject = inferred.facts_final.subject
        branches = [
            ConsultBranch(
                conditions=branch.conditions,
                violations=self._violations(
                    branch.hits, self.penalty.decide_hits(branch.hits, circumstances, subject)
                ),
            )
            for branch in inferred.branches
        ]
        status = "out_of_scope" if inferred.status == "out_of_scope_temporal" else inferred.status
        return ConsultResult(
            session_id=session_id,
            status=status,
            facts=inferred.facts_final,
            violations=self._violations(inferred.hits, penalty),
            total_recommended_fine=penalty.total_recommended_fine,
            total_points_deducted=penalty.total_points_deducted,
            sanctions=penalty.sanctions,
            aggravating=penalty.aggravating,
            mitigating=penalty.mitigating,
            questions=inferred.questions,
            branches=branches,
            depends_on=inferred.depends_on,
            explanation=self.explainer.explain(inferred, penalty, user_facts),
        )

    def _remarks(
        self, inferred: EngineResult, penalty: PenaltySummary, ground_steps: list[TraceStep]
    ) -> list[str]:
        remarks = [inferred.message] if inferred.message else []
        remarks += inferred.notes
        if inferred.branches:
            remark = f"Kết quả phụ thuộc vào {', '.join(inferred.depends_on)}."
            if inferred.branches_incomplete:
                remark += (
                    " Chỉ liệt kê các trường hợp hệ thống xác định được quy định; "
                    "trường hợp còn lại chưa đủ căn cứ."
                )
            remarks.append(remark)
        for decision in penalty.decisions:
            for item in decision.points_conditional:
                remarks.append(
                    f"Chưa tự áp: trừ {item.points} điểm giấy phép lái xe nếu “{item.condition}” "
                    f"({self.explainer.label_of(item.source)})."
                )
        mapped_acts = {a for s in ground_steps for a in s.produced.get("acts", [])}
        mapped_ids = {c for s in ground_steps for c in s.produced.get("grounded_violations", [])}
        grounded = [
            self.explainer.label_of(hit.citation_id)
            for hit in inferred.hits
            if hit.citation_id in mapped_ids or mapped_acts & set(hit.acts)
        ]
        if grounded:
            remarks.append(GROUNDED_WARNING.format(ids="; ".join(grounded)))
        return remarks
