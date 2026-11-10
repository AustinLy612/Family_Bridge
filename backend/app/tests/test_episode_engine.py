"""Episode schema v0 and the pure room engine (Plan §5.9), without a database.

- The schema rejects broken scripts (unknown references, missing roles, wrong version).
- The Lantern Forest Level 2 conversion runs end to end, so the schema can carry a real script.
- Feedback comes from authored rubric rules; reveals follow the declared fields only.
- The automatic disconnect pause is a participant-resumable pause; staff holds are not.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from app.content.loader import load_content
from app.content.models import Episode
from app.joint import engine
from app.joint.steps import MODULES, EngineError

CONTENT = Path(__file__).resolve().parents[3] / "content"
BOTH = {"adolescent", "caregiver"}


@pytest.fixture(scope="module")
def bundle() -> Any:
    return load_content(CONTENT)


def raw(name: str) -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(
        (CONTENT / "episodes" / name / "v1.yaml").read_text(encoding="utf-8")
    )
    return data


def run(ep: Episode, st: dict[str, Any], role: str, kind: str, value: Any = None) -> dict[str, Any]:
    step = engine.current_step(ep, st)
    action: dict[str, Any] = {"type": kind}
    if kind not in ("ready", "pause", "resume", "leave", "stop"):
        action["step_id"] = step.id
    if value is not None:
        action["value"] = value
    return engine.apply(ep, st, role, action, BOTH)[0]


def both(
    ep: Episode, st: dict[str, Any], kind: str, a: Any = None, c: Any = None
) -> dict[str, Any]:
    st = run(ep, st, "adolescent", kind, a)
    return run(ep, st, "caregiver", kind, c)


def test_schema_rejects_broken_scripts() -> None:
    data = raw("demo-stub-episode")
    bad_ref = {
        **data,
        "steps": [s | ({"source": "nope"} if s["id"] == "s5" else {}) for s in data["steps"]],
    }
    with pytest.raises(ValidationError, match="source must name"):
        Episode.model_validate(bad_ref)
    one_role = {
        **data,
        "steps": [
            s | ({"roles": {"adolescent": s["roles"]["adolescent"]}} if s["id"] == "s3" else {})
            for s in data["steps"]
        ],
    }
    with pytest.raises(ValidationError, match="both roles"):
        Episode.model_validate(one_role)
    with pytest.raises(ValidationError, match="schema_version"):
        Episode.model_validate({**data, "schema_version": 1})
    with pytest.raises(ValidationError):
        Episode.model_validate(
            {**data, "steps": [{"id": "x", "type": "teleport", "text": data["title"]}]}
        )


def test_every_step_type_is_in_the_stub(bundle: Any) -> None:
    ep = bundle.episode("demo-stub-episode", 1)
    assert {s.type for s in ep.steps} == set(MODULES)
    assert all(e.approval.status.value == "demo" for e in bundle.episodes)


def test_lantern_forest_level_two_runs_end_to_end(bundle: Any) -> None:
    ep = bundle.episode("demo-lantern-forest-l2", 1)
    st = engine.new_state(["adolescent", "caregiver"])
    st = both(ep, st, "ready")
    assert st["phase"] == "running"
    st = both(ep, st, "submit")  # intro
    st = both(ep, st, "distress", 3, 5)
    st = both(ep, st, "submit", "disappointed", "frustrated")  # emotion (choice text revealed)
    view = engine.project_for_role(ep, st, "caregiver", partner_present=True)
    assert view["step"]["revealed"]["adolescent"]["text"]["en"] == "Disappointed"
    st = both(ep, st, "submit")
    st = both(ep, st, "submit", "a-reflect", "c-demo")  # response (only rubric tags revealed)
    view = engine.project_for_role(ep, st, "adolescent", partner_present=True)
    assert view["step"]["revealed"]["caregiver"] == {"rubric_tag": "problem_solving"}
    st = both(ep, st, "submit")
    st = both(ep, st, "submit", ["notice", "name"], ["ask", "choice"])  # compose
    fb = engine.project_for_role(ep, st, "adolescent", partner_present=True)["step"]
    assert fb["feedback"]["title"]["en"] == "The lantern hears both of you"
    assert len(fb["feedback"]["notes"]) == 4
    st = both(ep, st, "submit")
    st = both(ep, st, "submit", ["fix"], ["push"])  # retry, then review its feedback
    review = engine.project_for_role(ep, st, "caregiver", partner_present=True)["step"]
    assert review["phase"] == "review" and review["feedback"]["title"]["en"] == "A first spark"
    st = both(ep, st, "submit")
    st = both(ep, st, "submit", "fox-validate", "fox-fix")
    st = both(ep, st, "skip")
    assert st["phase"] == "completed" and st["skipped"] == ["reflection"]
    assert engine.shared_tags(ep, st) == [
        "agency",
        "curiosity",
        "observation",
        "pressure",
        "problem_solving",
        "validation",
    ]
    rubric = engine.rubric_outputs(ep, st)
    assert rubric["caregiver"]["response"] == ["problem_solving"]
    assert rubric["adolescent"]["transfer"] == ["validation"]


def test_pauses_and_holds(bundle: Any) -> None:
    ep = bundle.episode("demo-stub-episode", 1)
    st = both(ep, engine.new_state(["adolescent", "caregiver"]), "ready")
    paused = engine.disconnect_pause(st)
    assert paused is not None and paused["pause"]["by"] == "disconnect"
    assert (
        engine.project_for_role(ep, paused, "adolescent", partner_present=False)["pause"] == "pause"
    )
    resumed = run(ep, paused, "caregiver", "resume")
    assert resumed["phase"] == "running"
    held = engine.control(ep, st, "pause", BOTH, is_demo=True)
    with pytest.raises(EngineError, match=r"room.not_allowed"):
        run(ep, held, "adolescent", "resume")
    stopped = run(ep, st, "adolescent", "stop")
    view = engine.project_for_role(ep, stopped, "caregiver", partner_present=True)
    assert view["phase"] == "paused" and view["pause"] == "hold"  # same as a therapist hold
    assert engine.control(ep, stopped, "resume", BOTH, is_demo=True)["phase"] == "running"
    with pytest.raises(EngineError, match=r"room.reset_demo_only"):
        engine.control(ep, st, "reset", BOTH, is_demo=False)
    ended = run(ep, st, "caregiver", "leave")
    with pytest.raises(EngineError, match=r"room.ended"):
        run(ep, ended, "adolescent", "resume")


def test_compose_rules_and_unskippable(bundle: Any) -> None:
    ep = bundle.episode("demo-stub-episode", 1)
    st = both(ep, engine.new_state(["adolescent", "caregiver"]), "ready")
    st = both(ep, st, "submit")
    st = both(ep, st, "skip")
    st = both(ep, st, "skip")
    assert engine.current_step(ep, st).id == "s4"
    for bad in (["f-hello", "f-ask", "f-notice"], [], ["nope"], "f-hello"):
        with pytest.raises(EngineError, match=r"room.invalid_value"):
            run(ep, st, "adolescent", "submit", bad)
    ep2 = Episode.model_validate(
        {
            **raw("demo-stub-episode"),
            "steps": [raw("demo-stub-episode")["steps"][0] | {"skippable": False}],
        }
    )
    st2 = both(ep2, engine.new_state(["adolescent", "caregiver"]), "ready")
    with pytest.raises(EngineError, match=r"room.not_skippable"):
        run(ep2, st2, "adolescent", "skip")
