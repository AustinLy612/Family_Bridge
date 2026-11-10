"""Authorisation (Plan §4.2): therapists are confined to their groups; participants never reach
staff or other users' data; every denial and cross-user read is audited.

`test_route_enumeration_*` walks EVERY API route, so a new endpoint is automatically covered:
it must either be on the participant allow-list (and then must not leak other users' ids) or
refuse participants.
"""

from __future__ import annotations

import re
import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    AuditLog,
    CaregiverLesson,
    ChatMessage,
    ChatRole,
    DetectionChannel,
    DiaryEntry,
    DiaryRevision,
    DiaryShare,
    LessonSource,
    LessonStatus,
    SafetyCategory,
    SafetySeverity,
    SafetySource,
    SkillProgress,
    SkillTest,
    SkillTestStatus,
    TeachingPhase,
    TeachingSession,
    User,
)
from app.safety.events import raise_event
from app.tests.factories import World, login

pytestmark = pytest.mark.db

# Routes a participant may call. Everything else must refuse them (401/403).
PARTICIPANT_ROUTES = {
    ("GET", "/api/v1/auth/session"),
    ("POST", "/api/v1/auth/login"),
    ("POST", "/api/v1/auth/logout"),
    ("POST", "/api/v1/auth/logout-all"),
    ("POST", "/api/v1/auth/codes/inspect"),
    ("POST", "/api/v1/auth/redeem"),
    ("POST", "/api/v1/auth/reset"),
    ("POST", "/api/v1/auth/password"),
    ("GET", "/api/v1/me"),
    ("PATCH", "/api/v1/me"),
    ("GET", "/api/v1/me/visibility"),
    ("GET", "/api/v1/me/consent"),
    ("PUT", "/api/v1/me/consent/{category}"),
    ("GET", "/api/v1/onboarding"),
    ("POST", "/api/v1/onboarding/accept"),
    ("GET", "/api/v1/site/help"),
    ("GET", "/api/v1/help"),
    ("GET", "/api/v1/meta/content"),
    # Phase 5 learning: own data only (role-gated per engine; walked with the other member's ids)
    ("GET", "/api/v1/learn/skills"),
    ("GET", "/api/v1/learn/profile"),
    ("PUT", "/api/v1/learn/profile"),
    ("GET", "/api/v1/learn/sessions/current"),
    ("POST", "/api/v1/learn/sessions"),
    ("GET", "/api/v1/learn/sessions/{session_id}"),
    ("POST", "/api/v1/learn/sessions/{session_id}/mood"),
    ("POST", "/api/v1/learn/sessions/{session_id}/checkin"),
    ("POST", "/api/v1/learn/sessions/{session_id}/choose"),
    ("POST", "/api/v1/learn/sessions/{session_id}/messages"),
    ("POST", "/api/v1/learn/sessions/{session_id}/end"),
    ("POST", "/api/v1/learn/sessions/{session_id}/post-mood"),
    ("POST", "/api/v1/learn/sessions/{session_id}/stop"),
    ("POST", "/api/v1/learn/sessions/{session_id}/tests"),
    ("GET", "/api/v1/learn/tests/{test_id}"),
    ("POST", "/api/v1/learn/tests/{test_id}/answers"),
    ("POST", "/api/v1/learn/tests/{test_id}/mood"),
    ("POST", "/api/v1/learn/tests/{test_id}/stop"),
    ("GET", "/api/v1/learn/caregiver/current"),
    ("POST", "/api/v1/learn/caregiver/lessons"),
    ("GET", "/api/v1/learn/caregiver/lessons/{lesson_id}"),
    ("POST", "/api/v1/learn/caregiver/lessons/{lesson_id}/adapt"),
    ("POST", "/api/v1/learn/caregiver/lessons/{lesson_id}/next"),
    ("POST", "/api/v1/learn/caregiver/lessons/{lesson_id}/practice"),
    ("POST", "/api/v1/learn/caregiver/lessons/{lesson_id}/quiz"),
    ("POST", "/api/v1/learn/caregiver/lessons/{lesson_id}/finish"),
    ("POST", "/api/v1/learn/caregiver/lessons/{lesson_id}/stop"),
    ("GET", "/api/v1/learn/group-review"),
    ("GET", "/api/v1/learn/progress"),
    ("GET", "/api/v1/learn/history"),
    # Phase 6 diary: own entries; "Shared with me" only what was shared (walked with the other
    # member's entry and share ids)
    ("GET", "/api/v1/diary/template"),
    ("GET", "/api/v1/diary/templates/{version}"),
    ("GET", "/api/v1/diary/entries"),
    ("POST", "/api/v1/diary/entries"),
    ("GET", "/api/v1/diary/entries/{entry_id}"),
    ("PUT", "/api/v1/diary/entries/{entry_id}"),
    ("GET", "/api/v1/diary/entries/{entry_id}/revisions"),
    ("GET", "/api/v1/diary/share-recipients"),
    ("POST", "/api/v1/diary/entries/{entry_id}/shares"),
    ("DELETE", "/api/v1/diary/shares/{share_id}"),
    ("GET", "/api/v1/diary/shared-with-me"),
    # Phase 7 homework: the group's open items for the caller's own role (D69)
    ("GET", "/api/v1/diary/homework"),
    ("GET", "/api/v1/homework"),
    # Phase 8 joint sessions: the caller's own invitations and solo rehearsal (Plan §5.9)
    ("GET", "/api/v1/joint/sessions"),
    ("GET", "/api/v1/joint/sessions/{session_id}"),
    ("POST", "/api/v1/joint/sessions/{session_id}/respond"),
    ("POST", "/api/v1/joint/solo"),
    # Phase 9: the browser reports usability events about the caller (closed vocabulary)
    ("POST", "/api/v1/research/client-events"),
}
# Logging out would end the session mid-test; these are checked separately.
SKIP_DURING_WALK = {("POST", "/api/v1/auth/logout"), ("POST", "/api/v1/auth/logout-all")}


