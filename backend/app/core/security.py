"""Passwords, usernames and one-time codes (Plan §5.1; D29, D30)."""

from __future__ import annotations

import re
import secrets
import time
from collections import defaultdict, deque
from threading import Lock

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.settings import get_settings

_hasher = PasswordHasher()  # Argon2id with library-recommended parameters
# Used to equalise timing when the username does not exist.
_DUMMY_HASH = _hasher.hash("timing-equaliser-not-a-password")

USERNAME_RE = re.compile(r"^[a-z0-9._-]{3,32}$")
# Code alphabet without look-alikes (no 0/O, 1/I/L), grouped for readability.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_CODE_LEN = 16  # ~79 bits of entropy

# Minimal local list; a breached-password check is optional per Plan §5.1.
_COMMON = frozenset(
    {
        "1234567890",
        "12345678910",
        "0123456789",
        "password123",
        "password1234",
        "qwertyuiop",
        "1qaz2wsx3edc",
        "iloveyou123",
        "abcdefghij",
        "aaaaaaaaaa",
        "1111111111",
        "88888888888",
        "woaini1314",
        "qwerty12345",
        "familybridge",
        "familybridge1",
    }
)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(stored_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(stored_hash or _DUMMY_HASH, password) and stored_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(stored_hash: str) -> bool:
    return _hasher.check_needs_rehash(stored_hash)


def password_problems(password: str, *, username: str | None = None) -> list[str]:
    """Return message keys for policy violations (empty list = acceptable)."""
    problems: list[str] = []
    min_len = get_settings().password_min_length
    if len(password) < min_len:
        problems.append("password.too_short")
    if len(password) > 128:
        problems.append("password.too_long")
    lowered = password.lower()
    if lowered in _COMMON or len(set(password)) <= 2:
        problems.append("password.too_common")
    if username and username.lower() in lowered:
        problems.append("password.contains_username")
    return problems


def normalise_username(raw: str) -> str:
    return raw.strip().lower()


def username_valid(username: str) -> bool:
    return bool(USERNAME_RE.fullmatch(username))


def new_code() -> str:
    """High-entropy one-time code, e.g. 'K7QM-3F9X-PLR2-8VDA'. Shown once, stored as a digest."""
    raw = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LEN))
    return "-".join(raw[i : i + 4] for i in range(0, _CODE_LEN, 4))


def normalise_code(raw: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]", "", raw).upper()
    return "-".join(cleaned[i : i + 4] for i in range(0, len(cleaned), 4))


def new_pseudonym() -> str:
    return "P-" + "".join(secrets.choice(_CODE_ALPHABET) for _ in range(8))


def new_token() -> str:
    return secrets.token_urlsafe(32)


class SlidingWindowLimiter:
    """In-process per-key rate limiter (single API instance in Stage 1; Redis later — Plan §3.1)."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def hit(self, key: str, *, limit: int, window_seconds: int) -> bool:
        """Record an attempt; return False if the key is over the limit."""
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > window_seconds:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


login_limiter = SlidingWindowLimiter()
code_limiter = SlidingWindowLimiter()
