#!/usr/bin/env bash
# Run every CI check locally (Plan Phase 0 task 7). Needs the db container for DB tests:
#   docker compose up -d db
set -euo pipefail
export PYTHONUTF8=1  # Windows consoles default to GBK here
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/backend/.venv/Scripts/python"; [ -x "$PY" ] || PY="$ROOT/backend/.venv/bin/python"

echo "== backend"; cd "$ROOT/backend"
"$PY" -m ruff check app migrations
"$PY" -m ruff format --check app migrations
"$PY" -m mypy app
"$PY" -m app.cli check-content
"$PY" -m pytest
"$PY" -m app.cli verify-audit
"$PY" -m pip_audit -r requirements.lock

echo "== frontend"; cd "$ROOT/frontend"
npm run lint
npm run format:check
npm run typecheck
npm test
npm run build
npm audit --omit=dev --audit-level=moderate

echo "== repo hygiene"; cd "$ROOT"
"$PY" scripts/scan_repo.py
echo "ALL CHECKS PASSED"
echo "(E2E is separate: start the stack, seed it, then 'cd frontend && npm run e2e'.)"
