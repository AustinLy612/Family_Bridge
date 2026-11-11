"""Caregiver structured lessons (Plan §5.5.2, D8/D23 — provisional).

explain -> practice -> quiz -> wrap_up -> done. Every step can be skipped; pausing is leaving
(D56). Generated, non-personal content (explanation, practice items, quiz) is snapshotted on
the lesson so a resumed lesson shows the same text. Free text (practice answers, reflection) is
risk-screened before evaluation (Plan §5.5.2 step 7) and stored encrypted.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import bad_request, conflict, not_found
from app.core.sessions import utcnow
from app.learning.progress import record_caregiver_lesson
from app.learning.references import references
from app.learning.teaching import Services
from app.models import (
    CaregiverLesson,
    CaregiverStep,
    GroupSkillRecord,
    LessonSource,
    LessonStatus,
    PracticeAttempt,
    QuizAttempt,
    User,
)
from app.safety.service import Context, SafetyOutcome

S = CaregiverStep
MAX_PRACTICE_ATTEMPTS = 2  # "second opportunity" (§6.3)
UNDERSTOOD_RATIO = 2 / 3
NEXT = {S.explain: S.practice, S.practice: S.quiz, S.quiz: S.wrap_up}
VARIANTS = ("standard", "simpler", "another_example")


def source_ref(c: CaregiverLesson) -> str:
    return f"caregiver_lesson:{c.id}"


def get_owned(db: Session, user: User, lesson_id: uuid.UUID) -> CaregiverLesson:
    c = db.get(CaregiverLesson, lesson_id)
    if c is None or c.user_id != user.id:
        raise not_found("lesson.not_found")
    return follow_language(c, user)


def follow_language(c: CaregiverLesson, user: User) -> CaregiverLesson:
    """An open lesson follows the learner's current language for the steps still to come."""
    if c.status == LessonStatus.ongoing and c.language != user.language:
        c.language = user.language
    return c


def open_lesson(db: Session, user: User) -> CaregiverLesson | None:
    c = db.scalar(
        select(CaregiverLesson).where(
            CaregiverLesson.user_id == user.id, CaregiverLesson.status == LessonStatus.ongoing
        )
    )
    return follow_language(c, user) if c else None


def _ensure_ongoing(c: CaregiverLesson) -> None:
    if c.status is not LessonStatus.ongoing:
        raise conflict("lesson.closed")


def _claim(db: Session, c: CaregiverLesson, expected: CaregiverStep, to: CaregiverStep) -> None:
    res = db.execute(
        update(CaregiverLesson)
        .where(
            CaregiverLesson.id == c.id,
            CaregiverLesson.step == expected,
            CaregiverLesson.status == LessonStatus.ongoing,
        )
        .values(step=to, last_active_at=func.now())
        .execution_options(synchronize_session=False)
    )
    if res.rowcount != 1:  # type: ignore[attr-defined]
        raise conflict("lesson.state_changed")
    db.refresh(c)


def _explain(svc: Services, db: Session, user: User, c: CaregiverLesson, variant: str) -> None:
    res = svc.ai.run(
        db,
        "explain_skill",
        {"skill_id": c.skill_id, "variant": variant},
        role="caregiver",
        language=c.language,
        caller="caregiver.explain",
        actor_id=user.id,
    )
    out = res.output or {}
    c.variant = variant
    c.explanation = {
        "title": out.get("title", ""),
        "summary": out.get("summary") or res.notice or "",
        "key_points": list(out.get("key_points") or []),
        "everyday_example": out.get("everyday_example", ""),
        "check_question": out.get("check_question", ""),
        "source": res.source.value,
        "grounding": res.grounding,
        "references": references(db, svc.ai, res.sources, c.language),
    }


