"""Deterministic rule checks (Plan §5.4 "Rule checks"; D6, D7)."""

from __future__ import annotations

import pytest

from app.ai.rules import RuleChecker, SourceChunk, cjk_ratio, shared_run, shared_words
from app.content.loader import ContentBundle, load_content
from app.settings import Settings
from app.tests.ai_fixtures import CHUNK_EN, CHUNK_ZH, chunks


@pytest.fixture(scope="module")
def bundle() -> ContentBundle:
    return load_content(Settings().content_dir)


@pytest.fixture(scope="module")
def checker(bundle: ContentBundle) -> RuleChecker:
    assert bundle.output_rules is not None
    return RuleChecker(bundle.output_rules, bundle.forbidden_phrases)


def _codes(v: list) -> set[str]:  # type: ignore[type-arg]
    return {str(x) for x in v}


# --- 1. citations ------------------------------------------------------------------------------


def test_citations(checker: RuleChecker) -> None:
    src = chunks()
    assert checker.citations(["S1"], "manual", src, True) == []
    assert "citation:unknown_label" in _codes(checker.citations(["S9"], "manual", src, True))
    assert "citation:manual_without_citation" in _codes(checker.citations([], "manual", src, True))
    assert "citation:manual_without_sufficient_retrieval" in _codes(
        checker.citations(["S1"], "manual", src, False)
    )
    assert "citation:manual_without_sufficient_retrieval" in _codes(
        checker.citations([], "manual", [], False)
    )
    assert checker.citations([], "general", [], False) == []


# --- 2. overlap (acceptance: a seeded copied-text output is blocked) -----------------------------


def test_seeded_copied_text_is_blocked(checker: RuleChecker) -> None:
    copied_zh = "你可以试试：" + CHUNK_ZH[5:30] + "。"
    copied_en = "Try this: " + " ".join(CHUNK_EN.split()[2:15]) + "."
    assert _codes(checker.overlap([copied_zh], chunks())) == {"overlap:retrieved_chunk"}
    assert _codes(checker.overlap([copied_en], chunks())) == {"overlap:retrieved_chunk"}


def test_paraphrase_is_allowed(checker: RuleChecker) -> None:
    para_zh = "情绪上来时，先坐稳，慢慢呼吸几次，再找找身边的颜色，然后再开口。"
    para_en = "When feelings surge, steady yourself, breathe slowly, look for colours, then speak."
    assert checker.overlap([para_zh, para_en], chunks()) == []


def test_overlap_thresholds() -> None:
    src = "abcdefghijklmnopqrstuvwxyz"
    assert shared_run("xx" + src[:20] + "yy", src, 20) == 20
    assert shared_run("xx" + src[:19] + "yy", src, 20) == 0
    words = "one two three four five six seven eight nine ten eleven twelve thirteen"
    assert shared_words("so " + " ".join(words.split()[:12]), words, 12)
    assert not shared_words(" ".join(words.split()[:11]), words, 12)


def test_overlap_checks_the_manual_fingerprint(bundle: ContentBundle) -> None:
    from app.kb import fingerprint as fp

    secret = "这是一段只为测试而虚构的手册文字它足够长可以组成多个窗口用于比较"
    assert bundle.output_rules is not None
    c = RuleChecker(bundle.output_rules, None, frozenset(fp.build([secret])))
    assert _codes(c.overlap(["开头" + secret[:24]], [])) == {"overlap:manual_fingerprint"}
    assert c.overlap(["完全不同的一句话，讲的是别的事情。"], []) == []


# --- 3. language --------------------------------------------------------------------------------


def test_language(checker: RuleChecker) -> None:
    assert checker.language(["我们来练习 TIPP 技能。"], "zh-CN") == []
    assert _codes(checker.language(["Let's practise TIPP now."], "zh-CN")) == {
        "language:not_chinese"
    }
    assert _codes(checker.language(["Let's practise 技能 now."], "en")) == {"language:not_english"}
    assert checker.language(["123 !!"], "en") == []
    assert cjk_ratio(["ab中"]) == pytest.approx(1 / 3)


# --- 5. output patterns ---------------------------------------------------------------------------

BLOCKED = [
    ("disclosure_request", "请详细说说你经历过的创伤。"),
    ("disclosure_request", "Tell me about the worst thing that happened at home."),
    ("blame_shame", "You're being dramatic and attention-seeking."),
    ("blame_shame", "这个回答太幼稚了，你应该感到羞耻。"),
    ("coercive_parenting", "如果孩子顶嘴，可以不给他吃晚饭。"),
    ("coercive_parenting", "Check her phone secretly while she sleeps."),
    ("diagnosis_medication", "You probably have depression."),
    ("diagnosis_medication", "可以把药加量到 20mg。"),
    ("fabricated_evidence", "Research shows 73% of teens feel better."),
    ("graphic_self_harm", "她拿起刀割手腕。"),
    ("adult_disclosure", "我以前也割过自己。"),
    ("adult_disclosure", "When I was depressed after my divorce I drank."),
    ("boundary", "这是我们之间的小秘密，不要告诉你的父母。"),
    ("boundary", "I love you and I'm your best friend."),
    ("stereotype", "男孩子天生就不会表达情绪。"),
    ("false_authority", "你的治疗师已经同意我可以查看你的日记。"),
    ("privacy", "你妈妈在日记卡上写了她很焦虑。"),
]

