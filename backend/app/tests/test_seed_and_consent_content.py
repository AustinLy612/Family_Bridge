"""Demo seed (Plan §5.1), CLI, and consent content validation (Plan §5.2; D31, D32)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.content.loader import ContentError, load_content, parse_restricted_markdown
from app.models import Family, FamilyMember, Group, Role, SafetyEvent, User
from app.services.seed import SeedExistsError, seed_demo, write_output
from app.settings import Settings

REAL_CONTENT = Path(__file__).resolve().parents[3] / "content"


@pytest.mark.db
def test_seed_demo(db: Session, tmp_path: Path) -> None:
    result = seed_demo(db)
    db.commit()
    users = db.execute(select(User)).scalars().all()
    assert all(u.is_demo for u in users)
    assert {u.role for u in users} == set(Role)
    assert db.execute(select(func.count()).select_from(Group)).scalar_one() == 1
    fams = db.execute(select(Family)).scalars().all()
    sizes = sorted(
        db.execute(
            select(func.count()).select_from(FamilyMember).where(FamilyMember.family_id == f.id)
        ).scalar_one()
        for f in fams
    )
    assert sizes == [2, 3]  # one family with two caregivers
    events = db.execute(select(SafetyEvent)).scalars().all()
    assert len(events) == 3 and all(e.family_id is not None for e in events)  # demo queue
    path = write_output(result, tmp_path / "seed_output")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert len(data["accounts"]) == len(users)
    assert {c["role"] for c in data["unused_codes"]} == {"caregiver", "therapist"}
    with pytest.raises(SeedExistsError):
        seed_demo(db)


def test_seed_output_dir_is_git_ignored() -> None:
    gitignore = (REAL_CONTENT.parent / ".gitignore").read_text(encoding="utf-8")
    assert "seed_output/" in gitignore.splitlines()


def test_real_consent_content_is_valid_and_matches_d32() -> None:
    bundle = load_content(REAL_CONTENT)
    for lang in ("zh-CN", "en"):
        doc = bundle.consent(lang)
        assert doc is not None and doc.approval.status.value == "draft"
        cats = {c.id: c for c in doc.categories}
        assert set(cats) == {
            "platform_terms",
            "therapist_access",
            "ai_provider_processing",
            "research_export",
        }
        assert not cats["research_export"].required and cats["research_export"].default
        assert all(c.required for k, c in cats.items() if k != "research_export")


FORBIDDEN_PROMISES = [
    "we will monitor",
    "24/7 monitoring",
    "someone will respond immediately",
    "we will rescue",
    "实时监控",
    "立即回应",
    "随时有人",
]


def test_consent_text_makes_no_rescue_or_monitoring_promise() -> None:
    for lang in ("zh", "en"):
        text = (REAL_CONTENT / "consent" / lang / "v1.md").read_text(encoding="utf-8").lower()
        for phrase in FORBIDDEN_PROMISES:
            assert phrase not in text, (lang, phrase)


def test_restricted_markdown_parser() -> None:
    sections = parse_restricted_markdown("## A\n\nline one\nline two\n\n- x\n- y\n## B\ntext\n")
    assert sections == [
        {
            "heading": "A",
            "blocks": [
                {"type": "paragraph", "text": "line one line two"},
                {"type": "bullets", "items": ["x", "y"]},
            ],
        },
        {"heading": "B", "blocks": [{"type": "paragraph", "text": "text"}]},
    ]
    for bad in ("## A\n<script>x</script>\n", "# Big\n", "orphan text\n## A\n"):
        with pytest.raises(ValueError):
            parse_restricted_markdown(bad)


def _write_consent(root: Path, lang_dir: str, language: str, extra_cat: bool = False) -> None:
    d = root / "consent" / lang_dir
    d.mkdir(parents=True, exist_ok=True)
    cats = "  - {id: platform_terms, required: true, grantee: platform, title: T, summary: S}\n"
    if extra_cat:
        cats += (
            "  - {id: research_export, required: false, grantee: research_team, "
            "title: T, summary: S}\n"
        )
    (d / "v1.md").write_text(
        f"---\nkind: consent\nid: onboarding\nversion: 1\nlanguage: {language}\n"
        f"approval: {{status: draft}}\nroles: [adolescent, caregiver]\ncategories:\n{cats}---\n"
        "## Heading\ntext\n",
        encoding="utf-8",
    )


def test_consent_languages_must_match(content_dir: Path) -> None:
    _write_consent(content_dir, "en", "en")
    with pytest.raises(ContentError, match="missing language"):
        load_content(content_dir)
    _write_consent(content_dir, "zh", "zh-CN", extra_cat=True)
    with pytest.raises(ContentError, match="categories differ"):
        load_content(content_dir)
    _write_consent(content_dir, "zh", "zh-CN")
    assert load_content(content_dir).consent("zh-CN") is not None


def test_consent_folder_must_match_language(content_dir: Path) -> None:
    _write_consent(content_dir, "en", "zh-CN")
    _write_consent(content_dir, "zh", "zh-CN")
    with pytest.raises(ContentError, match="does not match folder"):
        load_content(content_dir)


def test_settings_password_min_cannot_be_lowered() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(password_min_length=6)


@pytest.mark.db
def test_seed_demo_activity_is_valid_and_idempotent(db: Session) -> None:
    """Phase 7 walkthrough data (Plan §7.4): fictional entries valid against the templates."""
    from app.content.loader import load_content
    from app.diary.entries import template_for, validate_values
    from app.models import DiaryEntry, GroupSkillRecord, Task, TaskCompletion
    from app.models.diary import decode_values
    from app.services.seed_activity import seed_activity

    seed_demo(db)
    db.commit()
    group = db.execute(select(Group)).scalar_one()
    assert group.diary_days_per_week == 5
    assert db.execute(select(func.count()).select_from(Task)).scalar_one() == 2
    assert db.execute(select(func.count()).select_from(TaskCompletion)).scalar_one() == 1
    assert db.execute(select(func.count()).select_from(GroupSkillRecord)).scalar_one() == 1
    content = load_content(REAL_CONTENT)
    skills = (
        {s.id for m in content.taxonomy.modules for s in m.skills} if content.taxonomy else set()
    )
    entries = db.execute(select(DiaryEntry)).scalars().all()
    assert len(entries) == 4
    for e in entries:
        values = decode_values(e.values_json)
        assert validate_values(template_for(content, e.role), values, skills) == values
    assert seed_activity(db) is False
    # Phase 8: Family A's pair is suitable and has one demo invitation (demo episode, demo family)
    from app.models import DyadSuitability, JointSession

    assert db.execute(select(func.count()).select_from(DyadSuitability)).scalar_one() == 1
    joint = db.execute(select(JointSession)).scalar_one()
    assert joint.episode_id == "demo-stub-episode" and joint.status == "invited"
