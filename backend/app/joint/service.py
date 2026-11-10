"""Joint sessions: registry gates, scheduling, invitations and the room action pipeline
(Plan §5.9; Phase 8 tasks 1-5, 7).

Every room action runs in one transaction: lock the session row, drop duplicates by
idempotency key, apply the engine, store private inputs separately (distress ratings D76,
encrypted reflections D77), stamp the next sequence number, append a `RoomEvent`, and write the
`SharedCompletionRecord` when the room finishes.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.content.loader import ContentBundle
from app.content.models import Episode
from app.core import audit
from app.core.errors import bad_request, conflict, forbidden, not_found
from app.joint import engine
from app.joint.steps import EngineError
from app.models import (
    DistressRating,
    DyadSuitability,
    EpisodeApproval,
    Family,
    FamilyMember,
    JointSession,
    JointSessionResponse,
    PrivateReflection,
    Response,
    Role,
    RoomEvent,
    SessionStatus,
    SharedCompletionRecord,
    Suitability,
    User,
)
from app.research import events as research_events
from app.safety.service import Context, SafetyService

MAX_WINDOW = timedelta(days=14)
SOLO_WINDOW = timedelta(hours=12)
SOLO_EPISODE = ("demo-stub-episode", 1)
LOCATIONS = ("hospital", "remote")
FINISHED = (SessionStatus.completed, SessionStatus.ended)


def now() -> datetime:
    return datetime.now(UTC)


# --- research instrumentation (§5.10: pseudonymous, no free text) -----------------------


def research(db: Session, event_type: str, user: User | None, /, **props: Any) -> None:
    research_events.record(db, event_type, user, **props)


# --- episode registry (Plan §4.1 `Episode`; §4.2 approval) ------------------------------


def effective_status(db: Session, episode: Episode) -> str:
    row = db.execute(
        select(EpisodeApproval)
        .where(
            EpisodeApproval.episode_id == episode.id,
            EpisodeApproval.episode_version == episode.version,
        )
        .order_by(EpisodeApproval.decided_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    return row.status if row else episode.approval.status.value


def assignable(status: str, family: Family) -> bool:
    """Approved versions for anyone; demo versions only for demo families (§5.9)."""
    return status == "approved" or (status == "demo" and family.is_demo)


def can_approve(user: User) -> bool:
    return user.role is Role.admin or (user.role is Role.therapist and user.content_approver)


def decide_episode(
    db: Session, content: ContentBundle, actor: User, episode_id: str, version: int, status: str
) -> Episode:
    episode = content.episode(episode_id, version)
    if episode is None:
        raise not_found("episode.not_found")
    if not can_approve(actor):
        raise forbidden("episode.not_approver")
    current = effective_status(db, episode)
    allowed = {"approved": ("draft",), "retired": ("draft", "approved")}
    if status not in allowed or current not in allowed[status]:
        raise conflict("episode.invalid_transition")
    db.add(
        EpisodeApproval(
            episode_id=episode.id,
            episode_version=episode.version,
            status=status,
            decided_by=actor.id,
        )
    )
    audit.record(
        db,
        f"episode.{status}",
        actor=actor,
        target_type="episode",
        target_id=f"{episode.id}@{episode.version}",
    )
    return episode


# --- scheduling and invitations ---------------------------------------------------------


def _member(db: Session, family: Family, user_id: uuid.UUID, role: Role) -> User:
    m = db.execute(
        select(FamilyMember).where(
            FamilyMember.family_id == family.id,
            FamilyMember.user_id == user_id,
            FamilyMember.member_role == role,
        )
    ).scalar_one_or_none()
    if m is None:
        raise bad_request("joint.not_in_family")
    return m.user


def adolescent_of(db: Session, family: Family) -> User | None:
    m = db.execute(
        select(FamilyMember).where(
            FamilyMember.family_id == family.id, FamilyMember.member_role == Role.adolescent
        )
    ).scalar_one_or_none()
    return m.user if m else None


def is_suitable(db: Session, adolescent_id: uuid.UUID, caregiver_id: uuid.UUID) -> bool:
    row = db.execute(
        select(DyadSuitability).where(
            DyadSuitability.adolescent_id == adolescent_id,
            DyadSuitability.caregiver_id == caregiver_id,
        )
    ).scalar_one_or_none()
    return row is not None and row.decision is Suitability.suitable


def schedule(
    db: Session,
    content: ContentBundle,
    therapist: User,
    family: Family,
    *,
    caregiver_id: uuid.UUID,
    episode_id: str,
    version: int,
    opens_at: datetime,
    closes_at: datetime,
) -> JointSession:
    episode = content.episode(episode_id, version)
    if episode is None or "joint" not in episode.modes:
        raise bad_request("joint.unknown_episode")
    if not assignable(effective_status(db, episode), family):
        raise bad_request("joint.episode_not_approved")
    teen = adolescent_of(db, family)
    if teen is None:
        raise bad_request("joint.no_adolescent")
    carer = _member(db, family, caregiver_id, Role.caregiver)
    if not is_suitable(db, teen.id, carer.id):
        raise bad_request("joint.not_suitable")
    if opens_at.tzinfo is None or closes_at.tzinfo is None:
        raise bad_request("joint.invalid_window")
    if not (closes_at > opens_at and closes_at - opens_at <= MAX_WINDOW and closes_at > now()):
        raise bad_request("joint.invalid_window")
    s = JointSession(
        family_id=family.id,
        mode="joint",
        adolescent_id=teen.id,
        caregiver_id=carer.id,
        episode_id=episode.id,
        episode_version=episode.version,
        opens_at=opens_at,
        closes_at=closes_at,
        status=SessionStatus.invited,
        snapshot=engine.new_state(["adolescent", "caregiver"]),
        created_by=therapist.id,
    )
    db.add(s)
    db.flush()
    audit.record(
        db,
        "joint.scheduled",
        actor=therapist,
        target_type="joint_session",
        target_id=s.id,
        details={"episode": f"{episode.id}@{episode.version}"},
    )
    for u in (teen, carer):
        research(db, "joint.invited", u, session=str(s.id), episode=episode.id)
    return s


def cancel(db: Session, therapist: User, s: JointSession) -> None:
    if s.status != SessionStatus.invited:
        raise conflict("joint.not_cancellable")
    s.status = SessionStatus.cancelled
    audit.record(
        db, "joint.cancelled", actor=therapist, target_type="joint_session", target_id=s.id
    )


def start_solo(db: Session, content: ContentBundle, user: User) -> JointSession:
    """Solo rehearsal (§5.2): the same engine with one participant, stub episode only."""
    member = db.execute(
        select(FamilyMember).where(FamilyMember.user_id == user.id)
    ).scalar_one_or_none()
    if member is None:
        raise forbidden("joint.not_in_family")
    episode = content.episode(*SOLO_EPISODE)
    if episode is None:
        raise not_found("episode.not_found")
    t = now()
    s = JointSession(
        family_id=member.family_id,
        mode="solo",
        adolescent_id=user.id if user.role is Role.adolescent else None,
        caregiver_id=user.id if user.role is Role.caregiver else None,
        episode_id=episode.id,
        episode_version=episode.version,
        opens_at=t,
        closes_at=t + SOLO_WINDOW,
        status=SessionStatus.invited,
        snapshot=engine.new_state([user.role.value]),
        created_by=user.id,
    )
    db.add(s)
    db.flush()
    db.add(JointSessionResponse(session_id=s.id, user_id=user.id, response=Response.accepted))
    research(db, "joint.solo_started", user, session=str(s.id))
    return s


def get_for_participant(db: Session, user: User, session_id: uuid.UUID) -> JointSession:
    s = db.get(JointSession, session_id)
    if s is None or user.id not in s.participant_ids():
        raise not_found()
    return s


def responses(db: Session, s: JointSession) -> dict[uuid.UUID, JointSessionResponse]:
    rows = db.scalars(select(JointSessionResponse).where(JointSessionResponse.session_id == s.id))
    return {r.user_id: r for r in rows}


def respond(db: Session, user: User, s: JointSession, response: Response) -> None:
    if s.status != SessionStatus.invited or s.mode != "joint":
        raise conflict("joint.not_open")
    if s.closes_at <= now():
        raise conflict("joint.window_closed")
    existing = responses(db, s).get(user.id)
    if existing is not None:
        raise conflict("joint.already_responded")
    db.add(JointSessionResponse(session_id=s.id, user_id=user.id, response=response))
    if response == Response.declined:
        s.status = SessionStatus.declined  # the partner sees only that it won't run (§9.1C)
    audit.record(
        db, f"joint.{response.value}", actor=user, target_type="joint_session", target_id=s.id
    )
    research(db, "joint.response", user, session=str(s.id), response=response.value)


def role_of(s: JointSession, user: User) -> str:
    if user.id == s.adolescent_id:
        return "adolescent"
    if user.id == s.caregiver_id:
        return "caregiver"
    raise forbidden()


def participant_status(db: Session, s: JointSession, user: User) -> str:
    """Neutral status for one participant. Never says who declined or whether the partner has
    answered yet."""
    if s.status == SessionStatus.declined:
        mine = responses(db, s).get(user.id)
        return "you_declined" if mine and mine.response == Response.declined else "wont_run"
    if s.status == SessionStatus.cancelled:
        return "wont_run"
    if s.status in FINISHED:
        return str(s.status)
    if s.status == SessionStatus.active:
        return "active"
    if s.closes_at <= now():
        return "time_passed"
    resp = responses(db, s)
    if user.id not in resp:
        return "invited"
    if all(u in resp for u in s.participant_ids()):
        return "ready" if s.opens_at <= now() else "accepted"
    return "accepted"


def join_error(db: Session, s: JointSession, user: User) -> str | None:
    if s.status == SessionStatus.active:
        return None  # an active room stays open until it finishes
    if s.status != SessionStatus.invited:
        return "joint.not_open"
    t = now()
    if not (s.opens_at <= t < s.closes_at):
        return "joint.window_closed"
    resp = responses(db, s)
    if not all(u in resp and resp[u].response == Response.accepted for u in s.participant_ids()):
        return "joint.not_accepted"
    return None


def record_join(db: Session, s: JointSession, user: User, location: str | None) -> None:
    r = responses(db, s).get(user.id)
    if r is not None and location in LOCATIONS and r.join_location is None:
        r.join_location = location
    research(
        db,
        "joint.join",
        user,
        session=str(s.id),
        location=location if location in LOCATIONS else None,
    )


# --- the room ---------------------------------------------------------------------------


def episode_of(content: ContentBundle, s: JointSession) -> Episode:
    ep = content.episode(s.episode_id, s.episode_version)
    if ep is None:
        raise not_found("episode.not_found")
    return ep


@dataclass
class Outcome:
    state: dict[str, Any]
    seq: int
    duplicate: bool = False
    to_actor: list[dict[str, Any]] = field(default_factory=list)


def _lock(db: Session, session_id: uuid.UUID) -> JointSession:
    s = db.execute(
        select(JointSession).where(JointSession.id == session_id).with_for_update()
    ).scalar_one_or_none()
    if s is None:
        raise not_found()
    return s


def _persist(
    db: Session,
    s: JointSession,
    episode: Episode,
    old: dict[str, Any],
    new: dict[str, Any],
    *,
    actor: User | None,
    actor_role: str,
    kind: str,
    step_id: str | None,
    payload: dict[str, Any],
    idem: str | None,
) -> None:
    s.seq += 1
    s.snapshot = new
    db.add(
        RoomEvent(
            session_id=s.id,
            seq=s.seq,
            actor_id=actor.id if actor else None,
            actor_role=actor_role,
            type=kind,
            step_id=step_id,
            payload=payload,
            idempotency_key=idem,
        )
    )
    if old["phase"] == "lobby" and new["phase"] == "running" and s.started_at is None:
        s.status, s.started_at = SessionStatus.active, now()
        research(db, "joint.started", None, session=str(s.id), mode=s.mode)
    if new["phase"] in ("completed", "ended") and old["phase"] not in ("completed", "ended"):
        _finish(db, s, episode, new)
    if new["phase"] != old["phase"] and new["phase"] in ("paused", "paused_safety"):
        research(db, "joint.pause", None, session=str(s.id), by=new["pause"]["by"])


def _finish(db: Session, s: JointSession, episode: Episode, state: dict[str, Any]) -> None:
    completed = state["phase"] == "completed"
    s.status = SessionStatus.completed if completed else SessionStatus.ended
    s.ended_at = now()
    s.end_reason = None if completed else state.get("end_reason")
    if s.started_at is None:
        s.started_at = s.ended_at
    db.add(
        SharedCompletionRecord(
            session_id=s.id,
            episode_id=s.episode_id,
            episode_version=s.episode_version,
            status="completed" if completed else "partial",
            completed_step_ids=list(state["done"]),
            skipped_step_ids=list(state["skipped"]),
            shared_rubric_tags=engine.shared_tags(episode, state),
            started_at=s.started_at,
        )
    )
    research(
        db,
        "joint.finished",
        None,
        session=str(s.id),
        status="completed" if completed else "partial",
        reason=s.end_reason,
        steps_done=len(state["done"]),
        steps_skipped=len(state["skipped"]),
    )


def act(
    db: Session,
    content: ContentBundle,
    safety: SafetyService,
    session_id: uuid.UUID,
    user: User,
    action: dict[str, Any],
    present: set[str],
) -> Outcome:
    s = _lock(db, session_id)
    role = role_of(s, user)
    episode = episode_of(content, s)
    idem = action.get("id")
    if not isinstance(idem, str) or not 8 <= len(idem) <= 64:
        raise EngineError("room.missing_id")
    dup = db.execute(
        select(RoomEvent.seq).where(
            RoomEvent.session_id == s.id,
            RoomEvent.actor_id == user.id,
            RoomEvent.idempotency_key == idem,
        )
    ).scalar_one_or_none()
    if dup is not None:
        return Outcome(s.snapshot, s.seq, duplicate=True)
    if s.status not in (SessionStatus.invited, SessionStatus.active):
        raise EngineError("room.ended")

    old = s.snapshot
    kind = str(action.get("type"))
    value = action.get("value")
    step = engine.current_step(episode, old) if old["phase"] == "running" else None
    to_actor: list[dict[str, Any]] = []
    # Private inputs are checked before the engine, so the engine only sees an act.
    reflection_text: str | None = None
    if (
        kind == "submit"
        and step is not None
        and step.type == "private_reflection"
        and isinstance(value, str)
    ):
        reflection_text = value.strip()
    new, _completed = engine.apply(episode, old, role, action, present)

    payload: dict[str, Any] = {}
    step_id = action.get("step_id") if isinstance(action.get("step_id"), str) else None
    if kind == "submit" and step is not None and step.type not in ("private_reflection",):
        payload = {"value": value}
    if kind == "distress":
        db.add(
            DistressRating(
                user_id=user.id,
                session_id=s.id,
                context="episode_step",
                step_id=step_id,
                value=value,
            )
        )
    if kind == "skip" and step is not None and step.type == "distress_check":
        db.add(
            DistressRating(
                user_id=user.id,
                session_id=s.id,
                context="episode_step",
                step_id=step_id,
                value=None,
            )
        )
    if reflection_text is not None and step is not None:
        outcome = safety.screen_text(db, user, Context.joint, reflection_text, source_ref=str(s.id))
        db.add(
            PrivateReflection(
                session_id=s.id,
                user_id=user.id,
                step_id=step.id,
                text=reflection_text,
                flagged=outcome.action != "none",
            )
        )
        if outcome.should_stop:
            new = (
                engine.apply(episode, new, role, {"type": "stop"}, present)[0]
                if new["phase"] in engine.LIVE
                else new
            )
            to_actor.append({"type": "safety", "action": "stop"})
        elif outcome.action == "care_card":
            to_actor.append({"type": "safety", "action": "care_card"})
    if kind == "stop":
        safety.record_participant_stop(db, user, str(s.id))
        to_actor.append({"type": "safety", "action": "help"})
        audit.record(db, "joint.need_stop", actor=user, target_type="joint_session", target_id=s.id)
    if kind == "leave":
        research(db, "joint.leave", user, session=str(s.id))
    if kind in ("skip", "hint", "stop"):
        research(
            db,
            f"joint.{kind}",
            user,
            session=str(s.id),
            step_type=str(step.type) if step is not None else None,
        )

    _persist(
        db,
        s,
        episode,
        old,
        new,
        actor=user,
        actor_role=role,
        kind=kind,
        step_id=step_id,
        payload=payload,
        idem=idem,
    )
    return Outcome(new, s.seq, to_actor=to_actor)


def control(
    db: Session,
    content: ContentBundle,
    therapist: User,
    session_id: uuid.UUID,
    action: str,
    present: set[str],
    *,
    is_demo: bool,
) -> Outcome:
    s = _lock(db, session_id)
    if s.status not in (SessionStatus.invited, SessionStatus.active) and action != "reset":
        raise EngineError("room.ended")
    episode = episode_of(content, s)
    old = s.snapshot
    new = engine.control(episode, old, action, present, is_demo=is_demo)
    if action == "reset":
        s.status, s.started_at, s.ended_at, s.end_reason = SessionStatus.invited, None, None, None
        db.execute(
            SharedCompletionRecord.__table__.delete().where(  # type: ignore[attr-defined]
                SharedCompletionRecord.session_id == s.id
            )
        )
    _persist(
        db,
        s,
        episode,
        old,
        new,
        actor=therapist,
        actor_role="therapist",
        kind=f"control.{action}",
        step_id=None,
        payload={},
        idem=None,
    )
    audit.record(
        db, f"joint.control.{action}", actor=therapist, target_type="joint_session", target_id=s.id
    )
    return Outcome(new, s.seq)


def system_update(
    db: Session, content: ContentBundle, session_id: uuid.UUID, kind: str, present: set[str]
) -> Outcome | None:
    """Presence-driven changes: "auto_pause" after a disconnect, "recheck" when someone returns."""
    s = _lock(db, session_id)
    if s.status not in (SessionStatus.invited, SessionStatus.active):
        return None
    episode = episode_of(content, s)
    old = s.snapshot
    if kind == "auto_pause":
        new = engine.disconnect_pause(old)
        if new is None:
            return None
    else:
        new, completed = engine.try_advance(episode, old, present)
        if not completed and not (old["phase"] == "lobby" and _lobby_ready(old, present)):
            return None
        if old["phase"] == "lobby" and _lobby_ready(old, present):
            new["phase"] = "running"
    _persist(
        db,
        s,
        episode,
        old,
        new,
        actor=None,
        actor_role="system",
        kind=kind,
        step_id=None,
        payload={},
        idem=None,
    )
    return Outcome(new, s.seq)


def _lobby_ready(state: dict[str, Any], present: set[str]) -> bool:
    return all(state["ready"].values()) and set(state["roles"]) <= present


# --- therapist summary (after the session) ----------------------------------------------


def summary(
    db: Session, content: ContentBundle, therapist: User, s: JointSession
) -> dict[str, Any]:
    from app.models import SafetyEvent  # local: keeps the import surface small

    episode = episode_of(content, s)
    record = db.execute(
        select(SharedCompletionRecord).where(SharedCompletionRecord.session_id == s.id)
    ).scalar_one_or_none()
    users = {u: db.get(User, u) for u in s.participant_ids()}
    role_by_user = {u: role_of(s, users[u]) for u in users if users[u] is not None}  # type: ignore[arg-type]
    distress = db.scalars(
        select(DistressRating)
        .where(DistressRating.session_id == s.id)
        .order_by(DistressRating.created_at)
    ).all()
    reflections = db.scalars(
        select(PrivateReflection)
        .where(PrivateReflection.session_id == s.id)
        .order_by(PrivateReflection.created_at)
    ).all()
    events = db.scalars(select(SafetyEvent).where(SafetyEvent.source_ref == str(s.id))).all()
    audit.record(
        db,
        "joint.summary.read",
        actor=therapist,
        target_type="joint_session",
        target_id=s.id,
        details={"reflections": len(reflections)},
    )
    resp = responses(db, s)
    return {
        "record": None
        if record is None
        else {
            "status": record.status,
            "completed_step_ids": record.completed_step_ids,
            "skipped_step_ids": record.skipped_step_ids,
            "shared_rubric_tags": record.shared_rubric_tags,
            "started_at": record.started_at,
            "ended_at": record.ended_at,
        },
        "steps": [{"id": st.id, "type": st.type} for st in episode.steps],
        "rubric": engine.rubric_outputs(episode, s.snapshot),
        "responses": {
            role_by_user[u]: {"response": str(r.response), "join_location": r.join_location}
            for u, r in resp.items()
            if u in role_by_user
        },
        "distress": [
            {"role": role_by_user.get(d.user_id), "step_id": d.step_id, "value": d.value}
            for d in distress
        ],
        "reflections": [
            {"role": role_by_user.get(r.user_id), "text": r.text, "flagged": r.flagged}
            for r in reflections
        ],
        "safety_event_ids": [str(e.id) for e in events],
    }
