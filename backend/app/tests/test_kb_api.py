"""Admin knowledge-base status endpoint (Phase 3 task 7): admin-only, never returns manual text."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.content.loader import load_content
from app.kb import ingest as kbi
from app.kb.embedder import HashEmbedder
from app.kb.retrieval import KnowledgeService
from app.models.knowledge import KnowledgeChunk
from app.settings import Settings
from app.tests.factories import World, login
from app.tests.kb_fixtures import handout_index, write_pdf, write_transcriptions

pytestmark = pytest.mark.db


def _ingest(db: Session, settings: Settings, tmp_path: Path) -> None:
    index = handout_index()
    kbi.ingest(
        db,
        raw_pages=kbi.read_pdf(write_pdf(tmp_path / "m.pdf")),
        source_name="m.pdf",
        source_sha256="0" * 64,
        index=index,
        taxonomy=load_content(settings.content_dir).taxonomy,
        transcriptions=kbi.load_transcriptions(write_transcriptions(tmp_path / "t"), index),
        embedder=HashEmbedder(),
    )
    db.commit()


def test_empty_status(client: TestClient, world: World) -> None:
    login(client, world.admin)
    body = client.get("/api/v1/admin/kb").json()
    assert body["active"] is None and body["history"] == []
    assert body["retrieval"]["searches"] == 0
    assert set(body["min_score"]) == {"zh-CN", "en"}


def test_status_reports_counts_and_warnings_without_text(
    client: TestClient, world: World, db: Session, settings: Settings, tmp_path: Path
) -> None:
    _ingest(db, settings, tmp_path)
    KnowledgeService(settings, embedder=HashEmbedder()).search(
        db, "注意呼吸", language="zh-CN", caller="test"
    )
    db.commit()
    login(client, world.admin)
    r = client.get("/api/v1/admin/kb")
    assert r.status_code == 200
    body = r.json()
    a = body["active"]
    assert a["version"] == 1 and a["status"] == "active" and a["handouts"] == 4
    assert a["chunks_by_module"]["mindfulness"] >= 3
    assert a["transcribed_pages"] == [6]
    assert a["header_mismatches"] == [{"page": 7, "found": "ie.h3", "expected": "ie.h1"}]
    assert a["eval"] is None
    assert body["retrieval"]["searches"] == 1
    # No chunk text (manual content, D7) appears anywhere in the response.
    raw = r.text
    for text in db.execute(select(KnowledgeChunk.text)).scalars():
        for line in text.splitlines():
            assert line not in raw


def test_only_admins_can_read_kb_status(client: TestClient, world: World) -> None:
    for user in (world.t1, world.f1.teen, world.f1.carers[0]):
        login(client, user)
        assert client.get("/api/v1/admin/kb").status_code == 403
    client.post("/api/v1/auth/logout")
    assert client.get("/api/v1/admin/kb").status_code == 401
