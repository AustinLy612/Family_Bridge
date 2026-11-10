"""Pseudonymity of LLM calls (Plan §5.12): no code in the AI layer reads a participant's name,
username or relationship label, so none can reach a model prompt."""

from __future__ import annotations

import re
from pathlib import Path

AI_DIR = Path(__file__).resolve().parents[1] / "ai"
IDENTITY_FIELDS = re.compile(r"\b(display_alias|username|relationship_label|email)\b")


def test_ai_layer_reads_no_identity_fields() -> None:
    hits = [
        f"{path.name}:{n}"
        for path in sorted(AI_DIR.rglob("*.py"))
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if IDENTITY_FIELDS.search(line)
    ]
    assert hits == [], f"identity fields referenced in app/ai: {hits}"
