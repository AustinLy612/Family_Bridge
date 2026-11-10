"""Help-screen and safety content checks (Plan §7.2; Phase 2 acceptance).

- Help, consent and the frontend's safety/help strings contain no real-time-rescue promise
  (forbidden-phrase list in content/safety/forbidden_phrases.yaml).
- Every help page says plainly that the app is not monitored in real time.
- Broken lists or help pages stop the app from starting (content loader fails fast).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from app.content.loader import ContentBundle, ContentError, load_content
from app.content.phrases import forbidden_hits
from app.settings import REPO_ROOT, get_settings


@pytest.fixture(scope="module")
def bundle() -> ContentBundle:
    return load_content(get_settings().content_dir)


@pytest.fixture
def content_copy(tmp_path: Path) -> Path:
    dst = tmp_path / "content"
    shutil.copytree(get_settings().content_dir, dst)
    return dst


def _edit(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text, old
    path.write_text(text.replace(old, new), encoding="utf-8")


def test_help_pages_exist_for_both_languages_and_are_draft(bundle: ContentBundle) -> None:
    for lang in ("zh-CN", "en"):
        doc = bundle.help(lang)
        assert doc is not None and doc.language == lang
        assert doc.approval.status.value == "draft"  # O4, O10: pending hospital/clinical review


def test_help_pages_have_no_rescue_promise_and_say_not_monitored(bundle: ContentBundle) -> None:
    rules = bundle.forbidden_phrases
    assert rules is not None
    for lang, needle in (("en", "not monitored in real time"), ("zh-CN", "不会被实时监看")):
        doc = bundle.help(lang)
        assert doc is not None
        assert forbidden_hits(rules, lang, doc.all_text()) == []
        assert needle in " ".join(doc.all_text())


@pytest.mark.parametrize(
    ("lang", "text"),
    [
        ("en", "We will contact you as soon as we can."),
        ("en", "Someone will reach out to you."),
        ("en", "Your care team is watching over you."),
        ("en", "FamilyBridge is monitored in real time."),
        ("en", "Help is on the way."),
        ("en", "We offer 24/7 support."),
        ("en", "The app will alert your therapist."),
        ("en", "We'll keep you safe."),
        ("zh-CN", "我们会马上联系你。"),
        ("zh-CN", "治疗师会立即通知你"),
        ("zh-CN", "平台会实时监控你的情绪。"),
        ("zh-CN", "24小时守护你。"),
        ("zh-CN", "帮助马上就到。"),
        ("zh-CN", "你现在安全了。"),
        ("zh-CN", "系统会自动通知你的治疗师。"),
    ],
)
def test_forbidden_phrases_are_caught(bundle: ContentBundle, lang: str, text: str) -> None:
    assert bundle.forbidden_phrases is not None
    assert forbidden_hits(bundle.forbidden_phrases, lang, [text]), text


@pytest.mark.parametrize(
    ("lang", "text"),
    [
        ("en", "FamilyBridge is not monitored in real time."),
        ("en", "The app cannot send anyone to help you."),
        ("en", "You can contact the team when they are next open."),
        ("zh-CN", "FamilyBridge 不会被实时监看。"),
        ("zh-CN", "可以在团队下次上班时联系他们。"),
    ],
)
def test_honest_wording_is_allowed(bundle: ContentBundle, lang: str, text: str) -> None:
    assert bundle.forbidden_phrases is not None
    assert forbidden_hits(bundle.forbidden_phrases, lang, [text]) == []


def test_loader_rejects_a_rescue_promise_in_help(content_copy: Path) -> None:
    _edit(
        content_copy / "help" / "en.md",
        "Do not wait for a reply in this app.",
        "Do not worry, someone will call you.",
    )
    with pytest.raises(ContentError, match="forbidden phrase"):
        load_content(content_copy)


def test_loader_rejects_a_rescue_promise_in_consent(content_copy: Path) -> None:
    path = content_copy / "consent" / "zh" / "v1.md"
    text = path.read_text(encoding="utf-8")
    path.write_text(text.rstrip("\n") + "\n\n我们会马上联系你。\n", encoding="utf-8")
    with pytest.raises(ContentError, match="forbidden phrase"):
        load_content(content_copy)


def test_loader_requires_the_not_monitored_statement(content_copy: Path) -> None:
    _edit(
        content_copy / "help" / "zh.md",
        "FamilyBridge 不会被实时监看。",
        "FamilyBridge 是一个学习平台。",
    )
    with pytest.raises(ContentError, match="must say"):
        load_content(content_copy)


def test_loader_requires_both_help_languages(content_copy: Path) -> None:
    (content_copy / "help" / "zh.md").unlink()
    with pytest.raises(ContentError, match="every language"):
        load_content(content_copy)


def test_loader_rejects_html_in_help(content_copy: Path) -> None:
    _edit(content_copy / "help" / "en.md", "## For a moment", "## For a <b>moment</b>")
    with pytest.raises(ContentError, match="HTML"):
        load_content(content_copy)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("      - 割腕\n", "      - 割腕\n      - 割腕\n", "duplicate term"),
        (
            "    benign:\n      - 想死你了\n",
            "    benign:\n      - 想死你了\n      - 自杀\n",
            "both risky and benign",
        ),
        ("      - 自杀\n", "      - ' 自杀'\n", "whitespace"),
    ],
)
def test_keyword_list_validation(content_copy: Path, old: str, new: str, message: str) -> None:
    _edit(content_copy / "safety" / "risk_keywords.yaml", old, new)
    with pytest.raises(ContentError, match=message):
        load_content(content_copy)


def test_invalid_regex_in_forbidden_list_is_rejected(content_copy: Path) -> None:
    _edit(content_copy / "safety" / "forbidden_phrases.yaml", "'24/7'", "'24/7('")
    with pytest.raises(ContentError, match="invalid pattern"):
        load_content(content_copy)


def _strings(node: object) -> list[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [s for v in node.values() for s in _strings(v)]
    if isinstance(node, list):
        return [s for v in node for s in _strings(v)]
    return []


@pytest.mark.parametrize(("lang", "file"), [("en", "en.json"), ("zh-CN", "zh-CN.json")])
def test_frontend_strings_have_no_rescue_promise(
    bundle: ContentBundle, lang: str, file: str
) -> None:
    """Every UI string, not only the help screen, is scanned (Plan §7.2)."""
    locale = REPO_ROOT / "frontend" / "src" / "i18n" / "locales" / file
    strings = _strings(json.loads(locale.read_text(encoding="utf-8")))
    assert len(strings) > 100
    assert bundle.forbidden_phrases is not None
    assert forbidden_hits(bundle.forbidden_phrases, lang, strings) == []
