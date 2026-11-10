"""Adolescent skill test (Plan §5.5.1 step 7; ported from DBT_Revised `testing/`).

- Five scenario-based multiple-choice questions per attempt (`generate_skill_test`; the output
  schema rejects anything but exactly five).
- Generation runs as an in-process background task; the client polls the status.
- Retry-state handling: a generation failure leaves the test `generating` while attempts remain
  and only becomes `unavailable` after the last one. It is never marked terminated by a failed
  attempt (the DBT_Revised Celery task set USER_TERMINATED on the first failed retry).
- One question at a time, immediate correct / not-quite + explanation.
- Mastery at >= 4 of 5 (DBT_Revised pass rule). Participants see "You've got it" or "Worth
  another look", never a score. Retakes add an attempt informed by the previous ones.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import bad_request, conflict, not_found
from app.core.logging import get_logger
from app.core.sessions import utcnow
from app.learning import profile as profile_mod
from app.learning.progress import record_test
from app.models import (
    LearnerProfile,
    LessonStatus,
    MoodKind,
    MoodRecord,
    SkillTest,
    SkillTestQuestion,
    SkillTestStatus,
    TeachingSession,
    User,
)
from app.settings import get_settings

log = get_logger(__name__)

QUESTIONS = 5  # fixed by the AI output schema (SkillTestOut.questions)
MAX_GENERATION_ATTEMPTS = 3
RETRY_DELAYS = (0.0, 2.0, 5.0)  # seconds before attempt 1, 2, 3 (patched to 0 in tests)
OPEN = (SkillTestStatus.generating, SkillTestStatus.ready)


def is_mastered(correct: int) -> bool:
    return correct >= get_settings().skill_test_mastery_correct


def get_owned(db: Session, user: User, test_id: uuid.UUID) -> SkillTest:
    t = db.get(SkillTest, test_id)
    if t is None or t.user_id != user.id:
        raise not_found("test.not_found")
    return t


def create(db: Session, user: User, s: TeachingSession) -> tuple[SkillTest, bool]:
    """Start an attempt (or return the open one). Returns (test, needs_generation)."""
    if s.status is not LessonStatus.completed or not s.selected_skill:
        raise conflict("test.lesson_not_completed")
    current = db.scalar(
        select(SkillTest)
        .where(SkillTest.session_id == s.id, SkillTest.status.in_(OPEN))
        .order_by(SkillTest.attempt_no.desc())
    )
    if current is not None:
        return current, False
    n = (
        db.scalar(select(func.max(SkillTest.attempt_no)).where(SkillTest.session_id == s.id)) or 0
    ) + 1
    t = SkillTest(session_id=s.id, user_id=user.id, attempt_no=n, status=SkillTestStatus.generating)
    db.add(t)
    try:
        db.flush()
    except IntegrityError as exc:
        raise conflict("test.state_changed") from exc
    return t, True


def _inputs(db: Session, t: SkillTest) -> dict[str, Any]:
    s = db.get(TeachingSession, t.session_id)
    assert s is not None
    summary = json.loads(s.summary) if s.summary else {}
    previous = list(
        db.scalars(
            select(SkillTest)
            .where(SkillTest.session_id == s.id, SkillTest.attempt_no < t.attempt_no)
            .order_by(SkillTest.attempt_no)
        )
    )
    prev_questions = [
        q.question
        for p in previous
        for q in db.scalars(
            select(SkillTestQuestion)
            .where(SkillTestQuestion.test_id == p.id)
            .order_by(SkillTestQuestion.position)
        )
    ]
    return {
        "profile": profile_mod.for_ai(db.get(LearnerProfile, t.user_id)),
        "skill_id": s.selected_skill,
        "key_points": list(summary.get("key_points") or [])[:5],
        "attempt": min(t.attempt_no, 20),
        "previous_scores": [
            p.correct_count for p in previous if p.status is SkillTestStatus.completed
        ][-20:],
        "previous_questions": [q[:200] for q in prev_questions][-25:],
    }


def generate(
    session_factory: Callable[[], Session],
    ai: Any,
    test_id: uuid.UUID,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Background task: generate the questions, retrying; never raises."""
    for attempt in range(1, MAX_GENERATION_ATTEMPTS + 1):
        delay = RETRY_DELAYS[min(attempt - 1, len(RETRY_DELAYS) - 1)]
        if delay:
            sleep(delay)
        with session_factory() as db:
            t = db.get(SkillTest, test_id)
            if t is None or t.status is not SkillTestStatus.generating:
                return  # stopped by the student meanwhile
            s = db.get(TeachingSession, t.session_id)
            ok = False
            try:
                res = ai.run(
                    db,
                    "generate_skill_test",
                    _inputs(db, t),
                    role="adolescent",
                    language=s.language if s else "zh-CN",
                    caller="lesson.test",
                    actor_id=t.user_id,
                    use_cache=False,
                )
                questions = list((res.output or {}).get("questions") or [])
                if len(questions) == QUESTIONS:
                    for i, q in enumerate(questions, start=1):
                        db.add(
                            SkillTestQuestion(
                                test_id=t.id,
                                position=i,
                                scenario=q["scenario_text"],
                                question=q["question_text"],
                                options=list(q["options"]),
                                correct_index=int(q["correct_option"]),
                                explanation=q["explanation"],
                            )
                        )
                    t.total_questions = QUESTIONS
                    t.source = res.source
                    ok = True
            except Exception:
                log.exception("test.generation_error", test_id=str(test_id), attempt=attempt)
                db.rollback()
                t = db.get(SkillTest, test_id)
                if t is None:
                    return
            final = ok or attempt >= MAX_GENERATION_ATTEMPTS
            status = (
                SkillTestStatus.ready
                if ok
                else (SkillTestStatus.unavailable if final else SkillTestStatus.generating)
            )
            values: dict[str, Any] = {"generation_attempts": attempt, "status": status}
            if ok:
                values.update(total_questions=QUESTIONS, source=t.source)
            # Only a still-generating test changes (the student may have stopped it meanwhile).
            res = db.execute(
                update(SkillTest)
                .where(SkillTest.id == test_id, SkillTest.status == SkillTestStatus.generating)
                .values(**values)
                .execution_options(synchronize_session=False)
            )
            if res.rowcount != 1:  # type: ignore[attr-defined]
                db.rollback()
                return
            db.commit()
            if final:
                return


