"""Pseudonymous research events (Plan §5.10). No free text, no identities.

Every event type is declared here with its allowed properties, so nothing outside this list can
reach the `research_event` table. Property values are short tokens (ids, enums), numbers or
booleans; anything that looks like prose is refused. Measures that the app already stores in its
own tables (diary entries, lessons, tests, safety events, ...) are exported from those tables and
are not duplicated as events (see `app/research/export.py` and the data dictionary).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.models import ResearchEvent, User

TOKEN = re.compile(r"^[A-Za-z0-9_.:@-]{0,64}$")


@dataclass(frozen=True)
class EventType:
    description: str
    props: tuple[str, ...] = ()


EVENTS: dict[str, EventType] = {
    # enrolment funnel and log-in (§8.4)
    "login_success": EventType("Successful sign-in."),
    "login_failure": EventType("Failed sign-in (subject empty when the username is unknown)."),
    "enrolment.code_issued": EventType(
        "A one-time code was issued by staff.", ("role", "purpose", "family")
    ),
    "enrolment.code_redeemed": EventType("A one-time code was redeemed.", ("purpose",)),
    "enrolment.onboarded": EventType("The participant finished onboarding consent."),
    # joint sessions (§5.9)
    "joint.invited": EventType("Invited to a joint session.", ("session", "episode")),
    "joint.response": EventType("Answered a joint invitation.", ("session", "response")),
    "joint.join": EventType(
        "Joined a room; location is self-reported (hospital/remote) or empty.",
        ("session", "location"),
    ),
    "joint.started": EventType("Room started (both ready).", ("session", "mode")),
    "joint.pause": EventType(
        "Room paused; by = participant/disconnect/therapist/safety.", ("session", "by")
    ),
    "joint.finished": EventType(
        "Room completed or ended early.",
        ("session", "status", "reason", "steps_done", "steps_skipped"),
    ),
    "joint.leave": EventType("A participant left, ending the room.", ("session",)),
    "joint.skip": EventType("A participant skipped a step.", ("session", "step_type")),
    "joint.hint": EventType("A participant asked for a hint.", ("session", "step_type")),
    "joint.stop": EventType('A participant selected "I need to stop".', ("session", "step_type")),
    "joint.solo_started": EventType("A participant started a solo rehearsal.", ("session",)),
    "joint.latency": EventType(
        "Server time to apply a room action, in ms.", ("session", "ms", "action")
    ),
    "joint.rtt": EventType("Client-measured round trip to the room, in ms.", ("session", "ms")),
    # usability (§8.4), reported by the browser
    "client.error": EventType(
        "A client-side error: kind = js/api_5xx/network; area = screen key.", ("kind", "area")
    ),
    "task.outcome": EventType(
        "A scripted task ended: outcome = success/abandoned.", ("task", "outcome")
    ),
}

CLIENT_EVENTS = frozenset({"client.error", "task.outcome"})
CLIENT_KINDS = frozenset({"js", "api_5xx", "network"})
CLIENT_TASKS = frozenset({"diary_entry", "onboarding"})
CLIENT_OUTCOMES = frozenset({"success", "abandoned"})


class UnsafeEventError(ValueError):
    pass


def _check(kind: str, props: dict[str, Any]) -> dict[str, Any]:
    spec = EVENTS.get(kind)
    if spec is None:
        raise UnsafeEventError(f"unknown research event {kind!r}")
    out: dict[str, Any] = {}
    for key, value in props.items():
        if key not in spec.props:
            raise UnsafeEventError(f"{kind}: property {key!r} is not declared")
        if (
            value is None
            or isinstance(value, bool | int | float)
            or (isinstance(value, str) and TOKEN.match(value))
        ):
            out[key] = value
        else:
            raise UnsafeEventError(f"{kind}: property {key!r} is not a short token")
    return out


def record(db: Session, event_type: str, user: User | None, /, **props: Any) -> None:
    """Add a research event in the caller's transaction."""
    db.add(
        ResearchEvent(
            event_type=event_type,
            subject_pseudonym=user.pseudonym_code if user else None,
            subject_role=user.role.value if user else None,
            props=_check(event_type, props),
        )
    )