def start(
    svc: Services,
    db: Session,
    user: User,
    skill_id: str,
    *,
    group_record: GroupSkillRecord | None = None,
) -> CaregiverLesson:
    if skill_id not in svc.ai.skill_module:
        raise bad_request("lesson.unknown_skill")
    if group_record is not None and skill_id not in group_record.skill_ids:
        raise bad_request("lesson.skill_not_in_record")
    if open_lesson(db, user) is not None:
        raise conflict("lesson.open_exists")
    c = CaregiverLesson(
        user_id=user.id,
        language=user.language,
        skill_id=skill_id,
        source=LessonSource.group_review if group_record else LessonSource.explore,
        group_record_id=group_record.id if group_record else None,
        step=S.explain,
    )
    db.add(c)
    try:
        db.flush()
    except IntegrityError as exc:
        raise conflict("lesson.open_exists") from exc
    _explain(svc, db, user, c, "standard")
    return c


def adapt(svc: Services, db: Session, user: User, c: CaregiverLesson, variant: str) -> None:
    """Bounded adaptation buttons: "Explain more simply" / "Another example"."""
    _ensure_ongoing(c)
    if variant not in VARIANTS:
        raise bad_request("lesson.bad_variant")
    if c.step is not S.explain:
        raise conflict("lesson.state_changed")
    _explain(svc, db, user, c, variant)
    c.last_active_at = utcnow()


def advance(svc: Services, db: Session, user: User, c: CaregiverLesson, expected: str) -> None:
    """Next or Skip: both move on; nothing is marked as missed."""
    _ensure_ongoing(c)
    try:
        frm = CaregiverStep(expected)
    except ValueError as exc:
        raise bad_request("lesson.bad_step") from exc
    to = NEXT.get(frm)
    if to is None:
        raise conflict("lesson.state_changed")
    _claim(db, c, frm, to)
    if to is S.practice and c.items is None:
        res = svc.ai.run(
            db,
            "generate_practice_items",
            {"skill_id": c.skill_id},
            role="caregiver",
            language=c.language,
            caller="caregiver.practice",
            actor_id=user.id,
        )
        c.items = {"items": list((res.output or {}).get("items") or []), "source": res.source.value}
    if to is S.quiz and c.quiz is None:
        res = svc.ai.run(
            db,
            "generate_quiz",
            {"skill_id": c.skill_id},
            role="caregiver",
            language=c.language,
            caller="caregiver.quiz",
            actor_id=user.id,
        )
        c.quiz = {
            "questions": list((res.output or {}).get("questions") or []),
            "source": res.source.value,
        }


def _items(c: CaregiverLesson) -> list[dict[str, Any]]:
    return list((c.items or {}).get("items") or [])


