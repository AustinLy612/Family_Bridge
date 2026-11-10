"""Manual-overlap check (Plan §5.3 step 9; D7): repository text must not copy the manual."""

from __future__ import annotations

import re

from app.kb import fingerprint as fp

SOURCE = (
    "当强烈的情绪出现时，先停下来观察身体的感觉，再描述发生了什么，最后选择一个有效的行动方式。"
)


def test_copied_run_is_flagged_even_with_changed_punctuation() -> None:
    fpr = frozenset(fp.build([SOURCE]))
    copied = "说明：先停下来 观察身体的感觉；再描述发生了什么——最后选择"
    found = fp.overlaps(copied, fpr)
    assert len(found) == 1 and found[0].length >= fp.COPY_RUN


def test_shared_terms_and_paraphrases_pass() -> None:
    fpr = frozenset(fp.build([SOURCE]))
    assert fp.overlaps("情绪很强的时候，可以暂停一下，留意身体有什么变化。", fpr) == []
    assert fp.overlaps("观察身体的感觉", fpr) == []  # short shared phrase, below COPY_RUN


def test_fingerprint_file_holds_hashes_only() -> None:
    lines = fp.FINGERPRINT_PATH.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("# manual-fingerprint v1")
    body = lines[1:]
    assert len(body) > 10_000
    assert all(re.fullmatch(r"[0-9a-f]{12}", ln) for ln in body)


def test_repository_does_not_copy_the_manual() -> None:
    # Same check as scripts/scan_repo.py: every committable text file vs the committed fingerprint.
    assert fp.scan_repo(fp.FINGERPRINT_PATH.parents[1]) == []
