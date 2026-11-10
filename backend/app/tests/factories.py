"""Test data builders. Fictional data only."""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import hash_password, new_pseudonym
from app.core.sessions import utcnow
from app.models import (
    Family,
    FamilyMember,
    Group,
    GroupTherapist,
    Role,
    Site,
    User,
    UserStatus,
)

PASSWORD = "calm-river-stone-42"
_seq = itertools.count(1)
_HASH = hash_password(PASSWORD)  # hashing is slow; reuse one hash for every test user


def make_user(
    db: Session,
    role: Role,
    *,
    username: str | None = None,
    onboarded: bool = True,
    alias: str | None = None,
    language: str = "en",
) -> User:
    n = next(_seq)
    u = User(
        pseudonym_code=new_pseudonym(),
        username=username or f"{role.value[:5]}-{n}",
        role=role,
        display_alias=alias or f"{role.value.title()} {n}",
        language=language,
        a11y_prefs={},
        password_hash=_HASH,
        status=UserStatus.active,
        is_demo=True,
        failed_logins=0,
        onboarded_at=utcnow() if onboarded else None,
    )
    db.add(u)
    db.flush()
    return u


@dataclass
class Fam:
    family: Family
    teen: User
    carers: list[User]


@dataclass
class World:
    admin: User
    t1: User
    t2: User
    g1: Group
    g2: Group
    f1: Fam
    f2: Fam
    extra: dict[str, Any] = field(default_factory=dict)


def make_family(db: Session, group: Group, *, carers: int = 1, onboarded: bool = True) -> Fam:
    fam = Family(group_id=group.id, label=f"Family {next(_seq)}", is_demo=True)
    db.add(fam)
    db.flush()
    teen = make_user(db, Role.adolescent, onboarded=onboarded)
    db.add(FamilyMember(family_id=fam.id, user_id=teen.id, member_role=Role.adolescent))
    cs = []
    for _ in range(carers):
        c = make_user(db, Role.caregiver, onboarded=onboarded)
        db.add(
            FamilyMember(
                family_id=fam.id,
                user_id=c.id,
                member_role=Role.caregiver,
                relationship_label="parent",
            )
        )
        cs.append(c)
    db.flush()
    return Fam(fam, teen, cs)


def make_group(db: Session, therapist: User) -> Group:
    g = Group(name=f"Group {next(_seq)}", is_demo=True, created_by=therapist.id)
    db.add(g)
    db.flush()
    db.add(GroupTherapist(group_id=g.id, therapist_id=therapist.id))
    db.flush()
    return g


def make_world(db: Session) -> World:
    db.add(Site(name="Test site", timezone="Asia/Shanghai", help_contacts=[], service_hours={}))
    admin = make_user(db, Role.admin)
    t1 = make_user(db, Role.therapist)
    t2 = make_user(db, Role.therapist)
    g1, g2 = make_group(db, t1), make_group(db, t2)
    w = World(admin, t1, t2, g1, g2, make_family(db, g1, carers=2), make_family(db, g2))
    db.commit()
    return w


def login(client: TestClient, user: User | str, password: str = PASSWORD) -> str:
    """Sign in and return the CSRF token (the session cookie stays in the client)."""
    username = user if isinstance(user, str) else user.username
    r = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    token: str = r.json()["csrf_token"]
    client.headers["X-CSRF-Token"] = token
    return token
