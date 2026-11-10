"""LLM provider adapter (Plan §5.4 "Provider adapter"; Phase 4 task 1).

`LLMProvider` is the only way the app talks to a model. Implementations:

- `DeepSeekProvider`: OpenAI-compatible chat completions over httpx (D4, D48). Thinking mode
  is disabled; JSON mode for structured functions; plain-text streaming for `teaching_turn`.
  Bounded retries with exponential backoff and jitter on 429/5xx, timeouts and connection
  errors. Never retries 4xx (bad key, bad request).
- `MockProvider`: deterministic, offline; used in CI and tests (Plan §7.3).

A `CircuitBreaker` wraps every provider: after `llm_breaker_failures` consecutive failures it
opens for `llm_breaker_cooldown_seconds`, during which calls fail at once with
`CircuitOpenError` and the AI service serves fallbacks (Phase 4 acceptance: killing the
provider yields fallbacks, not errors). The API key is read only from settings (`.env`).
"""

from __future__ import annotations

import json
import random
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from app.settings import Settings

Message = dict[str, str]  # {"role": "system" | "user" | "assistant", "content": str}


class ProviderError(Exception):
    """The provider failed for this call (after retries). `code` goes into AIInteraction."""

    def __init__(self, code: str, detail: str = "", *, retryable: bool = False) -> None:
        self.code = code
        self.detail = detail[:300]
        self.retryable = retryable
        super().__init__(f"{code}: {self.detail}" if detail else code)


class CircuitOpenError(ProviderError):
    """The circuit breaker is open; no call was made."""

    def __init__(self) -> None:
        super().__init__("circuit_open")


@dataclass(frozen=True)
class LLMRequest:
    function: str  # AI function name (for logging and the mock)
    messages: list[Message]
    json_mode: bool = True
    max_tokens: int = 2048
    timeout: float = 30.0
    temperature: float = 0.4
    # Free-form hints for the mock provider only (e.g. chunk labels, language); never sent.
    hints: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LLMResult:
    text: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: int = 0


class LLMProvider(Protocol):
    name: str
    model: str

    def complete(self, request: LLMRequest) -> LLMResult: ...

    def stream(self, request: LLMRequest) -> Iterator[str]:
        """Yield text deltas. Raises ProviderError before the first delta on failure."""
        ...


# --- circuit breaker --------------------------------------------------------------------------


