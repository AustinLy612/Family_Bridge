"""Server-authoritative room engine (Plan §5.9; ideas from the Lantern Forest prototype).

Pure functions over a JSON snapshot, so the same state can be persisted, reloaded after a
restart, and tested without a server. Clients send typed actions, never states.

Phases: lobby -> running -> completed, with pauses in between and "ended" when someone leaves
or the therapist ends the room.
- Participant pause (and the automatic pause after a disconnect): either participant resumes.
- Therapist pause and safety pause (D75 "I need to stop"): only the therapist resumes (O7).
- A `requires: both` step never completes while a participant is absent (§5.4).
"""

from __future__ import annotations

import copy
from typing import Any

from app.content.models import Episode
from app.joint.steps import MODULES, SKIPPED, Ctx, EngineError, PrivateChoice

PARTICIPANT_ACTIONS = frozenset(
    {"ready", "submit", "skip", "hint", "distress", "pause", "resume", "leave", "stop"}
)
THERAPIST_ACTIONS = frozenset({"pause", "resume", "safety_pause", "terminate", "reset"})
LIVE = frozenset({"lobby", "running", "paused", "paused_safety"})
STAFF_HOLDS = frozenset({"therapist", "safety"})


def new_state(roles: list[str]) -> dict[str, Any]:
    return {
        "v": 1,
        "phase": "lobby",
        "pause": None,
        "roles": list(roles),
        "ready": {r: False for r in roles},
        "step": 0,
        "steps": {},
        "done": [],
        "skipped": [],
        "end_reason": None,
    }


def _ctx(episode: Episode, state: dict[str, Any]) -> Ctx:
    return Ctx(episode, tuple(state["roles"]), state["steps"])


def current_step(episode: Episode, state: dict[str, Any]) -> Any:
    i = state["step"]
    return episode.steps[i] if 0 <= i < len(episode.steps) else None


def _advance(episode: Episode, state: dict[str, Any], present: set[str]) -> list[str]:
    """Complete steps that are done; returns the ids of completed steps."""
    completed: list[str] = []
    ctx = _ctx(episode, state)
    while state["phase"] == "running":
        step = current_step(episode, state)
        if step is None:
            state["phase"] = "completed"
            break
        mod = MODULES[step.type]
        ss = state["steps"].setdefault(step.id, {})
        done = [mod.role_done(step, ss, r, ctx) for r in ctx.roles]
        finished = all(done) if step.requires == "both" else any(done)
        if not finished:
            break
        if step.requires == "both" and not set(ctx.roles) <= present:
            break  # a `both` step never advances with a participant absent
        (state["skipped"] if mod.all_skipped(step, ss, ctx) else state["done"]).append(step.id)
        completed.append(step.id)
        state["step"] += 1
    return completed


def try_advance(
    episode: Episode, state: dict[str, Any], present: set[str]
) -> tuple[dict[str, Any], list[str]]:
    """Re-check completion, e.g. when an absent participant comes back."""
    new = copy.deepcopy(state)
    return new, _advance(episode, new, present)


