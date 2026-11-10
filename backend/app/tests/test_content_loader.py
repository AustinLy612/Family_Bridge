"""Content loader: validates everything, fails fast (Plan Phase 0 task 6 + acceptance)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.content.loader import ContentError, load_content
from app.main import create_app
from app.settings import REPO_ROOT, Settings

VALID_TAXONOMY = """\
kind: skill_taxonomy
version: 1
approval: {status: draft, approved_by: null, approved_at: null}
modules:
  - id: mindfulness
    skills:
      - id: mf.states_of_mind
      - id: mf.what_skills
"""


def _write(d: Path, rel: str, text: str) -> None:
    p = d / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_repository_content_is_valid() -> None:
    bundle = load_content(REPO_ROOT / "content")
    assert bundle.taxonomy is not None
    ids = bundle.taxonomy.skill_ids()
    assert "wmp.validating_others" in ids and "ie.dear_man" in ids
    assert len(ids) == len(set(ids)) == 40  # Plan Appendix B
    assert bundle.taxonomy.approval.status == "draft"  # O10: not clinically reviewed


def test_valid_file_loads_with_hashes(content_dir: Path) -> None:
    _write(content_dir, "skills/taxonomy.yaml", VALID_TAXONOMY)
    _write(content_dir, "README.md", "docs are ignored")
    bundle = load_content(content_dir)
    assert list(bundle.hashes) == ["skills/taxonomy.yaml"]
    assert len(bundle.aggregate_hash) == 64


def test_hash_changes_when_content_changes(content_dir: Path) -> None:
    _write(content_dir, "skills/taxonomy.yaml", VALID_TAXONOMY)
    before = load_content(content_dir).aggregate_hash
    _write(content_dir, "skills/taxonomy.yaml", VALID_TAXONOMY.replace("version: 1", "version: 2"))
    assert load_content(content_dir).aggregate_hash != before


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("kind: skill_taxonomy\nversion: [1\n", "invalid YAML"),
        ("- just\n- a list\n", "top level must be a mapping"),
        (VALID_TAXONOMY.replace("mf.what_skills", "Not A Valid Id"), "should match pattern"),
        (VALID_TAXONOMY.replace("mf.what_skills", "mf.states_of_mind"), "duplicate skill id"),
        (VALID_TAXONOMY.replace("status: draft", "status: final"), "approval.status"),
        (
            VALID_TAXONOMY.replace("status: draft", "status: approved"),
            "requires approved_by and approved_at",
        ),
        (VALID_TAXONOMY + "unexpected_field: 1\n", "unexpected_field"),
        (VALID_TAXONOMY.replace("version: 1", "version: 0"), "version"),
    ],
)
def test_malformed_file_is_rejected(content_dir: Path, text: str, expected: str) -> None:
    _write(content_dir, "skills/taxonomy.yaml", text)
    with pytest.raises(ContentError) as exc:
        load_content(content_dir)
    assert expected in str(exc.value)


def test_unrecognised_file_is_rejected(content_dir: Path) -> None:
    _write(content_dir, "skills/taxonomy.yaml", VALID_TAXONOMY)
    _write(content_dir, "fallbacks/x.md", "no schema registered yet")
    with pytest.raises(ContentError, match="no schema registered"):
        load_content(content_dir)


def test_all_problems_are_reported_together(content_dir: Path) -> None:
    _write(content_dir, "skills/taxonomy.yaml", "kind: [\n")
    _write(content_dir, "stray.txt", "x")
    with pytest.raises(ContentError) as exc:
        load_content(content_dir)
    assert len(exc.value.problems) == 2


def test_app_refuses_to_start_with_invalid_content(content_dir: Path) -> None:
    _write(content_dir, "skills/taxonomy.yaml", "kind: [\n")
    with pytest.raises(ContentError):
        create_app(Settings(content_dir=content_dir, app_env="test"))
