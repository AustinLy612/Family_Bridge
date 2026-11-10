"""Repository hygiene scan (DEVELOPMENT_PROMPT §5 "Data hygiene"; Plan §5.12 secret scanning).

Fails if tracked files include .env files, PDF extracts, dumps/exports, strings that look like
live API keys, or text that copies the DBT manual (n-gram fingerprint check, Plan §5.3 step 9). Run: python scripts/scan_repo.py   (tracked + untracked-but-not-ignored files, i.e. everything that could be committed).
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FORBIDDEN_PATHS = [
    re.compile(r"(^|/)\.env($|\.(?!example$))"),  # .env, .env.local … but not .env.example
    re.compile(r"(^|/)knowledge/"),
    re.compile(r"(^|/)exports?/"),
    re.compile(r"\.(dump|sql\.gz|bak)$"),
    re.compile(r"\.pdf\.txt$|_extract\w*\.txt$"),
    re.compile(r"DBTA.*\.pdf$|DBT手册"),  # the copyrighted manual (D7)
]
SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{24,}"),  # DeepSeek/OpenAI-style keys
    re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
]
SKIP_SUFFIXES = {".pdf", ".png", ".jpg", ".woff", ".woff2", ".ico", ".lock"}


def manual_overlap_problems() -> list[str]:
    """Repository text must not copy the manual (D7): compare against the committed fingerprint.

    backend/app/kb/fingerprint.py is standard-library only, so this runs without the backend's
    dependencies (CI repo-hygiene job).
    """
    sys.path.insert(0, str(ROOT / "backend"))
    from app.kb import fingerprint as fp  # noqa: PLC0415

    if not fp.FINGERPRINT_PATH.is_file():
        return [f"{fp.FINGERPRINT_PATH.relative_to(ROOT)}: missing (run `python -m app.cli kb fingerprint`)"]
    return [
        f"{rel}: {o.length} characters match the copyrighted manual (starts '{o.excerpt}')"
        for rel, o in fp.scan_repo(ROOT)
    ]


def main() -> int:
    files = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=ROOT, capture_output=True, check=True
    ).stdout.decode().split("\0")
    problems: list[str] = []
    for rel in filter(None, files):
        if any(p.search(rel) for p in FORBIDDEN_PATHS):
            problems.append(f"{rel}: file type must never be committed")
            continue
        path = ROOT / rel
        if path.suffix.lower() in SKIP_SUFFIXES or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pat in SECRET_PATTERNS:
            if pat.search(text):
                problems.append(f"{rel}: looks like a secret ({pat.pattern})")
    problems += manual_overlap_problems()
    for p in problems:
        print(p, file=sys.stderr)
    print(f"scanned {len([f for f in files if f])} tracked files, {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
