"""Adolescent teaching process (Plan §5.5.1, D21; ported from DBT_Revised `teaching/`).

The server owns `TeachingSession.phase`. Every transition is a conditional UPDATE on the
expected phase ("claimed-phase", replacing DBT_Revised's Redis locks): a double submit or a
second tab gets `409 lesson.state_changed` instead of running the step twice. A chat turn claims
`busy_until` the same way while it streams.

Pausing is leaving: an ongoing lesson stays open with no time limit (D56). One open lesson per
learner (partial unique index); starting another asks the client to continue or close it.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ai.service import AIResult, AIService
from app.core.errors import bad_request, conflict, not_found
from app.core.logging import get_logger
from app.core.sessions import utcnow
from app.learning import profile as profile_mod
from app.learning.progress import record_lesson_completed
from app.learning.selection import apply_repeat_guard, build_context
from app.models import (
    ChatMessage,
    ChatRole,
    ContentSource,
    DetectionChannel,
    GroupSkillRecord,
    LearnerProfile,
    LessonSource,
    LessonStatus,
    MoodKind,
    MoodRecord,
    SafetyCategory,
    SafetySeverity,
    SafetySource,
    TeachingPhase,
    TeachingSession,
    User,
)
from app.safety.events import raise_event
from app.safety.service import Context, SafetyOutcome, SafetyService

P = TeachingPhase
log = get_logger(__name__)
BUSY_SECONDS = 180
HISTORY_TURNS = 12  # teaching_turn input cap
SUMMARY_HISTORY = 80
MIN_MESSAGES_TO_COMPLETE = 4  # two exchanges (DBT_Revised)
CLOSING_TYPES = ("summary", "feedback")
FAREWELL_PATTERNS = (
    "再见",
    "下周见",
    "明天见",
    "下次见",
    "今天就到这里",
    "今天就到这",
    "我们下次",
    "期待下次",
    "加油",
    "goodbye",
    "see you",
    "next time",
    "take care",
    "that's all for today",
)


# --- pure rules (ported; unit-tested) ---------------------------------------------------------


def current_step(message_count: int, plan_steps: int) -> int:
    if plan_steps <= 0:
        return 1
    return min(message_count // 2 + 1, plan_steps)


def has_farewell(content: str) -> bool:
    """At least two closing patterns (a goodbye plus a closure), as DBT_Revised."""
    text = (content or "").casefold()
    return sum(1 for p in FAREWELL_PATTERNS if p in text) >= 2


def should_auto_complete(
    message_type: str | None, content: str, message_count: int, plan_steps: int
) -> bool:
    if message_count < MIN_MESSAGES_TO_COMPLETE:
        return False
    if plan_steps > 0 and current_step(message_count, plan_steps) < plan_steps:
        return False
    return (message_type in CLOSING_TYPES) or has_farewell(content)


# --- helpers ---


def _json(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        data = json.loads(value)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _dump(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False)


def source_ref(s: TeachingSession) -> str:
    return f"lesson:{s.id}"


def get_owned(db: Session, user: User, session_id: uuid.UUID) -> TeachingSession:
    s = db.get(TeachingSession, session_id)
    if s is None or s.user_id != user.id:
        raise not_found("lesson.not_found")
    return follow_language(s, user)


def follow_language(s: TeachingSession, user: User) -> TeachingSession:
    """An open lesson follows the learner's current language (as DBT_Revised does per call): a
    switch mid-lesson applies to names and every AI step from now on; earlier messages stay as
    they were written."""
    if s.status == LessonStatus.ongoing and s.language != user.language:
        s.language = user.language
    return s


def open_session(db: Session, user: User) -> TeachingSession | None:
    s = db.scalar(
        select(TeachingSession).where(
            TeachingSession.user_id == user.id, TeachingSession.status == LessonStatus.ongoing
        )
    )
    return follow_language(s, user) if s else None


def claim(db: Session, s: TeachingSession, expected: TeachingPhase, to: TeachingPhase) -> None:
    """Move expected -> to, or 409 if another request already moved it."""
    res = db.execute(
        update(TeachingSession)
        .where(
            TeachingSession.id == s.id,
            TeachingSession.phase == expected,
            TeachingSession.status == LessonStatus.ongoing,
        )
        .values(phase=to, last_active_at=func.now())
        .execution_options(synchronize_session=False)
    )
    if res.rowcount != 1:  # type: ignore[attr-defined]
        raise conflict("lesson.state_changed")
    db.refresh(s)


def _ensure_ongoing(s: TeachingSession) -> None:
    if s.status is not LessonStatus.ongoing:
        raise conflict("lesson.closed")


def _messages(db: Session, s: TeachingSession) -> list[ChatMessage]:
    return list(
        db.scalars(
            select(ChatMessage).where(ChatMessage.session_id == s.id).order_by(ChatMessage.seq)
        )
    )


def _add_message(
    db: Session,
    s: TeachingSession,
    role: ChatRole,
    content: str,
    *,
    question: str | None = None,
    message_type: str | None = None,
    step: int | None = None,
    source: ContentSource | None = None,
) -> ChatMessage:
    seq = (
        db.scalar(select(func.max(ChatMessage.seq)).where(ChatMessage.session_id == s.id)) or 0
    ) + 1
    m = ChatMessage(
        session_id=s.id,
        seq=seq,
        role=role,
        content=content,
        question=question or None,
        message_type=message_type,
        teaching_step=step,
        source=source,
    )
    db.add(m)
    db.flush()
    return m


def _turns(messages: Sequence[ChatMessage]) -> list[dict[str, str]]:
    out = []
    for m in messages:
        text = m.content if not m.question else f"{m.content}\n\n{m.question}"
        out.append({"role": m.role.value, "content": text[:2000]})
    return out


def _plan_steps(s: TeachingSession) -> list[dict[str, Any]]:
    return list((s.plan or {}).get("steps") or [])


@dataclass
class Services:
    ai: AIService
    safety: SafetyService


# --- lifecycle ---


def start(
    db: Session,
    user: User,
    *,
    group_record: GroupSkillRecord | None = None,
    skill_id: str | None = None,
) -> TeachingSession:
    if open_session(db, user) is not None:
        raise conflict("lesson.open_exists")
    s = TeachingSession(user_id=user.id, language=user.language, phase=P.pre_mood_recording)
    if group_record is not None:
        if not skill_id or skill_id not in group_record.skill_ids:
            raise bad_request("lesson.skill_not_in_record")
        s.source = LessonSource.group_review
        s.group_record_id = group_record.id
        s.selected_skill = skill_id
    db.add(s)
    try:
        db.flush()
    except IntegrityError as exc:  # a parallel request opened one first
        raise conflict("lesson.open_exists") from exc
    return s


def stop(db: Session, user: User, s: TeachingSession) -> None:
    """Stop at any time, no penalty (Plan §5.5.1 terminal states)."""
    res = db.execute(
        update(TeachingSession)
        .where(TeachingSession.id == s.id, TeachingSession.status == LessonStatus.ongoing)
        .values(status=LessonStatus.user_terminated, completed_at=func.now(), busy_until=None)
        .execution_options(synchronize_session=False)
    )
    if res.rowcount != 1:  # type: ignore[attr-defined]
        raise conflict("lesson.closed")
    db.refresh(s)


def _stop_for_safety(db: Session, s: TeachingSession) -> None:
    db.execute(
        update(TeachingSession)
        .where(TeachingSession.id == s.id, TeachingSession.status == LessonStatus.ongoing)
        .values(status=LessonStatus.stopped_by_safety, completed_at=func.now(), busy_until=None)
        .execution_options(synchronize_session=False)
    )
    db.refresh(s)


def _screen(
    svc: Services, db: Session, user: User, s: TeachingSession, text: str | None
) -> SafetyOutcome | None:
    if not text or not text.strip():
        return None
    recent = [m.content for m in _messages(db, s) if m.role is ChatRole.student][-3:]
    outcome = svc.safety.screen_text(
        db, user, Context.lesson, text, recent=recent, source_ref=source_ref(s)
    )
    if outcome.should_stop:
        _stop_for_safety(db, s)
    return outcome


def _profile(db: Session, user: User) -> dict[str, Any] | None:
    return profile_mod.for_ai(db.get(LearnerProfile, user.id))


def _cap(text: str | None, svc: Services) -> str | None:
    text = (text or "").strip()
    if not text:
        return None
    if len(text) > svc.ai.settings.lesson_message_max_chars:
        raise bad_request("lesson.message_too_long")
    return text


# --- 1. pre-lesson mood -------------------------------------------------------------------------


def record_pre_mood(
    svc: Services, db: Session, user: User, s: TeachingSession, value: int, note: str | None
) -> SafetyOutcome | None:
    _ensure_ongoing(s)
    note = _cap(note, svc)
    group = s.source is LessonSource.group_review
    claim(
        db, s, P.pre_mood_recording, P.rag_retrieval_for_teaching if group else P.personal_inquiry
    )
    mood = MoodRecord(
        user_id=user.id, kind=MoodKind.before_teaching, value=value, note=note, session_id=s.id
    )
    db.add(mood)
    db.flush()
    s.pre_mood_id = mood.id
    outcome = _screen(svc, db, user, s, note)
    if outcome is not None and outcome.should_stop:
        return outcome
    if group:
        _prepare_teaching(svc, db, user, s)
        return outcome
    # 2. check-in greeting + one optional question (D22)
    res = svc.ai.run(
        db,
        "personal_inquiry",
        {"profile": _profile(db, user), "mood": value, "mood_note": note or ""},
        role="adolescent",
        language=s.language,
        caller="lesson.checkin",
        actor_id=user.id,
        use_cache=False,
    )
    out = res.output or {}
    s.inquiry = _dump(
        {
            "greeting": out.get("greeting", ""),
            "question": out.get("question", ""),
            "source": res.source.value,
        }
    )
    return outcome


# --- 2-3. check-in answer or skip, then recommendation -------------------------------------------


def answer_checkin(
    svc: Services, db: Session, user: User, s: TeachingSession, answer: str | None
) -> SafetyOutcome | None:
    _ensure_ongoing(s)
    answer = _cap(answer, svc)
    claim(db, s, P.personal_inquiry, P.skill_selection)
    s.checkin_skipped = answer is None
    s.personal_context = answer
    outcome = _screen(svc, db, user, s, answer)
    if outcome is not None and outcome.should_stop:
        return outcome
    _recommend(svc, db, user, s)
    return outcome


def _fallback_pick(svc: Services, avoid: Sequence[str]) -> str:
    tax = svc.ai.taxonomy
    order = [
        sk.id for m in (tax.modules if tax else []) if m.id != "orientation" for sk in m.skills
    ]
    fresh = [x for x in order if x not in set(avoid)] or order
    return fresh[0]


def _recommend(svc: Services, db: Session, user: User, s: TeachingSession) -> None:
    ctx = build_context(db, user.id, exclude=s.id)
    pre = db.get(MoodRecord, s.pre_mood_id) if s.pre_mood_id else None
    res = svc.ai.run(
        db,
        "select_skill",
        {
            "profile": _profile(db, user),
            "mood": pre.value if pre else None,
            "checkin_answer": s.personal_context or "",
            "history_skills": ctx.history_skills,
            "recent_skills": ctx.recent_skills,
            "weak_skills": ctx.weak_skills,
        },
        role="adolescent",
        language=s.language,
        caller="lesson.select_skill",
        actor_id=user.id,
        use_cache=False,
    )
    out = dict(res.output or {})
    if not out.get("selected_skill") or out["selected_skill"] not in svc.ai.skill_module:
        pick = _fallback_pick(svc, ctx.recent_skills)
        out = {
            "selected_skill": pick,
            "selected_module": svc.ai.skill_module.get(pick, ""),
            "reason": "",
            "skill_difficulty": "beginner",
            "alternative_skills": [],
        }
    guard = apply_repeat_guard(
        out,
        ctx,
        language=s.language,
        skill_module=svc.ai.skill_module,
        fallback=lambda avoid: _fallback_pick(svc, avoid),
    )
    rec = guard.output
    s.recommendation = _dump(
        {
            "skill": rec["selected_skill"],
            "module": rec.get("selected_module"),
            "reason": rec.get("reason", ""),
            "difficulty": rec.get("skill_difficulty", "beginner"),
            "alternatives": [
                a for a in rec.get("alternative_skills", []) if a in svc.ai.skill_module
            ],
            "is_repeat": bool(rec.get("is_repeat")),
            "repeat_justification": rec.get("repeat_justification", ""),
            "guard": guard.action,
            "source": res.source.value,
        }
    )


# --- 3b. confirm / alternative / choose another; 4-5. plan + opening ------------------------------


def choose_skill(
    svc: Services, db: Session, user: User, s: TeachingSession, skill_id: str, choice: str
) -> None:
    _ensure_ongoing(s)
    rec = _json(s.recommendation)
    if skill_id not in svc.ai.skill_module:
        raise bad_request("lesson.unknown_skill")
    if choice == "recommended" and skill_id != rec.get("skill"):
        raise bad_request("lesson.not_recommended")
    if choice == "alternative" and skill_id not in (rec.get("alternatives") or []):
        raise bad_request("lesson.not_an_alternative")
    claim(db, s, P.skill_selection, P.rag_retrieval_for_teaching)
    s.source = {
        "recommended": LessonSource.recommended,
        "alternative": LessonSource.alternative,
    }.get(choice, LessonSource.chosen)
    s.selected_skill = skill_id
    _prepare_teaching(svc, db, user, s)


def _prepare_teaching(svc: Services, db: Session, user: User, s: TeachingSession) -> None:
    skill = str(s.selected_skill)
    s.selected_module = svc.ai.skill_module.get(skill)
    profile = _profile(db, user)
    plan = svc.ai.run(
        db,
        "teaching_plan",
        {"profile": profile, "skill_id": skill},
        role="adolescent",
        language=s.language,
        caller="lesson.plan",
        actor_id=user.id,
    )
    steps = list((plan.output or {}).get("plan_steps") or [])
    s.plan = {"steps": steps, "source": plan.source.value}
    s.rag_chunk_ids = [r.chunk_id for r in plan.sources][:20]
    rec = _json(s.recommendation)
    reason = rec.get("reason", "") if rec.get("skill") == skill else ""
    opening = svc.ai.run(
        db,
        "teaching_opening",
        {
            "profile": profile,
            "skill_id": skill,
            "selection_reason": reason,
            "checkin_answer": s.personal_context or "",
            "plan_steps": steps,
        },
        role="adolescent",
        language=s.language,
        caller="lesson.opening",
        actor_id=user.id,
        use_cache=False,
    )
    out = opening.output or {}
    _add_message(
        db,
        s,
        ChatRole.coach,
        str(out.get("content") or opening.notice or ""),
        question=str(out.get("question") or ""),
        message_type=str(out.get("message_type") or "explanation"),
        step=1,
        source=opening.source,
    )
    claim(db, s, P.rag_retrieval_for_teaching, P.teaching)


# --- 5. streamed chat turn ---


def claim_turn(db: Session, s: TeachingSession) -> None:
    now = utcnow()
    res = db.execute(
        update(TeachingSession)
        .where(
            TeachingSession.id == s.id,
            TeachingSession.phase == P.teaching,
            TeachingSession.status == LessonStatus.ongoing,
            (TeachingSession.busy_until.is_(None)) | (TeachingSession.busy_until < now),
        )
        .values(busy_until=now + timedelta(seconds=BUSY_SECONDS), last_active_at=func.now())
        .execution_options(synchronize_session=False)
    )
    if res.rowcount != 1:  # type: ignore[attr-defined]
        raise conflict("lesson.busy")
    db.refresh(s)


def release_turn(db: Session, s: TeachingSession) -> None:
    db.execute(
        update(TeachingSession)
        .where(TeachingSession.id == s.id)
        .values(busy_until=None)
        .execution_options(synchronize_session=False)
    )


def begin_turn(
    svc: Services, db: Session, user: User, s: TeachingSession, message: str
) -> SafetyOutcome | None:
    """Claim the turn, store and screen the student's message (request transaction)."""
    _ensure_ongoing(s)
    text = _cap(message, svc)
    if text is None:
        raise bad_request("lesson.empty_message")
    claim_turn(db, s)
    outcome = _screen(svc, db, user, s, text)
    count = len(_messages(db, s))
    _add_message(
        db,
        s,
        ChatRole.student,
        text,
        step=current_step(count + 1, len(_plan_steps(s))),
    )
    s.turns += 1
    if outcome is not None and outcome.should_stop:
        s.busy_until = None
    return outcome


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def stream_turn(svc: Services, db: Session, user: User, session_id: uuid.UUID) -> Iterator[str]:
    """Generator for the SSE body. Runs in its own DB session after the request committed."""
    s = db.get(TeachingSession, session_id)
    assert s is not None
    try:
        msgs = _messages(db, s)
        student = msgs[-1]
        history = _turns(msgs[:-1])[-HISTORY_TURNS:]
        steps = _plan_steps(s)
        count = len(msgs)
        step = current_step(count, len(steps))
        last_type = next(
            (m.message_type for m in reversed(msgs) if m.role is ChatRole.coach and m.message_type),
            None,
        )
        at_cap = s.turns >= svc.ai.settings.lesson_max_turns
        closing = at_cap or (count + 1 >= MIN_MESSAGES_TO_COMPLETE and step >= len(steps))
        result: AIResult | None = None
        for ev in svc.ai.stream(
            db,
            "teaching_turn",
            {
                "profile": _profile(db, user),
                "skill_id": s.selected_skill,
                "plan_steps": steps,
                "current_step": step,
                "history": history,
                "message": student.content,
                "assess_risk": True,
                "last_message_type": last_type,
            },
            role="adolescent",
            language=s.language,
            caller="lesson.turn",
            actor_id=user.id,
            hints={"closing": closing},
        ):
            if ev.kind == "delta":
                yield _sse("delta", {"text": ev.text})
            elif ev.kind == "replace":
                yield _sse("replace", {})
            elif ev.kind == "final":
                result = ev.result
        assert result is not None
        out = result.output or {}
        content = str(out.get("content") or result.notice or "")
        message_type = str(out.get("message_type") or "practice")
        coach = _add_message(
            db,
            s,
            ChatRole.coach,
            content,
            question=str(out.get("question") or ""),
            message_type=message_type,
            step=step,
            source=result.source,
        )
        # Inline risk from the model (assess_risk channel inside teaching_turn).
        level = str(out.get("risk_level") or "none")
        if not result.is_fallback and (out.get("should_stop") or level in ("medium", "high")):
            stop_now = bool(out.get("should_stop")) or level == "high"
            raise_event(
                db,
                subject=user,
                category=SafetyCategory.risk_disclosure,
                severity=SafetySeverity.high if stop_now else SafetySeverity.medium,
                source=SafetySource.lesson,
                channel=DetectionChannel.llm,
                excerpt=student.content,
                detail={"level": level, "reasoning": str(out.get("risk_reasoning") or "")[:300]},
                source_ref=source_ref(s),
                activity_stopped=stop_now,
            )
            if stop_now:
                _stop_for_safety(db, s)
                db.commit()
                yield _sse("safety", {"action": "stop"})
                return
            yield _sse("safety", {"action": "care_card"})
        completed = at_cap or should_auto_complete(message_type, content, count + 1, len(steps))
        payload = {"message": message_view(coach), "completed": False}
        if completed:
            _summarise(svc, db, user, s)
            payload["completed"] = True
        release_turn(db, s)
        db.commit()
        yield _sse("final", payload)
    except Exception:  # the stream has started: report in-band, never leave the turn claimed
        log.exception("lesson.turn_failed", session_id=str(session_id))
        db.rollback()
        release_turn(db, s)
        db.commit()
        yield _sse("error", {"code": "lesson.turn_failed"})


