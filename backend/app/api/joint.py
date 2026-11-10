"""Joint sessions API (Plan §5.9; Phase 8 tasks 3-5, 7).

Participants: their own invitations (neutral copy, no reasons), accept / "not this time", a solo
rehearsal of the stub episode, and the room WebSocket. Therapists: schedule for suitable pairs
with an assignable episode version, the live board with controls, and the after-session summary.
Episode approval: therapists granted `content_approver`, and admins (Plan §4.2).

WebSocket protocol (`/api/v1/joint/sessions/{id}/ws`, same-origin, session cookie):
- client -> server: `join` {location}, `ping`, `rtt` {ms}, and actions `ready`, `submit`,
  `skip`, `hint`, `distress`, `pause`, `resume`, `leave`, `stop`, each with an idempotency `id`
  (and `step_id` / `value` where needed);
- server -> client: `state` (role-projected, with `seq`), `presence`, `paused`, `ended`, `ack`,
  `error`, `safety` (to the actor only), `pong`.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

import anyio
from fastapi import APIRouter, Depends, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Db, StaffUser, TherapistUser, require_roles
from app.content.loader import ContentBundle
from app.content.models import Episode
from app.core import audit
from app.core.errors import not_found
from app.core.policy import ensure_family, ensure_group
from app.core.sessions import COOKIE_NAME, resolve_session
from app.joint import engine
from app.joint import service as js
from app.joint.hub import Conn, Hub
from app.joint.steps import EngineError
from app.models import (
    DyadSuitability,
    Family,
    FamilyMember,
    JointSession,
    Response,
    Role,
    Suitability,
    User,
    UserStatus,
)

router = APIRouter(prefix="/api/v1", tags=["joint"])
ParticipantUser = Annotated[User, Depends(require_roles(Role.adolescent, Role.caregiver))]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _content(request: Request) -> ContentBundle:
    content: ContentBundle = request.app.state.content
    return content


def _hub(request: Request) -> Hub:
    hub: Hub = request.app.state.joint_hub
    return hub


Content = Annotated[ContentBundle, Depends(_content)]


def _bi(b: Any) -> Any:
    return b.model_dump(by_alias=True)


def episode_card(ep: Episode) -> dict[str, Any]:
    return {
        "id": ep.id,
        "version": ep.version,
        "title": _bi(ep.title),
        "objective": _bi(ep.objective),
        "behavioral_criterion": _bi(ep.behavioral_criterion),
        "estimated_minutes": ep.estimated_minutes,
        "skill_ids": ep.skill_ids,
        "world": ep.world,
        "level": ep.level,
        "modes": ep.modes,
    }


# --- participants -----------------------------------------------------------------------


def _participant_view(
    db: Session, content: ContentBundle, s: JointSession, user: User
) -> dict[str, Any]:
    ep = content.episode(s.episode_id, s.episode_version)
    status = js.participant_status(db, s, user)
    return {
        "id": str(s.id),
        "mode": s.mode,
        "episode": episode_card(ep) if ep else None,
        "opens_at": s.opens_at,
        "closes_at": s.closes_at,
        "status": status,
        "can_respond": status == "invited",
        "can_join": js.join_error(db, s, user) is None,
    }


@router.get("/joint/sessions")
def my_sessions(user: ParticipantUser, db: Db, content: Content) -> dict[str, Any]:
    rows = db.scalars(
        select(JointSession)
        .where((JointSession.adolescent_id == user.id) | (JointSession.caregiver_id == user.id))
        .order_by(JointSession.opens_at.desc())
        .limit(50)
    ).all()
    return {"sessions": [_participant_view(db, content, s, user) for s in rows]}


@router.get("/joint/sessions/{session_id}")
def my_session(
    session_id: uuid.UUID, user: ParticipantUser, db: Db, content: Content
) -> dict[str, Any]:
    return _participant_view(db, content, js.get_for_participant(db, user, session_id), user)


class RespondIn(Strict):
    response: Literal["accepted", "declined"]


@router.post("/joint/sessions/{session_id}/respond")
def respond(
    session_id: uuid.UUID, body: RespondIn, user: ParticipantUser, db: Db, content: Content
) -> dict[str, Any]:
    s = js.get_for_participant(db, user, session_id)
    js.respond(db, user, s, Response(body.response))
    return _participant_view(db, content, s, user)


@router.post("/joint/solo", status_code=201)
def start_solo(user: ParticipantUser, db: Db, content: Content) -> dict[str, Any]:
    s = js.start_solo(db, content, user)
    return _participant_view(db, content, s, user)


def _origin_ok(ws: WebSocket, allowed: list[str]) -> bool:
    """Cross-site WebSocket hijacking guard: the Origin must be this host or an allowed origin."""
    origin = ws.headers.get("origin")
    if not origin:
        return False
    if origin in allowed:
        return True
    return urlsplit(origin).netloc == ws.headers.get("host", "")


@router.websocket("/joint/sessions/{session_id}/ws")
async def room_socket(ws: WebSocket, session_id: uuid.UUID) -> None:
    app = ws.app
    hub: Hub = app.state.joint_hub
    settings = app.state.settings
    token = ws.cookies.get(COOKIE_NAME)
    if not _origin_ok(ws, settings.allowed_origins):
        await ws.close(code=4403)
        return

    def authorise(db: Session) -> tuple[uuid.UUID, str] | str:
        sess = resolve_session(db, token, settings)
        if sess is None:
            return "auth.required"
        user = db.get(User, sess.user_id)
        if user is None or user.status is not UserStatus.active or user.onboarded_at is None:
            return "auth.required"
        if user.role not in (Role.adolescent, Role.caregiver):
            return "access.forbidden"
        s = db.get(JointSession, session_id)
        if s is None or user.id not in s.participant_ids():
            from app.core.policy import deny

            deny(
                db,
                user,
                target_type="joint_session",
                target_id=session_id,
                reason="not_participant",
            )
            return "access.forbidden"
        err = js.join_error(db, s, user)
        if err:
            return err
        return user.id, js.role_of(s, user)

    who = await hub.run(authorise)
    await ws.accept()
    if isinstance(who, str):
        await ws.send_json({"type": "error", "code": who})
        await ws.close(code=4403)
        return
    user_id, role = who
    conn = Conn(ws, user_id, role)
    safety = app.state.safety
    await hub.connect(session_id, conn)

    def load_user(db: Session) -> User:
        u = db.get(User, user_id)
        assert u is not None
        return u

    try:
        while True:
            msg = await ws.receive_json()
            if not isinstance(msg, dict):
                continue
            kind = msg.get("type")
            if kind == "ping":
                alive = await hub.run(lambda db: resolve_session(db, token, settings) is not None)
                if not alive:  # signed out or expired: close the room connection too
                    await ws.close(code=4401)
                    break
                await ws.send_json({"type": "pong", "t": msg.get("t")})
            elif kind == "join":
                loc = msg.get("location")

                def join(db: Session, loc: Any = loc) -> None:
                    s = db.get(JointSession, session_id)
                    assert s is not None
                    js.record_join(db, s, load_user(db), loc if isinstance(loc, str) else None)

                await hub.run(join)
            elif kind == "rtt":
                ms = msg.get("ms")
                if isinstance(ms, (int, float)) and 0 <= ms <= 60_000:
                    rtt = round(float(ms), 1)

                    def log_rtt(db: Session, rtt: float = rtt) -> None:
                        js.research(db, "joint.rtt", load_user(db), session=str(session_id), ms=rtt)

                    await hub.run(log_rtt)
            elif kind in engine.PARTICIPANT_ACTIONS:
                try:
                    await hub.act(session_id, conn, msg, load_user, safety)
                except EngineError as e:
                    await ws.send_json({"type": "error", "code": e.code, "id": msg.get("id")})
            else:
                await ws.send_json(
                    {"type": "error", "code": "room.unknown_message", "id": msg.get("id")}
                )
    except WebSocketDisconnect:
        pass
    finally:
        # presence must be updated even when the server cancels the connection task
        with anyio.CancelScope(shield=True):
            await hub.disconnect(session_id, conn)


# --- therapists -------------------------------------------------------------------------


def _pairs(db: Session, family: Family) -> list[dict[str, Any]]:
    teen = js.adolescent_of(db, family)
    carers = db.scalars(
        select(FamilyMember).where(
            FamilyMember.family_id == family.id, FamilyMember.member_role == Role.caregiver
        )
    ).all()
    out = []
    for m in carers:
        row = (
            db.execute(
                select(DyadSuitability).where(
                    DyadSuitability.adolescent_id == teen.id,
                    DyadSuitability.caregiver_id == m.user_id,
                )
            ).scalar_one_or_none()
            if teen
            else None
        )
        out.append(
            {
                "caregiver_id": str(m.user_id),
                "caregiver_alias": m.user.display_alias,
                "adolescent_alias": teen.display_alias if teen else None,
                "suitable": row is not None and row.decision is Suitability.suitable,
            }
        )
    return out


def _board_row(
    db: Session, content: ContentBundle, hub: Hub, s: JointSession, aliases: dict[uuid.UUID, str]
) -> dict[str, Any]:
    ep = content.episode(s.episode_id, s.episode_version)
    resp = js.responses(db, s)
    present = hub.present(s.id)

    def person(uid: uuid.UUID | None, role: str) -> dict[str, Any] | None:
        if uid is None:
            return None
        r = resp.get(uid)
        return {
            "alias": aliases.get(uid, ""),
            "response": str(r.response) if r else None,  # declines: therapist only (§9.1C)
            "present": role in present,
        }

    return {
        "id": str(s.id),
        "family_id": str(s.family_id),
        "mode": s.mode,
        "episode": episode_card(ep) if ep else None,
        "opens_at": s.opens_at,
        "closes_at": s.closes_at,
        "status": str(s.status),
        "time_passed": s.status == "invited" and s.closes_at <= js.now(),
        "adolescent": person(s.adolescent_id, "adolescent"),
        "caregiver": person(s.caregiver_id, "caregiver"),
        "board": engine.board(ep, s.snapshot) if ep else None,
    }


@router.get("/groups/{group_id}/joint")
def group_joint(
    group_id: uuid.UUID, therapist: TherapistUser, db: Db, request: Request
) -> dict[str, Any]:
    group = ensure_group(db, therapist, group_id)
    content = _content(request)
    hub = _hub(request)
    families = db.scalars(
        select(Family).where(Family.group_id == group.id).order_by(Family.label)
    ).all()
    fam_ids = [f.id for f in families]
    sessions = (
        db.scalars(
            select(JointSession)
            .where(JointSession.family_id.in_(fam_ids), JointSession.mode == "joint")
            .order_by(JointSession.opens_at.desc())
            .limit(100)
        ).all()
        if fam_ids
        else []
    )
    uids = {u for s in sessions for u in s.participant_ids()}
    aliases = (
        {u.id: u.display_alias for u in db.scalars(select(User).where(User.id.in_(uids)))}
        if uids
        else {}
    )
    episodes = []
    for ep in content.episodes:
        if "joint" not in ep.modes:
            continue
        status = js.effective_status(db, ep)
        episodes.append(
            episode_card(ep)
            | {
                "status": status,
                "assignable_families": [str(f.id) for f in families if js.assignable(status, f)],
            }
        )
    catalog = content.episode_catalog
    return {
        "families": [
            {"id": str(f.id), "label": f.label, "is_demo": f.is_demo, "pairs": _pairs(db, f)}
            for f in families
        ],
        "episodes": episodes,
        "catalog": [] if catalog is None else catalog.model_dump(by_alias=True)["worlds"],
        "sessions": [_board_row(db, content, hub, s, aliases) for s in sessions],
    }


class ScheduleIn(Strict):
    family_id: uuid.UUID
    caregiver_id: uuid.UUID
    episode_id: str = Field(min_length=3, max_length=64)
    episode_version: int = Field(ge=1)
    opens_at: datetime
    closes_at: datetime


@router.post("/groups/{group_id}/joint-sessions", status_code=201)
def schedule(
    group_id: uuid.UUID, body: ScheduleIn, therapist: TherapistUser, db: Db, request: Request
) -> dict[str, Any]:
    group = ensure_group(db, therapist, group_id)
    family = ensure_family(db, therapist, body.family_id)
    if family.group_id != group.id:
        raise not_found()
    s = js.schedule(
        db,
        _content(request),
        therapist,
        family,
        caregiver_id=body.caregiver_id,
        episode_id=body.episode_id,
        version=body.episode_version,
        opens_at=body.opens_at,
        closes_at=body.closes_at,
    )
    return {"id": str(s.id)}


def _therapist_session(
    db: Session, therapist: User, session_id: uuid.UUID
) -> tuple[JointSession, Family]:
    s = db.get(JointSession, session_id)
    if s is None:
        raise not_found()
    family = ensure_family(db, therapist, s.family_id)
    return s, family


@router.delete("/joint-sessions/{session_id}", status_code=204)
def cancel(session_id: uuid.UUID, therapist: TherapistUser, db: Db) -> None:
    s, _ = _therapist_session(db, therapist, session_id)
    js.cancel(db, therapist, s)


class ControlIn(Strict):
    action: Literal["pause", "resume", "safety_pause", "terminate", "reset"]


@router.post("/joint-sessions/{session_id}/control")
async def control(
    session_id: uuid.UUID, body: ControlIn, therapist: TherapistUser, request: Request
) -> dict[str, Any]:
    hub = _hub(request)
    content = _content(request)

    def check(db: Session) -> bool:
        _, family = _therapist_session(db, therapist, session_id)
        return family.is_demo

    is_demo: bool = await hub.run(check)

    def do(db: Session, present: set[str]) -> js.Outcome:
        t = db.get(User, therapist.id)
        assert t is not None
        return js.control(db, content, t, session_id, body.action, present, is_demo=is_demo)

    try:
        out = await hub.therapist_control(session_id, do)
    except EngineError as e:
        from app.core.errors import conflict

        raise conflict(e.code) from e
    ep = content.episode(*(await hub.run(lambda db: _ep_key(db, session_id))))
    return {"board": engine.board(ep, out.state) if ep else None}


def _ep_key(db: Session, session_id: uuid.UUID) -> tuple[str, int]:
    s = db.get(JointSession, session_id)
    assert s is not None
    return s.episode_id, s.episode_version


@router.get("/joint-sessions/{session_id}/summary")
def summary(
    session_id: uuid.UUID, therapist: TherapistUser, db: Db, request: Request
) -> dict[str, Any]:
    s, _ = _therapist_session(db, therapist, session_id)
    content = _content(request)
    out = js.summary(db, content, therapist, s)
    ep = content.episode(s.episode_id, s.episode_version)
    out["episode"] = episode_card(ep) if ep else None
    out["status"] = str(s.status)
    out["id"] = str(s.id)
    out["aliases"] = {
        js.role_of(s, u): u.display_alias
        for u in (db.get(User, uid) for uid in s.participant_ids())
        if u is not None
    }
    return out


# --- episode registry (content review) --------------------------------------------------


@router.get("/episodes")
def list_episodes(user: StaffUser, db: Db, content: Content) -> dict[str, Any]:
    return {
        "can_approve": js.can_approve(user),
        "episodes": [
            episode_card(ep)
            | {"status": js.effective_status(db, ep), "file_status": ep.approval.status.value}
            for ep in content.episodes
        ],
    }


class DecisionIn(Strict):
    status: Literal["approved", "retired"]


@router.post("/episodes/{episode_id}/versions/{version}/decision")
def decide(
    episode_id: str, version: int, body: DecisionIn, user: StaffUser, db: Db, content: Content
) -> dict[str, Any]:
    ep = js.decide_episode(db, content, user, episode_id, version, body.status)
    return episode_card(ep) | {"status": js.effective_status(db, ep)}


_ = audit  # audit entries are written in the service layer
