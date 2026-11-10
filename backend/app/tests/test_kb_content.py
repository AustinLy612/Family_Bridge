"""Phase 3 content: retrieval eval set and handout index rules (Plan §5.3 steps 3, 8)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from app.content.loader import ContentError, load_content
from app.settings import get_settings

EVAL = "eval/retrieval/v1.yaml"


@pytest.fixture
def content_copy(tmp_path: Path) -> Path:
    return Path(shutil.copytree(get_settings().content_dir, tmp_path / "content"))


def _edit_eval(root: Path, fn) -> None:  # type: ignore[no-untyped-def]
    p = root / EVAL
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    fn(data)
    p.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


def test_repository_eval_set_meets_the_plan() -> None:
    bundle = load_content(get_settings().content_dir)
    ev, idx = bundle.retrieval_eval, bundle.handouts
    assert ev is not None and idx is not None
    assert len(ev.queries) >= 60 and ev.k == 5 and ev.target_recall == 0.85
    langs = {q.language for q in ev.queries}
    assert langs == {"zh-CN", "en"}
    modules = {h.module for h in idx.handouts}
    by_id = {h.id: h.module for h in idx.handouts}
    for lang in langs:
        covered = {by_id[q.expected[0]] for q in ev.queries if q.language == lang}
        assert covered == modules, f"{lang} queries miss modules {modules - covered}"


def test_unknown_handout_in_eval_is_rejected(content_copy: Path) -> None:
    _edit_eval(content_copy, lambda d: d["queries"][0].update(expected=["mf.h99"]))
    with pytest.raises(ContentError, match=r"unknown handout mf.h99"):
        load_content(content_copy)


def test_unknown_skill_filter_in_eval_is_rejected(content_copy: Path) -> None:
    _edit_eval(content_copy, lambda d: d["queries"][0].update(skill_ids=["mf.nope"]))
    with pytest.raises(ContentError, match=r"unknown skill mf.nope"):
        load_content(content_copy)


def test_eval_needs_enough_queries_per_language(content_copy: Path) -> None:
    _edit_eval(
        content_copy, lambda d: d.update(queries=[q for q in d["queries"] if q["language"] != "en"])
    )
    with pytest.raises(ContentError):
        load_content(content_copy)


def test_eval_must_cover_every_module(content_copy: Path) -> None:
    def drop_ie(d: dict) -> None:  # type: ignore[type-arg]
        d["queries"] = [q for q in d["queries"] if not q["expected"][0].startswith("ie.")]
        # keep enough queries so only the coverage rule fails
        extra = [dict(q, id=f"q9{i:02d}") for i, q in enumerate(d["queries"][:20])]
        d["queries"] += extra

    _edit_eval(content_copy, drop_ie)
    with pytest.raises(ContentError, match="no query covers module interpersonal_effectiveness"):
        load_content(content_copy)


def test_handout_pages_cannot_overlap(content_copy: Path) -> None:
    p = content_copy / "skills/handouts.yaml"
    text = p.read_text(encoding="utf-8").replace("pages: [6]", "pages: [5, 6]", 1)
    p.write_text(text, encoding="utf-8")
    with pytest.raises(ContentError, match="page 5 is in both"):
        load_content(content_copy)
