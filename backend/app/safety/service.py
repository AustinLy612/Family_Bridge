"""Safety service API (Plan §5.7; Phase 2 task 4).

Hooks for the features that accept participant input (lessons in Phase 5, Diary Cards in
Phase 6, joint sessions in Phase 8):

- `screen_text(db, user, context, text, ...)` screens free text, raises a `SafetyEvent` when
  needed and returns what the participant's screen must do next.
- `check_diary_urges(db, user, scores, entry_id)` applies the urge threshold (D14).
- `record_participant_stop(db, user, session_ref)` logs "I need to stop" in a joint session as
  a discomfort event, not a risk event.

Outcomes for the participant's screen (`SafetyOutcome.action`):
- "stop": stop the current AI activity and show the help screen with the stop notice;
- "help": show the help screen (urge threshold reached after a diary entry is saved);
- "care_card": keep going, but show the gentle care-team card (medium risk);
- "none": nothing to show.
The participant is never told an event id, category or score (Plan §4.2: help screen only).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from sqlalchemy.orm import Session

from app.content.loader import ContentBundle
from app.models import (
    DetectionChannel,
    SafetyCategory,
    SafetyEvent,
    SafetySeverity,
    SafetySource,
    Setting,
    User,
)
from app.safety.events import raise_event
from app.safety.screening import (
    KeywordMatcher,
    NoAssessor,
    RiskAssessor,
    RiskLevel,
    ScreenResult,
    screen,
)
from app.settings import Settings

URGE_THRESHOLD_KEY = "safety.diary_urge_threshold"
URGE_FIELDS = ("self_harm_urge", "suicide_urge")

Action = Literal["none", "care_card", "stop", "help"]


class Context(StrEnum):
    lesson = "lesson"
    diary = "diary"
    joint = "joint"


@dataclass(frozen=True)
class SafetyOutcome:
    action: Action
    level: RiskLevel
    event_id: str | None = None  # for the calling feature's own records; never sent to the client

    @property
    def should_stop(self) -> bool:
        return self.action == "stop"


NONE = SafetyOutcome("none", RiskLevel.none)


class SafetyService:
    def __init__(
        self,
        content: ContentBundle,
        settings: Settings,
        assessor: RiskAssessor | None = None,
    ) -> None:
        keywords = content.risk_keywords
        if keywords is None:
            raise RuntimeError("content/safety/risk_keywords.yaml is required")
        self.matcher = KeywordMatcher(keywords)
        self.settings = settings
        self.assessor: RiskAssessor = assessor or NoAssessor()

    # --- free text -------------------------------------------------------------------------

    def classify(
        self, text: str, *, recent: Sequence[str] = (), language: str = "zh-CN"
    ) -> ScreenResult:
        return screen(self.matcher, text, recent=recent, language=language, assessor=self.assessor)

    def screen_text(
        self,
        db: Session,
        user: User,
        context: Context,
        text: str,
        *,
        recent: Sequence[str] = (),
        source_ref: str | None = None,
    ) -> SafetyOutcome:
        """Screen one message; `recent` is the same user's earlier messages in this activity."""
        if not text.strip():
            return NONE
        result = self.classify(text, recent=recent, language=user.language)
        if result.level in (RiskLevel.none, RiskLevel.low):
            return SafetyOutcome("none", result.level)
        severity = SafetySeverity.high if result.should_stop else SafetySeverity.medium
        window = [m for m in recent[-3:] if m and m.strip()]
        excerpt = "\n".join([*window, text]) if window else text
        event = raise_event(
            db,
            subject=user,
            category=SafetyCategory.risk_disclosure,
            severity=severity,
            source=SafetySource(context.value),
            channel=DetectionChannel(result.channel or "keyword"),
            excerpt=excerpt,
            detail={
                "terms": result.terms,
                "level": result.level.value,
                "keywords_version": self.matcher.version,
                **(
                    {
                        "risk_type": result.assessment.risk_type,
                        "reasoning": result.assessment.reasoning,
                    }
                    if result.assessment
                    else {}
                ),
            },
            source_ref=source_ref,
            activity_stopped=result.should_stop,
        )
        action: Action = "stop" if result.should_stop else "care_card"
        return SafetyOutcome(action, result.level, str(event.id))

    # --- diary urge scores (D14) -----------------------------------------------------------

    def urge_threshold(self, db: Session) -> int:
        row = db.get(Setting, URGE_THRESHOLD_KEY)
        if row is not None and isinstance(row.value, int) and 1 <= row.value <= 10:
            return row.value
        return self.settings.diary_urge_threshold

    def check_diary_urges(
        self, db: Session, user: User, scores: Mapping[str, int | None], entry_id: str
    ) -> SafetyOutcome:
        threshold = self.urge_threshold(db)
        over = {f: v for f in URGE_FIELDS if (v := scores.get(f)) is not None and v >= threshold}
        if not over:
            return NONE
        event = raise_event(
            db,
            subject=user,
            category=SafetyCategory.urge_threshold,
            severity=SafetySeverity.high,
            source=SafetySource.diary,
            channel=DetectionChannel.threshold,
            detail={"fields": over, "threshold": threshold},
            source_ref=entry_id,
        )
        return SafetyOutcome("help", RiskLevel.high, str(event.id))

    # --- joint sessions: "I need to stop" ---------------------------------------------------

    def record_participant_stop(self, db: Session, user: User, session_ref: str) -> SafetyEvent:
        return raise_event(
            db,
            subject=user,
            category=SafetyCategory.discomfort_or_trauma_cue,
            severity=SafetySeverity.low,
            source=SafetySource.joint,
            channel=DetectionChannel.participant,
            source_ref=session_ref,
            created_by=user,
        )
