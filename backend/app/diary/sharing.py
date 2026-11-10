"""Diary sharing (Plan §5.2, §5.6; D66) and the therapist's diary review (Plan §5.8; D15).

Sharing:
- Per entry, chosen fields, with one named family member. The share stores a snapshot of exactly
  what the owner previewed; editing the entry later does not change it.
- Only adolescent -> caregiver is enabled (O6); the direction table is the only switch.
- Revoking removes access at once: every read filters on `revoked_at`, nothing is cached.
- Creating, revoking and reading shares is audited.

Therapist review: one panel per participant, never merged (Plan §5.3). Every read is audited.
"""

from __future__ import annotations

import json
import uuid
from collections import Counter
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.content.loader import ContentBundle
from app.content.models import DiaryFieldType, DiaryTemplate
from app.core import audit
from app.core.errors import bad_request, forbidden, not_found
from app.core.policy import audit_read
from app.core.sessions import utcnow
from app.diary import entries as en
from app.models import DiaryEntry, DiaryShare, Family, FamilyMember, Role, User, UserStatus
from app.models.diary import decode_values
from app.safety.events import family_of
from app.therapist import tasks as tk

# (owner role, recipient role) pairs that may share (O6: caregiver -> adolescent is not enabled).
ALLOWED_DIRECTIONS: frozenset[tuple[Role, Role]] = frozenset({(Role.adolescent, Role.caregiver)})
NOTE_FIELD = "note"
REVIEW_DAYS = (7, 14, 30, 90)


def can_share(user: User) -> bool:
    return any(owner is user.role for owner, _ in ALLOWED_DIRECTIONS)


def recipients(db: Session, user: User) -> list[tuple[FamilyMember, User]]:
    """Family members the user may share with. Callers address them by the membership id, so
    no other user's account id ever reaches a participant (Plan §4.2)."""
    me = family_of(db, user)
    if me is None:
        return []
    rows = db.execute(
        select(FamilyMember, User)
        .join(User, FamilyMember.user_id == User.id)
        .where(
            FamilyMember.family_id == me.family_id,
            User.id != user.id,
            User.status == UserStatus.active,
            User.onboarded_at.is_not(None),
        )
        .order_by(User.display_alias)
    ).all()
    return [(m, u) for m, u in rows if (user.role, u.role) in ALLOWED_DIRECTIONS]


def _shareable(entry: DiaryEntry) -> dict[str, Any]:
    values = en.values_of(entry)
    if entry.note:
        values[NOTE_FIELD] = entry.note
    return values


def create_share(
    db: Session, user: User, entry: DiaryEntry, member_id: uuid.UUID, field_ids: list[str]
) -> DiaryShare:
    if not can_share(user):
        raise forbidden("diary.share_not_allowed")
    recipient = next((u for m, u in recipients(db, user) if m.id == member_id), None)
    if recipient is None:
        raise bad_request("diary.invalid_recipient")
    available = _shareable(entry)
    if not field_ids or len(set(field_ids)) != len(field_ids):
        raise bad_request("diary.no_fields")
    if not set(field_ids) <= set(available):
        raise bad_request("diary.unknown_field")
    snapshot = {f: available[f] for f in field_ids}
    share = DiaryShare(
        entry_id=entry.id,
        owner_id=user.id,
        recipient_id=recipient.id,
        owner_role=entry.role,
        template_version=entry.template_version,
        entry_date=entry.entry_date,
        field_ids=list(field_ids),
        snapshot_json=json.dumps(snapshot, sort_keys=True),
    )
    db.add(share)
    db.flush()
    audit.record(
        db,
        "diary.share.create",
        actor=user,
        target_type="diary_share",
        target_id=share.id,
        details={"entry": str(entry.id), "recipient": str(recipient.id), "fields": field_ids},
    )
    return share


def revoke(db: Session, user: User, share_id: uuid.UUID) -> DiaryShare:
    share = db.get(DiaryShare, share_id)
    if share is None or share.owner_id != user.id:
        raise not_found()
    if share.revoked_at is None:
        share.revoked_at = utcnow()
        audit.record(
            db, "diary.share.revoke", actor=user, target_type="diary_share", target_id=share.id
        )
        db.flush()
    return share


def shares_of_entries(db: Session, entry_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[DiaryShare]]:
    out: dict[uuid.UUID, list[DiaryShare]] = {}
    if not entry_ids:
        return out
    rows = db.execute(
        select(DiaryShare).where(DiaryShare.entry_id.in_(entry_ids)).order_by(DiaryShare.created_at)
    ).scalars()
    for s in rows:
        out.setdefault(s.entry_id, []).append(s)
    return out


def owner_share_view(share: DiaryShare, aliases: dict[uuid.UUID, str]) -> dict[str, Any]:
    return {
        "id": str(share.id),
        "recipient": aliases.get(share.recipient_id, ""),
        "fields": share.field_ids,
        "created_at": share.created_at.isoformat(),
        "revoked_at": share.revoked_at.isoformat() if share.revoked_at else None,
    }