ALLOWED = [
    "我们来练习 GIVE 技能：温和地说话，表现出兴趣，认可对方，轻松一点。",
    "Notice the urge, name it, and choose one small step that fits your goal.",
    "如果你愿意，可以说一说这周哪一个时刻用到了这个技能。",
    "A specific, time-limited consequence works better than a long punishment.",
    "如果你现在有危险，请立刻联系身边的大人或拨打急救电话。",
]


@pytest.mark.parametrize(("category", "text"), BLOCKED)
def test_blocked_patterns(checker: RuleChecker, category: str, text: str) -> None:
    assert f"pattern:{category}" in _codes(checker.patterns([text]))


@pytest.mark.parametrize("text", ALLOWED)
def test_ordinary_coaching_passes(checker: RuleChecker, text: str) -> None:
    assert checker.patterns([text]) == []


@pytest.mark.parametrize(
    "text",
    [
        "Option B: she sighs and says 'you're overreacting'. That one invalidates.",
        'Saying "you\'re being dramatic" tells your teen the feeling is wrong.',
        "如果说“你太矫情了”，孩子会觉得感受不被接纳。",
    ],
)
def test_quoted_examples_of_invalidation_are_allowed(checker: RuleChecker, text: str) -> None:
    assert checker.patterns([text]) == []


def test_quoting_does_not_unlock_other_categories(checker: RuleChecker) -> None:
    assert "pattern:boundary" in _codes(checker.patterns(['"Keep this a secret," I said.']))
    assert "pattern:blame_shame" in _codes(checker.patterns(["Honestly, you're overreacting."]))


def test_crisis_promises_are_blocked(checker: RuleChecker) -> None:
    assert "pattern:crisis_promise" in _codes(checker.patterns(["We will call you right away."]))
    assert "pattern:crisis_promise" in _codes(checker.patterns(["治疗师会马上联系你。"]))
    assert "pattern:boundary" in _codes(checker.patterns(["I will always be here for you."]))
    assert "pattern:boundary" in _codes(checker.patterns(["我会一直陪着你。"]))


# --- 6. medical caution ---------------------------------------------------------------------------


def test_tipp_temperature_needs_health_caution(checker: RuleChecker) -> None:
    bare = ["Put your face in icy water for 30 seconds."]
    assert _codes(checker.medical_caution(bare)) == {"medical_caution:tipp_health_caution_missing"}
    ok = [*bare, "Check with a doctor first if you have a heart condition."]
    assert checker.medical_caution(ok) == []
    assert checker.medical_caution(["做十分钟剧烈运动。"]) != []
    assert checker.medical_caution(["做十分钟剧烈运动，有心脏问题先问医生。"]) == []


# --- taxonomy + combined --------------------------------------------------------------------------


def test_taxonomy() -> None:
    skills = {"dt.tipp": "distress_tolerance", "dt.stop": "distress_tolerance", "mf.wise": "mf"}
    assert (
        RuleChecker.taxonomy("dt.tipp", ["dt.stop", "mf.wise"], "distress_tolerance", skills) == []
    )
    codes = _codes(RuleChecker.taxonomy("dt.made_up", ["dt.tipp", "x"], "mf", skills))
    assert codes == {
        "taxonomy:selected_skill_not_in_taxonomy",
        "taxonomy:alternative_not_in_taxonomy",
    }
    assert _codes(RuleChecker.taxonomy("dt.tipp", ["dt.tipp", "dt.stop"], "mf", skills)) == {
        "taxonomy:module_mismatch",
        "taxonomy:alternative_repeats_selected",
    }


def test_check_skips_prose_rules_for_internal_functions(checker: RuleChecker) -> None:
    data: dict[str, object] = {
        "content": "You're being dramatic.",
        "grounding": "none",
        "source_chunk_ids": [],
    }
    assert checker.check(data, language="zh-CN", user_facing=False) == []
    assert checker.check(data, language="zh-CN", user_facing=True) != []


def test_source_chunk_is_frozen() -> None:
    s = SourceChunk("S1", "id", "t", "h", "title", "m")
    with pytest.raises(AttributeError):
        s.label = "S2"  # type: ignore[misc]