def answer(
    db: Session, user: User, t: SkillTest, position: int, answer_index: int
) -> dict[str, Any]:
    if t.status is not SkillTestStatus.ready:
        raise conflict("test.not_ready")
    if not 0 <= answer_index <= 3:
        raise bad_request("test.bad_answer")
    q = db.scalar(
        select(SkillTestQuestion).where(
            SkillTestQuestion.test_id == t.id, SkillTestQuestion.position == position
        )
    )
    if q is None:
        raise not_found("test.question_not_found")
    nxt = db.scalar(
        select(func.min(SkillTestQuestion.position)).where(
            SkillTestQuestion.test_id == t.id, SkillTestQuestion.answer_index.is_(None)
        )
    )
    if q.answer_index is None and nxt != position:
        raise conflict("test.out_of_order")
    if q.answer_index is None:
        res = db.execute(
            update(SkillTestQuestion)
            .where(SkillTestQuestion.id == q.id, SkillTestQuestion.answer_index.is_(None))
            .values(
                answer_index=answer_index,
                is_correct=answer_index == q.correct_index,
                answered_at=func.now(),
            )
            .execution_options(synchronize_session=False)
        )
        if res.rowcount != 1:  # type: ignore[attr-defined]
            raise conflict("test.state_changed")
        db.refresh(q)
    remaining = db.scalar(
        select(func.count()).where(
            SkillTestQuestion.test_id == t.id, SkillTestQuestion.answer_index.is_(None)
        )
    )
    if remaining == 0 and t.status is SkillTestStatus.ready:
        _complete(db, t)
    return {"question": question_view(q), "test": test_view(db, t)}


def _complete(db: Session, t: SkillTest) -> None:
    res = db.execute(
        update(SkillTest)
        .where(SkillTest.id == t.id, SkillTest.status == SkillTestStatus.ready)
        .values(status=SkillTestStatus.completed, completed_at=func.now())
        .execution_options(synchronize_session=False)
    )
    if res.rowcount != 1:  # type: ignore[attr-defined]
        return
    db.refresh(t)
    correct = db.scalar(
        select(func.count()).where(
            SkillTestQuestion.test_id == t.id, SkillTestQuestion.is_correct.is_(True)
        )
    )
    t.correct_count = int(correct or 0)
    t.mastered = is_mastered(t.correct_count)
    s = db.get(TeachingSession, t.session_id)
    if s is not None and s.selected_skill:
        record_test(db, t.user_id, s.selected_skill, t.mastered)


def stop(db: Session, t: SkillTest) -> None:
    res = db.execute(
        update(SkillTest)
        .where(SkillTest.id == t.id, SkillTest.status.in_(OPEN))
        .values(status=SkillTestStatus.user_terminated, completed_at=func.now())
        .execution_options(synchronize_session=False)
    )
    if res.rowcount != 1:  # type: ignore[attr-defined]
        raise conflict("test.closed")
    db.refresh(t)


def record_mood(db: Session, user: User, t: SkillTest, value: int, note: str | None) -> None:
    if t.status is not SkillTestStatus.completed:
        raise conflict("test.not_completed")
    if t.post_mood_id is not None:
        raise conflict("test.mood_recorded")
    mood = MoodRecord(
        user_id=user.id,
        kind=MoodKind.after_testing,
        value=value,
        note=note,
        session_id=t.session_id,
        test_id=t.id,
    )
    db.add(mood)
    db.flush()
    t.post_mood_id = mood.id


# --- views ---


def outcome(t: SkillTest) -> str | None:
    """got_it | another_look (participant wording); None until completed."""
    if t.status is not SkillTestStatus.completed:
        return None
    return "got_it" if t.mastered else "another_look"


def question_view(q: SkillTestQuestion) -> dict[str, Any]:
    answered = q.answer_index is not None
    return {
        "position": q.position,
        "scenario": q.scenario,
        "question": q.question,
        "options": list(q.options),
        "answer_index": q.answer_index,
        "is_correct": q.is_correct,
        "correct_index": q.correct_index if answered else None,
        "explanation": q.explanation if answered else None,
    }


def test_view(db: Session, t: SkillTest, *, questions: bool = True) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": str(t.id),
        "session_id": str(t.session_id),
        "attempt_no": t.attempt_no,
        "status": t.status.value,
        "source": t.source.value if t.source else None,
        "outcome": outcome(t),
        "mood_recorded": t.post_mood_id is not None,
        "created_at": t.created_at.isoformat() if t.created_at else utcnow().isoformat(),
    }
    if questions:
        out["questions"] = [
            question_view(q)
            for q in db.scalars(
                select(SkillTestQuestion)
                .where(SkillTestQuestion.test_id == t.id)
                .order_by(SkillTestQuestion.position)
            )
        ]
    return out


def tests_view(db: Session, s: TeachingSession) -> list[dict[str, Any]]:
    return [
        test_view(db, t, questions=False)
        for t in db.scalars(
            select(SkillTest).where(SkillTest.session_id == s.id).order_by(SkillTest.attempt_no)
        )
    ]
