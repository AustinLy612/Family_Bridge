"""LLM provider: DeepSeek client (retries, errors, request body) and the circuit breaker (D48)."""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest
from pydantic import SecretStr

from app.ai.provider import (
    CircuitBreaker,
    CircuitOpenError,
    DeepSeekProvider,
    GuardedProvider,
    LLMRequest,
    MockProvider,
    ProviderError,
)
from app.settings import Settings

KEY = "sk-test-not-a-real-key"
REQ = LLMRequest(function="hint", messages=[{"role": "user", "content": "hi"}], max_tokens=50)


def _ok(content: str = '{"ok": true}', finish: str = "stop") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": "deepseek-flash",
            "choices": [{"message": {"content": content}, "finish_reason": finish}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 4},
        },
    )


def _provider(
    settings: Settings, handler: Callable[[httpx.Request], httpx.Response], key: str = KEY
) -> tuple[DeepSeekProvider, list[httpx.Request], list[float]]:
    seen: list[httpx.Request] = []
    sleeps: list[float] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    s = settings.model_copy(update={"deepseek_api_key": SecretStr(key), "llm_max_retries": 2})
    client = httpx.Client(transport=httpx.MockTransport(wrapped))
    return DeepSeekProvider(s, client=client, sleep=sleeps.append), seen, sleeps


def test_request_body_disables_thinking_and_asks_for_json(settings: Settings) -> None:
    p, seen, _ = _provider(settings, lambda r: _ok())
    res = p.complete(REQ)
    assert res.text == '{"ok": true}' and res.input_tokens == 3 and res.output_tokens == 4
    body = json.loads(seen[0].content)
    assert body["thinking"] == {"type": "disabled"}
    assert body["response_format"] == {"type": "json_object"}
    assert body["model"] == settings.deepseek_model and body["stream"] is False
    assert seen[0].headers["Authorization"] == f"Bearer {KEY}"


@pytest.mark.parametrize("key", ["", "change-me"])
def test_missing_key_fails_without_a_request(settings: Settings, key: str) -> None:
    p, seen, _ = _provider(settings, lambda r: _ok(), key=key)
    with pytest.raises(ProviderError) as e:
        p.complete(REQ)
    assert e.value.code == "no_api_key" and seen == []


def test_auth_error_is_not_retried_and_never_echoes_the_key(settings: Settings) -> None:
    msg = f"Authentication Fails. Your api key: {KEY} is invalid"
    p, seen, _ = _provider(
        settings, lambda r: httpx.Response(401, json={"error": {"message": msg}})
    )
    with pytest.raises(ProviderError) as e:
        p.complete(REQ)
    assert e.value.code == "auth" and len(seen) == 1
    assert KEY not in str(e.value)


def test_server_errors_are_retried_with_backoff(settings: Settings) -> None:
    replies = iter([httpx.Response(503), httpx.Response(429), _ok()])
    p, seen, sleeps = _provider(settings, lambda r: next(replies))
    assert p.complete(REQ).text == '{"ok": true}'
    assert len(seen) == 3 and len(sleeps) == 2 and all(0 < s <= 12 for s in sleeps)


def test_retries_are_bounded(settings: Settings) -> None:
    p, seen, _ = _provider(settings, lambda r: httpx.Response(500))
    with pytest.raises(ProviderError) as e:
        p.complete(REQ)
    assert e.value.code == "http_500" and len(seen) == 3  # 1 + llm_max_retries


def test_timeouts_are_retried(settings: Settings) -> None:
    calls = {"n": 0}

    def handler(r: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ReadTimeout("slow", request=r)
        return _ok()

    p, _, _ = _provider(settings, handler)
    assert p.complete(REQ).text
    assert calls["n"] == 2


def test_truncated_and_malformed_responses(settings: Settings) -> None:
    p, _, _ = _provider(settings, lambda r: _ok(finish="length"))
    with pytest.raises(ProviderError) as e:
        p.complete(REQ)
    assert e.value.code == "truncated"
    p, _, _ = _provider(settings, lambda r: httpx.Response(200, json={"nope": 1}))
    with pytest.raises(ProviderError) as e:
        p.complete(REQ)
    assert e.value.code == "bad_response"


def test_stream_yields_content_pieces(settings: Settings) -> None:
    lines = [
        'data: {"choices":[{"delta":{"content":"Hel"}}]}',
        "",
        'data: {"choices":[{"delta":{"content":"lo."}}]}',
        "data: [DONE]",
    ]
    p, seen, _ = _provider(settings, lambda r: httpx.Response(200, text="\n".join(lines)))
    assert "".join(p.stream(REQ)) == "Hello."
    body = json.loads(seen[0].content)
    assert body["stream"] is True and "response_format" not in body


# --- circuit breaker ----------------------------------------------------------------------------


def test_breaker_opens_after_consecutive_failures_then_half_opens() -> None:
    now = [0.0]
    b = CircuitBreaker(3, 60, clock=lambda: now[0])
    mock = MockProvider()
    mock.fail_with = ProviderError("timeout", retryable=True)
    g = GuardedProvider(mock, b)
    for _ in range(3):
        with pytest.raises(ProviderError):
            g.complete(REQ)
    assert b.state == "open"
    with pytest.raises(CircuitOpenError):
        g.complete(REQ)
    assert len(mock.requests) == 3  # the open breaker made no call
    now[0] = 61
    assert b.state == "half_open"
    mock.fail_with = None
    mock.script.append('{"x": 1}')
    g.complete(REQ)  # the trial call succeeds and closes the breaker
    assert b.state == "closed"


def test_half_open_failure_reopens() -> None:
    now = [0.0]
    b = CircuitBreaker(1, 10, clock=lambda: now[0])
    b.failure()
    now[0] = 11
    b.before_call()  # trial
    with pytest.raises(CircuitOpenError):
        b.before_call()  # only one trial at a time
    b.failure()
    assert b.state == "open"


def test_success_resets_the_failure_count() -> None:
    b = CircuitBreaker(2, 10)
    b.failure()
    b.success()
    b.failure()
    assert b.state == "closed"
