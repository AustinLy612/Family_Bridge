"""Research export (Plan §5.10, §8.5): pseudonymous CSV tables in a zip, with a data dictionary.

Rules, each covered by a test (`app/tests/test_research_export.py`):
- **No free text and no direct identifiers.** No usernames, display names, family labels,
  relationship labels, notes, chat, answers, reflections, excerpts or recommendation text. People
  appear by their random `pseudonym_code`; groups, families, sessions, lessons and homework by
  keyed codes (HMAC of the internal id, stable across exports, not reversible without the key).
- **Adolescent and caregiver data are separate files** (`adolescent/`, `caregiver/`); `shared/`
  holds group-, family- and session-level tables with no per-person values.
- **Consent (D32, D81):** a participant's record is exported only if it was made while their
  research-export consent was on. Data from before the first decision or after a withdrawal is
  left out; turning consent back on includes data from then on.
- **Dates (D82):** calendar date in the site time zone plus study day (day 1 = account
  creation); no time of day. Durations are numbers.
- Demo groups, families and accounts are left out unless `include_demo` is set.
- Every export is audited with its row counts (by the caller).
"""

from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import io
import json
import uuid
import zipfile
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.content.loader import ContentBundle
from app.models import (
    CaregiverLesson,
    ConsentRecord,
    DiaryEntry,
    DiaryShare,
    DistressRating,
    Family,
    FamilyMember,
    Group,
    GroupSkillRecord,
    GroupTherapist,
    Invitation,
    JointSession,
    JointSessionResponse,
    LearnerProfile,
    MoodRecord,
    PracticeAttempt,
    QuizAttempt,
    RecruitmentCount,
    ResearchEvent,
    Role,
    SafetyEvent,
    SkillProgress,
    SkillTest,
    Task,
    TaskCompletion,
    TeachingSession,
    TherapistTime,
    User,
)
from app.services.site import get_site

CONSENT_CATEGORY = "research_export"
SCOPES = ("shared", "adolescent", "caregiver")
PARTICIPANT_ROLES = (Role.adolescent, Role.caregiver)
CODED_PROPS = {"session": "S", "family": "F"}


@dataclass(frozen=True)
class Column:
    name: str
    type: str  # code | date | int | number | bool | text-enum | json | list
    description: str


@dataclass(frozen=True)
class Table:
    scope: str
    name: str
    description: str
    source: str
    columns: tuple[Column, ...]
    rows: Callable[[Ctx], Iterable[dict[str, Any]]]
    # Diary tables add one column per template field (see `diary_columns`).
    dynamic: Callable[[Ctx], list[Column]] | None = None

    @property
    def path(self) -> str:
        return f"{self.scope}/{self.name}.csv"


def C(name: str, type_: str, description: str) -> Column:  # noqa: N802 - short spec helper
    return Column(name, type_, description)


PCODE = C(
    "participant_code", "code", "Random pseudonymous code of the person (User.pseudonym_code)."
)
DATE = C("date", "date", "Calendar date in the site time zone (D82).")
SDAY = C("study_day", "int", "Days since the person's account was created; day 1 = that day.")


# --- context ------------------------------------------------------------------------------


@dataclass
class Person:
    user: User
    family: Family
    group: Group
    enrol: date
    grants: list[tuple[datetime, bool]] = field(default_factory=list)

    @property
    def role(self) -> str:
        return self.user.role.value

    def allowed(self, when: datetime | None) -> bool:
        """True when the research-export consent was on at `when` (D81)."""
        if when is None:
            return False
        state = False
        seen = False
        for at, granted in self.grants:
            if at <= when:
                state, seen = granted, True
            else:
                break
        return seen and state

    @property
    def ever_allowed(self) -> bool:
        return any(g for _, g in self.grants)


