"""Diary Cards API (Plan §5.6; Phase 6).

Participants: their own cards only (create, edit within 7 days, revisions, share chosen fields).
Recipients: "Shared with me" (active shares only). Therapists: per-family review (D15), audited.
Admins have no diary access (Plan §4.2: break-glass only, not built).
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.deps import Db, TherapistUser, require_roles
from app.content.loader import ContentBundle
from app.core.errors import conflict, not_found
from app.core.policy import audit_read, ensure_family
from app.diary import entries as en
from app.diary import sharing as sh
from app.models import DiaryEntry, FamilyMember, Role, User
from app.safety.service import SafetyService
from app.therapist import tasks as tk

router = APIRouter(prefix="/api/v1", tags=["diary"])

ParticipantUser = Annotated[User, Depends(require_roles(Role.adolescent, Role.caregiver))]


class Ctx:
    def __init__(self, request: Request) -> None:
        self.content: ContentBundle = request.app.state.content
        self.safety: SafetyService = request.app.state.safety
        self.ai = request.app.state.ai

    def skill_name(self, skill_id: str, lang: str) -> str:
        return str(self.ai.skill_name(skill_id, lang) or skill_id)

    def skills(self, lang: str) -> list[dict[str, Any]]:
        tax = self.ai.taxonomy
        return [
            {
                "id": m.id,
                "name": self.ai.module_name(m.id, lang),
                "skills": [{"id": s.id, "name": self.skill_name(s.id, lang)} for s in m.skills],
            }
            for m in (tax.modules if tax else [])
        ]


C = Annotated[Ctx, Depends(Ctx)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EntryIn(Strict):
    entry_date: date
    values: dict[str, Any] = Field(default_factory=dict)
    note: str | None = Field(default=None, max_length=4000)  # the 1000 limit is checked below
    homework: list[uuid.UUID] = Field(default_factory=list, max_length=40)  # ticked task ids


class EntryUpdate(Strict):
    values: dict[str, Any] = Field(default_factory=dict)
    note: str | None = Field(default=None, max_length=4000)
    revision_no: int = Field(ge=1)
    homework: list[uuid.UUID] | None = Field(default=None, max_length=40)  # None = unchanged


class ShareIn(Strict):
    recipient: uuid.UUID  # the family membership id from /diary/share-recipients
    fields: list[str] = Field(min_length=1, max_length=40)


def _window(db: Db) -> dict[str, str]:
    today = en.site_today(db)
    first, _ = en.editable_dates(today)
    return {"today": today.isoformat(), "editable_from": first.isoformat()}


def _owner_entries(db: Db, rows: list[DiaryEntry]) -> list[dict[str, Any]]:
    today = en.site_today(db)
    shares = sh.shares_of_entries(db, [e.id for e in rows])
    aliases = sh.aliases_of(db, {s.recipient_id for ss in shares.values() for s in ss})
    homework = tk.homework_of_entries(db, [e.id for e in rows])
    out = []
    for e in rows:
        v = en.entry_view(e, today)
        v["shares"] = [sh.owner_share_view(s, aliases) for s in shares.get(e.id, [])]
        v["homework"] = [tk.participant_view(t) for t in homework.get(e.id, [])]
        out.append(v)
    return out


# --- participant: template and entries ---


@router.get("/diary/template")
def template(user: ParticipantUser, db: Db, ctx: C) -> dict[str, Any]:
    t = en.template_for(ctx.content, user.role)
    return {
        "template": en.template_view(t, user.language, ctx.skills(user.language)),
        "can_share": sh.can_share(user),
        **_window(db),
    }


@router.get("/diary/templates/{version}")
def template_version(version: int, user: ParticipantUser, ctx: C) -> dict[str, Any]:
    """Older versions, for editing or viewing entries made with them."""
    t = en.template_for(ctx.content, user.role, version)
    return {"template": en.template_view(t, user.language, ctx.skills(user.language))}


@router.get("/diary/homework")
def diary_homework(
    user: ParticipantUser, db: Db, day: Annotated[date | None, Query(alias="date")] = None
) -> dict[str, Any]:
    """Homework open on an entry's day, for the diary card's checklist (D69)."""
    day = day or en.site_today(db)
    return {"items": [tk.participant_view(t) for t in tk.tasks_for(db, user, day)]}


@router.get("/homework")
def my_homework(user: ParticipantUser, db: Db) -> dict[str, Any]:
    """This week's homework for Home (read-only; ticking happens in the diary)."""
    return {"items": tk.my_homework(db, user, en.site_today(db))}


@router.get("/diary/entries")
def list_entries(
    user: ParticipantUser, db: Db, days: Annotated[int, Query(ge=1, le=90)] = 30
) -> dict[str, Any]:
    today = en.site_today(db)
    rows = en.entries_of(db, user.id, today - timedelta(days=days - 1))
    return {"entries": _owner_entries(db, rows), **_window(db)}


