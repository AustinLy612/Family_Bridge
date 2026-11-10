from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.settings import Settings


def test_origins_accept_comma_separated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://localhost:5173, http://127.0.0.1:5173")
    assert Settings().allowed_origins == ["http://localhost:5173", "http://127.0.0.1:5173"]


def test_secrets_are_not_printed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-should-not-appear")
    s = Settings()
    assert "sk-should-not-appear" not in repr(s)
    assert "sk-should-not-appear" not in str(s)
    assert s.deepseek_api_key.get_secret_value() == "sk-should-not-appear"


def test_urge_threshold_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DIARY_URGE_THRESHOLD", "11")
    with pytest.raises(ValidationError):
        Settings()