def aliases_of(db: Session, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    rows = db.execute(select(User.id, User.display_alias).where(User.id.in_(ids))).all()
    return {r[0]: r[1] for r in rows}


# --- rendering values in the reader's language ---


def render_items(
    template: DiaryTemplate | None,
    values: dict[str, Any],
    lang: str,
    skill_name: Any,
) -> list[dict[str, Any]]:
    """Fields in template order with labels, for read-only views (shared items, review)."""
    items: list[dict[str, Any]] = []
    if template is None:
        return items
    for f in template.fields:
        if f.id not in values:
            continue
        value = values[f.id]
        display: str | None = None
        if f.type is DiaryFieldType.frequency:
            opt = next((o for o in f.options if o.id == value), None)
            display = en._t(opt.label, lang) if opt else str(value)
        elif f.type is DiaryFieldType.skills:
            display = (
                "、".join(skill_name(s, lang) for s in value)
                if lang == "zh-CN"
                else ", ".join(skill_name(s, lang) for s in value)
            )
        items.append(
            {
                "field_id": f.id,
                "label": en._t(f.label, lang),
                "type": f.type.value,
                "value": value,
                "display": display,
            }
        )
    return items


def shared_with_me(
    db: Session, content: ContentBundle, user: User, skill_name: Any
) -> list[dict[str, Any]]:
    shares = list(
        db.execute(
            select(DiaryShare)
            .where(DiaryShare.recipient_id == user.id, DiaryShare.revoked_at.is_(None))
            .order_by(DiaryShare.entry_date.desc(), DiaryShare.created_at.desc())
        ).scalars()
    )
    aliases = aliases_of(db, {s.owner_id for s in shares})
    out = []
    for s in shares:
        template = content.diary_template(s.owner_role.value, s.template_version)
        out.append(
            {
                "id": str(s.id),
                "from": aliases.get(s.owner_id, ""),
                "entry_date": s.entry_date.isoformat(),
                "shared_at": s.created_at.isoformat(),
                "items": render_items(
                    template, decode_values(s.snapshot_json), user.language, skill_name
                ),
            }
        )
    for owner in {s.owner_id for s in shares}:
        audit_read(
            db,
            user,
            "diary.shared.read",
            target_type="user",
            target_id=owner,
            shares=[str(s.id) for s in shares if s.owner_id == owner],
        )
    return out


# --- therapist review (D15) ---


def family_review(
    db: Session,
    content: ContentBundle,
    therapist: User,
    family: Family,
    days: int,
    skill_name: Any,
) -> dict[str, Any]:
    if days not in REVIEW_DAYS:
        raise bad_request("diary.invalid_range")
    today = en.site_today(db)
    since = today - timedelta(days=days - 1)
    members = [
        m
        for m in db.execute(
            select(FamilyMember).where(FamilyMember.family_id == family.id)
        ).scalars()
        if m.member_role in en.DIARY_ROLES
    ]
    members.sort(key=lambda m: (m.member_role is not Role.adolescent, m.user.display_alias))
    per_week = family.group.diary_days_per_week
    panels = []
    for m in members:
        panel = _panel(db, content, therapist, m.user, since, today, days, skill_name)
        panel["completion"]["days_per_week"] = per_week
        panel["completion"]["expected_days"] = expected_days(days, per_week)
        panels.append(panel)
        audit_read(
            db, therapist, "diary.review", target_type="user", target_id=m.user_id, days=days
        )
    return {
        "from": since.isoformat(),
        "to": today.isoformat(),
        "days": days,
        "days_per_week": per_week,
        "participants": panels,
    }


def expected_days(days: int, per_week: int) -> int:
    """Days with an entry expected over a range, from the group's days-per-week (D70)."""
    return max(1, round(days * per_week / 7))


def _panel(
    db: Session,
    content: ContentBundle,
    therapist: User,
    user: User,
    since: date,
    today: date,
    days: int,
    skill_name: Any,
) -> dict[str, Any]:
    template = content.diary_template(user.role.value)
    rows = en.entries_of(db, user.id, since)
    chronological = sorted(rows, key=lambda e: (e.entry_date, e.created_at))
    scale_fields = (
        [f for f in template.fields if f.type is DiaryFieldType.scale] if template else []
    )
    lang = therapist.language
    series = []
    for f in scale_fields:
        points = []
        for e in chronological:
            v = en.values_of(e).get(f.id)
            if isinstance(v, int):
                points.append(
                    {"date": e.entry_date.isoformat(), "at": e.created_at.isoformat(), "value": v}
                )
        series.append(
            {"field_id": f.id, "label": en._t(f.label, lang), "urge": f.urge, "points": points}
        )
    skills: Counter[str] = Counter()
    used = 0
    for e in rows:
        v = en.values_of(e)
        if v.get("skill_used") is True:
            used += 1
        for s in v.get("skills_used", []) or []:
            skills[s] += 1
    shares = shares_of_entries(db, [e.id for e in rows])
    aliases = aliases_of(db, {s.recipient_id for ss in shares.values() for s in ss})
    homework = tk.homework_of_entries(db, [e.id for e in rows])
    entries = []
    for e in rows:
        v = en.entry_view(e, today, for_staff=True)
        v["homework"] = [t.title for t in homework.get(e.id, [])]
        tpl = content.diary_template(e.role.value, e.template_version)
        v["items"] = render_items(tpl, en.values_of(e), lang, skill_name)
        v["shares"] = [owner_share_view(s, aliases) for s in shares.get(e.id, [])]
        entries.append(v)
    return {
        "user_id": str(user.id),
        "alias": user.display_alias,
        "role": user.role.value,
        "series": series,
        "skill_use": {
            "entries_with_skill": used,
            "skills": [
                {"skill_id": s, "name": skill_name(s, lang), "count": c}
                for s, c in skills.most_common()
            ],
        },
        "completion": {
            "days_with_entries": len({e.entry_date for e in rows}),
            "days": days,
            "entries": len(rows),
        },
        "entries": entries,
    }