class Ctx:
    def __init__(
        self, db: Session, content: ContentBundle, secret: str, *, include_demo: bool
    ) -> None:
        self.db = db
        self.content = content
        self._key = secret.encode()
        self.include_demo = include_demo
        site = get_site(db)
        try:
            self.tz = ZoneInfo(site.timezone if site else "Asia/Shanghai")
        except ZoneInfoNotFoundError:
            self.tz = ZoneInfo("Asia/Shanghai")
        self.groups = {
            g.id: g for g in db.execute(select(Group)).scalars() if include_demo or not g.is_demo
        }
        self.families = {
            f.id: f
            for f in db.execute(select(Family)).scalars()
            if f.group_id in self.groups and (include_demo or not f.is_demo)
        }
        self.people: dict[uuid.UUID, Person] = {}
        for m in db.execute(select(FamilyMember)).scalars():
            fam = self.families.get(m.family_id)
            u = db.get(User, m.user_id)
            if fam is None or u is None or u.role not in PARTICIPANT_ROLES:
                continue
            if u.is_demo and not include_demo:
                continue
            self.people[u.id] = Person(u, fam, self.groups[fam.group_id], self.day(u.created_at))
        for r in db.execute(
            select(ConsentRecord)
            .where(ConsentRecord.category == CONSENT_CATEGORY)
            .order_by(ConsentRecord.recorded_at, ConsentRecord.id)
        ).scalars():
            p = self.people.get(r.user_id)
            if p is not None:
                p.grants.append((r.recorded_at, bool(r.granted)))
        self.by_pseudonym = {p.user.pseudonym_code: p for p in self.people.values()}
        self.therapists = {
            u.id: u
            for u in db.execute(select(User).where(User.role == Role.therapist)).scalars()
            if include_demo or not u.is_demo
        }
        self._sessions: dict[uuid.UUID, bool] | None = None

    # codes and dates
    def code(self, prefix: str, value: uuid.UUID | str | None) -> str | None:
        if value is None:
            return None
        mac = hmac.new(self._key, f"{prefix}:{value}".encode(), hashlib.sha256).digest()
        return prefix + base64.b32encode(mac).decode()[:10]

    def day(self, when: datetime) -> date:
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        return when.astimezone(self.tz).date()

    def when(self, p: Person, when: datetime | date | None) -> dict[str, Any]:
        if when is None:
            return {"date": None, "study_day": None}
        d = when if isinstance(when, date) and not isinstance(when, datetime) else self.day(when)
        return {"date": d.isoformat(), "study_day": (d - p.enrol).days + 1}

    def person(self, user_id: uuid.UUID | None, role: str, at: datetime | None) -> Person | None:
        """The person if they are in scope, have the role, and consent covered `at`."""
        p = self.people.get(user_id) if user_id else None
        if p is None or p.role != role or not p.allowed(at):
            return None
        return p

    def session_ok(self, s: JointSession) -> bool:
        """A session is exported when its family is in scope and every participant consented at
        the time it was scheduled."""
        if self._sessions is None:
            self._sessions = {}
        if s.id not in self._sessions:
            ids = [i for i in (s.adolescent_id, s.caregiver_id) if i]
            self._sessions[s.id] = (
                s.family_id in self.families
                and bool(ids)
                and all(i in self.people and self.people[i].allowed(s.created_at) for i in ids)
            )
        return self._sessions[s.id]

    def props(self, props: dict[str, Any]) -> str:
        out = {}
        for k, v in sorted((props or {}).items()):
            out[k] = self.code(CODED_PROPS[k], v) if k in CODED_PROPS and v else v
        return json.dumps(out, sort_keys=True, ensure_ascii=True)


def _iso(d: date | datetime | None, ctx: Ctx) -> str | None:
    if d is None:
        return None
    if isinstance(d, datetime):
        return ctx.day(d).isoformat()
    return d.isoformat()


def _minutes(a: datetime | None, b: datetime | None) -> float | None:
    if a is None or b is None:
        return None
    return round((b - a).total_seconds() / 60, 1)


# --- shared tables ------------------------------------------------------------------------


def _groups(ctx: Ctx) -> Iterable[dict[str, Any]]:
    links = defaultdict(list)
    for gt in ctx.db.execute(select(GroupTherapist)).scalars():
        if gt.therapist_id in ctx.therapists:
            links[gt.group_id].append(ctx.therapists[gt.therapist_id].pseudonym_code)
    fams: dict[uuid.UUID, int] = defaultdict(int)
    for f in ctx.families.values():
        fams[f.group_id] += 1
    for g in ctx.groups.values():
        yield {
            "group_code": ctx.code("G", g.id),
            "diary_days_per_week": g.diary_days_per_week,
            "family_count": fams[g.id],
            "therapist_codes": ";".join(sorted(links[g.id])),
            "created_date": _iso(g.created_at, ctx),
        }


