"""Request/response schemas for the Phase 1 API. Error responses use `{"detail": {"code": ...}}`."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import Role, Suitability, User

Language = Literal["zh-CN", "en"]
ParticipantRole = Literal["adolescent", "caregiver"]
TEXT_SCALES = (1.0, 1.25, 1.5, 2.0)


class In(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- accessibility prefs (mirror frontend/src/app/accessibility.tsx) ------------------------


class A11yPrefs(In):
    reduceMotion: bool | None = None  # noqa: N815 (shared JSON shape with the frontend)
    highContrast: bool = False  # noqa: N815
    calmPalette: bool = False  # noqa: N815
    textScale: float = 1  # noqa: N815
    sound: bool = False
    showIllustrations: bool | None = None  # noqa: N815

    @field_validator("textScale")
    @classmethod
    def _scale(cls, v: float) -> float:
        if v not in TEXT_SCALES:
            raise ValueError(f"textScale must be one of {TEXT_SCALES}")
        return v


# --- users / sessions ------------------------------------------------------------------------


class UserOut(BaseModel):
    id: uuid.UUID
    pseudonym: str
    username: str
    role: Role
    display_alias: str
    language: str
    a11y_prefs: dict[str, Any]
    onboarded: bool
    is_demo: bool

    @classmethod
    def of(cls, u: User) -> UserOut:
        return cls(
            id=u.id,
            pseudonym=u.pseudonym_code,
            username=u.username,
            role=u.role,
            display_alias=u.display_alias,
            language=u.language,
            a11y_prefs=u.a11y_prefs or {},
            onboarded=u.onboarded_at is not None,
            is_demo=u.is_demo,
        )


class SessionOut(BaseModel):
    user: UserOut | None
    csrf_token: str | None = None


class LoginIn(In):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class CodeIn(In):
    code: str = Field(min_length=4, max_length=40)


class CodeInfo(BaseModel):
    purpose: Literal["invite", "reset"]
    role: Role
    expires_at: datetime
    username: str | None = None  # reset codes only: which account is being reset


class RedeemIn(In):
    code: str = Field(min_length=4, max_length=40)
    username: str = Field(min_length=1, max_length=64)
    display_alias: str = Field(min_length=1, max_length=40)
    language: Language
    password: str = Field(min_length=1, max_length=256)


class ResetIn(In):
    code: str = Field(min_length=4, max_length=40)
    password: str = Field(min_length=1, max_length=256)


class PasswordChangeIn(In):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


class MePatch(In):
    display_alias: str | None = Field(default=None, min_length=1, max_length=40)
    language: Language | None = None
    a11y_prefs: A11yPrefs | None = None


# --- consent / onboarding --------------------------------------------------------------------


class ConsentCategoryOut(BaseModel):
    id: str
    required: bool
    default: bool
    grantee: str
    title: str
    summary: str


class OnboardingDoc(BaseModel):
    document_id: str
    version: int
    language: str
    approval: str
    sections: list[dict[str, Any]]
    categories: list[ConsentCategoryOut]


class HelpContact(In):
    label: dict[str, str]
    phone: str = Field(max_length=40)
    hours: dict[str, str] = Field(default_factory=dict)


class SiteHelp(BaseModel):
    name: str
    help_contacts: list[dict[str, Any]]
    service_hours: dict[str, str]
    placeholder: bool  # True until the hospital supplies real contacts (O4)


class OnboardingOut(BaseModel):
    completed: bool
    document: OnboardingDoc
    help: SiteHelp


class OnboardingAccept(In):
    version: int
    language: Language
    decisions: dict[str, bool]


class ConsentState(BaseModel):
    category: str
    required: bool
    granted: bool
    recorded_at: datetime | None


class ConsentChange(In):
    granted: bool


# --- visibility ------------------------------------------------------------------------------


class Viewer(BaseModel):
    kind: Literal["self", "assigned_therapist", "family_member", "admin", "ai_provider", "research"]
    alias: str | None = None
    role: Role | None = None
    sees: list[str]  # message keys, e.g. "visibility.sees.diary_cards"


class VisibilityOut(BaseModel):
    viewers: list[Viewer]


# --- admin -----------------------------------------------------------------------------------


class IssuedCode(BaseModel):
    """A one-time code. It is returned exactly once and never stored in readable form."""

    invitation_id: uuid.UUID
    code: str
    expires_at: datetime


class TherapistOut(BaseModel):
    id: uuid.UUID
    username: str
    display_alias: str
    status: str
    last_login_at: datetime | None
    group_count: int
    content_approver: bool = False


class PendingInvite(BaseModel):
    id: uuid.UUID
    role: Role
    relationship_label: str | None
    expires_at: datetime
    created_at: datetime


class TherapistList(BaseModel):
    therapists: list[TherapistOut]
    pending: list[PendingInvite]


class StatusIn(In):
    status: Literal["active", "disabled"]


class SiteIn(In):
    name: str = Field(min_length=1, max_length=200)
    timezone: str = Field(min_length=1, max_length=64)
    help_contacts: list[HelpContact] = Field(max_length=10)
    service_hours: dict[Language, str]


class SiteOut(BaseModel):
    name: str
    timezone: str
    help_contacts: list[dict[str, Any]]
    service_hours: dict[str, str]
    updated_at: datetime


# --- groups and families ---------------------------------------------------------------------


class GroupIn(In):
    name: str = Field(min_length=1, max_length=120)
    therapist_ids: list[uuid.UUID] = Field(default_factory=list)


class GroupTherapistsIn(In):
    therapist_ids: list[uuid.UUID] = Field(min_length=1)


class GroupSummary(BaseModel):
    id: uuid.UUID
    name: str
    family_count: int
    therapists: list[str]
    is_demo: bool


class FamilyIn(In):
    label: str = Field(min_length=1, max_length=60)


class FamilySummary(BaseModel):
    id: uuid.UUID
    label: str
    member_count: int
    pending_invites: int


class GroupDetail(GroupSummary):
    families: list[FamilySummary]


class MemberOut(BaseModel):
    user_id: uuid.UUID
    pseudonym: str
    display_alias: str
    role: Role
    relationship_label: str | None
    onboarded: bool
    status: str


class DyadOut(BaseModel):
    adolescent_id: uuid.UUID
    caregiver_id: uuid.UUID
    decision: Suitability
    note: str | None
    decided_at: datetime | None


class FamilyDetail(BaseModel):
    id: uuid.UUID
    group_id: uuid.UUID
    label: str
    members: list[MemberOut]
    pending: list[PendingInvite]
    dyads: list[DyadOut]


class InviteIn(In):
    role: ParticipantRole
    relationship_label: str | None = Field(default=None, max_length=40)


class SuitabilityIn(In):
    adolescent_id: uuid.UUID
    caregiver_id: uuid.UUID
    decision: Suitability
    note: str | None = Field(default=None, max_length=1000)


# --- help screen and safety (Phase 2) --------------------------------------------------------


class NoticeOut(BaseModel):
    title: str
    body: str


class HelpDocOut(BaseModel):
    version: int
    language: str
    approval: str
    stop_notice: NoticeOut
    care_card: NoticeOut
    sections: list[dict[str, Any]]


class HelpPageOut(BaseModel):
    document: HelpDocOut
    site: SiteHelp


class PersonRef(BaseModel):
    id: uuid.UUID
    alias: str
    role: Role


class FamilyRef(BaseModel):
    id: uuid.UUID
    label: str
    group_id: uuid.UUID
    group_name: str


class SafetyEventSummary(BaseModel):
    id: uuid.UUID
    category: str
    severity: str
    status: str
    source: str
    channel: str
    subject: PersonRef
    family: FamilyRef | None
    assignee: PersonRef | None
    occurrences: int
    activity_stopped: bool
    created_at: datetime
    updated_at: datetime


class SafetyCounts(BaseModel):
    new: int
    open: int


class SafetyEventList(BaseModel):
    events: list[SafetyEventSummary]
    counts: SafetyCounts


class SafetyNoteOut(BaseModel):
    id: uuid.UUID
    author: PersonRef
    body: str
    created_at: datetime


class SafetyTimelineItem(BaseModel):
    status: str
    at: datetime


class SafetyEventDetail(SafetyEventSummary):
    excerpt: str | None
    matched_terms: list[str]
    created_by: PersonRef | None
    follow_up: str | None
    resolved_by: PersonRef | None
    notes: list[SafetyNoteOut]
    timeline: list[SafetyTimelineItem]
    next_statuses: list[str]  # empty for admins (read-only oversight, D39)


ManualCategory = Literal[
    "discomfort_or_trauma_cue",
    "risk_disclosure",
    "suspected_abuse",
    "parental_coercion",
    "privacy_breach",
    "delayed_clinician_response",
]


class SafetyEventIn(In):
    subject_user_id: uuid.UUID
    category: ManualCategory
    severity: Literal["low", "medium", "high"]
    description: str = Field(min_length=1, max_length=2000)


class SafetyStatusIn(In):
    status: Literal["acknowledged", "in_review", "resolved"]
    note: str | None = Field(default=None, max_length=4000)
    follow_up: str | None = Field(default=None, max_length=4000)


class SafetyNoteIn(In):
    body: str = Field(min_length=1, max_length=4000)


class SafetySubject(BaseModel):
    user: PersonRef
    family: FamilyRef


class ApproverIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content_approver: bool
