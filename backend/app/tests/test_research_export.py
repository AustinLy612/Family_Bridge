"""Phase 9 acceptance: research instrumentation and export (Plan §5.10; D80-D83).

- The export contains no free text and no direct identifiers.
- Adolescent and caregiver data are exported separately.
- Consent: only records made while the research-export consent was on (D81).
- Dates only, with study day; never a time of day (D82).
- Every export is audited; only admins can export.
- The data dictionary covers every exported column and the checked-in copy is current.
- Research events accept only declared, non-prose properties; client events are a closed set.
- Recruitment denominators: own groups only, funnel order checked, audited.
"""

from __future__ import annotations

import csv
import io
import re
import uuid
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.content.loader import load_content
from app.models import (
    AuditLog,
    ChatMessage,
    ConsentRecord,
    DiaryEntry,
    Family,
    FamilyMember,
    Group,
    GroupSkillRecord,
    LearnerProfile,
    PracticeAttempt,
    RecruitmentCount,
    ResearchEvent,
    Role,
    SafetyEvent,
    Task,
    TeachingSession,
    User,
)
from app.research import events as ev
from app.research import export as rx
from app.research.dictionary import render
from app.services.seed import seed_demo
from app.settings import Settings
from app.tests.factories import World, login

UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
TIME_RE = re.compile(r"\d{2}:\d{2}(:\d{2})?")
SECRET = "test-export-key"
REPO = Path(__file__).resolve().parents[3]


def grant(db: Session, user: User, at: datetime, granted: bool = True) -> None:
    db.add(
        ConsentRecord(
            user_id=user.id,
            document_id="consent-test",
            document_version=1,
            document_sha256="0" * 64,
            category=rx.CONSENT_CATEGORY,
            grantee="research_export",
            granted=granted,
            recorded_at=at,
        )
    )


def participants(db: Session) -> list[User]:
    return list(
        db.execute(select(User).where(User.role.in_([Role.adolescent, Role.caregiver]))).scalars()
    )


def files(export: rx.Export) -> dict[str, list[dict[str, str]]]:
    return {
        name: list(csv.DictReader(io.StringIO(data.decode("utf-8"))))
        for name, data in export.files.items()
        if name.endswith(".csv")
    }


def data_text(export: rx.Export) -> str:
    """Everything a researcher receives except the dictionary (which only describes columns)."""
    return "\n".join(
        data.decode("utf-8")
        for name, data in export.files.items()
        if name not in ("data_dictionary.csv", "event_types.csv", "README.txt")
    )


@pytest.fixture
def seeded(db: Session, settings: Settings) -> tuple[Session, rx.Export]:
    seed_demo(db)
    early = datetime.now(UTC) - timedelta(days=60)
    for u in participants(db):
        grant(db, u, early)
    # sentinel free text in every kind of free-text field the app stores
    entry = db.execute(select(DiaryEntry)).scalars().first()
    assert entry is not None
    entry.note = "SENTINEL-DIARY-NOTE"
    ev_ = db.execute(select(SafetyEvent)).scalars().first()
    assert ev_ is not None
    ev_.trigger_excerpt = "SENTINEL-EXCERPT"
    ev_.detection_detail = "SENTINEL-DETAIL"
    task = db.execute(select(Task)).scalars().first()
    if task is not None:
        task.title, task.details = "SENTINEL-TASK-TITLE", "SENTINEL-TASK-DETAILS"
    db.commit()
    content = load_content(settings.content_dir)
    return db, rx.build(db, content, SECRET, include_demo=True)


def test_export_has_no_free_text_or_direct_identifiers(seeded: tuple[Session, rx.Export]) -> None:
    db, export = seeded
    text = data_text(export)
    forbidden: set[str] = {
        "SENTINEL-DIARY-NOTE",
        "SENTINEL-EXCERPT",
        "SENTINEL-DETAIL",
        "SENTINEL-TASK-TITLE",
        "SENTINEL-TASK-DETAILS",
    }
    for u in db.execute(select(User)).scalars():
        forbidden |= {u.username, u.display_alias}
    forbidden |= {f.label for f in db.execute(select(Family)).scalars()}
    forbidden |= {g.name for g in db.execute(select(Group)).scalars()}
    forbidden |= {
        m.relationship_label
        for m in db.execute(select(FamilyMember)).scalars()
        if m.relationship_label
    }
    for model, cols in (
        (ChatMessage, ("content",)),
        (PracticeAttempt, ("answer", "feedback")),
        (GroupSkillRecord, ("note",)),
        (TeachingSession, ("summary", "personal_context", "inquiry")),
        (LearnerProfile, ("other_hobby_text", "other_concern_text")),
        (Task, ("title", "details")),
    ):
        for row in db.execute(select(model)).scalars():
            forbidden |= {getattr(row, c) for c in cols if getattr(row, c)}
    forbidden = {f for f in forbidden if f and len(f) >= 4}
    assert len(forbidden) > 20
    leaks = sorted(f for f in forbidden if f in text)
    assert leaks == []
    assert not UUID_RE.search(text), "internal ids must be coded"
    # demo data really was exported (the test is not vacuous)
    rows = files(export)
    assert rows["adolescent/diary_entries.csv"] and rows["adolescent/safety_events.csv"]
    assert rows["caregiver/participants.csv"] and rows["shared/groups.csv"]