def _families(ctx: Ctx) -> Iterable[dict[str, Any]]:
    counts: dict[uuid.UUID, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for p in ctx.people.values():
        if p.ever_allowed:
            counts[p.family.id][p.role] += 1
    for f in ctx.families.values():
        yield {
            "family_code": ctx.code("F", f.id),
            "group_code": ctx.code("G", f.group_id),
            "adolescents_exported": counts[f.id]["adolescent"],
            "caregivers_exported": counts[f.id]["caregiver"],
            "created_date": _iso(f.created_at, ctx),
        }


def _therapists(ctx: Ctx) -> Iterable[dict[str, Any]]:
    groups = defaultdict(list)
    for gt in ctx.db.execute(select(GroupTherapist)).scalars():
        if gt.group_id in ctx.groups:
            groups[gt.therapist_id].append(ctx.code("G", gt.group_id) or "")
    for t in ctx.therapists.values():
        if groups[t.id]:
            yield {
                "therapist_code": t.pseudonym_code,
                "group_codes": ";".join(sorted(groups[t.id])),
            }


def _recruitment(ctx: Ctx) -> Iterable[dict[str, Any]]:
    rows = list(
        ctx.db.execute(select(RecruitmentCount).order_by(RecruitmentCount.recorded_at)).scalars()
    )
    latest: dict[tuple[Any, ...], uuid.UUID] = {}
    for r in rows:
        latest[(r.group_id, r.period_start, r.period_end)] = r.id
    for r in rows:
        if r.group_id not in ctx.groups:
            continue
        rec = ctx.therapists.get(r.recorded_by) if r.recorded_by else None
        yield {
            "group_code": ctx.code("G", r.group_id),
            "period_start": r.period_start.isoformat(),
            "period_end": r.period_end.isoformat(),
            "screened": r.screened,
            "eligible": r.eligible,
            "approached": r.approached,
            "consented": r.consented,
            "recorded_date": _iso(r.recorded_at, ctx),
            "recorded_by": rec.pseudonym_code if rec else None,
            "is_latest": latest[(r.group_id, r.period_start, r.period_end)] == r.id,
        }


def _codes(ctx: Ctx) -> Iterable[dict[str, Any]]:
    for inv in ctx.db.execute(select(Invitation).order_by(Invitation.created_at)).scalars():
        if inv.intended_role not in PARTICIPANT_ROLES or inv.family_id not in ctx.families:
            continue
        yield {
            "family_code": ctx.code("F", inv.family_id),
            "role": inv.intended_role.value,
            "purpose": inv.purpose.value,
            "issued_date": _iso(inv.created_at, ctx),
            "expires_date": _iso(inv.expires_at, ctx),
            "redeemed_date": _iso(inv.used_at, ctx),
            "revoked_date": _iso(inv.revoked_at, ctx),
        }


def _homework(ctx: Ctx) -> Iterable[dict[str, Any]]:
    for t in ctx.db.execute(select(Task).order_by(Task.starts_on)).scalars():
        if t.group_id in ctx.groups:
            yield {
                "task_code": ctx.code("T", t.id),
                "group_code": ctx.code("G", t.group_id),
                "kind": t.kind,
                "for_roles": ";".join(sorted(t.for_roles)),
                "skill_ids": ";".join(t.skill_ids or []),
                "starts_on": t.starts_on.isoformat(),
                "due_on": t.due_on.isoformat(),
            }


def _group_sessions(ctx: Ctx) -> Iterable[dict[str, Any]]:
    for r in ctx.db.execute(
        select(GroupSkillRecord).order_by(GroupSkillRecord.session_date)
    ).scalars():
        if r.group_id in ctx.groups:
            yield {
                "group_code": ctx.code("G", r.group_id),
                "session_date": r.session_date.isoformat(),
                "skill_ids": ";".join(r.skill_ids or []),
            }


def _therapist_time(ctx: Ctx) -> Iterable[dict[str, Any]]:
    for r in ctx.db.execute(select(TherapistTime).order_by(TherapistTime.day)).scalars():
        if r.family_id in ctx.families and r.therapist_id in ctx.therapists:
            yield {
                "therapist_code": ctx.therapists[r.therapist_id].pseudonym_code,
                "family_code": ctx.code("F", r.family_id),
                "date": r.day.isoformat(),
                "seconds": r.seconds,
            }


def _joint_sessions(ctx: Ctx) -> Iterable[dict[str, Any]]:
    for s in ctx.db.execute(select(JointSession).order_by(JointSession.created_at)).scalars():
        if not ctx.session_ok(s):
            continue
        snap = s.snapshot or {}
        fam = ctx.families[s.family_id]
        yield {
            "session_code": ctx.code("S", s.id),
            "family_code": ctx.code("F", s.family_id),
            "group_code": ctx.code("G", fam.group_id),
            "mode": s.mode,
            "episode_id": s.episode_id,
            "episode_version": s.episode_version,
            "scheduled_date": _iso(s.created_at, ctx),
            "opens_date": _iso(s.opens_at, ctx),
            "closes_date": _iso(s.closes_at, ctx),
            "status": str(s.status),
            "started_date": _iso(s.started_at, ctx),
            "ended_date": _iso(s.ended_at, ctx),
            "duration_minutes": _minutes(s.started_at, s.ended_at),
            "steps_done": len(snap.get("done", [])) if snap else None,
            "steps_skipped": len(snap.get("skipped", [])) if snap else None,
            "end_reason": s.end_reason,
        }


def _shared_events(ctx: Ctx) -> Iterable[dict[str, Any]]:
    sessions = {s.id: s for s in ctx.db.execute(select(JointSession)).scalars()}
    for e in ctx.db.execute(
        select(ResearchEvent)
        .where(ResearchEvent.subject_pseudonym.is_(None))
        .order_by(ResearchEvent.id)
    ).scalars():
        props = e.props or {}
        if "session" in props:
            try:
                s = sessions.get(uuid.UUID(str(props["session"])))
            except ValueError:
                s = None
            if s is None or not ctx.session_ok(s):
                continue
        if props.get("family"):
            try:
                if uuid.UUID(str(props["family"])) not in ctx.families:
                    continue
            except ValueError:
                continue
        yield {
            "date": _iso(e.occurred_at, ctx),
            "event_type": e.event_type,
            "props": ctx.props(props),
        }


# --- per-role tables ----------------------------------------------------------------------


def _participants(role: str) -> Callable[[Ctx], Iterable[dict[str, Any]]]:
    def rows(ctx: Ctx) -> Iterable[dict[str, Any]]:
        profiles = {p.user_id: p for p in ctx.db.execute(select(LearnerProfile)).scalars()}
        for p in ctx.people.values():
            if p.role != role or not p.ever_allowed:
                continue
            u = p.user
            now = datetime.now(UTC)
            row: dict[str, Any] = {
                "participant_code": u.pseudonym_code,
                "family_code": ctx.code("F", p.family.id),
                "group_code": ctx.code("G", p.group.id),
                "language": u.language,
                "enrolled_date": p.enrol.isoformat(),
                "onboarded_date": _iso(u.onboarded_at, ctx),
                "onboarded_study_day": ctx.when(p, u.onboarded_at)["study_day"],
                "account_status": u.status.value,
                "research_consent_now": p.allowed(now),
            }
            if role == "adolescent":
                lp = profiles.get(u.id)
                row |= {
                    "age": lp.age if lp else None,
                    "gender": lp.gender.value if lp and lp.gender else None,
                    "grade": lp.grade if lp else None,
                }
            yield row

    return rows


def _events(role: str) -> Callable[[Ctx], Iterable[dict[str, Any]]]:
    def rows(ctx: Ctx) -> Iterable[dict[str, Any]]:
        for e in ctx.db.execute(
            select(ResearchEvent)
            .where(ResearchEvent.subject_pseudonym.is_not(None))
            .order_by(ResearchEvent.id)
        ).scalars():
            p = ctx.by_pseudonym.get(e.subject_pseudonym or "")
            if p is None or p.role != role or not p.allowed(e.occurred_at):
                continue
            yield {
                "participant_code": p.user.pseudonym_code,
                **ctx.when(p, e.occurred_at),
                "event_type": e.event_type,
                "props": ctx.props(e.props),
            }

    return rows


def diary_columns(role: str) -> Callable[[Ctx], list[Column]]:
    def cols(ctx: Ctx) -> list[Column]:
        out: dict[str, Column] = {}
        for t in ctx.content.diary_templates(role):
            for f in t.fields:
                if f.type.value == "note":
                    continue  # free text never leaves the app
                kind = {
                    "scale": "int",
                    "boolean": "bool",
                    "frequency": "text-enum",
                    "skills": "list",
                }[f.type.value]
                out.setdefault(
                    f"f_{f.id}",
                    Column(
                        f"f_{f.id}",
                        kind,
                        f"Diary field `{f.id}` ({f.label.en}); empty if not answered.",
                    ),
                )
        return list(out.values())

    return cols


def _diary(role: str) -> Callable[[Ctx], Iterable[dict[str, Any]]]:
    def rows(ctx: Ctx) -> Iterable[dict[str, Any]]:
        fields = [c.name for c in diary_columns(role)(ctx)]
        shared = {
            s.entry_id
            for s in ctx.db.execute(
                select(DiaryShare).where(DiaryShare.revoked_at.is_(None))
            ).scalars()
        }
        ticks: dict[uuid.UUID, int] = defaultdict(int)
        for tc in ctx.db.execute(select(TaskCompletion)).scalars():
            ticks[tc.entry_id] += 1
        for e in ctx.db.execute(select(DiaryEntry).order_by(DiaryEntry.entry_date)).scalars():
            p = ctx.person(e.user_id, role, e.created_at)
            if p is None:
                continue
            values = json.loads(e.values_json or "{}")
            row: dict[str, Any] = {
                "participant_code": p.user.pseudonym_code,
                "entry_date": e.entry_date.isoformat(),
                "study_day": ctx.when(p, e.entry_date)["study_day"],
                "template_version": e.template_version,
                "late": e.is_late,
                "revision_no": e.revision_no,
                "shared_with_therapist_or_family": e.id in shared,
                "homework_ticked": ticks[e.id],
            }
            for name in fields:
                v = values.get(name[2:])
                row[name] = ";".join(map(str, v)) if isinstance(v, list) else v
            yield row

    return rows


def _homework_done(role: str) -> Callable[[Ctx], Iterable[dict[str, Any]]]:
    def rows(ctx: Ctx) -> Iterable[dict[str, Any]]:
        for tc in ctx.db.execute(
            select(TaskCompletion).order_by(TaskCompletion.completed_on)
        ).scalars():
            p = ctx.person(tc.user_id, role, tc.created_at)
            if p is not None:
                yield {
                    "participant_code": p.user.pseudonym_code,
                    "task_code": ctx.code("T", tc.task_id),
                    "completed_on": tc.completed_on.isoformat(),
                    "study_day": ctx.when(p, tc.completed_on)["study_day"],
                }

    return rows


def _safety(role: str) -> Callable[[Ctx], Iterable[dict[str, Any]]]:
    def rows(ctx: Ctx) -> Iterable[dict[str, Any]]:
        for s in ctx.db.execute(select(SafetyEvent).order_by(SafetyEvent.created_at)).scalars():
            p = ctx.person(s.subject_user_id, role, s.created_at)
            if p is not None:
                yield {
                    "participant_code": p.user.pseudonym_code,
                    **ctx.when(p, s.created_at),
                    "category": s.category.value,
                    "severity": s.severity.value,
                    "source": s.source.value,
                    "channel": s.channel.value,
                    "status": s.status.value,
                    "activity_stopped": s.activity_stopped,
                    "occurrences": s.occurrences,
                }

    return rows


def _joint_participation(role: str) -> Callable[[Ctx], Iterable[dict[str, Any]]]:
    def rows(ctx: Ctx) -> Iterable[dict[str, Any]]:
        sessions = {s.id: s for s in ctx.db.execute(select(JointSession)).scalars()}
        for r in ctx.db.execute(
            select(JointSessionResponse).order_by(JointSessionResponse.responded_at)
        ).scalars():
            s = sessions.get(r.session_id)
            p = ctx.person(r.user_id, role, r.responded_at)
            if s is None or p is None or not ctx.session_ok(s):
                continue
            yield {
                "session_code": ctx.code("S", s.id),
                "participant_code": p.user.pseudonym_code,
                "mode": s.mode,
                "response": str(r.response),
                **ctx.when(p, r.responded_at),
                "join_location": r.join_location,
            }

    return rows


def _distress(role: str) -> Callable[[Ctx], Iterable[dict[str, Any]]]:
    def rows(ctx: Ctx) -> Iterable[dict[str, Any]]:
        sessions = {s.id: s for s in ctx.db.execute(select(JointSession)).scalars()}
        for d in ctx.db.execute(
            select(DistressRating).order_by(DistressRating.created_at)
        ).scalars():
            p = ctx.person(d.user_id, role, d.created_at)
            s = sessions.get(d.session_id) if d.session_id else None
            if p is None or (s is not None and not ctx.session_ok(s)):
                continue
            yield {
                "session_code": ctx.code("S", d.session_id),
                "participant_code": p.user.pseudonym_code,
                **ctx.when(p, d.created_at),
                "context": d.context,
                "step_id": d.step_id,
                "value": d.value,
                "skipped": d.value is None,
            }

    return rows


def _skill_progress(role: str) -> Callable[[Ctx], Iterable[dict[str, Any]]]:
    def rows(ctx: Ctx) -> Iterable[dict[str, Any]]:
        for sp in ctx.db.execute(select(SkillProgress)).scalars():
            # one row spans time: export it only if consent covers the latest practice
            p = ctx.person(sp.user_id, role, sp.last_practised_at)
            if p is None or not p.allowed(sp.first_practised_at):
                continue
            yield {
                "participant_code": p.user.pseudonym_code,
                "skill_id": sp.skill_id,
                "lessons_completed": sp.lessons_completed,
                "mastered": sp.mastered,
                "quiz_outcome": sp.quiz_outcome,
                "practice_categories": json.dumps(sp.practice_categories or {}, sort_keys=True),
                "first_date": _iso(sp.first_practised_at, ctx),
                "last_date": _iso(sp.last_practised_at, ctx),
            }

    return rows


def _lessons(ctx: Ctx) -> Iterable[dict[str, Any]]:
    moods = {m.id: m.value for m in ctx.db.execute(select(MoodRecord)).scalars()}
    for s in ctx.db.execute(select(TeachingSession).order_by(TeachingSession.started_at)).scalars():
        p = ctx.person(s.user_id, "adolescent", s.started_at)
        if p is None:
            continue
        try:
            rec = json.loads(s.recommendation) if s.recommendation else {}
        except ValueError:
            rec = {}
        recommended = rec.get("skill") if isinstance(rec, dict) else None
        yield {
            "lesson_code": ctx.code("L", s.id),
            "participant_code": p.user.pseudonym_code,
            **ctx.when(p, s.started_at),
            "language": s.language,
            "source": s.source.value if s.source else None,
            "status": s.status.value,
            "phase_reached": s.phase.value,
            "checkin_skipped": s.checkin_skipped,
            "recommended_skill": recommended if isinstance(recommended, str) else None,
            "selected_skill": s.selected_skill,
            "followed_recommendation": (s.source.value == "recommended") if s.source else None,
            "turns": s.turns,
            "minutes": _minutes(s.started_at, s.completed_at),
            "mood_before": moods.get(s.pre_mood_id) if s.pre_mood_id else None,
            "mood_after": moods.get(s.post_mood_id) if s.post_mood_id else None,
        }


def _tests(ctx: Ctx) -> Iterable[dict[str, Any]]:
    moods = {m.id: m.value for m in ctx.db.execute(select(MoodRecord)).scalars()}
    for t in ctx.db.execute(select(SkillTest).order_by(SkillTest.created_at)).scalars():
        p = ctx.person(t.user_id, "adolescent", t.created_at)
        if p is None:
            continue
        yield {
            "lesson_code": ctx.code("L", t.session_id),
            "participant_code": p.user.pseudonym_code,
            **ctx.when(p, t.created_at),
            "attempt_no": t.attempt_no,
            "status": t.status.value,
            "total_questions": t.total_questions,
            "correct_count": t.correct_count,
            "mastered": t.mastered,
            "mood_after": moods.get(t.post_mood_id) if t.post_mood_id else None,
        }


def _caregiver_lessons(ctx: Ctx) -> Iterable[dict[str, Any]]:
    for c in ctx.db.execute(select(CaregiverLesson).order_by(CaregiverLesson.started_at)).scalars():
        p = ctx.person(c.user_id, "caregiver", c.started_at)
        if p is None:
            continue
        yield {
            "lesson_code": ctx.code("L", c.id),
            "participant_code": p.user.pseudonym_code,
            **ctx.when(p, c.started_at),
            "language": c.language,
            "skill_id": c.skill_id,
            "source": c.source.value,
            "status": c.status.value,
            "step_reached": c.step.value,
            "variant": c.variant,
            "reflection_skipped": c.reflection_skipped,
            "minutes": _minutes(c.started_at, c.completed_at),
        }


def _lesson_owner(ctx: Ctx) -> dict[uuid.UUID, uuid.UUID]:
    return {c.id: c.user_id for c in ctx.db.execute(select(CaregiverLesson)).scalars()}


def _practice(ctx: Ctx) -> Iterable[dict[str, Any]]:
    owners = _lesson_owner(ctx)
    for a in ctx.db.execute(select(PracticeAttempt).order_by(PracticeAttempt.created_at)).scalars():
        p = ctx.person(owners.get(a.lesson_id), "caregiver", a.created_at)
        if p is None:
            continue
        yield {
            "lesson_code": ctx.code("L", a.lesson_id),
            "participant_code": p.user.pseudonym_code,
            **ctx.when(p, a.created_at),
            "item_index": a.item_index,
            "attempt_no": a.attempt_no,
            "category": a.category,
        }


def _quiz(ctx: Ctx) -> Iterable[dict[str, Any]]:
    owners = _lesson_owner(ctx)
    for q in ctx.db.execute(select(QuizAttempt).order_by(QuizAttempt.created_at)).scalars():
        p = ctx.person(owners.get(q.lesson_id), "caregiver", q.created_at)
        if p is None:
            continue
        yield {
            "lesson_code": ctx.code("L", q.lesson_id),
            "participant_code": p.user.pseudonym_code,
            **ctx.when(p, q.created_at),
            "question_index": q.question_index,
            "correct": q.is_correct,
        }


# --- table specs --------------------------------------------------------------------------

GCODE = C("group_code", "code", "Keyed code of the group.")
FCODE = C("family_code", "code", "Keyed code of the family.")
SCODE = C("session_code", "code", "Keyed code of the joint session.")
LCODE = C("lesson_code", "code", "Keyed code of the lesson.")


def _role_tables(role: str) -> list[Table]:
    tables = [
        Table(
            role,
            "participants",
            f"One row per {role} who has ever had research-export consent on.",
            "User, FamilyMember, ConsentRecord"
            + (", LearnerProfile" if role == "adolescent" else ""),
            (
                PCODE,
                FCODE,
                GCODE,
                C("language", "text-enum", "Interface language: zh-CN or en."),
                C("enrolled_date", "date", "Account creation date (study day 1)."),
                C("onboarded_date", "date", "Date onboarding consent was completed."),
                C("onboarded_study_day", "int", "Study day of onboarding."),
                C("account_status", "text-enum", "active or deactivated."),
                C("research_consent_now", "bool", "Research-export consent is on at export time."),
                *(
                    (
                        C("age", "int", "Age from the learning profile."),
                        C("gender", "text-enum", "Gender from the learning profile, if given."),
                        C("grade", "text-enum", "School grade from the learning profile."),
                    )
                    if role == "adolescent"
                    else ()
                ),
            ),
            _participants(role),
        ),
        Table(
            role,
            "events",
            "Instrumentation events about this person (log-in, enrolment, joint, usability).",
            "ResearchEvent (see event_types.csv)",
            (
                PCODE,
                DATE,
                SDAY,
                C("event_type", "text-enum", "See event_types.csv."),
                C("props", "json", "Declared properties only; session/family ids are coded."),
            ),
            _events(role),
        ),
        Table(
            role,
            "diary_entries",
            "One row per Diary Card entry (latest revision). Note fields are never exported.",
            "DiaryEntry, DiaryShare, TaskCompletion; field list from content/diary templates",
            (
                PCODE,
                C("entry_date", "date", "The day the card is about."),
                SDAY,
                C("template_version", "int", "Diary template version."),
                C("late", "bool", "Saved after its day (within the edit window)."),
                C("revision_no", "int", "1 = never corrected; each correction adds 1."),
                C(
                    "shared_with_therapist_or_family",
                    "bool",
                    "Any item of this entry is currently shared.",
                ),
                C("homework_ticked", "int", "Homework items ticked in this entry."),
            ),
            _diary(role),
            diary_columns(role),
        ),
        Table(
            role,
            "homework_done",
            "Homework ticks (one per item per entry).",
            "TaskCompletion",
            (
                PCODE,
                C("task_code", "code", "Keyed code of the homework (shared/homework.csv)."),
                C("completed_on", "date", "Diary day the item was ticked on."),
                SDAY,
            ),
            _homework_done(role),
        ),
        Table(
            role,
            "safety_events",
            "Safety events about this person, by category. No excerpts or notes.",
            "SafetyEvent",
            (
                PCODE,
                DATE,
                SDAY,
                C("category", "text-enum", "Safety category (Plan §5.3)."),
                C("severity", "text-enum", "low, medium or high."),
                C("source", "text-enum", "lesson, diary, joint or manual."),
                C("channel", "text-enum", "How it was detected."),
                C("status", "text-enum", "Workflow status at export time."),
                C("activity_stopped", "bool", "The activity was stopped."),
                C("occurrences", "int", "Repeat detections merged into this event."),
            ),
            _safety(role),
        ),
        Table(
            role,
            "joint_participation",
            "This person's answer to each joint invitation, and their self-reported join location.",
            "JointSessionResponse",
            (
                SCODE,
                PCODE,
                C("mode", "text-enum", "joint or solo."),
                C("response", "text-enum", "accepted or declined."),
                DATE,
                SDAY,
                C("join_location", "text-enum", "hospital, remote or empty."),
            ),
            _joint_participation(role),
        ),
        Table(
            role,
            "distress_ratings",
            "Optional 0-10 tension ratings during joint sessions (D76).",
            "DistressRating",
            (
                SCODE,
                PCODE,
                DATE,
                SDAY,
                C("context", "text-enum", "Where it was asked."),
                C("step_id", "text-enum", "Episode step id."),
                C("value", "int", "0-10; empty when skipped."),
                C("skipped", "bool", "The person skipped the rating."),
            ),
            _distress(role),
        ),
        Table(
            role,
            "skill_progress",
            "Per-skill learning progress.",
            "SkillProgress",
            (
                PCODE,
                C("skill_id", "text-enum", "Skill taxonomy id."),
                C("lessons_completed", "int", "Lessons completed for the skill."),
                C("mastered", "bool", "Mastery from the latest skill test (adolescents)."),
                C("quiz_outcome", "text-enum", "Latest caregiver quiz outcome."),
                C(
                    "practice_categories",
                    "json",
                    "Counts of caregiver practice answers by rubric category.",
                ),
                C("first_date", "date", "First practice."),
                C("last_date", "date", "Latest practice."),
            ),
            _skill_progress(role),
        ),
    ]
    if role == "adolescent":
        tables += [
            Table(
                role,
                "lessons",
                "Adolescent lessons: source, check-in, recommendation, completion and mood.",
                "TeachingSession, MoodRecord",
                (
                    LCODE,
                    PCODE,
                    DATE,
                    SDAY,
                    C("language", "text-enum", "Lesson language."),
                    C("source", "text-enum", "recommended, alternative, chosen or group_review."),
                    C(
                        "status",
                        "text-enum",
                        "ongoing, completed, user_terminated or stopped_by_safety.",
                    ),
                    C("phase_reached", "text-enum", "Last lesson phase reached."),
                    C("checkin_skipped", "bool", "The check-in question was skipped."),
                    C("recommended_skill", "text-enum", "Skill id the AI recommended."),
                    C("selected_skill", "text-enum", "Skill id actually taught."),
                    C("followed_recommendation", "bool", "The recommended skill was accepted."),
                    C("turns", "int", "Number of participant turns."),
                    C("minutes", "number", "Start to completion, in minutes."),
                    C("mood_before", "int", "Mood before teaching (1-5)."),
                    C("mood_after", "int", "Mood after teaching (1-5)."),
                ),
                _lessons,
            ),
            Table(
                role,
                "skill_tests",
                "Skill-test attempts after lessons.",
                "SkillTest, MoodRecord",
                (
                    LCODE,
                    PCODE,
                    DATE,
                    SDAY,
                    C("attempt_no", "int", "1 = first attempt."),
                    C("status", "text-enum", "Test status."),
                    C("total_questions", "int", "Questions."),
                    C("correct_count", "int", "Correct answers."),
                    C("mastered", "bool", "Met the mastery rule."),
                    C("mood_after", "int", "Mood after testing (1-5)."),
                ),
                _tests,
            ),
        ]
    else:
        tables += [
            Table(
                role,
                "lessons",
                "Caregiver structured lessons.",
                "CaregiverLesson",
                (
                    LCODE,
                    PCODE,
                    DATE,
                    SDAY,
                    C("language", "text-enum", "Lesson language."),
                    C("skill_id", "text-enum", "Skill taxonomy id."),
                    C("source", "text-enum", "explore or group_review."),
                    C(
                        "status",
                        "text-enum",
                        "ongoing, completed, user_terminated or stopped_by_safety.",
                    ),
                    C("step_reached", "text-enum", "Last lesson step reached."),
                    C("variant", "text-enum", "Practice variant."),
                    C(
                        "reflection_skipped",
                        "bool",
                        "The closing reflection was skipped (its text is never exported).",
                    ),
                    C("minutes", "number", "Start to completion, in minutes."),
                ),
                _caregiver_lessons,
            ),
            Table(
                role,
                "practice_attempts",
                "Practice answers by rubric category (the answer text is never exported).",
                "PracticeAttempt",
                (
                    LCODE,
                    PCODE,
                    DATE,
                    SDAY,
                    C("item_index", "int", "Practice item."),
                    C("attempt_no", "int", "Attempt."),
                    C("category", "text-enum", "Rubric category of the answer."),
                ),
                _practice,
            ),
            Table(
                role,
                "quiz_attempts",
                "Quiz answers: correct or not.",
                "QuizAttempt",
                (
                    LCODE,
                    PCODE,
                    DATE,
                    SDAY,
                    C("question_index", "int", "Question."),
                    C("correct", "bool", "Answered correctly."),
                ),
                _quiz,
            ),
        ]
    return tables


TABLES: list[Table] = [
    Table(
        "shared",
        "groups",
        "One row per group.",
        "Group, GroupTherapist, Family",
        (
            GCODE,
            C("diary_days_per_week", "int", "Diary expectation, days per week (D70)."),
            C("family_count", "int", "Families in the group."),
            C("therapist_codes", "list", "Therapists of the group (pseudonym codes)."),
            C("created_date", "date", "Group created."),
        ),
        _groups,
    ),
    Table(
        "shared",
        "families",
        "One row per family.",
        "Family, FamilyMember",
        (
            FCODE,
            GCODE,
            C("adolescents_exported", "int", "Adolescents of this family in the export."),
            C("caregivers_exported", "int", "Caregivers of this family in the export."),
            C("created_date", "date", "Family created."),
        ),
        _families,
    ),
    Table(
        "shared",
        "therapists",
        "Therapists linked to exported groups.",
        "User, GroupTherapist",
        (
            C("therapist_code", "code", "Pseudonym code of the therapist."),
            C("group_codes", "list", "Groups of the therapist."),
        ),
        _therapists,
    ),
    Table(
        "shared",
        "recruitment",
        "Enrolment-funnel denominators entered by therapists (counts of families).",
        "RecruitmentCount",
        (
            GCODE,
            C("period_start", "date", "Period start."),
            C("period_end", "date", "Period end."),
            C("screened", "int", "Families screened."),
            C("eligible", "int", "Families eligible."),
            C("approached", "int", "Families approached."),
            C("consented", "int", "Families consented."),
            C("recorded_date", "date", "When the figures were saved."),
            C("recorded_by", "code", "Therapist code."),
            C("is_latest", "bool", "The current figures for this group and period."),
        ),
        _recruitment,
    ),
    Table(
        "shared",
        "codes_issued",
        "One-time participant codes (invitations and resets) for the enrolment funnel.",
        "Invitation",
        (
            FCODE,
            C("role", "text-enum", "adolescent or caregiver."),
            C("purpose", "text-enum", "invitation or reset."),
            C("issued_date", "date", "Issued."),
            C("expires_date", "date", "Expires."),
            C("redeemed_date", "date", "Redeemed, if used."),
            C("revoked_date", "date", "Revoked, if revoked."),
        ),
        _codes,
    ),
    Table(
        "shared",
        "homework",
        "Homework set by therapists (titles and details are not exported).",
        "Task",
        (
            C("task_code", "code", "Keyed code of the homework."),
            GCODE,
            C("kind", "text-enum", "homework."),
            C("for_roles", "list", "Roles it was set for."),
            C("skill_ids", "list", "Linked skills."),
            C("starts_on", "date", "First day."),
            C("due_on", "date", "Last day."),
        ),
        _homework,
    ),
    Table(
        "shared",
        "group_sessions",
        "Skills covered in each group session (notes are not exported).",
        "GroupSkillRecord",
        (
            GCODE,
            C("session_date", "date", "Session date."),
            C("skill_ids", "list", "Skills covered."),
        ),
        _group_sessions,
    ),
    Table(
        "shared",
        "therapist_time",
        "Therapist time per family per day (focus time on that family's screens).",
        "TherapistTime",
        (
            C("therapist_code", "code", "Therapist."),
            FCODE,
            C("date", "date", "Day."),
            C("seconds", "int", "Seconds in focus."),
        ),
        _therapist_time,
    ),
    Table(
        "shared",
        "joint_sessions",
        "Joint and solo sessions whose participants all consented when it was scheduled. "
        "No choices, text or ratings.",
        "JointSession",
        (
            SCODE,
            FCODE,
            GCODE,
            C("mode", "text-enum", "joint or solo."),
            C("episode_id", "text-enum", "Episode id."),
            C("episode_version", "int", "Episode version."),
            C("scheduled_date", "date", "Scheduled."),
            C("opens_date", "date", "Window opens."),
            C("closes_date", "date", "Window closes."),
            C("status", "text-enum", "invited, declined, cancelled, active, completed or ended."),
            C("started_date", "date", "Room started."),
            C("ended_date", "date", "Room ended."),
            C("duration_minutes", "number", "Start to end, in minutes."),
            C("steps_done", "int", "Steps completed."),
            C("steps_skipped", "int", "Steps skipped by everyone."),
            C("end_reason", "text-enum", "Why it ended early, if it did."),
        ),
        _joint_sessions,
    ),
    Table(
        "shared",
        "events",
        "Events with no single subject: room state and latency, codes issued, "
        "log-in failures for unknown usernames.",
        "ResearchEvent",
        (
            DATE,
            C("event_type", "text-enum", "See event_types.csv."),
            C("props", "json", "Declared properties; session/family ids are coded."),
        ),
        _shared_events,
    ),
    *_role_tables("adolescent"),
    *_role_tables("caregiver"),
]


# --- build --------------------------------------------------------------------------------


@dataclass
class Export:
    files: dict[str, bytes]
    counts: dict[str, int]


def _csv(columns: list[Column], rows: Iterable[dict[str, Any]]) -> tuple[bytes, int]:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    names = [c.name for c in columns]
    w.writerow(names)
    n = 0
    for r in rows:
        extra = set(r) - set(names)
        if extra:
            raise RuntimeError(f"undeclared export column(s): {sorted(extra)}")
        w.writerow(["" if r.get(k) is None else r.get(k) for k in names])
        n += 1
    return buf.getvalue().encode("utf-8"), n


def columns_of(table: Table, ctx: Ctx) -> list[Column]:
    return list(table.columns) + (table.dynamic(ctx) if table.dynamic else [])


def dictionary_rows(ctx: Ctx) -> list[dict[str, str]]:
    out = []
    for t in TABLES:
        for c in columns_of(t, ctx):
            out.append(
                {
                    "file": t.path,
                    "column": c.name,
                    "type": c.type,
                    "description": c.description,
                    "table_description": t.description,
                    "source": t.source,
                }
            )
    return out


def build(
    db: Session, content: ContentBundle, secret: str, *, include_demo: bool = False
) -> Export:
    ctx = Ctx(db, content, secret, include_demo=include_demo)
    files: dict[str, bytes] = {}
    counts: dict[str, int] = {}
    for t in TABLES:
        data, n = _csv(columns_of(t, ctx), t.rows(ctx))
        files[t.path] = data
        counts[t.path] = n
    dict_cols = [
        C(k, "text", k)
        for k in ("file", "column", "type", "description", "table_description", "source")
    ]
    files["data_dictionary.csv"], _ = _csv(dict_cols, dictionary_rows(ctx))
    ev_cols = [C("event_type", "text", ""), C("description", "text", ""), C("props", "text", "")]
    from app.research.events import EVENTS

    files["event_types.csv"], _ = _csv(
        ev_cols,
        (
            {"event_type": k, "description": v.description, "props": ";".join(v.props)}
            for k, v in EVENTS.items()
        ),
    )
    files["README.txt"] = _readme(counts, include_demo, ctx).encode("utf-8")
    return Export(files, counts)


def _readme(counts: dict[str, int], include_demo: bool, ctx: Ctx) -> str:
    lines = [
        "FamilyBridge research export (Plan section 5.10).",
        f"Generated on {datetime.now(ctx.tz).date().isoformat()} (site time zone).",
        f"Demo data included: {'yes' if include_demo else 'no'}.",
        "",
        "Pseudonymous: no names, usernames, labels or free text. Codes are stable across exports.",
        "Adolescent and caregiver data are in separate folders;",
        "shared/ has group, family and session tables.",
        "A participant's records are included only if made while their",
        "research-export consent was on.",
        "Dates are calendar dates plus study day (day 1 = account creation); no time of day.",
        "See data_dictionary.csv and event_types.csv.",
        "",
        "Rows per file:",
        *(f"  {k}: {v}" for k, v in counts.items()),
        "",
    ]
    return "\n".join(lines)


def to_zip(export: Export) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in export.files.items():
            z.writestr(name, data)
    return buf.getvalue()