def _api_routes(client: TestClient) -> list[tuple[str, str]]:
    spec = client.app.openapi()  # type: ignore[attr-defined]
    out = []
    for path, ops in spec["paths"].items():
        if not path.startswith("/api/"):
            continue
        for method in ops:
            out.append((method.upper(), path))
    return sorted(out)


def _fill(path: str, ids: dict[str, str]) -> str:
    return re.sub(r"\{(\w+)\}", lambda m: ids.get(m.group(1), str(uuid.uuid4())), path)


def _walk_as(
    client: TestClient, actor: User, victim_ids: dict[str, str], secrets: list[str]
) -> None:
    login(client, actor)
    routes = _api_routes(client)
    assert len(routes) > 25  # sanity: we really enumerated the app
    for method, path in routes:
        if (method, path) in SKIP_DURING_WALK:
            continue
        url = _fill(path, victim_ids)
        r = client.request(method, url, json={})
        if (method, path) in PARTICIPANT_ROUTES:
            for s in secrets:
                assert s not in r.text, f"{method} {path} leaked another user's identifier"
        else:
            assert r.status_code in (401, 403), f"{method} {path} -> {r.status_code} {r.text[:200]}"


def _event_about(db: Session, user: User) -> str:
    """A safety event about the other family member (Phase 2): it must never reach participants."""
    event = raise_event(
        db,
        subject=user,
        category=SafetyCategory.risk_disclosure,
        severity=SafetySeverity.high,
        source=SafetySource.lesson,
        channel=DetectionChannel.keyword,
        excerpt="fictional test excerpt",
    )
    db.commit()
    return str(event.id)


def _lessons_of(db: Session, user: User) -> dict[str, str]:
    """Lessons, a test and progress belonging to `user`, with recognisable private text."""
    s = TeachingSession(
        user_id=user.id,
        language="en",
        phase=TeachingPhase.done,
        status=LessonStatus.completed,
        selected_skill="dt.tipp",
        personal_context="fictional private check-in",
        summary='{"summary_text": "fictional private summary"}',
    )
    db.add(s)
    db.flush()
    db.add(ChatMessage(session_id=s.id, seq=1, role=ChatRole.student, content="fictional chat"))
    t = SkillTest(session_id=s.id, user_id=user.id, attempt_no=1, status=SkillTestStatus.ready)
    c = CaregiverLesson(
        user_id=user.id,
        language="en",
        skill_id="dt.tipp",
        source=LessonSource.explore,
        status=LessonStatus.completed,
        reflection="fictional private reflection",
    )
    db.add_all([t, c, SkillProgress(user_id=user.id, skill_id="er.check_the_facts")])
    db.commit()
    return {"session_id": str(s.id), "test_id": str(t.id), "lesson_id": str(c.id)}