def apply(
    episode: Episode,
    state: dict[str, Any],
    role: str,
    action: dict[str, Any],
    present: set[str],
) -> tuple[dict[str, Any], list[str]]:
    """Apply one participant action; returns the new state and ids of steps it completed."""
    kind = action.get("type")
    if kind not in PARTICIPANT_ACTIONS or role not in state["roles"]:
        raise EngineError("room.not_allowed")
    phase = state["phase"]
    if phase not in LIVE:
        raise EngineError("room.ended")
    new = copy.deepcopy(state)

    if kind == "leave":
        new["phase"], new["end_reason"], new["pause"] = "ended", "left", None
        return new, []
    if kind == "stop":  # "I need to stop" (D75): safety pause, only the therapist resumes
        new["pause"] = {"by": "safety", "from": _resume_to(new)}
        new["phase"] = "paused_safety"
        return new, []
    if kind == "pause":
        if phase not in ("running", "lobby"):
            raise EngineError("room.not_running")
        new["pause"] = {"by": "participant", "from": phase}
        new["phase"] = "paused"
        return new, []
    if kind == "resume":
        if phase != "paused" or new["pause"]["by"] in STAFF_HOLDS:
            raise EngineError("room.not_allowed")
        new["phase"], new["pause"] = new["pause"]["from"], None
        return new, _advance(episode, new, present)
    if phase in ("paused", "paused_safety"):
        raise EngineError("room.paused")

    if kind == "ready":
        if phase != "lobby":
            raise EngineError("room.not_allowed")
        new["ready"][role] = True
        if all(new["ready"].values()) and set(new["roles"]) <= present:
            new["phase"] = "running"
        return new, []

    if phase != "running":
        raise EngineError("room.not_running")
    step = current_step(episode, new)
    if step is None or action.get("step_id") != step.id:
        raise EngineError("room.wrong_step")
    ss = new["steps"].setdefault(step.id, {})
    if kind == "hint":
        shown = ss.setdefault("hints", {}).get(role, 0)
        if shown >= len(step.hints):
            raise EngineError("room.no_hint")
        ss["hints"][role] = shown + 1
        return new, []
    if kind == "skip" and not step.skippable:
        raise EngineError("room.not_skippable")
    if kind == "distress" and step.type != "distress_check":
        raise EngineError("room.wrong_step")
    if kind == "submit" and step.type == "distress_check":
        raise EngineError("room.wrong_step")  # distress values arrive as `distress`
    mod = MODULES[step.type]
    mod.act(
        step,
        ss,
        role,
        "skip" if kind == "skip" else "submit",
        action.get("value"),
        _ctx(episode, new),
    )
    return new, _advance(episode, new, present)


def _resume_to(state: dict[str, Any]) -> str:
    if state["phase"] in ("paused", "paused_safety") and state["pause"]:
        return str(state["pause"]["from"])
    return str(state["phase"])


def control(
    episode: Episode, state: dict[str, Any], action: str, present: set[str], *, is_demo: bool
) -> dict[str, Any]:
    """Therapist controls: pause / resume / safety pause / end at any time; reset demo rooms."""
    if action not in THERAPIST_ACTIONS:
        raise EngineError("room.not_allowed")
    new = copy.deepcopy(state)
    phase = state["phase"]
    if action == "reset":
        if not is_demo:
            raise EngineError("room.reset_demo_only")
        return new_state(state["roles"])
    if phase not in LIVE:
        raise EngineError("room.ended")
    if action == "terminate":
        new["phase"], new["end_reason"], new["pause"] = "ended", "therapist_ended", None
    elif action in ("pause", "safety_pause"):
        by = "therapist" if action == "pause" else "safety"
        new["pause"] = {"by": by, "from": _resume_to(new)}
        new["phase"] = "paused" if by == "therapist" else "paused_safety"
    elif action == "resume":
        if phase not in ("paused", "paused_safety"):
            raise EngineError("room.not_paused")
        new["phase"], new["pause"] = new["pause"]["from"], None
        _advance(episode, new, present)
    return new


def disconnect_pause(state: dict[str, Any]) -> dict[str, Any] | None:
    """Automatic pause after ROOM_DISCONNECT_PAUSE_SECONDS; either participant may resume."""
    if state["phase"] != "running":
        return None
    new = copy.deepcopy(state)
    new["pause"] = {"by": "disconnect", "from": "running"}
    new["phase"] = "paused"
    return new


# --- projections -------------------------------------------------------------------------


def _pause_view(state: dict[str, Any]) -> str | None:
    """Participants see only whether they can resume: "pause" (either of you) or "hold"
    (the therapist will pick it up). Safety and therapist holds look the same (D10, no reason)."""
    if state["phase"] not in ("paused", "paused_safety"):
        return None
    return "hold" if state["pause"]["by"] in STAFF_HOLDS else "pause"


