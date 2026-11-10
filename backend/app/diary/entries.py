"""Diary entries (Plan §5.6; D63–D66).

- Values are validated against the template version the entry was made with. Skipped fields are
  simply absent; fields hidden by `show_if` are dropped when their yes/no field is not "yes".
- Entries can be added or edited for today and the previous 6 days in the site's time zone
  (D65); older entries are read-only. An entry added after its day is marked late for research
  only — the participant never sees that flag (§8.4).
- Every save appends a full revision (correction log).
- After saving: the note is risk-screened and the urge threshold applies (D14). No AI processing
  of diary values (Plan §5.6).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.content.loader import ContentBundle
from app.content.models import (
    DIARY_NOTE_MAX,
    DIARY_URGE_FIELDS,
    SCALE_MAX,
    SCALE_MIN,
    DiaryField,
    DiaryFieldType,
    DiaryTemplate,
)
from app.core.errors import bad_request, conflict, not_found
from app.core.sessions import utcnow
from app.models import DiaryEntry, DiaryRevision, Role, User
from app.models.diary import decode_values
from app.safety.service import Context, SafetyOutcome, SafetyService
from app.services.site import get_site

EDIT_DAYS = 7  # today and the previous 6 days (D65)
DIARY_ROLES = (Role.adolescent, Role.caregiver)


# --- dates ---


def site_today(db: Session) -> date:
    site = get_site(db)
    try:
        tz = ZoneInfo(site.timezone if site else "Asia/Shanghai")
    except ZoneInfoNotFoundError:
        tz = ZoneInfo("Asia/Shanghai")
    return datetime.now(tz).date()


def editable_dates(today: date) -> tuple[date, date]:
    return today - timedelta(days=EDIT_DAYS - 1), today


def is_editable(entry_date: date, today: date) -> bool:
    first, last = editable_dates(today)
    return first <= entry_date <= last


# --- templates ---


def template_for(content: ContentBundle, role: Role, version: int | None = None) -> DiaryTemplate:
    t = content.diary_template(role.value, version)
    if t is None:
        raise not_found("diary.no_template")
    return t


def taxonomy_ids(content: ContentBundle) -> set[str]:
    tax = content.taxonomy
    return {s.id for m in tax.modules for s in m.skills} if tax else set()


def validate_values(
    template: DiaryTemplate, raw: dict[str, Any], skill_ids: set[str]
) -> dict[str, Any]:
    """Return the cleaned values (note excluded). Unknown fields or bad values are rejected."""
    out: dict[str, Any] = {}
    for key, value in raw.items():
        f = template.field(key)
        if f is None or f.type is DiaryFieldType.note:
            raise bad_request("diary.unknown_field")
        if value is None:
            continue  # skipped
        out[key] = _check_value(f, value, skill_ids)
    for f in template.fields:  # drop answers to questions that were not shown
        if f.show_if is not None and out.get(f.show_if) is not True:
            out.pop(f.id, None)
    return out


def _check_value(f: DiaryField, value: Any, skill_ids: set[str]) -> Any:
    t = f.type
    if t is DiaryFieldType.scale:
        if isinstance(value, bool) or not isinstance(value, int):
            raise bad_request("diary.invalid_value")
        if not SCALE_MIN <= value <= SCALE_MAX:
            raise bad_request("diary.invalid_value")
        return value
    if t is DiaryFieldType.boolean:
        if not isinstance(value, bool):
            raise bad_request("diary.invalid_value")
        return value
    if t is DiaryFieldType.frequency:
        if value not in {o.id for o in f.options}:
            raise bad_request("diary.invalid_value")
        return value
    if t is DiaryFieldType.skills:
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise bad_request("diary.invalid_value")
        if len(set(value)) != len(value) or not set(value) <= skill_ids:
            raise bad_request("diary.invalid_value")
        return value
    raise bad_request("diary.invalid_value")  # pragma: no cover


def clean_note(note: str | None) -> str | None:
    note = (note or "").strip()
    if len(note) > DIARY_NOTE_MAX:
        raise bad_request("diary.note_too_long")
    return note or None


# --- safety ---


def source_ref(entry: DiaryEntry) -> str:
    return f"diary:{entry.id}"


@dataclass(frozen=True)
class SaveResult:
    entry: DiaryEntry
    safety: str  # none | care_card | help — the diary is never "stopped", it is already saved


def _screen(
    db: Session,
    safety: SafetyService,
    user: User,
    entry: DiaryEntry,
    values: dict[str, Any],
    note: str | None,
    *,
    note_changed: bool,
) -> str:
    outcomes: list[SafetyOutcome] = []
    if note and note_changed:
        outcomes.append(
            safety.screen_text(db, user, Context.diary, note, source_ref=source_ref(entry))
        )
    if entry.role is Role.adolescent or any(f in values for f in DIARY_URGE_FIELDS):
        scores = {f: values.get(f) for f in DIARY_URGE_FIELDS}
        outcomes.append(safety.check_diary_urges(db, user, scores, source_ref(entry)))
    actions = {o.action for o in outcomes}
    if actions & {"stop", "help"}:
        return "help"
    return "care_card" if "care_card" in actions else "none"


# --- create / edit ---


def _revision(db: Session, entry: DiaryEntry, user: User) -> None:
    db.add(
        DiaryRevision(
            entry_id=entry.id,
            revision_no=entry.revision_no,
            entry_date=entry.entry_date,
            values_json=entry.values_json,
            note=entry.note,
            saved_by=user.id,
        )
    )


def create(
    db: Session,
    content: ContentBundle,
    safety: SafetyService,
    user: User,
    entry_date: date,
    raw_values: dict[str, Any],
    note: str | None,
    *,
    has_homework: bool = False,
) -> SaveResult:
    if user.role not in DIARY_ROLES:
        raise bad_request("diary.not_participant")
    today = site_today(db)
    if not is_editable(entry_date, today):
        raise bad_request("diary.date_out_of_range")
    template = template_for(content, user.role)
    values = validate_values(template, raw_values, taxonomy_ids(content))
    note = clean_note(note)
    if not values and not note and not has_homework:
        raise bad_request("diary.empty")
    entry = DiaryEntry(
        id=uuid.uuid4(),
        user_id=user.id,
        role=user.role,
        template_version=template.version,
        entry_date=entry_date,
        values_json=json.dumps(values, sort_keys=True),
        note=note,
        is_late=entry_date < today,
        revision_no=1,
    )
    db.add(entry)
    db.flush()
    _revision(db, entry, user)
    action = _screen(db, safety, user, entry, values, note, note_changed=True)
    db.flush()
    return SaveResult(entry, action)


def get_owned(db: Session, user: User, entry_id: uuid.UUID) -> DiaryEntry:
    entry = db.get(DiaryEntry, entry_id)
    if entry is None or entry.user_id != user.id:
        raise not_found()  # someone else's entry looks the same as a missing one
    return entry


def update(
    db: Session,
    content: ContentBundle,
    safety: SafetyService,
    user: User,
    entry: DiaryEntry,
    raw_values: dict[str, Any],
    note: str | None,
    expected_revision: int,
    *,
    has_homework: bool = False,
) -> SaveResult:
    if not is_editable(entry.entry_date, site_today(db)):
        raise conflict("diary.read_only")
    if expected_revision != entry.revision_no:
        raise conflict("diary.changed_elsewhere")
    template = template_for(content, entry.role, entry.template_version)
    values = validate_values(template, raw_values, taxonomy_ids(content))
    note = clean_note(note)
    if not values and not note and not has_homework:
        raise bad_request("diary.empty")
    new_json = json.dumps(values, sort_keys=True)
    if new_json == entry.values_json and note == entry.note:
        return SaveResult(entry, "none")  # nothing changed: no revision
    note_changed = note != entry.note
    entry.values_json = new_json
    entry.note = note
    entry.revision_no += 1
    entry.updated_at = utcnow()
    _revision(db, entry, user)
    action = _screen(db, safety, user, entry, values, note, note_changed=note_changed)
    db.flush()
    return SaveResult(entry, action)


# --- reading ---


def entries_of(db: Session, user_id: uuid.UUID, since: date) -> list[DiaryEntry]:
    return list(
        db.execute(
            select(DiaryEntry)
            .where(DiaryEntry.user_id == user_id, DiaryEntry.entry_date >= since)
            .order_by(DiaryEntry.entry_date.desc(), DiaryEntry.created_at.desc())
        ).scalars()
    )


def revisions_of(db: Session, entry: DiaryEntry) -> list[DiaryRevision]:
    return list(
        db.execute(
            select(DiaryRevision)
            .where(DiaryRevision.entry_id == entry.id)
            .order_by(DiaryRevision.revision_no)
        ).scalars()
    )


def values_of(entry: DiaryEntry | DiaryRevision) -> dict[str, Any]:
    return decode_values(entry.values_json)


def entry_view(entry: DiaryEntry, today: date, *, for_staff: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": str(entry.id),
        "entry_date": entry.entry_date.isoformat(),
        "recorded_at": entry.created_at.isoformat(),
        "updated_at": entry.updated_at.isoformat(),
        "template_version": entry.template_version,
        "values": values_of(entry),
        "note": entry.note,
        "revision_no": entry.revision_no,
        "editable": is_editable(entry.entry_date, today) and not for_staff,
    }
    if for_staff:
        out["added_later"] = entry.is_late  # neutral research flag; never shown to participants
    return out


def revision_view(rev: DiaryRevision) -> dict[str, Any]:
    return {
        "revision_no": rev.revision_no,
        "saved_at": rev.saved_at.isoformat(),
        "values": values_of(rev),
        "note": rev.note,
    }


# --- template rendering (labels in one language) ---


def _t(b: Any, lang: str) -> str | None:
    if b is None:
        return None
    return str(b.zh_CN if lang == "zh-CN" else b.en)


def template_view(
    template: DiaryTemplate, lang: str, skills: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "role": template.role,
        "version": template.version,
        "title": _t(template.title, lang),
        "intro": _t(template.intro, lang),
        "groups": [
            {
                "id": g.id,
                "label": _t(g.label, lang),
                "fields": [
                    {
                        "id": f.id,
                        "type": f.type.value,
                        "label": _t(f.label, lang),
                        "hint": _t(f.hint, lang),
                        "low": _t(f.low, lang),
                        "high": _t(f.high, lang),
                        "options": [{"id": o.id, "label": _t(o.label, lang)} for o in f.options],
                        "show_if": f.show_if,
                        "urge": f.urge,
                    }
                    for f in g.fields
                ],
            }
            for g in template.groups
        ],
        "skills": skills,
        "note_max": DIARY_NOTE_MAX,
    }