def _diary_of(db: Session, user: User, share_to: User | None = None) -> dict[str, str]:
    """A diary entry (and optionally a share with someone else) with recognisable private text."""
    e = DiaryEntry(
        user_id=user.id,
        role=user.role,
        template_version=1,
        entry_date=date.today(),
        values_json='{"sad": 7}',
        note="fictional private diary note",
    )
    db.add(e)
    db.flush()
    db.add(
        DiaryRevision(
            entry_id=e.id,
            revision_no=1,
            entry_date=e.entry_date,
            values_json=e.values_json,
            note=e.note,
            saved_by=user.id,
        )
    )
    ids = {"entry_id": str(e.id), "version": "1"}
    if share_to is not None:
        share = DiaryShare(
            entry_id=e.id,
            owner_id=user.id,
            recipient_id=share_to.id,
            owner_role=user.role,
            template_version=1,
            entry_date=e.entry_date,
            field_ids=["note"],
            snapshot_json='{"note": "fictional private diary note"}',
        )
        db.add(share)
        db.flush()
        ids["share_id"] = str(share.id)
    db.commit()
    return ids


LESSON_SECRETS = [
    "fictional private diary note",
    "fictional private check-in",
    "fictional private summary",
    "fictional chat",
    "fictional private reflection",
]


def test_route_enumeration_caregiver_never_reaches_adolescent_data(
    client: TestClient, world: World, db: Session
) -> None:
    teen = world.f1.teen
    ids = {
        **_lessons_of(db, teen),
        # shared with the *other* caregiver only, so the walking caregiver must not see it
        **_diary_of(db, teen, share_to=world.f1.carers[1]),
        "user_id": str(teen.id),
        "family_id": str(world.f1.family.id),
        "group_id": str(world.g1.id),
        "invitation_id": str(uuid.uuid4()),
        "category": "research_export",
        "event_id": _event_about(db, teen),
    }
    secrets = [str(teen.id), teen.pseudonym_code, teen.username, "fictional test excerpt"]
    secrets += LESSON_SECRETS
    _walk_as(client, world.f1.carers[0], ids, secrets)


def test_route_enumeration_adolescent_never_reaches_caregiver_data(
    client: TestClient, world: World, db: Session
) -> None:
    carer = world.f1.carers[0]
    ids = {
        **_lessons_of(db, carer),
        **_diary_of(db, carer),
        "user_id": str(carer.id),
        "family_id": str(world.f1.family.id),
        "group_id": str(world.g1.id),
        "invitation_id": str(uuid.uuid4()),
        "category": "research_export",
        "event_id": _event_about(db, carer),
    }
    secrets = [str(carer.id), carer.pseudonym_code, carer.username, "fictional test excerpt"]
    secrets += LESSON_SECRETS
    _walk_as(client, world.f1.teen, ids, secrets)


def test_participant_denials_are_audited(client: TestClient, world: World, db: Session) -> None:
    before = db.execute(select(func.count()).select_from(AuditLog)).scalar_one()
    login(client, world.f1.carers[0])
    assert client.get(f"/api/v1/families/{world.f1.family.id}").status_code == 403
    row = db.execute(select(AuditLog).order_by(AuditLog.id.desc()).limit(1)).scalar_one()
    assert row.action == "access.denied" and row.actor_id == world.f1.carers[0].id
    assert row.details == {"reason": "role"} and row.target_id == "/api/v1/families/{family_id}"
    assert db.execute(select(func.count()).select_from(AuditLog)).scalar_one() > before


def test_signed_out_gets_401_everywhere_private(client: TestClient, world: World) -> None:
    public = {
        ("GET", "/api/v1/auth/session"),
        ("POST", "/api/v1/auth/login"),
        ("POST", "/api/v1/auth/codes/inspect"),
        ("POST", "/api/v1/auth/redeem"),
        ("POST", "/api/v1/auth/reset"),
        ("GET", "/api/v1/site/help"),
        ("GET", "/api/v1/help"),
        ("GET", "/api/v1/meta/content"),
    }
    for method, path in _api_routes(client):
        if (method, path) in public:
            continue
        r = client.request(method, _fill(path, {}), json={})
        assert r.status_code == 401, f"{method} {path} -> {r.status_code}"


# --- therapists ------------------------------------------------------------------------------


def test_therapist_cannot_read_other_groups(client: TestClient, world: World, db: Session) -> None:
    login(client, world.t1)
    assert [g["id"] for g in client.get("/api/v1/groups").json()] == [str(world.g1.id)]
    attempts = [
        ("GET", f"/api/v1/groups/{world.g2.id}", None),
        ("GET", f"/api/v1/families/{world.f2.family.id}", None),
        ("POST", f"/api/v1/groups/{world.g2.id}/families", {"label": "x"}),
        ("POST", f"/api/v1/families/{world.f2.family.id}/invitations", {"role": "caregiver"}),
        (
            "PUT",
            f"/api/v1/families/{world.f2.family.id}/suitability",
            {
                "adolescent_id": str(world.f2.teen.id),
                "caregiver_id": str(world.f2.carers[0].id),
                "decision": "suitable",
            },
        ),
    ]
    for method, url, body in attempts:
        r = client.request(method, url, json=body)
        assert r.status_code == 403, (method, url, r.status_code)
        assert str(world.f2.teen.id) not in r.text
    denied = (
        db.execute(
            select(AuditLog).where(
                AuditLog.action == "access.denied", AuditLog.actor_id == world.t1.id
            )
        )
        .scalars()
        .all()
    )
    assert len(denied) == len(attempts)
    assert {d.details["reason"] for d in denied} == {"not_assigned"}