def _step_view(episode: Episode, state: dict[str, Any], role: str) -> dict[str, Any] | None:
    step = current_step(episode, state)
    if step is None or state["phase"] == "lobby":
        return None
    ss = state["steps"].get(step.id, {})
    hints_shown = ss.get("hints", {}).get(role, 0)
    base = {
        "id": step.id,
        "type": step.type,
        "title": step.title.model_dump(by_alias=True) if step.title else None,
        "text": step.text.model_dump(by_alias=True),
        "skippable": step.skippable,
        "requires": step.requires,
        "hints": [h.model_dump(by_alias=True) for h in step.hints[:hints_shown]],
        "hints_left": len(step.hints) - hints_shown,
    }
    extra: dict[str, Any] = MODULES[step.type].project(step, ss, role, _ctx(episode, state))
    return base | extra


def project_for_role(
    episode: Episode, state: dict[str, Any], role: str, *, partner_present: bool | None
) -> dict[str, Any]:
    partner = [r for r in state["roles"] if r != role]
    return {
        "phase": "paused" if state["phase"] == "paused_safety" else state["phase"],
        "pause": _pause_view(state),
        "me": role,
        "solo": not partner,
        "ready": {
            "me": state["ready"].get(role, False),
            "partner": state["ready"].get(partner[0], False) if partner else None,
        },
        "partner_present": partner_present if partner else None,
        "step_index": min(state["step"], len(episode.steps)),
        "step_count": len(episode.steps),
        "step": _step_view(episode, state, role)
        if state["phase"] in ("running", "paused", "paused_safety")
        else None,
        "end_reason": "ended" if state["phase"] == "ended" else None,
    }


def board(episode: Episode, state: dict[str, Any]) -> dict[str, Any]:
    """Therapist live board: status only, no private inputs."""
    step = current_step(episode, state)
    ss = state["steps"].get(step.id, {}) if step else {}
    acted = {
        r: bool(ss.get("acts", {}).get(r) or ss.get("acks", {}).get(r)) for r in state["roles"]
    }
    return {
        "phase": state["phase"],
        "pause_by": state["pause"]["by"] if state["pause"] else None,
        "ready": state["ready"],
        "step_index": min(state["step"], len(episode.steps)),
        "step_count": len(episode.steps),
        "step_id": step.id if step else None,
        "step_type": step.type if step else None,
        "acted": acted,
        "end_reason": state["end_reason"],
    }


def rubric_outputs(episode: Episode, state: dict[str, Any]) -> dict[str, dict[str, list[str]]]:
    """Rubric-coded outputs per role and step, for the therapist after the session (§4.2)."""
    out: dict[str, dict[str, list[str]]] = {r: {} for r in state["roles"]}
    for step in episode.steps:
        ss = state["steps"].get(step.id)
        if not ss:
            continue
        data = ss.get("data", {})
        for r in state["roles"]:
            tags: list[str] = []
            if step.type == "private_choice":
                tags = PrivateChoice().rubric(step, ss, r)
            elif step.type in ("cooperative_compose", "retry"):
                src = episode.step(step.of) if step.type == "retry" else step
                ids = data.get(r, [])
                tags = [f.rubric_tag for f in src.fragments if f.id in ids]  # type: ignore[union-attr]
            elif step.type == "transfer_probe":
                tags = [o.rubric_tag for o in step.options if o.id == data.get(r)]
            if ss.get("acts", {}).get(r) == SKIPPED:
                tags = ["skipped"]
            if tags:
                out[r][step.id] = tags
    return out


def shared_tags(episode: Episode, state: dict[str, Any]) -> list[str]:
    """Rubric tags of the shared composition(s) only (§5.3): no private choices."""
    tags: set[str] = set()
    for step in episode.steps:
        if step.type not in ("cooperative_compose", "retry"):
            continue
        src = episode.step(step.of) if step.type == "retry" else step
        data = state["steps"].get(step.id, {}).get("data", {})
        for ids in data.values():
            tags |= {f.rubric_tag for f in src.fragments if f.id in ids}  # type: ignore[union-attr]
    return sorted(tags)
