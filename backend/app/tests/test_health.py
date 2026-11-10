"""Health, request ids, security headers (Plan Phase 0 task 2)."""

from __future__ import annotations

import pytest
from sqlalchemy import Engine

from app.core.db import make_engine
from app.settings import Settings
from app.tests.conftest import make_client

UNREACHABLE = "postgresql+psycopg://nobody:secretpw@127.0.0.1:1/test_unreachable?connect_timeout=1"


def test_live(settings: Settings) -> None:
    r = make_client(settings).get("/health/live")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_ready_reports_503_when_database_unreachable(settings: Settings) -> None:
    client = make_client(settings, make_engine(UNREACHABLE))
    r = client.get("/health/ready")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "unavailable"
    assert body["checks"]["database"]["ok"] is False
    assert body["checks"]["content"]["ok"] is True
    assert "nobody" not in r.text and "secretpw" not in r.text  # no credentials leak


@pytest.mark.db
def test_ready_ok_with_migrated_test_database(settings: Settings, db_engine: Engine) -> None:
    r = make_client(settings, db_engine).get("/health/ready")
    assert r.status_code == 200, r.text
    checks = r.json()["checks"]
    assert checks["database"]["ok"] and checks["migrations"]["ok"] and checks["content"]["ok"]
    assert checks["migrations"]["current"] == checks["migrations"]["expected"]


def test_request_id_is_generated_and_echoed(settings: Settings) -> None:
    client = make_client(settings)
    generated = client.get("/health/live").headers["X-Request-ID"]
    assert len(generated) == 32
    echoed = client.get("/health/live", headers={"X-Request-ID": "abc12345-ok"})
    assert echoed.headers["X-Request-ID"] == "abc12345-ok"
    # Unsafe caller-supplied ids are replaced, not reflected.
    unsafe = client.get("/health/live", headers={"X-Request-ID": "<script>"})
    assert unsafe.headers["X-Request-ID"] != "<script>"


def test_security_headers(settings: Settings) -> None:
    h = make_client(settings).get("/health/live").headers
    assert h["X-Content-Type-Options"] == "nosniff"
    assert h["X-Frame-Options"] == "DENY"
    assert "default-src 'none'" in h["Content-Security-Policy"]
    assert "Strict-Transport-Security" not in h  # HSTS only in production


def test_production_disables_interactive_docs(settings: Settings) -> None:
    client = make_client(settings, app_env="production")
    assert client.get("/docs").status_code == 404
    assert "Strict-Transport-Security" in client.get("/health/live").headers


def test_content_versions_endpoint(settings: Settings) -> None:
    body = make_client(settings).get("/api/v1/meta/content").json()
    assert "skills/taxonomy.yaml" in body["files"]
    assert len(body["version"]) == 64