def test_therapist_cannot_revoke_other_groups_invitation(client: TestClient, world: World) -> None:
    login(client, world.t2)
    inv = client.post(
        f"/api/v1/families/{world.f2.family.id}/invitations", json={"role": "caregiver"}
    ).json()
    login(client, world.t1)
    assert client.post(f"/api/v1/invitations/{inv['invitation_id']}/revoke").status_code == 403


def test_therapist_cannot_use_admin_routes(client: TestClient, world: World) -> None:
    login(client, world.t1)
    assert client.get("/api/v1/admin/therapists").status_code == 403
    assert (
        client.put(
            f"/api/v1/groups/{world.g1.id}/therapists", json={"therapist_ids": [str(world.t1.id)]}
        ).status_code
        == 403
    )


def test_cross_user_reads_are_audited(client: TestClient, world: World, db: Session) -> None:
    login(client, world.t1)
    r = client.get(f"/api/v1/families/{world.f1.family.id}")
    assert r.status_code == 200
    roles = [m["role"] for m in r.json()["members"]]
    assert roles == ["adolescent", "caregiver", "caregiver"]
    row = db.execute(select(AuditLog).order_by(AuditLog.id.desc()).limit(1)).scalar_one()
    assert row.action == "family.read" and row.target_id == str(world.f1.family.id)
    assert row.actor_id == world.t1.id


def test_admin_manages_all_and_assigns_therapists(client: TestClient, world: World) -> None:
    login(client, world.admin)
    assert len(client.get("/api/v1/groups").json()) == 2
    r = client.put(
        f"/api/v1/groups/{world.g2.id}/therapists",
        json={"therapist_ids": [str(world.t1.id), str(world.t2.id)]},
    )
    assert r.status_code == 200 and len(r.json()["therapists"]) == 2
    login(client, world.t1)
    assert client.get(f"/api/v1/families/{world.f2.family.id}").status_code == 200


def test_suitability_set_and_dyads(client: TestClient, world: World) -> None:
    login(client, world.t1)
    fam = world.f1
    dyads = client.get(f"/api/v1/families/{fam.family.id}").json()["dyads"]
    assert len(dyads) == 2 and {d["decision"] for d in dyads} == {"not_assessed"}
    body = {
        "adolescent_id": str(fam.teen.id),
        "caregiver_id": str(fam.carers[0].id),
        "decision": "not_suitable",
        "note": "Revisit after week 4",
    }
    r = client.put(f"/api/v1/families/{fam.family.id}/suitability", json=body)
    assert r.status_code == 200 and r.json()["decision"] == "not_suitable"
    wrong = body | {"adolescent_id": str(fam.carers[1].id)}
    assert (
        client.put(f"/api/v1/families/{fam.family.id}/suitability", json=wrong).status_code == 400
    )
    login(client, world.admin)  # suitability is a clinical decision: therapists only
    assert client.put(f"/api/v1/families/{fam.family.id}/suitability", json=body).status_code == 403


def test_site_settings_admin_only_and_audited(
    client: TestClient, world: World, db: Session
) -> None:
    body = {
        "name": "Demo Hospital",
        "timezone": "Asia/Shanghai",
        "help_contacts": [{"label": {"zh-CN": "团队", "en": "Team"}, "phone": "000", "hours": {}}],
        "service_hours": {"zh-CN": "工作日", "en": "Weekdays"},
    }
    login(client, world.t1)
    assert client.put("/api/v1/admin/site", json=body).status_code == 403
    login(client, world.admin)
    r = client.put("/api/v1/admin/site", json=body)
    assert r.status_code == 200 and r.json()["help_contacts"][0]["phone"] == "000"
    one_lang = body | {"help_contacts": [{"label": {"en": "Team"}, "phone": "1", "hours": {}}]}
    assert client.put("/api/v1/admin/site", json=one_lang).status_code == 400
    assert db.execute(select(AuditLog).where(AuditLog.action == "site.updated")).first()
    assert client.get("/api/v1/site/help").json()["help_contacts"][0]["label"]["en"] == "Team"
