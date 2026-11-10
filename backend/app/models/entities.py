"""Phase 1 entities (Plan §4.1): Site, User, Group, Family, FamilyMember, Invitation,
ConsentRecord, DyadSuitability, AuditLog, Setting, plus AuthSession and a minimal ResearchEvent
(login metric required by Plan §5.1; extended in Phase 9).

Identifiers are random UUIDs; users carry a random `pseudonym_code` used in logs and exports.
No real names are required anywhere.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.crypto import EncryptedText
from app.core.db import Base


def _enum(e: type[StrEnum], name: str) -> SAEnum:
    return SAEnum(e, name=name, values_callable=lambda x: [m.value for m in x])


class Role(StrEnum):
    admin = "admin"
    therapist = "therapist"
    adolescent = "adolescent"
    caregiver = "caregiver"


PARTICIPANT_ROLES = frozenset({Role.adolescent, Role.caregiver})


class UserStatus(StrEnum):
    active = "active"
    disabled = "disabled"


class CodePurpose(StrEnum):
    invite = "invite"
    reset = "reset"


class Suitability(StrEnum):
    suitable = "suitable"
    not_suitable = "not_suitable"
    not_assessed = "not_assessed"


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )


def _now() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Site(Base):
    __tablename__ = "site"
    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(200))
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Shanghai")
    # [{"label": {"zh-CN":..,"en":..}, "phone": "...", "hours": {...}}] — placeholders (O4)
    help_contacts: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    service_hours: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = _now()


class User(Base):
    __tablename__ = "app_user"
    id: Mapped[uuid.UUID] = _uuid_pk()
    pseudonym_code: Mapped[str] = mapped_column(String(16), unique=True)
    username: Mapped[str] = mapped_column(String(32), unique=True)  # stored lower-case (D29)
    role: Mapped[Role] = mapped_column(_enum(Role, "user_role"))
    display_alias: Mapped[str] = mapped_column(String(40))
    language: Mapped[str] = mapped_column(String(8), default="zh-CN")
    a11y_prefs: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    password_hash: Mapped[str] = mapped_column(Text)
    status: Mapped[UserStatus] = mapped_column(
        _enum(UserStatus, "user_status"), default=UserStatus.active
    )
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    # Therapists only: may approve or retire episode versions (Plan §4.2 `content_approver`).
    content_approver: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Participants must finish onboarding consent; staff accounts are created onboarded.
    onboarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now()

    __table_args__ = (Index("ux_app_user_username_lower", func.lower(username), unique=True),)

    @property
    def is_participant(self) -> bool:
        return self.role in PARTICIPANT_ROLES


class Group(Base):
    __tablename__ = "dbt_group"
    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(120))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"))
    created_at: Mapped[datetime] = _now()
    # Diary expectation (D70): days per week with at least one entry, 1-7 (7 = daily).
    diary_days_per_week: Mapped[int] = mapped_column(Integer, default=7, server_default="7")
    therapists: Mapped[list[GroupTherapist]] = relationship(cascade="all, delete-orphan")
    families: Mapped[list[Family]] = relationship(back_populates="group")
    __table_args__ = (
        CheckConstraint("diary_days_per_week BETWEEN 1 AND 7", name="ck_group_diary_days"),
    )


class GroupTherapist(Base):
    __tablename__ = "group_therapist"
    group_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("dbt_group.id"), primary_key=True)
    therapist_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"), primary_key=True)


class Family(Base):
    __tablename__ = "family"
    id: Mapped[uuid.UUID] = _uuid_pk()
    group_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("dbt_group.id"), index=True)
    label: Mapped[str] = mapped_column(String(60))  # pseudonymous label chosen by the therapist
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = _now()
    group: Mapped[Group] = relationship(back_populates="families")
    members: Mapped[list[FamilyMember]] = relationship(back_populates="family")


class FamilyMember(Base):
    __tablename__ = "family_member"
    id: Mapped[uuid.UUID] = _uuid_pk()
    family_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("family.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"), unique=True)
    member_role: Mapped[Role] = mapped_column(_enum(Role, "user_role"))
    relationship_label: Mapped[str | None] = mapped_column(EncryptedText)
    family: Mapped[Family] = relationship(back_populates="members")
    user: Mapped[User] = relationship()


class Invitation(Base):
    """One-time code: invitation (new account) or password reset (D30). Only a digest is stored."""

    __tablename__ = "invitation"
    id: Mapped[uuid.UUID] = _uuid_pk()
    purpose: Mapped[CodePurpose] = mapped_column(_enum(CodePurpose, "code_purpose"))
    code_digest: Mapped[str] = mapped_column(String(64), unique=True)
    intended_role: Mapped[Role] = mapped_column(_enum(Role, "user_role"))
    family_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("family.id"), index=True)
    target_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    relationship_label: Mapped[str | None] = mapped_column(EncryptedText)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    used_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"))
    created_at: Mapped[datetime] = _now()


class ConsentRecord(Base):
    """Append-only per-category consent decisions.

    The latest row per (user, category) is the current decision.
    """

    __tablename__ = "consent_record"
    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"), index=True)
    document_id: Mapped[str] = mapped_column(String(64))
    document_version: Mapped[int] = mapped_column(Integer)
    document_sha256: Mapped[str] = mapped_column(String(64))
    category: Mapped[str] = mapped_column(String(48))
    grantee: Mapped[str] = mapped_column(String(48))
    granted: Mapped[bool] = mapped_column(Boolean)
    recorded_at: Mapped[datetime] = _now()
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_consent_user_category", "user_id", "category", "recorded_at"),)


class DyadSuitability(Base):
    __tablename__ = "dyad_suitability"
    id: Mapped[uuid.UUID] = _uuid_pk()
    family_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("family.id"), index=True)
    adolescent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"))
    caregiver_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"))
    decision: Mapped[Suitability] = mapped_column(
        _enum(Suitability, "suitability"), default=Suitability.not_assessed
    )
    note: Mapped[str | None] = mapped_column(EncryptedText)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("adolescent_id", "caregiver_id"),)


class AuditLog(Base):
    """Append-only, hash-chained (Plan §5.12). UPDATE/DELETE are blocked by a DB trigger."""

    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    actor_role: Mapped[str | None] = mapped_column(String(16))
    action: Mapped[str] = mapped_column(String(64))
    target_type: Mapped[str | None] = mapped_column(String(48))
    target_id: Mapped[str | None] = mapped_column(String(64))
    request_id: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64), unique=True)


class Setting(Base):
    """Typed, audited configuration (thresholds, SLAs, retention) — values validated by callers."""

    __tablename__ = "setting"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    updated_at: Mapped[datetime] = _now()


class AuthSession(Base):
    """Server-side session; the cookie carries a random token, only its digest is stored."""

    __tablename__ = "auth_session"
    id: Mapped[uuid.UUID] = _uuid_pk()
    token_digest: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"), index=True)
    created_at: Mapped[datetime] = _now()
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ResearchEvent(Base):
    """Pseudonymous instrumentation event (Plan §5.10). No free text, no identities."""

    __tablename__ = "research_event"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime] = _now()
    event_type: Mapped[str] = mapped_column(String(48), index=True)
    subject_pseudonym: Mapped[str | None] = mapped_column(String(16))
    subject_role: Mapped[str | None] = mapped_column(String(16))
    props: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