# --- 6. end, summary, post-lesson mood ----------------------------------------------------------


def end_lesson(svc: Services, db: Session, user: User, s: TeachingSession) -> None:
    """*End lesson*: go to the summary now (the student decides when they have had enough)."""
    _ensure_ongoing(s)
    if s.busy_until is not None and s.busy_until > utcnow():
        raise conflict("lesson.busy")
    _summarise(svc, db, user, s)


def _summarise(svc: Services, db: Session, user: User, s: TeachingSession) -> None:
    claim(db, s, P.teaching, P.summary)
    msgs = _messages(db, s)
    res = svc.ai.run(
        db,
        "teaching_summary",
        {
            "profile": _profile(db, user),
            "skill_id": s.selected_skill,
            "history": _turns(msgs)[-SUMMARY_HISTORY:],
        },
        role="adolescent",
        language=s.language,
        caller="lesson.summary",
        actor_id=user.id,
        use_cache=False,
    )
    out = res.output or {}
    s.understanding = str(out.get("understanding") or "") or None
    s.summary = _dump(
        {
            "key_points": list(out.get("key_points") or []),
            "recommendations": list(out.get("recommendations") or []),
            "summary_text": str(out.get("summary_text") or res.notice or ""),
            "source": res.source.value,
        }
    )
    s.busy_until = None


