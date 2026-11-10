"""Keyword risk channel (Plan §5.7; Phase 2 acceptance): zh/en detection, no over-triggering on
ordinary frustration, multi-turn and indirect disclosures (§9.2), and the LLM-channel contract.

These run against the real `content/safety/risk_keywords.yaml` (draft lists, O10), so a list edit
that breaks a case fails CI.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import pytest

from app.content.loader import ContentBundle, load_content
from app.safety.screening import (
    Assessment,
    KeywordMatcher,
    RiskLevel,
    Tier,
    screen,
)
from app.settings import get_settings


@pytest.fixture(scope="module")
def bundle() -> ContentBundle:
    return load_content(get_settings().content_dir)


@pytest.fixture(scope="module")
def matcher(bundle: ContentBundle) -> KeywordMatcher:
    assert bundle.risk_keywords is not None
    return KeywordMatcher(bundle.risk_keywords)


HIGH = [
    # zh (from DBT_Revised's tests and lists)
    "我想自杀",
    "我想伤害自己",
    "活不下去了，想结束生命",
    "我想割腕",
    "我想自杀，不想活了，我要跳楼",
    "有时候觉得死了算了",
    # en
    "I want to die",
    "sometimes I think about killing myself",
    "I just want to end my life",
    "I've been cutting myself again",
    "I don't want to live anymore",
    "I don’t want to live anymore",  # noqa: RUF001 (curly apostrophe on purpose)
    "I took an overdose once",
    # indirect (§9.2)
    "everyone would be better off without me",
    "I wrote a goodbye note",
    "I just want to go to sleep and never wake up",
    "大家没有我会更好",
    "我已经写好了遗书",
    "真想一了百了",
    # spacing / width tricks
    "想 死",
    "我 想 自 杀",
    "I WANT TO DIE",
    "I want  to\tdie",
]

MEDIUM = [
    "我感到绝望",
    "活着没意义",
    "我真的撑不下去了",
    "I feel hopeless",
    "I can't go on like this",
    "I hate myself",
    "我恨我自己",
    "讨厌自己",
    "nothing matters anymore",
]

# Ordinary frustration and figures of speech must not trigger (Plan §5.7).
BENIGN = [
    "今天天气很好",
    "我觉得正念呼吸很有帮助",
    "今天心情不好，感觉很累",
    "笑死我了",
    "热死了，空调坏了",
    "这道题难死了",
    "作业烦死了",
    "想死你了！",
    "植物死掉了",
    "我要杀了这个boss",
    "我妈妈气死我了",
    "this is so annoying",
    "this homework is killing me",
    "I'm dying to see that film",
    "I could kill for a pizza",
    "we're going to kill them at basketball",
    "the lesson felt hopelessly long",
    "nothing matters more than family",
    "my phone died",
    "I hate Mondays",
    "we watched Suicide Squad",
    "I jumped off the diving board",
]


@pytest.mark.parametrize("text", HIGH)
def test_high_risk_stops(matcher: KeywordMatcher, text: str) -> None:
    r = screen(matcher, text)
    assert r.level is RiskLevel.high and r.should_stop and r.channel == "keyword", r


@pytest.mark.parametrize("text", MEDIUM)
def test_moderate_and_concern_are_medium(matcher: KeywordMatcher, text: str) -> None:
    r = screen(matcher, text)
    assert r.level is RiskLevel.medium and not r.should_stop, r


@pytest.mark.parametrize("text", BENIGN)
def test_benign_text_does_not_trigger(matcher: KeywordMatcher, text: str) -> None:
    r = screen(matcher, text)
    assert r.level is RiskLevel.none and not r.should_stop and r.terms == [], (text, r.terms)


def test_reports_the_matched_terms(matcher: KeywordMatcher) -> None:
    r = screen(matcher, "我想自杀，不想活了，我要跳楼")
    assert {"自杀", "不想活", "跳楼"} <= set(r.hits[Tier.high])


def test_languages_are_checked_whatever_the_user_language(matcher: KeywordMatcher) -> None:
    assert screen(matcher, "I want to die", language="zh-CN").level is RiskLevel.high
    assert screen(matcher, "我想自杀", language="en").level is RiskLevel.high


def test_multi_turn_phrase_split_across_messages(matcher: KeywordMatcher) -> None:
    r = screen(matcher, "活了", recent=["我真的不想"])
    assert r.level is RiskLevel.high and "不想活" in r.terms
    r = screen(matcher, "without me", recent=["honestly everyone would be better off"])
    assert r.level is RiskLevel.high


def test_earlier_flag_is_not_raised_again_on_later_turns(matcher: KeywordMatcher) -> None:
    assert screen(matcher, "今天还好", recent=["我想自杀"]).level is RiskLevel.none
    # ...but saying it again is a new hit.
    assert screen(matcher, "我还是想自杀", recent=["我想自杀"]).level is RiskLevel.high


def test_only_recent_turns_are_joined(matcher: KeywordMatcher) -> None:
    old = ["我真的不想", "ok", "ok", "ok"]
    assert screen(matcher, "活了", recent=old).level is RiskLevel.none


def test_multi_turn_escalation_from_medium_to_high(matcher: KeywordMatcher) -> None:
    turns = ["school is hard", "I feel hopeless", "I want to die"]
    levels = [screen(matcher, t, recent=turns[:i]).level for i, t in enumerate(turns)]
    assert levels == [RiskLevel.none, RiskLevel.medium, RiskLevel.high]


class FakeAssessor:
    def __init__(self, result: Assessment | None) -> None:
        self.result = result
        self.calls: list[str] = []

    def assess(
        self,
        text: str,
        recent: Sequence[str],
        language: str,
        hits: Mapping[Tier, Sequence[str]] | None = None,
    ) -> Assessment | None:
        self.calls.append(text)
        return self.result


def test_llm_channel_runs_only_when_keywords_fire(matcher: KeywordMatcher) -> None:
    a = FakeAssessor(Assessment(RiskLevel.low, should_stop=False))
    screen(matcher, "今天天气很好", assessor=a)
    assert a.calls == []
    r = screen(matcher, "I feel hopeless", assessor=a)
    assert a.calls == ["I feel hopeless"] and r.level is RiskLevel.low and r.channel == "llm"


def test_llm_unavailable_falls_back_to_keywords(matcher: KeywordMatcher) -> None:
    r = screen(matcher, "我想自杀", assessor=FakeAssessor(None))
    assert r.level is RiskLevel.high and r.should_stop and r.channel == "keyword"


def test_llm_high_always_stops(matcher: KeywordMatcher) -> None:
    r = screen(matcher, "I feel hopeless", assessor=FakeAssessor(Assessment(RiskLevel.high, False)))
    assert r.should_stop


def test_keyword_lists_are_draft_and_bilingual(bundle: ContentBundle) -> None:
    kw = bundle.risk_keywords
    assert kw is not None and kw.approval.status.value == "draft"  # O10
    assert set(kw.languages) == {"zh-CN", "en"}
    assert len(kw.languages["zh-CN"].high) >= 15 and len(kw.languages["en"].high) >= 15
