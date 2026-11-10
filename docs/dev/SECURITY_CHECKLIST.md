# Security checklist (Phase 10 task 1; Plan §5.12)

Pass carried out on 2026-11-09 against the code in this repository. "Test" names an automated
check that fails if the control breaks. Status: **done**, **done (dev)** (implemented; production
values or infrastructure are still to be set) or **open** (open item number).

| # | Control (Plan §5.12) | Status | Evidence |
|---|---|---|---|
| 1 | TLS outside localhost; HSTS | done (dev) | HSTS is sent when `APP_ENV=production` (`SecurityHeadersMiddleware`, `hsts=settings.is_production`). Compose binds the API and web to 127.0.0.1 only. A production deployment must terminate TLS in front of nginx; this repository has no certificates. |
| 2 | CSP and secure headers | done | API: `default-src 'none'`, nosniff, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, COOP, Permissions-Policy (`app/core/middleware.py`). Web: CSP `default-src 'self'` with `frame-ancestors 'none'` (`frontend/nginx/default.conf`). Test: `test_health.py::test_security_headers`. |
| 3 | CSRF protection | done | A per-session token is required on unsafe methods (`X-CSRF-Token`); the WebSocket checks the origin. Tests: `test_auth.py::test_csrf_required_on_unsafe_methods`; the cross-site WebSocket guard in `test_joint.py`. |
| 4 | Strict CORS | done | Only `ALLOWED_ORIGINS` are allowed, with credentials, a fixed method list and three headers (`app/main.py`). |
| 5 | Field-level encryption (AES-GCM) | done | `EncryptedText` covers diary notes and values, private reflections, safety trigger excerpts and detection details, practice answers and feedback, chat content, lesson inquiry, context, recommendation and summary, relationship labels, and profile "other" text. Tests read raw ciphertext with SQL and check for the `v1:` prefix: `test_safety_events.py`, `test_invitations.py`, `test_ai_service.py`, `test_joint.py`. |
| 6 | Key-rotation procedure | **open (O25)**; constraints documented | The admin guide, "Encryption key" (`docs/guides/ADMIN_GUIDE.en.md` §7), explains that the app reads one key version only, so `FIELD_ENCRYPTION_KEY` must not be changed on a database with data, and what changing `SECRET_KEY` does. Ciphertext carries a `v1:` version prefix, so a re-encryption tool (`v1:` → `v2:`) can be added; it is not built yet. |
| 7 | Pseudonymous ids in logs, exports and LLM calls | done | Logs carry request ids and pseudonym codes. LLM calls send no names or usernames (`app/ai`). The export uses pseudonym codes and keyed codes (D84). Tests: `test_research_export.py`; `test_llm_identifiers.py` (no code in `app/ai` reads a display alias, username, relationship label or email). |
| 8 | Append-only audit log with hash chain; verify command | done | DB triggers block UPDATE, DELETE and TRUNCATE; the hash chain is checked by `python -m app.cli verify-audit`, which `scripts/check.sh` runs. |
| 9 | Least-privilege DB roles | **done (new in Phase 10)** | The API connects as `familybridge_app` (group `familybridge_app_rw`, migration `0011_least_privilege`). It has DML only, no DDL, and only SELECT and INSERT on `audit_log`. Migrations run as the owner (`MIGRATION_DATABASE_URL`). Test: `test_least_privilege.py`. |
| 10 | Dependency pinning | done | `backend/requirements.lock` (exact pins); `frontend/package-lock.json`, with dev tools pinned with `--save-exact`. |
| 11 | `pip-audit` / `npm audit` in CI | done, one item justified | CI runs `pip-audit -r requirements.lock` and `npm audit --omit=dev --audit-level=moderate`; both are clean (0 vulnerabilities). The full `npm audit` (dev tools included) lists 7 **moderate** advisories, all `minimatch` ReDoS (GHSA-g3hv-75wg-m249) under `typescript-eslint`. These are lint tooling only and not in the built bundle; the only offered fix is a breaking downgrade. Justified; track the upstream fix (O26). |
| 12 | Secret scanning; no secrets in logs | done | `scripts/scan_repo.py` (CI job `repo-hygiene` and `scripts/check.sh`) checks for key patterns, `.env` files, the manual text and exports. Settings use `SecretStr`; nothing logs passwords, keys or tokens. `.env`, `seed_output/` and `exports/` are git-ignored. |
| 13 | Backups (`pg_dump` procedure) | done (documented) | The procedure is in the admin guide, "Backups" (`docs/guides/ADMIN_GUIDE.en.md` §6). It is not automated in Stage 1. |
| 14 | No admin break-glass access | done | Not implemented (O15). Admins see account data only; the policy route walk (`test_policy.py`) enforces this. |

## Items for the deployer

- **DeepSeek API key:** the key in `.env` was pasted in chat (D4, D48). The project lead decided
  rotation is not needed (D90). It is kept only in the git-ignored `.env`. Phase 10 ran the
  adversarial benchmark with it, as asked (D86).
- Set real values for `SECRET_KEY`, `FIELD_ENCRYPTION_KEY`, `POSTGRES_PASSWORD` and
  `APP_DB_PASSWORD`, and set `APP_ENV=production`. `.env.example` has placeholders only.
- Put TLS (and, if wanted, a WAF) in front of the web container. Keep the API and the database
  off public interfaces.