def record_post_mood(
    svc: Services, db: Session, user: User, s: TeachingSession, value: int, note: str | None
) -> SafetyOutcome | None:
    _ensure_ongoing(s)
    note = _cap(note, svc)
    claim(db, s, P.summary, P.done)
    mood = MoodRecord(
        user_id=user.id, kind=MoodKind.after_teaching, value=value, note=note, session_id=s.id
    )
    db.add(mood)
    db.flush()
    s.post_mood_id = mood.id
    s.status = LessonStatus.completed
    s.completed_at = utcnow()
    record_lesson_completed(db, user.id, str(s.selected_skill))
    return _screen(svc, db, user, s, note)


# --- views (participant-facing; internal codes never included) ----------------------------------


def message_view(m: ChatMessage) -> dict[str, Any]:
    return {
        "seq": m.seq,
        "role": m.role.value,
        "content": m.content,
        "question": m.question,
        "source": m.source.value if m.source else None,
    }


def session_view(db: Session, svc: Services, s: TeachingSession) -> dict[str, Any]:
    lang = s.language
    inquiry = _json(s.inquiry)
    rec = _json(s.recommendation)
    summary = _json(s.summary)

    def skill(sid: str | None) -> dict[str, str] | None:
        if not sid:
            return None
        return {
            "id": sid,
            "name": svc.ai.skill_name(sid, lang) or sid,
            "module": svc.ai.module_name(svc.ai.skill_module.get(sid), lang),
        }

    from app.learning.testing import tests_view  # local import: testing imports teaching

    return {
        "id": str(s.id),
        "phase": s.phase.value,
        "status": s.status.value,
        "source": s.source.value if s.source else None,
        "language": lang,
        "started_at": s.started_at.isoformat(),
        "completed_at": s.completed_at.isoformat() if s.completed_at else None,
        "checkin": {
            "greeting": inquiry.get("greeting", ""),
            "question": inquiry.get("question", ""),
            "source": inquiry.get("source"),
            "skipped": s.checkin_skipped,
        }
        if inquiry
        else None,
        "recommendation": {
            "skill": skill(rec.get("skill")),
            "reason": rec.get("reason", ""),
            "alternatives": [skill(a) for a in rec.get("alternatives", [])],
            "is_repeat": bool(rec.get("is_repeat")),
            "source": rec.get("source"),
        }
        if rec
        else None,
        "skill": skill(s.selected_skill),
        "plan": [
            {"title": st.get("title", ""), "minutes": st.get("estimated_minutes")}
            for st in _plan_steps(s)
        ],
        "plan_source": (s.plan or {}).get("source"),
        "messages": [message_view(m) for m in _messages(db, s)],
        "summary": {
            "summary_text": summary.get("summary_text", ""),
            "key_points": summary.get("key_points", []),
            "recommendations": summary.get("recommendations", []),
            "source": summary.get("source"),
        }
        if summary
        else None,
        "busy": bool(s.busy_until and s.busy_until > utcnow()),
        "tests": tests_view(db, s),
    }