@router.post("/diary/entries", status_code=201)
def create_entry(body: EntryIn, user: ParticipantUser, db: Db, ctx: C) -> dict[str, Any]:
    ticked = tk.validate_homework(db, user, body.entry_date, body.homework)
    res = en.create(
        db,
        ctx.content,
        ctx.safety,
        user,
        body.entry_date,
        body.values,
        body.note,
        has_homework=bool(ticked),
    )
    tk.sync_completions(db, user, res.entry, ticked)
    return {"entry": _owner_entries(db, [res.entry])[0], "safety": res.safety}


@router.get("/diary/entries/{entry_id}")
def get_entry(entry_id: uuid.UUID, user: ParticipantUser, db: Db) -> dict[str, Any]:
    e = en.get_owned(db, user, entry_id)
    return {"entry": _owner_entries(db, [e])[0]}


@router.put("/diary/entries/{entry_id}")
def update_entry(
    entry_id: uuid.UUID, body: EntryUpdate, user: ParticipantUser, db: Db, ctx: C
) -> dict[str, Any]:
    e = en.get_owned(db, user, entry_id)
    if body.homework is None:
        ticked = tk.homework_of_entries(db, [e.id]).get(e.id, [])
    else:
        if not en.is_editable(e.entry_date, en.site_today(db)):
            raise conflict("diary.read_only")
        ticked = tk.validate_homework(db, user, e.entry_date, body.homework, e)
    res = en.update(
        db,
        ctx.content,
        ctx.safety,
        user,
        e,
        body.values,
        body.note,
        body.revision_no,
        has_homework=bool(ticked),
    )
    tk.sync_completions(db, user, e, ticked)
    return {"entry": _owner_entries(db, [res.entry])[0], "safety": res.safety}


@router.get("/diary/entries/{entry_id}/revisions")
def entry_revisions(entry_id: uuid.UUID, user: ParticipantUser, db: Db) -> dict[str, Any]:
    e = en.get_owned(db, user, entry_id)
    return {"revisions": [en.revision_view(r) for r in en.revisions_of(db, e)]}


# --- participant: sharing ---


@router.get("/diary/share-recipients")
def share_recipients(user: ParticipantUser, db: Db) -> dict[str, Any]:
    return {
        "recipients": [
            {"id": str(m.id), "alias": u.display_alias} for m, u in sh.recipients(db, user)
        ]
    }


@router.post("/diary/entries/{entry_id}/shares", status_code=201)
def create_share(
    entry_id: uuid.UUID, body: ShareIn, user: ParticipantUser, db: Db
) -> dict[str, Any]:
    e = en.get_owned(db, user, entry_id)
    s = sh.create_share(db, user, e, body.recipient, body.fields)
    return {"share": sh.owner_share_view(s, sh.aliases_of(db, {s.recipient_id}))}


@router.delete("/diary/shares/{share_id}")
def revoke_share(share_id: uuid.UUID, user: ParticipantUser, db: Db) -> dict[str, Any]:
    s = sh.revoke(db, user, share_id)
    return {"share": sh.owner_share_view(s, sh.aliases_of(db, {s.recipient_id}))}


@router.get("/diary/shared-with-me")
def shared_with_me(user: ParticipantUser, db: Db, ctx: C) -> dict[str, Any]:
    return {"items": sh.shared_with_me(db, ctx.content, user, ctx.skill_name)}


# --- therapist review (D15) ---


@router.get("/families/{family_id}/diary")
def family_diary(
    family_id: uuid.UUID,
    therapist: TherapistUser,
    db: Db,
    ctx: C,
    days: Annotated[int, Query()] = 30,
) -> dict[str, Any]:
    family = ensure_family(db, therapist, family_id)
    return sh.family_review(db, ctx.content, therapist, family, days, ctx.skill_name)


@router.get("/families/{family_id}/diary/entries/{entry_id}/revisions")
def family_entry_revisions(
    family_id: uuid.UUID, entry_id: uuid.UUID, therapist: TherapistUser, db: Db
) -> dict[str, Any]:
    family = ensure_family(db, therapist, family_id)
    e = db.get(DiaryEntry, entry_id)
    member = (
        db.execute(
            select(FamilyMember).where(
                FamilyMember.family_id == family.id, FamilyMember.user_id == e.user_id
            )
        ).scalar_one_or_none()
        if e is not None
        else None
    )
    if e is None or member is None:
        raise not_found()
    audit_read(db, therapist, "diary.revisions.read", target_type="diary_entry", target_id=e.id)
    return {"revisions": [en.revision_view(r) for r in en.revisions_of(db, e)]}
