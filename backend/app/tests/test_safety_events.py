"""Safety service and events (Plan §5.7; Phase 2 tasks 1, 4): event creation from screening,
urge threshold, encryption at rest, de-duplication per activity, status workflow and audit.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.content.loader import load_content
from app.core.errors import ApiError
from app.models import (
    AuditLog,
    SafetyCategory,
    SafetyEvent,
    SafetySeverity,
    SafetyStatus,
    Setting,
)
from app.safety import events
from app.safety.screening import RiskLevel
from app.safety.service import Context, SafetyService
from app.settings import get_settings
from app.tests.factories import World

pytestmark = pytest.mark.db


@pytest.fixture(scope="module")
def service() -> SafetyService:
    s = get_settings()
    return SafetyService(load_content(s.content_dir), s)


def _events(db: Session) -> list[SafetyEvent]:
    return list(db.execute(select(SafetyEvent).order_by(SafetyEvent.created_at)).scalars())


def test_high_risk_text_stops_and_creates_an_event(
    db: Session, world: World, service: SafetyService
) -> None:
    teen = world.f1.teen
    out = service.screen_text(db, teen, Context.lesson, "我想自杀", source_ref="lesson-1")
    db.commit()
    assert out.action == "stop" and out.should_stop and out.level is RiskLevel.high
    [e] = _events(db)
    assert e.category is SafetyCategory.risk_disclosure and e.severity is SafetySeverity.high
    assert e.status is SafetyStatus.new and e.activity_stopped and e.channel.value == "keyword"
    assert e.source.value == "lesson" and e.family_id == world.f1.family.id
    assert e.trigger_excerpt == "我想自杀"
    assert str(e.id) == out.event_id


def test_medium_risk_shows_care_card_without_stopping(
    db: Session, world: World, service: SafetyService
) -> None:
    out = service.screen_text(db, world.f1.carers[0], Context.lesson, "I feel hopeless")
    db.commit()
    assert out.action == "care_card" and not out.should_stop
    [e] = _events(db)
    assert e.severity is SafetySeverity.medium and not e.activity_stopped


def test_benign_text_creates_nothing(db: Session, world: World, service: SafetyService) -> None:
    for t in ["笑死我了", "this is so annoying", "", "   "]:
        assert service.screen_text(db, world.f1.teen, Context.diary, t).action == "none"
    assert _events(db) == []


def test_excerpt_and_detail_are_encrypted_at_rest(
    db: Session, world: World, service: SafetyService
) -> None:
    service.screen_text(db, world.f1.teen, Context.diary, "I want to die", source_ref="d1")
    db.commit()
    raw = db.execute(text("SELECT trigger_excerpt, detection_detail FROM safety_event")).one()
    assert raw[0].startswith("v1:") and "die" not in raw[0]
    assert raw[1].startswith("v1:") and "want to die" not in raw[1]


def test_audit_entries_never_contain_the_excerpt(
    db: Session, world: World, service: SafetyService
) -> None:
    service.screen_text(db, world.f1.teen, Context.lesson, "I want to die, secret words")
    db.commit()
    row = db.execute(select(AuditLog).order_by(AuditLog.id.desc()).limit(1)).scalar_one()
    assert row.action == "safety.event_created"
    assert "secret" not in str(row.details) and "die" not in str(row.details)
    assert row.details["subject"] == world.f1.teen.pseudonym_code


def test_multi_turn_context_is_kept_in_the_excerpt(
    db: Session, world: World, service: SafetyService
) -> None:
    out = service.screen_text(db, world.f1.teen, Context.lesson, "活了", recent=["我真的不想"])
    db.commit()
    assert out.action == "stop"
    assert _events(db)[0].trigger_excerpt == "我真的不想\n活了"


def test_repeat_flags_in_one_activity_share_one_event(
    db: Session, world: World, service: SafetyService
) -> None:
    teen = world.f1.teen
    service.screen_text(db, teen, Context.lesson, "I feel hopeless", source_ref="L1")
    service.screen_text(db, teen, Context.lesson, "I hate myself", source_ref="L1")
    service.screen_text(db, teen, Context.lesson, "I want to die", source_ref="L1")
    service.screen_text(db, teen, Context.lesson, "I feel hopeless", source_ref="L2")
    db.commit()
    first, second = _events(db)
    assert first.occurrences == 3 and first.severity is SafetySeverity.high  # only goes up
    assert first.activity_stopped
    assert "hopeless" in (first.trigger_excerpt or "") and "die" in (first.trigger_excerpt or "")
    assert second.source_ref == "L2" and second.occurrences == 1


def test_resolved_events_are_not_reused(db: Session, world: World, service: SafetyService) -> None:
    teen = world.f1.teen
    service.screen_text(db, teen, Context.lesson, "I feel hopeless", source_ref="L1")
    [e] = _events(db)
    events.transition(db, e, world.t1, SafetyStatus.acknowledged)
    events.transition(db, e, world.t1, SafetyStatus.resolved, follow_up="Talked in group.")
    service.screen_text(db, teen, Context.lesson, "I feel hopeless", source_ref="L1")
    db.commit()
    assert len(_events(db)) == 2


# --- urge threshold (D14) ---------------------------------------------------------------------


def test_urge_at_threshold_shows_help_and_raises_event(
    db: Session, world: World, service: SafetyService
) -> None:
    threshold = get_settings().diary_urge_threshold
    assert (
        service.check_diary_urges(
            db, world.f1.teen, {"self_harm_urge": threshold - 1, "suicide_urge": None}, "e0"
        ).action
        == "none"
    )
    out = service.check_diary_urges(db, world.f1.teen, {"suicide_urge": threshold}, "e1")
    db.commit()
    assert out.action == "help"
    [e] = _events(db)
    assert e.category is SafetyCategory.urge_threshold and e.channel.value == "threshold"
    assert e.severity is SafetySeverity.high and e.trigger_excerpt is None


def test_urge_threshold_setting_overrides_the_default(
    db: Session, world: World, service: SafetyService
) -> None:
    db.add(Setting(key="safety.diary_urge_threshold", value=9))
    db.flush()
    assert service.urge_threshold(db) == 9
    assert service.check_diary_urges(db, world.f1.teen, {"self_harm_urge": 8}, "e").action == "none"
    assert service.check_diary_urges(db, world.f1.teen, {"self_harm_urge": 9}, "e").action == "help"


def test_participant_stop_is_a_discomfort_event(
    db: Session, world: World, service: SafetyService
) -> None:
    e = service.record_participant_stop(db, world.f1.carers[0], "joint-1")
    db.commit()
    assert e.category is SafetyCategory.discomfort_or_trauma_cue
    assert e.severity is SafetySeverity.low and e.channel.value == "participant"


# --- workflow ---------------------------------------------------------------------------------


def _one(db: Session, world: World, service: SafetyService) -> SafetyEvent:
    service.screen_text(db, world.f1.teen, Context.lesson, "I want to die")
    db.commit()
    return _events(db)[0]


def test_status_workflow_is_audited(db: Session, world: World, service: SafetyService) -> None:
    e = _one(db, world, service)
    before = db.execute(select(func.count()).select_from(AuditLog)).scalar_one()
    events.transition(db, e, world.t1, SafetyStatus.acknowledged)
    assert e.assignee_id == world.t1.id and e.acknowledged_at is not None
    events.transition(db, e, world.t1, SafetyStatus.in_review, note="Calling family tomorrow.")
    events.transition(db, e, world.t1, SafetyStatus.resolved, follow_up="Safety plan reviewed.")
    db.commit()
    assert e.status is SafetyStatus.resolved and e.resolved_by == world.t1.id
    assert e.follow_up == "Safety plan reviewed." and len(e.notes) == 1
    rows = (
        db.execute(select(AuditLog).where(AuditLog.id > 0).order_by(AuditLog.id.desc()).limit(4))
        .scalars()
        .all()
    )
    actions = [r.action for r in reversed(rows)]
    assert actions == [
        "safety.status_changed",
        "safety.status_changed",
        "safety.note_added",
        "safety.status_changed",
    ]
    assert db.execute(select(func.count()).select_from(AuditLog)).scalar_one() == before + 4
    raw = db.execute(text("SELECT follow_up FROM safety_event")).scalar_one()
    assert raw.startswith("v1:")
    raw_note = db.execute(text("SELECT body FROM safety_event_note")).scalar_one()
    assert raw_note.startswith("v1:")


@pytest.mark.parametrize(
    ("path", "to"),
    [
        ([], SafetyStatus.in_review),
        ([], SafetyStatus.resolved),
        ([SafetyStatus.acknowledged], SafetyStatus.acknowledged),
        ([SafetyStatus.acknowledged, SafetyStatus.resolved], SafetyStatus.in_review),
    ],
)
def test_invalid_transitions_are_refused(
    db: Session, world: World, service: SafetyService, path: list[SafetyStatus], to: SafetyStatus
) -> None:
    e = _one(db, world, service)
    for step in path:
        events.transition(db, e, world.t1, step, follow_up="x")
    with pytest.raises(ApiError) as exc:
        events.transition(db, e, world.t1, to, follow_up="x")
    assert exc.value.detail["code"] == "safety.transition_invalid"  # type: ignore[index]


def test_resolving_requires_a_follow_up(db: Session, world: World, service: SafetyService) -> None:
    e = _one(db, world, service)
    events.transition(db, e, world.t1, SafetyStatus.acknowledged)
    with pytest.raises(ApiError) as exc:
        events.transition(db, e, world.t1, SafetyStatus.resolved, follow_up="  ")
    assert exc.value.detail["code"] == "safety.follow_up_required"  # type: ignore[index]
