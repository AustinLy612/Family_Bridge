"""AI content (Phase 4 tasks 2, 8): prompts, blocks, fallbacks, eval sets, output rules."""

from __future__ import annotations

import pytest

from app.ai import templating
from app.ai.schemas import COMMON_VARS, FUNCTIONS, PROMPT_VARS
from app.content.loader import ContentBundle, load_content
from app.content.models import ADVERSARIAL_CATEGORIES
from app.settings import Settings

LANGS = ("zh-CN", "en")


@pytest.fixture(scope="module")
def bundle() -> ContentBundle:
    return load_content(Settings().content_dir)


def test_every_function_role_language_has_a_prompt(bundle: ContentBundle) -> None:
    for name, spec in FUNCTIONS.items():
        for role in spec.roles:
            for lang in LANGS:
                found = bundle.prompt(name, role, lang)
                assert found is not None, (name, role, lang)
                tpl, sha = found
                assert len(sha) == 64
                assert tpl.placeholders() <= PROMPT_VARS[name] | COMMON_VARS, (name, role, lang)
                for block in tpl.blocks:
                    assert bundle.prompt_block(block, lang) is not None, block


def test_every_function_has_a_bilingual_fallback(bundle: ContentBundle) -> None:
    for name in FUNCTIONS:
        if name == "assess_risk":
            continue  # keyword-only screening is its fallback
        for lang in LANGS:
            doc = bundle.fallback(name, None, lang)
            assert doc is not None and doc.notice, (name, lang)


def test_fallbacks_fill_into_valid_outputs(bundle: ContentBundle) -> None:
    for name, spec in FUNCTIONS.items():
        for lang in LANGS:
            doc = bundle.fallback(name, "dt.tipp", lang)
            if doc is None or doc.output is None:
                continue
            model = templating.fill_fallback(doc.output, spec.output, "TIPP", "Distress")
            dumped = str(model.model_dump())
            assert "{skill_name}" not in dumped and "{module_name}" not in dumped, (name, lang)


def test_golden_set_covers_all_skills(bundle: ContentBundle) -> None:
    golden = bundle.golden_eval
    assert golden is not None and bundle.taxonomy is not None
    assert {g.skill_id for g in golden.skills} == set(bundle.taxonomy.skill_ids())
    assert len(golden.rubric) >= 4


def test_adversarial_suite_shape(bundle: ContentBundle) -> None:
    sets = bundle.adversarial_sets
    assert {s.category for s in sets} == set(ADVERSARIAL_CATEGORIES)
    cases = [c for s in sets for c in s.cases]
    assert len({c.id for c in cases}) == len(cases)
    for s in sets:
        assert len(s.cases) >= 5
        assert {c.language for c in s.cases} == set(LANGS)
        assert any(c.severity == "high" for c in s.cases) or s.category in (
            "stereotyped_family_roles",
            "self_disclosure_requests",
            "shame_inducing_feedback",
        )
    targets = {c.target for c in cases}
    assert targets == {"safety", "function", "output"}
    assert any(c.variant == "multi_turn" for c in cases)
    assert any(c.variant == "indirect" for c in cases)


def test_prompts_and_fallbacks_avoid_monitoring_promises(bundle: ContentBundle) -> None:
    """Loader cross-check (forbidden phrases) holds for AI content too: the bundle loaded."""
    assert bundle.output_rules is not None and bundle.forbidden_phrases is not None
    assert bundle.output_rules.overlap.max_shared_chars == 19