def test_dates_only_and_study_days(seeded: tuple[Session, rx.Export]) -> None:
    _db, export = seeded
    assert not TIME_RE.search(data_text(export)), "no time of day in exports (D82)"
    rows = files(export)
    teen = rows["adolescent/participants.csv"][0]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", teen["enrolled_date"])
    for r in rows["adolescent/events.csv"]:
        assert int(r["study_day"]) >= 1


def test_adolescent_and_caregiver_files_are_separate(seeded: tuple[Session, rx.Export]) -> None:
    db, export = seeded
    rows = files(export)
    teens = {u.pseudonym_code for u in participants(db) if u.role == Role.adolescent}
    carers = {u.pseudonym_code for u in participants(db) if u.role == Role.caregiver}
    for name, table in rows.items():
        codes = {r.get("participant_code") for r in table} - {None, ""}
        if name.startswith("adolescent/"):
            assert codes <= teens, name
        elif name.startswith("caregiver/"):
            assert codes <= carers, name
        else:
            assert not codes, f"{name} must not hold per-person rows"
    assert {r["participant_code"] for r in rows["adolescent/participants.csv"]} == teens
    assert {r["participant_code"] for r in rows["caregiver/participants.csv"]} == carers


def test_dictionary_covers_every_column_and_doc_is_current(
    seeded: tuple[Session, rx.Export], settings: Settings
) -> None:
    _db, export = seeded
    described = {(r["file"], r["column"]) for r in files(export)["data_dictionary.csv"]}
    for t in rx.TABLES:
        header = export.files[t.path].decode("utf-8").splitlines()[0].split(",")
        assert {(t.path, h) for h in header} <= described, t.path
    for c in (c for t in rx.TABLES for c in t.columns):
        assert c.type in {"code", "date", "int", "number", "bool", "text-enum", "list", "json"}
    doc = (REPO / "docs/research/DATA_DICTIONARY.md").read_text(encoding="utf-8")
    assert doc == render(load_content(settings.content_dir)), "run `app.cli research-dictionary`"
    assert set(ev.EVENTS) <= {r["event_type"] for r in files(export)["event_types.csv"]}


def test_consent_window_after_withdrawal(world: World, db: Session, settings: Settings) -> None:
    teen = world.f1.teen
    t0 = datetime.now(UTC) - timedelta(days=10)
    grant(db, teen, t0)
    grant(db, teen, t0 + timedelta(days=3), granted=False)
    grant(db, teen, t0 + timedelta(days=6))
    for day, label in ((-1, "before"), (1, "on1"), (4, "off"), (7, "on2")):
        db.add(
            ResearchEvent(
                occurred_at=t0 + timedelta(days=day),
                event_type="task.outcome",
                subject_pseudonym=teen.pseudonym_code,
                subject_role="adolescent",
                props={"task": label, "outcome": "success"},
            )
        )
    db.commit()
    out = rx.build(db, load_content(settings.content_dir), SECRET, include_demo=True)
    got = [r for r in files(out)["adolescent/events.csv"] if r["event_type"] == "task.outcome"]
    assert sorted(r["props"] for r in got) == sorted(
        f'{{"outcome": "success", "task": "{x}"}}' for x in ("on1", "on2")
    )
    # a caregiver who never consented is not exported at all
    assert not files(out)["caregiver/participants.csv"]


def test_demo_data_is_left_out_unless_asked(world: World, db: Session, settings: Settings) -> None:
    for u in (world.f1.teen, world.f2.teen):
        grant(db, u, datetime.now(UTC) - timedelta(days=1))
    world.f2.teen.is_demo = False
    db.get(Family, world.f2.family.id).is_demo = False  # type: ignore[union-attr]
    world.g2.is_demo = False
    db.commit()
    content = load_content(settings.content_dir)
    real = files(rx.build(db, content, SECRET))["adolescent/participants.csv"]
    both = files(rx.build(db, content, SECRET, include_demo=True))["adolescent/participants.csv"]
    assert [r["participant_code"] for r in real] == [world.f2.teen.pseudonym_code]
    assert len(both) == 2


def test_codes_are_stable_and_keyed(world: World, db: Session, settings: Settings) -> None:
    content = load_content(settings.content_dir)
    a = rx.Ctx(db, content, SECRET, include_demo=True).code("G", world.g1.id)
    b = rx.Ctx(db, content, SECRET, include_demo=True).code("G", world.g1.id)
    c = rx.Ctx(db, content, "other-key", include_demo=True).code("G", world.g1.id)
    assert a == b != c and a and a.startswith("G") and str(world.g1.id) not in a


