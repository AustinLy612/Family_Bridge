"""Diary templates (Plan §5.6; D9, D17): schema rules and repository checks. No database."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml

from app.content.loader import ContentError, load_content
from app.content.models import DiaryFieldType, DiaryTemplate
from app.settings import get_settings


@pytest.fixture
def content_copy(tmp_path: Path) -> Path:
    return Path(shutil.copytree(get_settings().content_dir, tmp_path / "content"))


def _teen(root: Path) -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(
        (root / "diary/adolescent/v1.yaml").read_text(encoding="utf-8")
    )
    return data


def _write(root: Path, rel: str, data: dict[str, Any]) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


def test_repository_templates() -> None:
    bundle = load_content(get_settings().content_dir)
    teen = bundle.diary_template("adolescent")
    carer = bundle.diary_template("caregiver")
    assert teen is not None and carer is not None
    ids = {f.id for f in teen.fields}
    # D9: the proposal fields plus the DBT_Revised EMA items, including both urges
    assert {"sad", "anxious", "angry", "calm", "hopeful", "distress"} <= ids
    assert {"self_harm_urge", "suicide_urge", "skill_used", "skills_used", "skill_helpful"} <= ids
    assert {"doctor_visit", "group_therapy", "medication_change", "note"} <= ids
    assert {f.id for f in carer.fields} >= {"validating", "invalidating", "distress", "note"}
    assert not any(f.urge for f in carer.fields)
    # every label exists in both languages and the drafts are marked as drafts (O3)
    for t in (teen, carer):
        assert t.approval.status == "draft"
        texts = t.all_text()
        assert len(texts["zh-CN"]) == len(texts["en"]) > 10
        assert all(f.type is not DiaryFieldType.note or f.show_if is None for f in t.fields)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (
            lambda d: d["groups"][0]["fields"].append(dict(d["groups"][0]["fields"][0])),
            "duplicate field",
        ),
        (lambda d: _field(d, "skills_used").update(show_if="sad"), "show_if"),
        (lambda d: _field(d, "skills_used").update(show_if="skill_helpful"), "show_if"),
        (lambda d: _field(d, "sad").update(urge=True), "urge fields"),
        (lambda d: _field(d, "self_harm_urge").update(urge=False), "urge: true"),
        (lambda d: _field(d, "skill_used").update(low={"zh-CN": "低", "en": "low"}), "anchors"),
        (lambda d: _field(d, "doctor_visit").update(type="frequency"), "at least two options"),
        (lambda d: _field(d, "sad").update(label={"en": "Sad"}), "zh-CN"),
    ],
)
def test_invalid_templates_are_rejected(change: Any, message: str) -> None:
    data = _teen(get_settings().content_dir)
    change(data)
    with pytest.raises(ValueError, match=message):
        DiaryTemplate.model_validate(data)


def _field(data: dict[str, Any], field_id: str) -> dict[str, Any]:
    for g in data["groups"]:
        for f in g["fields"]:
            if f["id"] == field_id:
                return f  # type: ignore[no-any-return]
    raise KeyError(field_id)


def test_loader_checks_folder_version_and_wording(content_copy: Path) -> None:
    data = _teen(content_copy)
    _write(content_copy, "diary/caregiver/v2.yaml", data)  # role does not match the folder
    data3 = dict(data, version=3)
    _write(content_copy, "diary/adolescent/v2.yaml", data3)  # version does not match the name
    data4 = dict(data, version=4)
    data4["intro"] = {
        "zh-CN": "记下此刻的感受。",
        "en": "Your therapist will contact you if a score is high.",  # a rescue promise (§7.2)
    }
    _write(content_copy, "diary/adolescent/v4.yaml", data4)
    with pytest.raises(ContentError) as err:
        load_content(content_copy)
    text = "\n".join(err.value.problems)
    assert "does not match folder" in text
    assert "does not match version 3" in text
    assert "diary/adolescent/v4.yaml: forbidden phrase" in text


def test_latest_live_version_is_served(content_copy: Path) -> None:
    data = _teen(content_copy)
    v2 = dict(data, version=2, approval={"status": "retired"})
    _write(content_copy, "diary/adolescent/v2.yaml", v2)
    bundle = load_content(content_copy)
    t = bundle.diary_template("adolescent")
    assert t is not None and t.version == 1  # retired versions are not offered for new entries
    old = bundle.diary_template("adolescent", 2)
    assert old is not None and old.version == 2  # but still render entries made with them