class CircuitBreaker:
    """Consecutive-failure breaker: closed -> open (cooldown) -> half-open (one trial call)."""

    def __init__(
        self, failures: int, cooldown_seconds: float, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.threshold = failures
        self.cooldown = cooldown_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._failures = 0
        self._opened_at: float | None = None
        self._trial = False

    @property
    def state(self) -> str:
        with self._lock:
            return self._state()

    def _state(self) -> str:
        if self._opened_at is None:
            return "closed"
        if self._clock() - self._opened_at >= self.cooldown:
            return "half_open"
        return "open"

    def before_call(self) -> None:
        with self._lock:
            state = self._state()
            if state == "open" or (state == "half_open" and self._trial):
                raise CircuitOpenError()
            if state == "half_open":
                self._trial = True

    def success(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = None
            self._trial = False

    def failure(self) -> None:
        with self._lock:
            self._failures += 1
            self._trial = False
            if self._failures >= self.threshold or self._opened_at is not None:
                self._opened_at = self._clock()

    def reset(self) -> None:
        self.success()


class GuardedProvider:
    """Wraps a provider with the circuit breaker. This is what the AI service uses."""

    def __init__(self, inner: LLMProvider, breaker: CircuitBreaker) -> None:
        self.inner = inner
        self.breaker = breaker
        self.name = inner.name
        self.model = inner.model

    def complete(self, request: LLMRequest) -> LLMResult:
        self.breaker.before_call()
        try:
            result = self.inner.complete(request)
        except ProviderError:
            self.breaker.failure()
            raise
        self.breaker.success()
        return result

    def stream(self, request: LLMRequest) -> Iterator[str]:
        self.breaker.before_call()
        try:
            yield from self.inner.stream(request)
        except ProviderError:
            self.breaker.failure()
            raise
        self.breaker.success()


# --- DeepSeek ---------------------------------------------------------------------------------

RETRY_STATUS = frozenset({429, 500, 502, 503, 504, 529})


class DeepSeekProvider:
    name = "deepseek"

    def __init__(
        self,
        settings: Settings,
        *,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.model = settings.deepseek_model
        self._key = settings.deepseek_api_key.get_secret_value()
        self._url = settings.deepseek_base_url.rstrip("/") + "/chat/completions"
        self._retries = settings.llm_max_retries
        self._client = client or httpx.Client()
        self._sleep = sleep

    def _body(self, request: LLMRequest, *, stream: bool) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": request.messages,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "thinking": {"type": "disabled"},  # D48
            "stream": stream,
        }
        if request.json_mode and not stream:
            body["response_format"] = {"type": "json_object"}
        return body

    def _headers(self) -> dict[str, str]:
        if not self._key or self._key == "change-me":
            raise ProviderError("no_api_key", "DEEPSEEK_API_KEY is not set")
        return {"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"}

    def _backoff(self, attempt: int) -> None:
        self._sleep(min(8.0, 0.5 * 2**attempt) * (0.5 + random.random()))  # noqa: S311

    def _send(self, request: LLMRequest, *, stream: bool) -> httpx.Response:
        headers = self._headers()
        body = self._body(request, stream=stream)
        last: ProviderError | None = None
        for attempt in range(self._retries + 1):
            try:
                req = self._client.build_request(
                    "POST", self._url, json=body, headers=headers, timeout=request.timeout
                )
                resp = self._client.send(req, stream=stream)
            except httpx.TimeoutException as exc:
                last = ProviderError("timeout", str(exc), retryable=True)
            except httpx.HTTPError as exc:
                last = ProviderError("connection", type(exc).__name__, retryable=True)
            else:
                if resp.status_code == 200:
                    return resp
                detail = _error_detail(resp, stream=stream)
                if resp.status_code not in RETRY_STATUS:
                    code = "auth" if resp.status_code in (401, 403) else f"http_{resp.status_code}"
                    raise ProviderError(code, detail)
                last = ProviderError(f"http_{resp.status_code}", detail, retryable=True)
            if attempt < self._retries:
                self._backoff(attempt)
        assert last is not None
        raise last

    def complete(self, request: LLMRequest) -> LLMResult:
        started = time.perf_counter()
        resp = self._send(request, stream=False)
        try:
            data = resp.json()
            text = data["choices"][0]["message"].get("content") or ""
            usage = data.get("usage") or {}
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ProviderError("bad_response", type(exc).__name__) from exc
        if data["choices"][0].get("finish_reason") == "length":
            raise ProviderError("truncated", "max_tokens reached")
        return LLMResult(
            text=text,
            model=str(data.get("model") or self.model),
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    def stream(self, request: LLMRequest) -> Iterator[str]:
        resp = self._send(request, stream=True)
        try:
            for line in resp.iter_lines():
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    delta = json.loads(payload)["choices"][0].get("delta") or {}
                except (ValueError, KeyError, IndexError):
                    continue
                piece = delta.get("content")
                if piece:
                    yield piece
        except httpx.HTTPError as exc:
            raise ProviderError("stream_broken", type(exc).__name__) from exc
        finally:
            resp.close()


def _error_detail(resp: httpx.Response, *, stream: bool) -> str:
    try:
        if stream:
            resp.read()
        err = resp.json().get("error", {})
        msg = str(err.get("message", ""))
    except (ValueError, AttributeError, httpx.HTTPError):
        msg = ""
    # Never echo anything that could contain the key back into logs.
    return msg.split("Your api key")[0].strip()[:200]


# --- mock -------------------------------------------------------------------------------------

Responder = Callable[[LLMRequest], str]


class MockProvider:
    """Deterministic offline provider.

    By default it answers with `app.ai.mock.default_response(request)`: schema-valid output that
    cites the first chunk label it was given. Tests can queue raw outputs (`script`) or set
    `fail_with` to simulate provider failures.
    """

    name = "mock"
    model = "mock-1"

    def __init__(self, responder: Responder | None = None) -> None:
        from app.ai.mock import default_response

        self.responder = responder or default_response
        self.script: list[str] = []
        self.fail_with: ProviderError | None = None
        self.requests: list[LLMRequest] = []

    def _next(self, request: LLMRequest) -> str:
        self.requests.append(request)
        if self.fail_with is not None:
            raise self.fail_with
        if self.script:
            return self.script.pop(0)
        return self.responder(request)

    def complete(self, request: LLMRequest) -> LLMResult:
        text = self._next(request)
        return LLMResult(text=text, model=self.model, input_tokens=0, output_tokens=0)

    def stream(self, request: LLMRequest) -> Iterator[str]:
        text = self._next(request)
        for i in range(0, len(text), 7):
            yield text[i : i + 7]


def build_provider(settings: Settings) -> GuardedProvider:
    inner: LLMProvider = (
        MockProvider() if settings.llm_provider == "mock" else DeepSeekProvider(settings)
    )
    breaker = CircuitBreaker(settings.llm_breaker_failures, settings.llm_breaker_cooldown_seconds)
    return GuardedProvider(inner, breaker)