def practise(
    svc: Services,
    db: Session,
    user: User,
    c: CaregiverLesson,
    item_index: int,
    *,
    option_index: int | None,
    text: str | None,
) -> tuple[dict[str, Any] | None, SafetyOutcome | None]:
    _ensure_ongoing(c)
    if c.step is not S.practice:
        raise conflict("lesson.state_changed")
    items = _items(c)
    if not 0 <= item_index < len(items):
        raise not_found("lesson.item_not_found")
    item = items[item_index]
    done = db.scalar(
        select(func.count()).where(
            PracticeAttempt.lesson_id == c.id, PracticeAttempt.item_index == item_index
        )
    )
    if (done or 0) >= MAX_PRACTICE_ATTEMPTS:
        raise conflict("lesson.no_more_attempts")
    rubric: str | None = None
    if item["answer_mode"] == "choice":
        opts = item.get("options") or []
        if option_index is None or not 0 <= option_index < len(opts):
            raise bad_request("lesson.bad_answer")
        answer = str(opts[option_index]["text"])
        rubric = str(opts[option_index]["rubric_tag"])
    else:
        answer = (text or "").strip()
        if not answer:
            raise bad_request("lesson.empty_message")
        if len(answer) > svc.ai.settings.lesson_message_max_chars:
            raise bad_request("lesson.message_too_long")
    outcome: SafetyOutcome | None = None
    if rubric is None:  # free text is screened before evaluation
        outcome = svc.safety.screen_text(db, user, Context.lesson, answer, source_ref=source_ref(c))
        if outcome.should_stop:
            _stop(db, c, LessonStatus.stopped_by_safety)
            return None, outcome
    res = svc.ai.run(
        db,
        "evaluate_practice_answer",
        {
            "skill_id": c.skill_id,
            "item": {
                "scenario": item["scenario"],
                "prompt": item["prompt"],
                "answer_mode": item["answer_mode"],
                "options": [o["text"] for o in item.get("options") or []],
            },
            "answer": answer,
            "rubric_tag": rubric,
        },
        role="caregiver",
        language=c.language,
        caller="caregiver.evaluate",
        actor_id=user.id,
        use_cache=False,
    )
    out = res.output or {}
    attempt_no = (done or 0) + 1
    feedback = {
        "what_worked": out.get("what_worked") or res.notice or "",
        "why": out.get("why", ""),
        "try_next": out.get("try_next", ""),
    }
    db.add(
        PracticeAttempt(
            lesson_id=c.id,
            item_index=item_index,
            attempt_no=attempt_no,
            answer=answer,
            category=str(out.get("category") or rubric or "unrated")[:40],
            feedback=json.dumps(feedback, ensure_ascii=False),
            source=res.source,
        )
    )
    try:
        db.flush()
    except IntegrityError as exc:
        raise conflict("lesson.state_changed") from exc
    c.last_active_at = utcnow()
    return {
        **feedback,
        "attempt_no": attempt_no,
        "can_retry": attempt_no < MAX_PRACTICE_ATTEMPTS and bool(out.get("allow_retry", True)),
        "source": res.source.value,
    }, outcome


def answer_quiz(
    db: Session, c: CaregiverLesson, question_index: int, answer_index: int
) -> dict[str, Any]:
    _ensure_ongoing(c)
    if c.step is not S.quiz:
        raise conflict("lesson.state_changed")
    questions = list((c.quiz or {}).get("questions") or [])
    if not 0 <= question_index < len(questions):
        raise not_found("lesson.item_not_found")
    q = questions[question_index]
    if not 0 <= answer_index < len(q["options"]):
        raise bad_request("lesson.bad_answer")
    existing = db.scalar(
        select(QuizAttempt).where(
            QuizAttempt.lesson_id == c.id, QuizAttempt.question_index == question_index
        )
    )
    if existing is None:
        existing = QuizAttempt(
            lesson_id=c.id,
            question_index=question_index,
            answer_index=answer_index,
            is_correct=answer_index == int(q["correct_index"]),
        )
        db.add(existing)
        try:
            db.flush()
        except IntegrityError as exc:
            raise conflict("lesson.state_changed") from exc
    return {
        "question_index": question_index,
        "answer_index": existing.answer_index,
        "is_correct": existing.is_correct,
        "correct_index": int(q["correct_index"]),
        "explanation": q["explanation"],
    }


def quiz_outcome(db: Session, c: CaregiverLesson) -> str:
    rows = list(db.scalars(select(QuizAttempt).where(QuizAttempt.lesson_id == c.id)))
    if not rows:
        return "practised"
    ratio = sum(1 for r in rows if r.is_correct) / len(rows)
    return "understood" if ratio >= UNDERSTOOD_RATIO else "worth_revisiting"


