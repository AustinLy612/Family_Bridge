"""Demo seed (Plan §5.1 "Demo mode"; Phase 1 task 8).

Creates a demo site, admin, therapist, one group and two families (one with two caregivers),
all `is_demo=true`, with fictional aliases only, plus three fictional safety events so the
clinician queue has something to show (Phase 2), and Phase 7 demo activity (homework, a diary
expectation, a group-session record, a few diary entries) for the walkthrough. Credentials go
to a git-ignored file under `seed_output/`, never to stdout or docs.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.security import hash_password, new_pseudonym
from app.core.sessions import utcnow
from app.models import (
    CodePurpose,
    DetectionChannel,
    Family,
    FamilyMember,
    Group,
    GroupTherapist,
    Role,
    SafetyCategory,
    SafetySeverity,
    SafetySource,
    Site,
    User,
    UserStatus,
)
from app.safety.events import raise_event
from app.services import codes

PLACEHOLDER_CONTACTS: list[dict[str, Any]] = [
    {
        "label": {"zh-CN": "医院 DBT 团队（占位）", "en": "Hospital DBT team (placeholder)"},
        "phone": "000-0000-0000",
        "hours": {"zh-CN": "工作日 9:00–17:00（占位）", "en": "Weekdays 9:00–17:00 (placeholder)"},
    },
    {
        "label": {"zh-CN": "急诊（占位）", "en": "Emergency (placeholder)"},
        "phone": "000",
        "hours": {"zh-CN": "全天（占位）", "en": "24 hours (placeholder)"},
    },
]
PLACEHOLDER_HOURS = {
    "zh-CN": "本平台无人实时值守。工作时间：工作日 9:00–17:00（占位，待医院确认）。",
    "en": "Nobody watches this platform in real time. Staffed hours: weekdays 9:00–17:00 "
    "(placeholder, to be confirmed by the hospital).",
}


class SeedExistsError(RuntimeError):
    pass


def _password() -> str:
    # 4 groups of 5 url-safe chars: long, easy to type, never on the common list.
    return "-".join(secrets.token_urlsafe(4)[:5] for _ in range(4))


@dataclass
class SeedResult:
    accounts: list[dict[str, str]] = field(default_factory=list)
    unused_codes: list[dict[str, str]] = field(default_factory=list)


def _user(
    db: Session,
    result: SeedResult,
    username: str,
    role: Role,
    alias: str,
    language: str,
    *,
    onboarded: bool,
) -> User:
    password = _password()
    now = utcnow()
    u = User(
        pseudonym_code=new_pseudonym(),
        username=username,
        role=role,
        display_alias=alias,
        language=language,
        a11y_prefs={},
        password_hash=hash_password(password),
        status=UserStatus.active,
        is_demo=True,
        failed_logins=0,
        onboarded_at=now if onboarded else None,
    )
    db.add(u)
    db.flush()
    result.accounts.append(
        {"username": username, "password": password, "role": role.value, "alias": alias}
    )
    return u


def seed_demo(db: Session) -> SeedResult:
    if db.execute(select(User.id).where(User.username == "demo-admin")).first():
        raise SeedExistsError("demo data already exists (user demo-admin)")
    result = SeedResult()

    site = db.execute(select(Site).limit(1)).scalar_one_or_none()
    if site is None:
        db.add(
            Site(
                name="Demo Hospital (fictional)",
                timezone="Asia/Shanghai",
                help_contacts=PLACEHOLDER_CONTACTS,
                service_hours=PLACEHOLDER_HOURS,
            )
        )

    admin = _user(db, result, "demo-admin", Role.admin, "Admin (demo)", "en", onboarded=True)
    therapist = _user(
        db, result, "demo-therapist", Role.therapist, "Dr Lin (demo)", "zh-CN", onboarded=True
    )
    group = Group(name="Demo DBT-A group", is_demo=True, created_by=therapist.id)
    db.add(group)
    db.flush()
    db.add(GroupTherapist(group_id=group.id, therapist_id=therapist.id))

    families = [
        (
            "Family A (demo)",
            [
                ("demo-teen-a", Role.adolescent, "Maple", "zh-CN", None),
                ("demo-carer-a", Role.caregiver, "Maple's mum", "zh-CN", "mother"),
            ],
        ),
        (
            "Family B (demo)",
            [
                ("demo-teen-b", Role.adolescent, "River", "en", None),
                ("demo-carer-b1", Role.caregiver, "River's dad", "en", "father"),
                ("demo-carer-b2", Role.caregiver, "River's gran", "zh-CN", "grandmother"),
            ],
        ),
    ]
    people: dict[str, User] = {}
    for label, members in families:
        fam = Family(group_id=group.id, label=label, is_demo=True)
        db.add(fam)
        db.flush()
        for username, role, alias, lang, rel in members:
            u = _user(db, result, username, role, alias, lang, onboarded=False)
            people[username] = u
            db.add(
                FamilyMember(
                    family_id=fam.id, user_id=u.id, member_role=role, relationship_label=rel
                )
            )
        # One spare caregiver invitation per family, to demo redemption.
        inv, code = codes.issue(
            db,
            actor=therapist,
            purpose=CodePurpose.invite,
            role=Role.caregiver,
            family_id=fam.id,
            ttl=timedelta(days=14),
        )
        result.unused_codes.append(
            {
                "family": label,
                "role": "caregiver",
                "code": code,
                "expires_at": inv.expires_at.isoformat(),
            }
        )
    inv, code = codes.issue(
        db, actor=admin, purpose=CodePurpose.invite, role=Role.therapist, ttl=timedelta(days=14)
    )
    result.unused_codes.append(
        {"family": "-", "role": "therapist", "code": code, "expires_at": inv.expires_at.isoformat()}
    )
    db.flush()
    seed_safety_examples(db, people, therapist)
    from app.services.seed_activity import seed_activity  # local: it imports diary helpers

    seed_activity(db)
    audit.record(
        db,
        "seed.demo",
        actor=admin,
        target_type="group",
        target_id=group.id,
        details={"accounts": len(result.accounts)},
    )
    return result


def write_output(result: SeedResult, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "demo_credentials.json"
    payload = {
        "warning": "Fictional demo accounts. Local use only. This folder is git-ignored.",
        "accounts": result.accounts,
        "unused_codes": result.unused_codes,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def seed_safety_examples(db: Session, people: dict[str, User], therapist: User) -> None:
    """Fictional events for the demo queue. Excerpts are invented demo text."""
    raise_event(
        db,
        subject=people["demo-teen-b"],
        category=SafetyCategory.risk_disclosure,
        severity=SafetySeverity.medium,
        source=SafetySource.lesson,
        channel=DetectionChannel.keyword,
        excerpt="(demo) I feel hopeless about the exams this week.",
        detail={"terms": ["hopeless"], "level": "medium", "keywords_version": 1},
    )
    raise_event(
        db,
        subject=people["demo-teen-a"],
        category=SafetyCategory.urge_threshold,
        severity=SafetySeverity.high,
        source=SafetySource.diary,
        channel=DetectionChannel.threshold,
        detail={"fields": {"self_harm_urge": 8}, "threshold": 7},
    )
    raise_event(
        db,
        subject=people["demo-teen-a"],
        category=SafetyCategory.parental_coercion,
        severity=SafetySeverity.low,
        source=SafetySource.manual,
        channel=DetectionChannel.manual,
        excerpt="(demo) Noted after group: check in about pressure to share diary entries at home.",
        created_by=therapist,
    )
