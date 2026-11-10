"""Adversarial benchmark harness (Plan §7.3): with the mock provider, which mirrors the keyword
channel, every high-severity case must be handled safely by the deterministic layers alone."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.ai import evaluation as ev
from app.ai.wiring import LLMRiskAssessor
from app.content.loader import load_content
from app.safety.service import SafetyService
from app.settings import Settings
from app.tests.ai_fixtures import make_ai

pytestmark = pytest.mark.db


def test_adversarial_suite_passes_on_the_deterministic_layers(
    db: Session, clean_db: Engine, settings: Settings
) -> None:
    content = load_content(settings.content_dir)
    ai, _ = make_ai(
        content, settings, session_factory=lambda: Session(clean_db, expire_on_commit=False)
    )
    safety = SafetyService(content, settings, LLMRiskAssessor(ai))
    report = ev.run_adversarial(db, ai, safety, content.adversarial_sets)
    failed = [c.id for c in report.cases if not c.passed]
    assert report.passed, failed
    assert report.by_severity["high"]["passed"] == report.by_severity["high"]["cases"]
    run = ev.record(db, "adversarial", ai, report.passed, report.summary())
    assert run.passed and run.summary["cases_total"] == len(report.cases) >= 65


def test_export_for_review_writes_jsonl_with_golden_points(
    db: Session, settings: Settings, tmp_path: Path
) -> None:
    content = load_content(settings.content_dir)
    ai, _ = make_ai(content, settings)
    report = ev.run_sweep(db, ai, ["dt.tipp"], languages=("en",), roles=("caregiver",))
    n = ev.export_for_review(report, content.golden_eval, tmp_path / "out.jsonl")
    lines = (tmp_path / "out.jsonl").read_text(encoding="utf-8").splitlines()
    assert n == len(lines) > 0
    first = json.loads(lines[0])
    assert first["expected_key_points"] and set(first["rating"]) and first["output"]
    assert all(v is None for v in first["rating"].values())  # filled in by the clinician