def finish(
    svc: Services, db: Session, user: User, c: CaregiverLesson, reflection: str | None
) -> SafetyOutcome | None:
    """Wrap-up: optional, private reflection; then the lesson is complete."""
    _ensure_ongoing(c)
    text = (reflection or "").strip() or None
    if text and len(text) > svc.ai.settings.lesson_message_max_chars:
        raise bad_request("lesson.message_too_long")
    _claim(db, c, S.wrap_up, S.done)
    outcome: SafetyOutcome | None = None
    if text:
        outcome = svc.safety.screen_text(db, user, Context.lesson, text, source_ref=source_ref(c))
        if outcome.should_stop:
            _stop(db, c, LessonStatus.stopped_by_safety)
            return outcome
    c.reflection = text
    c.reflection_skipped = text is None
    c.status = LessonStatus.completed
    c.completed_at = utcnow()
    categories = list(
        db.scalars(select(PracticeAttempt.category).where(PracticeAttempt.lesson_id == c.id))
    )
    record_caregiver_lesson(
        db, user.id, c.skill_id, quiz_outcome=quiz_outcome(db, c), categories=categories
    )
    return outcome


def _stop(db: Session, c: CaregiverLesson, status: LessonStatus) -> None:
    res = db.execute(
        update(CaregiverLesson)
        .where(CaregiverLesson.id == c.id, CaregiverLesson.status == LessonStatus.ongoing)
        .values(status=status, completed_at=func.now())
        .execution_options(synchronize_session=False)
    )
    if res.rowcount != 1:  # type: ignore[attr-defined]
        raise conflict("lesson.closed")
    db.refresh(c)


def stop(db: Session, c: CaregiverLesson) -> None:
    _stop(db, c, LessonStatus.user_terminated)


# --- view (participant-facing; rubric tags never included) ---------------------------------------


def lesson_view(db: Session, svc: Services, c: CaregiverLesson) -> dict[str, Any]:
    lang = c.language
    attempts = list(
        db.scalars(
            select(PracticeAttempt)
            .where(PracticeAttempt.lesson_id == c.id)
            .order_by(PracticeAttempt.item_index, PracticeAttempt.attempt_no)
        )
    )
    quiz_rows = {
        r.question_index: r
        for r in db.scalars(select(QuizAttempt).where(QuizAttempt.lesson_id == c.id))
    }
    items = []
    for i, it in enumerate(_items(c)):
        mine = [a for a in attempts if a.item_index == i]
        items.append(
            {
                "scenario": it["scenario"],
                "prompt": it["prompt"],
                "answer_mode": it["answer_mode"],
                "options": [o["text"] for o in it.get("options") or []],
                "attempts": [
                    {
                        "attempt_no": a.attempt_no,
                        "answer": a.answer,
                        "feedback": json.loads(a.feedback),
                        "source": a.source.value,
                    }
                    for a in mine
                ],
                "can_retry": len(mine) < MAX_PRACTICE_ATTEMPTS,
            }
        )
    questions = []
    for i, q in enumerate((c.quiz or {}).get("questions") or []):
        row = quiz_rows.get(i)
        questions.append(
            {
                "stem": q["stem"],
                "options": q["options"],
                "answer_index": row.answer_index if row else None,
                "is_correct": row.is_correct if row else None,
                "correct_index": q["correct_index"] if row else None,
                "explanation": q["explanation"] if row else None,
            }
        )
    done = c.status is LessonStatus.completed
    return {
        "id": str(c.id),
        "kind": "caregiver",
        "step": c.step.value,
        "status": c.status.value,
        "source": c.source.value,
        "language": lang,
        "skill": {
            "id": c.skill_id,
            "name": svc.ai.skill_name(c.skill_id, lang) or c.skill_id,
            "module": svc.ai.module_name(svc.ai.skill_module.get(c.skill_id), lang),
        },
        "variant": c.variant,
        "explanation": c.explanation,
        "practice": {"items": items, "source": (c.items or {}).get("source")} if c.items else None,
        "quiz": {"questions": questions, "source": (c.quiz or {}).get("source")}
        if c.quiz
        else None,
        "outcome": quiz_outcome(db, c) if done else None,
        "reflection": c.reflection,
        "started_at": c.started_at.isoformat(),
        "completed_at": c.completed_at.isoformat() if c.completed_at else None,
    }
