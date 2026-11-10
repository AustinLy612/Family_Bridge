"""The check-in passes an automated scan for probing / disclosure patterns (Phase 5 acceptance;
D22: optional, one question, no follow-up probing, no trauma / self-harm / family-conflict detail).

Scanned: the prompt's own JSON example, the mock output, and the authored fallback, in both
languages, with the same output rules the AI service applies to every model answer.
"""

from __future__ import annotations

import json
import re

import pytest

from app.ai.mock import default_response
from app.ai.provider import LLMRequest
from app.ai.rules import RuleChecker
from app.content.loader import ContentBundle, load_content
from app.settings import Settings

LANGS = ("zh-CN", "en")
PROBING = ["disclosure_request", "privacy", "graphic_self_harm", "blame_shame", "boundary"]


@pytest.fixture(scope="module")
def bundle() -> ContentBundle:
    return load_content(Settings().content_dir)


@pytest.fixture(scope="module")
def checker(bundle: ContentBundle) -> RuleChecker:
    assert bundle.output_rules is not None
    return RuleChecker(bundle.output_rules, bundle.forbidden_phrases)


def _texts(out: dict[str, object]) -> list[str]:
    return [str(out[k]) for k in ("greeting", "question") if out.get(k)]


def _assert_clean(checker: RuleChecker, texts: list[str]) -> None:
    hits = [v for v in checker.patterns(texts) if v.rule in PROBING]
    assert not hits, (hits, texts)


@pytest.mark.parametrize("lang", LANGS)
def test_prompt_example_is_clean(bundle: ContentBundle, checker: RuleChecker, lang: str) -> None:
    found = bundle.prompt("personal_inquiry", "adolescent", lang)
    assert found is not None
    prompt = found[0]
    m = re.search(r"\{.*\"greeting\".*\}", prompt.system)
    assert m, "the prompt carries a JSON example"
    example = json.loads(m.group(0))
    _assert_clean(checker, _texts(example))
    # the prompt itself tells the model not to probe
    text = prompt.system.casefold()
    assert ("one question" in text and "self-harm" in text) or (
        "只问一个问题" in text and "伤害自己" in text
    )


@pytest.mark.parametrize("lang", LANGS)
def test_mock_and_fallback_are_clean(
    bundle: ContentBundle, checker: RuleChecker, lang: str
) -> None:
    mock = json.loads(
        default_response(
            LLMRequest(function="personal_inquiry", messages=[], hints={"language": lang})
        )
    )
    _assert_clean(checker, _texts(mock))
    doc = bundle.fallback("personal_inquiry", None, lang)
    assert doc is not None and doc.output is not None
    _assert_clean(checker, _texts(dict(doc.output)))


@pytest.mark.parametrize(
    "probe",
    [
        "Can you tell me more about what happened at home and who hurt you?",
        "你能详细说说你是怎么伤害自己的吗？",
    ],
)
def test_scan_catches_probing_questions(checker: RuleChecker, probe: str) -> None:
    hits = [v for v in checker.patterns([probe]) if v.rule in PROBING]
    assert hits
