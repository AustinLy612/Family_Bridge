"""Admin AI status endpoint (Phase 4): admin-only, counts and codes only, never AI text."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.ai import evaluation as ev
from app.content.loader import load_content
from app.settings import Settings
from app.tests.ai_fixtures import make_ai
from app.tests.factories import World, login

pytestmark = pytest.mark.db


def test_status_is_admin_only(client: TestClient, world: World) -> None:
    assert client.get("/api/v1/admin/ai").status_code == 401
    for user in (world.t1, world.f1.teen, world.f1.carers[0]):
        c = TestClient(client.app)
        login(c, user)
        assert c.get("/api/v1/admin/ai").status_code == 403


def test_status_reports_usage_without_text(
    client: TestClient, world: World, db: Session, settings: Settings
) -> None:
    ai, _ = make_ai(load_content(settings.content_dir), settings)
    report = ev.run_sweep(db, ai, ["dt.tipp"], languages=("en",))
    ev.record(db, "sweep_sample", ai, report.passed, report.summary())
    ai.run(
        db, "explain_skill", {"skill_id": "dt.tipp"}, role="caregiver", language="en", caller="test"
    )  # cached
    db.commit()
    login(client, world.admin)
    r = client.get("/api/v1/admin/ai")
    assert r.status_code == 200
    body = r.json()
    assert body["provider"] == "mock" and body["breaker"] == "closed"
    assert body["calls"] == len(report.calls) + 1 and body["fallbacks"] == 0
    assert {f["function"] for f in body["functions"]} >= {"explain_skill", "teaching_turn"}
    assert body["cache_items"] >= 1 and "unreviewed" in body["cache_by_review"]
    assert len(body["prompts"]) == 32 and all(p["approval"] for p in body["prompts"])
    assert body["eval_runs"][0]["kind"] == "sweep_sample"
    assert "cases" not in body["eval_runs"][0]["headline"]
    text = r.text
    # no generated content leaves through this endpoint (only counts, ids and codes)
    for c in report.calls:
        for v in (c.output or {}).values():
            if isinstance(v, str) and len(v) > 25:
                assert v not in text
