"""Individual skill learning (Plan §4.1, §5.5; Phase 5 task 1).

Adolescents: `LearnerProfile`, `MoodRecord`, `TeachingSession` (the D21 phase state machine),
`ChatMessage`, `SkillTest`, `SkillTestQuestion`. Caregivers: `CaregiverLesson`, `PracticeAttempt`,
`QuizAttempt`. Both: `GroupSkillRecord` (D24), `SkillProgress` (non-competitive, §5.13).

Privacy (Plan §4.2, §5.12): everything a participant writes (mood notes, check-in answers, chat
messages, practice answers, reflections) and AI text that responds to it is stored encrypted.
Rows are only ever read by their owner and, per D15, by the group's therapist (audited).
At most one open lesson per learner and engine (D56) is enforced by partial unique indexes.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.crypto import EncryptedText
from app.core.db import Base
from app.models.ai import ContentSource
from app.models.entities import _enum, _now, _uuid_pk

USER_FK = "app_user.id"


# --- profile and mood ---


class Gender(StrEnum):
    male = "male"
    female = "female"
    other = "other"
    prefer_not_to_say = "prefer_not_to_say"


class LearnerProfile(Base):
    """Adolescent profile questionnaire (Plan §5.5.1 step 0; DBT_Revised UserProfile). Private:
    never visible to caregivers; therapist-readable per D15."""

    __tablename__ = "learner_profile"
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(USER_FK, ondelete="CASCADE"), primary_key=True
    )
    gender: Mapped[Gender | None] = mapped_column(_enum(Gender, "learner_gender"), nullable=True)
    age: Mapped[int] = mapped_column(SmallInteger)
    grade: Mapped[str] = mapped_column(String(10))  # grade_7 .. grade_12 (初一–高三)
    hobby_tags: Mapped[list[str]] = mapped_column(JSONB, default=list)
    concern_tags: Mapped[list[str]] = mapped_column(JSONB, default=list)  # max 5
    other_hobby_text: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)
    other_concern_text: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = _now()


class MoodKind(StrEnum):
    before_teaching = "before_teaching"
    after_teaching = "after_teaching"
    after_testing = "after_testing"


class MoodRecord(Base):
    __tablename__ = "mood_record"
    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(USER_FK, ondelete="CASCADE"))
    kind: Mapped[MoodKind] = mapped_column(_enum(MoodKind, "mood_kind"))
    value: Mapped[int] = mapped_column(SmallInteger)  # 1-5
    note: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("teaching_session.id", ondelete="CASCADE"), nullable=True
    )
    test_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("skill_test.id", ondelete="CASCADE"), nullable=True
    )
    created_at: Mapped[datetime] = _now()

    __table_args__ = (Index("ix_mood_record_user", "user_id", "created_at"),)


# --- group review (D24) ---


class GroupSkillRecord(Base):
    """Skills covered in a group session, entered by the therapist (Plan §5.5.3)."""

    __tablename__ = "group_skill_record"
    id: Mapped[uuid.UUID] = _uuid_pk()
    group_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("dbt_group.id", ondelete="CASCADE"))
    session_date: Mapped[date] = mapped_column(Date)
    skill_ids: Mapped[list[str]] = mapped_column(ARRAY(String(60)))
    note: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)  # therapists only
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(USER_FK, ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = _now()

    __table_args__ = (Index("ix_group_skill_record_group", "group_id", "session_date"),)


# --- adolescent teaching process (D21) ---


class LessonSource(StrEnum):
    recommended = "recommended"  # AI recommendation accepted
    alternative = "alternative"  # one of the recommended alternatives
    chosen = "chosen"  # "choose another skill" from the taxonomy
    group_review = "group_review"  # skill fixed from a GroupSkillRecord (D24)
    explore = "explore"  # caregiver "Explore skills"


class TeachingPhase(StrEnum):
    """Same order as DBT_Revised; the server is the only one that advances it."""

    pre_mood_recording = "pre_mood_recording"
    personal_inquiry = "personal_inquiry"
    skill_selection = "skill_selection"  # info_collection is folded in (no separate wait)
    rag_retrieval_for_teaching = "rag_retrieval_for_teaching"
    teaching = "teaching"
    summary = "summary"  # post-lesson mood + summary shown
    done = "done"


class LessonStatus(StrEnum):
    ongoing = "ongoing"  # includes paused (D56): resumable any time
    completed = "completed"
    user_terminated = "user_terminated"
    stopped_by_safety = "stopped_by_safety"


TERMINAL_STATUSES = (
    LessonStatus.completed,
    LessonStatus.user_terminated,
    LessonStatus.stopped_by_safety,
)


class TeachingSession(Base):
    __tablename__ = "teaching_session"
    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(USER_FK, ondelete="CASCADE"))
    language: Mapped[str] = mapped_column(String(8))
    phase: Mapped[TeachingPhase] = mapped_column(
        _enum(TeachingPhase, "teaching_phase"), default=TeachingPhase.pre_mood_recording
    )
    status: Mapped[LessonStatus] = mapped_column(
        _enum(LessonStatus, "lesson_status"), default=LessonStatus.ongoing
    )
    source: Mapped[LessonSource | None] = mapped_column(
        _enum(LessonSource, "lesson_source"), nullable=True
    )
    group_record_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("group_skill_record.id", ondelete="SET NULL"), nullable=True
    )
    # Check-in (D22): optional; skipped/answered is recorded, the answer is encrypted.
    inquiry: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)  # JSON
    checkin_skipped: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    personal_context: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)
    # Recommendation (JSON: module, skill, reason, difficulty, alternatives, repeat, source)
    recommendation: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)
    selected_module: Mapped[str | None] = mapped_column(String(40), nullable=True)
    selected_skill: Mapped[str | None] = mapped_column(String(60), nullable=True)
    plan: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)  # steps, source
    rag_chunk_ids: Mapped[list[str]] = mapped_column(ARRAY(String(36)), default=list)
    summary: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)  # JSON
    understanding: Mapped[str | None] = mapped_column(String(20), nullable=True)  # internal
    turns: Mapped[int] = mapped_column(Integer, default=0)  # student messages in teaching
    # Claimed while a chat turn streams, so a double submit cannot start a second one.
    busy_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pre_mood_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("mood_record.id", ondelete="SET NULL", use_alter=True), nullable=True
    )
    post_mood_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("mood_record.id", ondelete="SET NULL", use_alter=True), nullable=True
    )
    started_at: Mapped[datetime] = _now()
    last_active_at: Mapped[datetime] = _now()
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_teaching_session_user", "user_id", "started_at"),
        Index(
            "ux_teaching_session_one_open",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'ongoing'"),
        ),
    )


class ChatRole(StrEnum):
    student = "student"
    coach = "coach"


class ChatMessage(Base):
    __tablename__ = "chat_message"
    id: Mapped[uuid.UUID] = _uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("teaching_session.id", ondelete="CASCADE")
    )
    seq: Mapped[int] = mapped_column(Integer)
    role: Mapped[ChatRole] = mapped_column(_enum(ChatRole, "chat_role"))
    content: Mapped[str] = mapped_column(EncryptedText)
    question: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)
    message_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    teaching_step: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[ContentSource | None] = mapped_column(
        _enum(ContentSource, "ai_content_source"), nullable=True
    )
    created_at: Mapped[datetime] = _now()

    __table_args__ = (UniqueConstraint("session_id", "seq", name="uq_chat_message_seq"),)


class SkillTestStatus(StrEnum):
    generating = "generating"  # background generation (with retries) in progress
    ready = "ready"
    completed = "completed"
    unavailable = "unavailable"  # every generation attempt failed; nothing to answer
    user_terminated = "user_terminated"
    stopped_by_safety = "stopped_by_safety"


class SkillTest(Base):
    __tablename__ = "skill_test"
    id: Mapped[uuid.UUID] = _uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("teaching_session.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(USER_FK, ondelete="CASCADE"))
    attempt_no: Mapped[int] = mapped_column(Integer)
    status: Mapped[SkillTestStatus] = mapped_column(
        _enum(SkillTestStatus, "skill_test_status"), default=SkillTestStatus.generating
    )
    generation_attempts: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[ContentSource | None] = mapped_column(
        _enum(ContentSource, "ai_content_source"), nullable=True
    )
    total_questions: Mapped[int] = mapped_column(Integer, default=0)
    correct_count: Mapped[int] = mapped_column(Integer, default=0)
    mastered: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    post_mood_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("mood_record.id", ondelete="SET NULL", use_alter=True), nullable=True
    )
    created_at: Mapped[datetime] = _now()
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("session_id", "attempt_no", name="uq_skill_test_attempt"),
        Index("ix_skill_test_user", "user_id", "created_at"),
    )


class SkillTestQuestion(Base):
    __tablename__ = "skill_test_question"
    id: Mapped[uuid.UUID] = _uuid_pk()
    test_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("skill_test.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(SmallInteger)
    scenario: Mapped[str] = mapped_column(String(400))
    question: Mapped[str] = mapped_column(String(300))
    options: Mapped[list[str]] = mapped_column(JSONB)
    correct_index: Mapped[int] = mapped_column(SmallInteger)
    explanation: Mapped[str] = mapped_column(String(500))
    answer_index: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    is_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint("test_id", "position", name="uq_skill_test_question_pos"),)


# --- caregiver structured lessons (D8/D23) ---


class CaregiverStep(StrEnum):
    explain = "explain"
    practice = "practice"
    quiz = "quiz"
    wrap_up = "wrap_up"
    done = "done"


class CaregiverLesson(Base):
    __tablename__ = "caregiver_lesson"
    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(USER_FK, ondelete="CASCADE"))
    language: Mapped[str] = mapped_column(String(8))
    skill_id: Mapped[str] = mapped_column(String(60))
    source: Mapped[LessonSource] = mapped_column(_enum(LessonSource, "lesson_source"))
    group_record_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("group_skill_record.id", ondelete="SET NULL"), nullable=True
    )
    step: Mapped[CaregiverStep] = mapped_column(
        _enum(CaregiverStep, "caregiver_step"), default=CaregiverStep.explain
    )
    status: Mapped[LessonStatus] = mapped_column(
        _enum(LessonStatus, "lesson_status"), default=LessonStatus.ongoing
    )
    # Generated (non-personal) content snapshots, so a resumed lesson shows the same text.
    explanation: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    variant: Mapped[str] = mapped_column(String(20), default="standard")
    items: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    quiz: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    reflection: Mapped[str | None] = mapped_column(EncryptedText, nullable=True)
    reflection_skipped: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    started_at: Mapped[datetime] = _now()
    last_active_at: Mapped[datetime] = _now()
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_caregiver_lesson_user", "user_id", "started_at"),
        Index(
            "ux_caregiver_lesson_one_open",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'ongoing'"),
        ),
    )


class PracticeAttempt(Base):
    __tablename__ = "practice_attempt"
    id: Mapped[uuid.UUID] = _uuid_pk()
    lesson_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("caregiver_lesson.id", ondelete="CASCADE")
    )
    item_index: Mapped[int] = mapped_column(SmallInteger)
    attempt_no: Mapped[int] = mapped_column(SmallInteger)  # 1 or 2 ("second opportunity")
    answer: Mapped[str] = mapped_column(EncryptedText)
    category: Mapped[str] = mapped_column(String(40))  # rubric tag, internal
    feedback: Mapped[str] = mapped_column(EncryptedText)  # JSON: what_worked, why, try_next
    source: Mapped[ContentSource] = mapped_column(_enum(ContentSource, "ai_content_source"))
    created_at: Mapped[datetime] = _now()

    __table_args__ = (
        UniqueConstraint("lesson_id", "item_index", "attempt_no", name="uq_practice_attempt"),
    )


class QuizAttempt(Base):
    __tablename__ = "quiz_attempt"
    id: Mapped[uuid.UUID] = _uuid_pk()
    lesson_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("caregiver_lesson.id", ondelete="CASCADE")
    )
    question_index: Mapped[int] = mapped_column(SmallInteger)
    answer_index: Mapped[int] = mapped_column(SmallInteger)
    is_correct: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = _now()

    __table_args__ = (UniqueConstraint("lesson_id", "question_index", name="uq_quiz_attempt"),)


# --- progress (non-competitive, Plan §5.13) ---


class SkillProgress(Base):
    """Per user x skill. Only ever grows; never compared across people or days."""

    __tablename__ = "skill_progress"
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(USER_FK, ondelete="CASCADE"), primary_key=True
    )
    skill_id: Mapped[str] = mapped_column(String(60), primary_key=True)
    lessons_completed: Mapped[int] = mapped_column(Integer, default=0)
    # Adolescent tests: None = never tested; internal mastery flag (≥ 4/5).
    mastered: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # Caregiver quick check: practised | understood | worth_revisiting
    quiz_outcome: Mapped[str | None] = mapped_column(String(20), nullable=True)
    practice_categories: Mapped[dict[str, int]] = mapped_column(JSONB, default=dict)
    first_practised_at: Mapped[datetime] = _now()
    last_practised_at: Mapped[datetime] = _now()