def test_only_admins_export_and_every_export_is_audited(
    client: TestClient, world: World, db: Session
) -> None:
    for who in (world.t1, world.f1.teen):
        login(client, who)
        assert client.get("/api/v1/admin/research-export").status_code == 403
        assert client.post("/api/v1/admin/research-export", json={}).status_code == 403
        client.post("/api/v1/auth/logout")
    login(client, world.admin)
    preview = client.get("/api/v1/admin/research-export?include_demo=true")
    assert preview.status_code == 200
    paths = {f["path"] for f in preview.json()["files"]}
    assert {"adolescent/participants.csv", "caregiver/participants.csv"} <= paths
    r = client.post("/api/v1/admin/research-export", json={"include_demo": True})
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    assert "no-store" in r.headers["cache-control"]
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert "data_dictionary.csv" in names and "adolescent/events.csv" in names
    entries = (
        db.execute(
            select(AuditLog).where(
                AuditLog.action == "research.export", AuditLog.actor_id == world.admin.id
            )
        )
        .scalars()
        .all()
    )
    assert len(entries) == 1
    assert entries[0].details["include_demo"] is True
    assert "adolescent/participants.csv" in entries[0].details["rows"]


def test_research_events_refuse_undeclared_or_prose_values(db: Session, world: World) -> None:
    with pytest.raises(ev.UnsafeEventError):
        ev.record(db, "made.up", None)
    with pytest.raises(ev.UnsafeEventError):
        ev.record(db, "joint.leave", world.f1.teen, note="x")
    with pytest.raises(ev.UnsafeEventError):
        ev.record(db, "joint.leave", world.f1.teen, session="I feel awful today, please help")
    ev.record(db, "joint.leave", world.f1.teen, session=str(uuid.uuid4()))


def test_client_events_closed_vocabulary_and_cap(
    client: TestClient, world: World, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    login(client, world.f1.teen)
    url = "/api/v1/research/client-events"
    ok = [
        {"type": "client.error", "kind": "js", "area": "adolescent:diary"},
        {"type": "task.outcome", "task": "diary_entry", "outcome": "abandoned"},
    ]
    for body in ok:
        assert client.post(url, json=body).status_code == 204
    bad = [
        {"type": "client.error", "kind": "js", "area": "My diary was awful"},
        {"type": "client.error", "kind": "js", "message": "TypeError: x"},
        {"type": "client.error"},
        {"type": "task.outcome", "task": "diary_entry"},
        {"type": "free.text", "kind": "js"},
    ]
    for body in bad:
        assert client.post(url, json=body).status_code == 422, body
    rows = (
        db.execute(
            select(ResearchEvent).where(
                ResearchEvent.subject_pseudonym == world.f1.teen.pseudonym_code
            )
        )
        .scalars()
        .all()
    )
    kinds = sorted(r.event_type for r in rows if r.event_type in ev.CLIENT_EVENTS)
    assert kinds == ["client.error", "task.outcome"]
    monkeypatch.setattr("app.api.research.CLIENT_EVENT_CAP_PER_HOUR", 2)
    assert client.post(url, json=ok[0]).status_code == 204  # accepted, but not stored
    db.expire_all()
    n = sum(
        1
        for r in db.execute(select(ResearchEvent)).scalars()
        if r.subject_pseudonym == world.f1.teen.pseudonym_code and r.event_type in ev.CLIENT_EVENTS
    )
    assert n == 2


def test_enrolment_events_are_recorded(client: TestClient, world: World, db: Session) -> None:
    login(client, world.t1)
    r = client.post(
        f"/api/v1/families/{world.f1.family.id}/invitations",
        json={"role": "caregiver", "relationship_label": "aunt"},
    )
    assert r.status_code == 201, r.text
    issued = (
        db.execute(select(ResearchEvent).where(ResearchEvent.event_type == "enrolment.code_issued"))
        .scalars()
        .all()
    )
    assert issued and issued[-1].props["role"] == "caregiver"
    assert "aunt" not in str(issued[-1].props)


def test_recruitment_counts(client: TestClient, world: World, db: Session) -> None:
    login(client, world.t1)
    url = f"/api/v1/groups/{world.g1.id}/recruitment"
    body = {
        "period_start": "2026-10-01",
        "period_end": "2026-10-31",
        "screened": 12,
        "eligible": 9,
        "approached": 8,
        "consented": 5,
    }
    assert client.post(url, json=body).status_code == 201
    assert client.post(url, json=body | {"consented": 6}).status_code == 201  # correction
    items = client.get(url).json()["items"]
    assert len(items) == 1 and items[0]["consented"] == 6
    bad = client.post(url, json=body | {"eligible": 20})
    assert bad.status_code == 400 and bad.json()["detail"]["code"] == "recruitment.funnel_order"
    bad = client.post(url, json=body | {"period_end": "2026-09-01"})
    assert bad.json()["detail"]["code"] == "recruitment.invalid_period"
    assert client.get(f"/api/v1/groups/{world.g2.id}/recruitment").status_code in (403, 404)
    assert len(db.execute(select(RecruitmentCount)).scalars().all()) == 2
    audited = (
        db.execute(
            select(AuditLog).where(
                AuditLog.action == "recruitment.recorded", AuditLog.actor_id == world.t1.id
            )
        )
        .scalars()
        .all()
    )
    assert len(audited) == 2
