"""Individual skill learning API (Plan §5.5; Phase 5).

Adolescents: profile questionnaire, the teaching process (SSE chat), skill tests.
Caregivers: structured lessons. Both: skills list, group review, progress, past lessons (D57).
Therapists: group skill records (D24; minimal here, completed in Phase 7).

Everything a participant reads here is their own; nothing is visible to other family members.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import date
from typing import Annotated, Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.deps import Db, OnboardedUser, StaffUser, require_roles
from app.core import audit
from app.core.errors import bad_request, forbidden, not_found
from app.core.policy import audit_read, ensure_group
from app.core.sessions import utcnow
from app.learning import caregiver as cg
from app.learning import profile as prof
from app.learning import teaching as tc
from app.learning import testing as ts
from app.learning.progress import history_view, progress_view
from app.models import (
    CaregiverLesson,
    GroupSkillRecord,
    LearnerProfile,
    Role,
    TeachingSession,
    User,
)
from app.safety.events import family_of
from app.safety.service import Context, SafetyOutcome

router = APIRouter(prefix="/api/v1", tags=["learning"])

AdolescentUser = Annotated[User, Depends(require_roles(Role.adolescent))]
CaregiverUser = Annotated[User, Depends(require_roles(Role.caregiver))]
ParticipantUser = Annotated[User, Depends(require_roles(Role.adolescent, Role.caregiver))]


def _svc(request: Request) -> tc.Services:
    return tc.Services(request.app.state.ai, request.app.state.safety)


Svc = Annotated[tc.Services, Depends(_svc)]


def _safety(outcome: SafetyOutcome | None) -> str:
    return outcome.action if outcome is not None else "none"


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MoodIn(Strict):
    value: int = Field(ge=1, le=5)
    note: str | None = Field(default=None, max_length=2000)


# --- skills ---


@router.get("/learn/skills")
def skills(user: OnboardedUser, svc: Svc) -> dict[str, Any]:
    tax = svc.ai.taxonomy
    lang = user.language
    return {
        "modules": [
            {
                "id": m.id,
                "name": svc.ai.module_name(m.id, lang),
                "skills": [
                    {"id": s.id, "name": svc.ai.skill_name(s.id, lang) or s.id} for s in m.skills
                ],
            }
            for m in (tax.modules if tax else [])
        ]
    }


def _names(svc: tc.Services, lang: str) -> Any:
    def names(sid: str) -> tuple[str, str, str]:
        mid = svc.ai.skill_module.get(sid, "")
        return svc.ai.skill_name(sid, lang) or sid, mid, svc.ai.module_name(mid, lang)

    return names


# --- profile questionnaire (adolescents) ---


@router.get("/learn/profile")
def get_profile(user: AdolescentUser, db: Db) -> dict[str, Any]:
    p = db.get(LearnerProfile, user.id)
    return {
        "profile": prof.ProfileOut.of(p).model_dump() if p else None,
        "options": prof.ProfileOptions().model_dump(),
    }


@router.put("/learn/profile")
def put_profile(body: prof.ProfileIn, user: AdolescentUser, db: Db) -> dict[str, Any]:
    p = db.get(LearnerProfile, user.id)
    created = p is None
    if p is None:
        p = LearnerProfile(user_id=user.id)
        db.add(p)
    for k, v in body.model_dump().items():
        setattr(p, k, v)
    p.updated_at = utcnow()
    db.flush()
    audit.record(
        db,
        "learner_profile.created" if created else "learner_profile.updated",
        actor=user,
        target_type="user",
        target_id=user.id,
    )
    return {
        "profile": prof.ProfileOut.of(p).model_dump(),
        "options": prof.ProfileOptions().model_dump(),
    }


# --- adolescent teaching process ---


class StartIn(Strict):
    group_record_id: uuid.UUID | None = None
    skill_id: str | None = Field(default=None, max_length=60)


def _record_for(db: Db, user: User, record_id: uuid.UUID) -> GroupSkillRecord:
    rec = db.get(GroupSkillRecord, record_id)
    member = family_of(db, user)
    if rec is None or member is None or rec.group_id != member.family.group_id:
        raise not_found("group_review.not_found")
    return rec


def _lesson_out(
    db: Db, svc: tc.Services, s: TeachingSession, outcome: SafetyOutcome | None = None
) -> dict[str, Any]:
    return {"lesson": tc.session_view(db, svc, s), "safety": _safety(outcome)}


@router.get("/learn/sessions/current")
def current_session(user: AdolescentUser, db: Db, svc: Svc) -> dict[str, Any]:
    s = tc.open_session(db, user)
    return {"lesson": tc.session_view(db, svc, s) if s else None}


@router.post("/learn/sessions", status_code=201)
def start_session(body: StartIn, user: AdolescentUser, db: Db, svc: Svc) -> dict[str, Any]:
    if db.get(LearnerProfile, user.id) is None:
        raise bad_request("lesson.profile_required")
    rec = _record_for(db, user, body.group_record_id) if body.group_record_id else None
    s = tc.start(db, user, group_record=rec, skill_id=body.skill_id)
    return _lesson_out(db, svc, s)


@router.get("/learn/sessions/{session_id}")
def get_session(session_id: uuid.UUID, user: AdolescentUser, db: Db, svc: Svc) -> dict[str, Any]:
    s = tc.get_owned(db, user, session_id)
    tc.refresh_for_language(svc, db, user, s)
    return _lesson_out(db, svc, s)


@router.post("/learn/sessions/{session_id}/mood")
def pre_mood(
    session_id: uuid.UUID, body: MoodIn, user: AdolescentUser, db: Db, svc: Svc
) -> dict[str, Any]:
    s = tc.get_owned(db, user, session_id)
    outcome = tc.record_pre_mood(svc, db, user, s, body.value, body.note)
    return _lesson_out(db, svc, s, outcome)


class CheckinIn(Strict):
    answer: str | None = Field(default=None, max_length=2000)
    skip: bool = False  # "Skip" and "Just pick a skill for me" both skip (D22)


@router.post("/learn/sessions/{session_id}/checkin")
def checkin(
    session_id: uuid.UUID, body: CheckinIn, user: AdolescentUser, db: Db, svc: Svc
) -> dict[str, Any]:
    s = tc.get_owned(db, user, session_id)
    outcome = tc.answer_checkin(svc, db, user, s, None if body.skip else body.answer)
    return _lesson_out(db, svc, s, outcome)


class ChooseIn(Strict):
    skill_id: str = Field(max_length=60)
    choice: Literal["recommended", "alternative", "chosen"]


@router.post("/learn/sessions/{session_id}/choose")
def choose(
    session_id: uuid.UUID, body: ChooseIn, user: AdolescentUser, db: Db, svc: Svc
) -> dict[str, Any]:
    s = tc.get_owned(db, user, session_id)
    tc.choose_skill(svc, db, user, s, body.skill_id, body.choice)
    return _lesson_out(db, svc, s)


class MessageIn(Strict):
    message: str = Field(min_length=1, max_length=2000)


_SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


@router.post("/learn/sessions/{session_id}/messages")
def send_message(
    session_id: uuid.UUID,
    body: MessageIn,
    request: Request,
    user: AdolescentUser,
    db: Db,
    svc: Svc,
) -> Response:
    """Server-sent events: `safety`, `delta`, `replace`, `final`, `error`."""
    s = tc.get_owned(db, user, session_id)
    outcome = tc.begin_turn(svc, db, user, s, body.message)
    db.commit()
    if outcome is not None and outcome.should_stop:
        return StreamingResponse(
            iter([tc._sse("safety", {"action": "stop"})]),
            media_type="text/event-stream",
            headers=_SSE_HEADERS,
        )
    first = [tc._sse("safety", {"action": "care_card"})] if _safety(outcome) == "care_card" else []
    factory = request.app.state.session_factory
    user_id = user.id

    def body_iter() -> Iterator[str]:
        yield from first
        with factory() as sdb:
            me = sdb.get(User, user_id)
            assert me is not None
            yield from tc.stream_turn(svc, sdb, me, session_id)

    return StreamingResponse(body_iter(), media_type="text/event-stream", headers=_SSE_HEADERS)


@router.post("/learn/sessions/{session_id}/end")
def end(session_id: uuid.UUID, user: AdolescentUser, db: Db, svc: Svc) -> dict[str, Any]:
    s = tc.get_owned(db, user, session_id)
    tc.end_lesson(svc, db, user, s)
    return _lesson_out(db, svc, s)


@router.post("/learn/sessions/{session_id}/post-mood")
def post_mood(
    session_id: uuid.UUID, body: MoodIn, user: AdolescentUser, db: Db, svc: Svc
) -> dict[str, Any]:
    s = tc.get_owned(db, user, session_id)
    outcome = tc.record_post_mood(svc, db, user, s, body.value, body.note)
    return _lesson_out(db, svc, s, outcome)


@router.post("/learn/sessions/{session_id}/stop")
def stop_session(session_id: uuid.UUID, user: AdolescentUser, db: Db, svc: Svc) -> dict[str, Any]:
    s = tc.get_owned(db, user, session_id)
    tc.stop(db, user, s)
    return _lesson_out(db, svc, s)


# --- skill tests ---


@router.post("/learn/sessions/{session_id}/tests", status_code=201)
def start_test(
    session_id: uuid.UUID,
    request: Request,
    background: BackgroundTasks,
    user: AdolescentUser,
    db: Db,
) -> dict[str, Any]:
    s = tc.get_owned(db, user, session_id)
    t, generate = ts.create(db, user, s)
    if generate:
        db.commit()  # the background task reads the row from its own session
        background.add_task(
            ts.generate, request.app.state.session_factory, request.app.state.ai, t.id
        )
    return {"test": ts.test_view(db, t)}


@router.get("/learn/tests/{test_id}")
def get_test(test_id: uuid.UUID, user: AdolescentUser, db: Db) -> dict[str, Any]:
    return {"test": ts.test_view(db, ts.get_owned(db, user, test_id))}


class AnswerIn(Strict):
    position: int = Field(ge=1, le=ts.QUESTIONS)
    answer_index: int = Field(ge=0, le=3)


@router.post("/learn/tests/{test_id}/answers")
def answer_test(test_id: uuid.UUID, body: AnswerIn, user: AdolescentUser, db: Db) -> dict[str, Any]:
    t = ts.get_owned(db, user, test_id)
    return ts.answer(db, user, t, body.position, body.answer_index)


@router.post("/learn/tests/{test_id}/mood")
def test_mood(
    test_id: uuid.UUID, body: MoodIn, user: AdolescentUser, db: Db, svc: Svc
) -> dict[str, Any]:
    t = ts.get_owned(db, user, test_id)
    note = (body.note or "").strip() or None
    if note and len(note) > svc.ai.settings.lesson_message_max_chars:
        raise bad_request("lesson.message_too_long")
    ts.record_mood(db, user, t, body.value, note)
    outcome = None
    if note:
        s = db.get(TeachingSession, t.session_id)
        assert s is not None
        outcome = svc.safety.screen_text(
            db, user, Context.lesson, note, source_ref=tc.source_ref(s)
        )
    return {"test": ts.test_view(db, t), "safety": _safety(outcome)}


@router.post("/learn/tests/{test_id}/stop")
def stop_test(test_id: uuid.UUID, user: AdolescentUser, db: Db) -> dict[str, Any]:
    t = ts.get_owned(db, user, test_id)
    ts.stop(db, t)
    return {"test": ts.test_view(db, t)}


# --- caregiver structured lessons ---


class CaregiverStartIn(Strict):
    skill_id: str = Field(max_length=60)
    group_record_id: uuid.UUID | None = None


def _cg_out(
    db: Db, svc: tc.Services, c: CaregiverLesson, outcome: SafetyOutcome | None = None
) -> dict[str, Any]:
    return {"lesson": cg.lesson_view(db, svc, c), "safety": _safety(outcome)}


@router.get("/learn/caregiver/current")
def caregiver_current(user: CaregiverUser, db: Db, svc: Svc) -> dict[str, Any]:
    c = cg.open_lesson(db, user)
    return {"lesson": cg.lesson_view(db, svc, c) if c else None}


@router.post("/learn/caregiver/lessons", status_code=201)
def caregiver_start(
    body: CaregiverStartIn, user: CaregiverUser, db: Db, svc: Svc
) -> dict[str, Any]:
    rec = _record_for(db, user, body.group_record_id) if body.group_record_id else None
    return _cg_out(db, svc, cg.start(svc, db, user, body.skill_id, group_record=rec))


@router.get("/learn/caregiver/lessons/{lesson_id}")
def caregiver_get(lesson_id: uuid.UUID, user: CaregiverUser, db: Db, svc: Svc) -> dict[str, Any]:
    c = cg.get_owned(db, user, lesson_id)
    cg.refresh_for_language(svc, db, user, c)
    return _cg_out(db, svc, c)


class AdaptIn(Strict):
    variant: Literal["standard", "simpler", "another_example"]


@router.post("/learn/caregiver/lessons/{lesson_id}/adapt")
def caregiver_adapt(
    lesson_id: uuid.UUID, body: AdaptIn, user: CaregiverUser, db: Db, svc: Svc
) -> dict[str, Any]:
    c = cg.get_owned(db, user, lesson_id)
    cg.adapt(svc, db, user, c, body.variant)
    return _cg_out(db, svc, c)


class AdvanceIn(Strict):
    from_step: Literal["explain", "practice", "quiz"]


@router.post("/learn/caregiver/lessons/{lesson_id}/next")
def caregiver_next(
    lesson_id: uuid.UUID, body: AdvanceIn, user: CaregiverUser, db: Db, svc: Svc
) -> dict[str, Any]:
    c = cg.get_owned(db, user, lesson_id)
    cg.advance(svc, db, user, c, body.from_step)
    return _cg_out(db, svc, c)


class PracticeIn(Strict):
    item_index: int = Field(ge=0, le=5)
    option_index: int | None = Field(default=None, ge=0, le=3)
    text: str | None = Field(default=None, max_length=2000)


@router.post("/learn/caregiver/lessons/{lesson_id}/practice")
def caregiver_practice(
    lesson_id: uuid.UUID, body: PracticeIn, user: CaregiverUser, db: Db, svc: Svc
) -> dict[str, Any]:
    c = cg.get_owned(db, user, lesson_id)
    feedback, outcome = cg.practise(
        svc, db, user, c, body.item_index, option_index=body.option_index, text=body.text
    )
    return {**_cg_out(db, svc, c, outcome), "feedback": feedback}


class QuizIn(Strict):
    question_index: int = Field(ge=0, le=5)
    answer_index: int = Field(ge=0, le=3)


@router.post("/learn/caregiver/lessons/{lesson_id}/quiz")
def caregiver_quiz(
    lesson_id: uuid.UUID, body: QuizIn, user: CaregiverUser, db: Db, svc: Svc
) -> dict[str, Any]:
    c = cg.get_owned(db, user, lesson_id)
    result = cg.answer_quiz(db, c, body.question_index, body.answer_index)
    return {**_cg_out(db, svc, c), "result": result}


class FinishIn(Strict):
    reflection: str | None = Field(default=None, max_length=2000)


@router.post("/learn/caregiver/lessons/{lesson_id}/finish")
def caregiver_finish(
    lesson_id: uuid.UUID, body: FinishIn, user: CaregiverUser, db: Db, svc: Svc
) -> dict[str, Any]:
    c = cg.get_owned(db, user, lesson_id)
    outcome = cg.finish(svc, db, user, c, body.reflection)
    return _cg_out(db, svc, c, outcome)


@router.post("/learn/caregiver/lessons/{lesson_id}/stop")
def caregiver_stop(lesson_id: uuid.UUID, user: CaregiverUser, db: Db, svc: Svc) -> dict[str, Any]:
    c = cg.get_owned(db, user, lesson_id)
    cg.stop(db, c)
    return _cg_out(db, svc, c)


# --- group review, progress, history (both participant roles) ---


@router.get("/learn/group-review")
def group_review(user: ParticipantUser, db: Db, svc: Svc) -> dict[str, Any]:
    """Skills from your group. Optional: no due dates, no completion state (D24)."""
    member = family_of(db, user)
    if member is None:
        return {"records": []}
    names = _names(svc, user.language)
    rows = db.scalars(
        select(GroupSkillRecord)
        .where(GroupSkillRecord.group_id == member.family.group_id)
        .order_by(GroupSkillRecord.session_date.desc(), GroupSkillRecord.created_at.desc())
        .limit(50)
    )
    return {
        "records": [
            {
                "id": str(r.id),
                "session_date": r.session_date.isoformat(),
                "skills": [
                    {"id": sid, "name": names(sid)[0], "module": names(sid)[2]}
                    for sid in r.skill_ids
                ],
            }
            for r in rows
        ]
    }


@router.get("/learn/progress")
def progress(user: ParticipantUser, db: Db, svc: Svc) -> dict[str, Any]:
    return {"skills": progress_view(db, user.id, _names(svc, user.language))}


@router.get("/learn/history")
def history(user: ParticipantUser, db: Db, svc: Svc) -> dict[str, Any]:
    return {"lessons": history_view(db, user.id, _names(svc, user.language))}


# --- therapist: group skill records (D24) ---


class GroupRecordIn(Strict):
    session_date: date
    skill_ids: list[str] = Field(min_length=1, max_length=8)
    note: str | None = Field(default=None, max_length=1000)


def _record_out(svc: tc.Services, r: GroupSkillRecord, lang: str) -> dict[str, Any]:
    names = _names(svc, lang)
    return {
        "id": str(r.id),
        "session_date": r.session_date.isoformat(),
        "skills": [{"id": s, "name": names(s)[0], "module": names(s)[2]} for s in r.skill_ids],
        "note": r.note,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


@router.get("/groups/{group_id}/skill-records")
def list_records(group_id: uuid.UUID, user: StaffUser, db: Db, svc: Svc) -> dict[str, Any]:
    ensure_group(db, user, group_id)
    rows = db.scalars(
        select(GroupSkillRecord)
        .where(GroupSkillRecord.group_id == group_id)
        .order_by(GroupSkillRecord.session_date.desc())
    )
    audit_read(db, user, "group_skill_record.list", target_type="group", target_id=group_id)
    return {"records": [_record_out(svc, r, user.language) for r in rows]}


@router.post("/groups/{group_id}/skill-records", status_code=201)
def create_record(
    group_id: uuid.UUID, body: GroupRecordIn, user: StaffUser, db: Db, svc: Svc
) -> dict[str, Any]:
    if user.role is not Role.therapist:
        raise forbidden("group_review.therapist_only")
    ensure_group(db, user, group_id)
    ids = list(dict.fromkeys(body.skill_ids))
    unknown = [s for s in ids if s not in svc.ai.skill_module]
    if unknown:
        raise bad_request("group_review.unknown_skill")
    r = GroupSkillRecord(
        group_id=group_id,
        session_date=body.session_date,
        skill_ids=ids,
        note=(body.note or "").strip() or None,
        created_by=user.id,
    )
    db.add(r)
    db.flush()
    audit.record(
        db,
        "group_skill_record.created",
        actor=user,
        target_type="group",
        target_id=group_id,
        details={"record_id": str(r.id), "skills": ids},
    )
    return {"record": _record_out(svc, r, user.language)}


@router.delete("/groups/{group_id}/skill-records/{record_id}", status_code=204)
def delete_record(group_id: uuid.UUID, record_id: uuid.UUID, user: StaffUser, db: Db) -> None:
    if user.role is not Role.therapist:
        raise forbidden("group_review.therapist_only")
    ensure_group(db, user, group_id)
    r = db.get(GroupSkillRecord, record_id)
    if r is None or r.group_id != group_id:
        raise not_found()
    db.delete(r)
    audit.record(
        db,
        "group_skill_record.deleted",
        actor=user,
        target_type="group",
        target_id=group_id,
        details={"record_id": str(record_id)},
    )
