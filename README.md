# GenAI-DBT FamilyBridge

A trauma-informed, clinician-supervised web platform that supports hospital-based parent–adolescent
DBT-A skills groups. **Stage 1: fictional/demo data only.** FamilyBridge is an adjunct to clinician-led
care. It is not a therapist and not a crisis-monitoring system.

- Standing brief: [DEVELOPMENT_PROMPT.md](DEVELOPMENT_PROMPT.md)
- Phase-by-phase plan and decision log: [docs/dev/DEVELOPMENT_PLAN.md](docs/dev/DEVELOPMENT_PLAN.md)
- Clinical/user-facing content (versioned, with approval status): [content/](content/README.md)

**Status:** Stage 1 build complete through Phase 10 (hardening and handover). Clinical content is
draft and demo-only; read the [known limitations](docs/guides/KNOWN_LIMITATIONS.en.md) first.

**Guides** (English and 中文):

| Guide | English | 中文 |
|---|---|---|
| Admin (setup, accounts, backups, keys, export, audit) | [ADMIN_GUIDE.en.md](docs/guides/ADMIN_GUIDE.en.md) | [ADMIN_GUIDE.zh-CN.md](docs/guides/ADMIN_GUIDE.zh-CN.md) |
| Therapist quick guide | [THERAPIST_QUICK_GUIDE.en.md](docs/guides/THERAPIST_QUICK_GUIDE.en.md) | [THERAPIST_QUICK_GUIDE.zh-CN.md](docs/guides/THERAPIST_QUICK_GUIDE.zh-CN.md) |
| Content authoring | [CONTENT_AUTHORING.en.md](docs/guides/CONTENT_AUTHORING.en.md) | [CONTENT_AUTHORING.zh-CN.md](docs/guides/CONTENT_AUTHORING.zh-CN.md) |
| Known limitations | [KNOWN_LIMITATIONS.en.md](docs/guides/KNOWN_LIMITATIONS.en.md) | [KNOWN_LIMITATIONS.zh-CN.md](docs/guides/KNOWN_LIMITATIONS.zh-CN.md) |
| Co-design demo script | [DEMO_SCRIPT.en.md](docs/guides/DEMO_SCRIPT.en.md) | [DEMO_SCRIPT.zh-CN.md](docs/guides/DEMO_SCRIPT.zh-CN.md) |

## Stack

| Part | Tech |
|---|---|
| API | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic |
| Database | PostgreSQL 16 + pgvector + pg_trgm (Docker image `pgvector/pgvector:pg16`) |
| Web | React 18, TypeScript, Vite, React Router, TanStack Query, react-i18next, Radix UI, Framer Motion |
| Tests | pytest, Vitest + Testing Library (Playwright from Phase 1) |
| Packaging | Docker Compose (`db`, `api`, `web`), bound to `127.0.0.1` only |

## First-time setup

Prerequisites: Docker Desktop, Python 3.12, Node 24.

```bash
cp .env.example .env
```

Edit `.env` and replace every `change-me` with a local value. `POSTGRES_PASSWORD` must match the password
inside both database URLs. `APP_DB_PASSWORD` is the password of the API's restricted database role (Phase 10);
use a different value. **Never commit `.env`.** The DeepSeek key goes only in `DEEPSEEK_API_KEY` in `.env`.
Use `LLM_PROVIDER=mock` for offline development.

## Run the whole stack

```bash
docker compose up -d --build
```

| URL | What |
|---|---|
| http://localhost:8080 | Web app (production build; nginx proxies `/api` and `/health`) |
| http://localhost:8000/health/ready | API readiness: database, migrations at head, content valid |
| http://localhost:8000/docs | API docs (development only) |

The API applies migrations on start and **refuses to start if any file in `content/` is invalid.**

## Develop locally (hot reload)

```bash
docker compose up -d db
```

Backend (from `backend/`):

```bash
py -3.12 -m venv .venv && .venv/Scripts/python -m pip install -r requirements-dev.lock
```
```bash
.venv/Scripts/python -m app.cli migrate
```
```bash
.venv/Scripts/python -m uvicorn app.asgi:app --reload --host 127.0.0.1 --port 8000
```

Frontend (from `frontend/`):

```bash
npm ci && npm run dev
```

The dev server runs at http://127.0.0.1:5173 and proxies `/api` and `/health` to port 8000.
The **component gallery** is at http://127.0.0.1:5173/dev/gallery. It exists in development builds only.

## Accounts and demo data

There is no public sign-up. Accounts are created from one-time codes (Plan §5.1):

- **Admin** accounts are created with the CLI.
- The admin issues a **therapist** code (Admin → Therapists). The therapist redeems it at `/redeem`,
  choosing a username, display name, language and password.
- The therapist creates a group and a family, then issues **teen** and **caregiver** codes (one teen per
  family). Each participant redeems their own code and completes onboarding consent separately before
  they can use the app.
- Codes are shown once, stored only as a keyed hash, single-use, and expire (invitations: 14 days,
  `INVITATION_TTL_DAYS`; reset codes: 48 hours, `RESET_CODE_TTL_HOURS`).
- **Forgotten password:** the therapist issues a reset code for members of their groups; the admin does
  this for therapists (decision D30). Redeeming it at `/reset` signs the account out everywhere.

Demo data (fictional; refused when `APP_ENV=production`), from `backend/`:

```bash
.venv/Scripts/python -m app.cli seed-demo
```

This creates a demo site with placeholder help contacts, an admin, a therapist, one group and two families
(one with two caregivers), plus unused codes. Usernames and passwords are written to
`seed_output/demo_credentials.json`, which is git-ignored. They are never printed or documented.

Other commands:

```bash
.venv/Scripts/python -m app.cli create-admin --username site-admin
```
```bash
.venv/Scripts/python -m app.cli verify-audit
```

`create-admin` prompts for the password (or use `--password-stdin`). `verify-audit` checks the audit log's
hash chain and exits non-zero if any entry was changed or removed.

## Safety core (Phase 2)

FamilyBridge is **not monitored in real time** and sends no SMS, calls or email. Safety events go to an
in-app queue only (Plan §5.7, O12).

- **Help screen:** `/teen/help` and `/caregiver/help`, linked from the header ("Get help") and the
  navigation on every participant screen. The text comes from `content/help/{zh,en}.md` (draft, O4).
  Contacts and staffed hours come from Admin → Site settings.
- **Screening:** `app/safety/service.py` (`SafetyService.screen_text`, `check_diary_urges`,
  `record_participant_stop`) is the hook later features call. The keyword lists are in
  `content/safety/risk_keywords.yaml` (draft, seeded from DBT_Revised, O10). A high-risk match stops
  the activity. Moderate terms and concern indicators show a gentle care card. The LLM channel is
  added in Phase 4.
- **Forbidden phrases:** `content/safety/forbidden_phrases.yaml`. The content loader rejects any help
  or consent text that promises monitoring, contact or rescue. A test also scans every frontend UI
  string.
- **Queue:**
  - Therapists: Safety queue, for their own groups only. The workflow is new → acknowledged →
    in review → resolved, and resolving needs a follow-up. Therapists can add notes and record events
    by hand.
  - Admins: Safety oversight, read-only, with every read audited (D39).
  - There is no SLA escalation job (D38). `SAFETY_ACK_SLA_HOURS` is unused.
  - The urge threshold is `DIARY_URGE_THRESHOLD`, a placeholder that a
    `safety.diary_urge_threshold` setting can override.
- `seed-demo` adds three fictional events so the queue has something to show.

## Knowledge base (Phase 3)

The DBT manual is used **only** for grounding AI answers: its text lives in the database, never in
the repository, and participants only ever see original wording (D7). The ingestion tool needs the
optional `kb-ingest` extra (PyMuPDF, AGPL, not in the API image).

- **Inputs:**
  - The manual PDF in `docs/` (git-ignored).
  - `content/skills/handouts.yaml`, the committed handout-to-page map (D44).
  - The diagram-page transcriptions in `knowledge/transcriptions/pNNN.md` (git-ignored, D43).
- **Model:** `intfloat/multilingual-e5-large` via fastembed (about 2.2 GB). It is cached in
  `knowledge/models/` (git-ignored), and the API container mounts that folder.
- **Commands** (from `backend/`):

  ```bash
  .venv/Scripts/python -m app.cli kb ingest         # new version, activated; prints warnings
  .venv/Scripts/python -m app.cli kb status
  .venv/Scripts/python -m app.cli kb search "如何认可孩子的感受" --language zh-CN
  .venv/Scripts/python -m app.cli kb eval --record  # recall@5 / MRR per language; exit 1 below target
  .venv/Scripts/python -m app.cli kb fingerprint    # after re-ingesting a changed manual
  .venv/Scripts/python -m app.cli kb overlap-check
  ```

- **Retrieval:** `app/kb/retrieval.py` provides `KnowledgeService.search`. It is hybrid: e5 cosine
  search plus a jieba keyword index, fused with RRF.
  - It accepts skill and module filters and returns one result per handout.
  - Every search is logged with a SHA-256 of the query, never the text.
  - `sufficient` uses `RAG_MIN_SCORE_ZH`/`RAG_MIN_SCORE_EN` (D46).
- **Evaluation:** `content/eval/retrieval/v1.yaml` holds 78 draft queries (43 zh, 35 en) covering
  every module. The target is recall@5 ≥ 0.85 in each language.
- **Copy check:** `scripts/manual_fingerprint.txt` holds hashes of the manual, not text. The check
  runs in `scan_repo.py` and in the tests, and fails if any committable file shares 20 or more
  consecutive characters with the manual.
- **Admin → Knowledge base** shows versions, counts, header checks and the last evaluation. It never
  shows manual text.

## AI layer (Phase 4)

Every AI call goes through `app/ai/service.py` (Plan §5.4). The model never controls state or
access; callers get a validated result or an authored fallback.

- **Pipeline:**
  - Input schema (extra fields rejected), length cap, injection heuristic. Participant text is
    wrapped as data.
  - Skill-scoped retrieval (D51), then the prompt from `content/prompts/`.
  - DeepSeek `deepseek-flash` (D48), with retries and a circuit breaker.
  - Repair and validation against `app/ai/schemas.py`, then the rule checks: citations, manual
    overlap, language, output patterns (`content/safety/output_rules.yaml`), TIPP health caution,
    taxonomy.
  - At most one regeneration, then the authored fallback in `content/fallbacks/`.
- **Labels:** each output is marked AI from the manual, AI general knowledge, or authored. The
  frontend shows this with `ProvenanceChip` / `provenanceOf`.
- **Logs:** `ai_interaction` stores hashes, check codes and the encrypted output, never the
  participant's text.
- **Risk:** `assess_risk` is the LLM channel of safety screening and decides when it answers
  validly (D49). Without it, the keyword result applies.
- **Offline:** `LLM_PROVIDER=mock` is deterministic, and the tests always use it.
- **Commands** (from `backend/`; they use `.env`, so `LLM_PROVIDER=deepseek` makes real calls):

  ```bash
  .venv/Scripts/python -m app.cli ai status
  .venv/Scripts/python -m app.cli ai smoke                 # one call per language, outcome only
  .venv/Scripts/python -m app.cli ai eval                  # adversarial benchmark (81 cases)
  .venv/Scripts/python -m app.cli ai sweep --export ../exports/review.jsonl  # sample skills (D50)
  .venv/Scripts/python -m app.cli ai sweep --all           # every skill
  ```

- **Exports:** the review export holds AI output, so keep it in a git-ignored folder. It pairs each
  output with the golden key points (`content/eval/golden/v1.yaml`) and an empty clinician rubric.
- **Admin → AI layer** shows provider, breaker, per-function calls and fallbacks, rejection codes,
  prompt approval and evaluation runs: counts and codes only.

## Lessons (Phase 5)

Adolescent and caregiver learning (Plan §5.5). Code is in `backend/app/learning/` and
`frontend/src/features/lessons/`; the API is in `backend/app/api/learning.py`.

- **Adolescent:**
  - Profile first (age and grade are required).
  - Each lesson runs: mood → optional check-in (skippable) → AI-recommended skill with two
    alternatives → streamed teaching chat → summary → mood. A quick check and retakes are
    optional.
  - The repeat guard and the auto-complete rules are described in D59.
- **Caregiver:** a structured lesson runs: explanation (simpler, or another example) → practice
  with feedback → a 3-question quiz → reflection.
- **Group review:** therapists record the skills taught in a group session, and families can
  open those skills as optional lessons. Nothing is ever due or overdue.
- **Pausing:** a paused lesson can be resumed at any time, with one open lesson per learner
  (D56). Past lessons show their summary and transcript to the owner only (D57).
- **Safety:** every student message is screened before it reaches the model. A stop ends the
  lesson and opens Help. Model text is released sentence by sentence only after the rule checks.
- **Outcomes:** participants never see scores, "fail", streaks or badges, only "You've got
  it" / "Worth another look" and "practised / understood / worth revisiting" (D60).
- **E2E with the mock provider:** `frontend/e2e/lessons.spec.ts`. A message containing
  `[[mock:rule-violation]]` makes the mock produce a blocked sentence (D61).

## Diary Cards (Phase 6)

Private, role-specific cards (Plan §5.6). Templates are versioned YAML in `content/diary/{role}/`
(draft wording, O3). Code is in `backend/app/diary/`, `backend/app/api/diary.py`,
`frontend/src/features/diary/` and `frontend/src/routes/therapist/DiaryReviewPage.tsx`.

- **Entries:**
  - Several per day (D64); today and the previous 6 days can be added or edited (D65).
  - Every save keeps a revision. Values and notes are encrypted.
- **Safety:** an urge at or above the threshold (`DIARY_URGE_THRESHOLD`, or the admin setting)
  and a worrying note both open Help after saving and create an event for the therapist.
- **Sharing (adolescent → caregiver only, O6):** per entry, chosen items, with a preview. A share
  can be stopped at any time and access ends at once (D66, D67).
- **Therapist:** Diary review → family. Each person's card is a separate panel with trend lines,
  skill use, a neutral calendar and the entries; opening it is audited.
- **No negative copy:** missing days are only ever met with "Missed entries are okay".
- **Homework and expectations:** added in Phase 7 (below).
- **E2E:** `frontend/e2e/diary.spec.ts`. To run the whole suite against a local stack, set
  `CODE_IP_MAX_ATTEMPTS=200` in your local `.env` (dev only; the default is 20).

## Therapist dashboard (Phase 7)

Therapist-only screens for the therapist's own groups (Plan §5.8). Code is in
`backend/app/therapist/`, `backend/app/api/therapist.py` and `frontend/src/routes/therapist/`.

- **Schedule:** the group's diary expectation (days per week, D70) and homework per role (D69).
  Participants see this week's homework on Home and tick it in the diary card's Homework
  checklist. The status table shows "Done" or "Not yet"; there is no overdue copy.
- **Group sessions:** record which skills each session covered; adolescents then get a Group
  review lesson for them.
- **Learning review** (from a family): summaries, check-in status and moods per lesson, and
  caregiver practice results. The participant's own words open only on request, and that read is
  audited.
- **Progress:** a coverage map of skills practised per person, with no totals.
- **Content review:** mark cached AI explanations and quizzes "reviewed" or "needs change" (D71).
  "Needs change" withdraws the item, and the next request regenerates it.
- **Metrics:** enrolment, diary completion against the expectation, homework, learning, safety
  acknowledgement within the SLA, and therapist time per family (a focus heartbeat, D73).
- **Demo data:** `seed-demo` includes a week of fictional activity. For an older demo database:

  ```bash
  cd backend
  .venv/Scripts/python -m app.cli seed-demo-activity
  ```

- **E2E:** `frontend/e2e/therapist.spec.ts`. The usability walkthrough
  (`docs/dev/USABILITY_WALKTHROUGH.md`) is automated in `frontend/e2e/walkthrough.spec.ts`; it runs
  against the demo seed and switches demo accounts to English.

## Joint sessions (Phase 8)

Parent–adolescent rooms for one episode (Plan §5.9). Code is in `backend/app/joint/` (pure step
engine, service, WebSocket hub), `backend/app/api/joint.py`, `frontend/src/features/joint/` and
`frontend/src/routes/therapist/Joint*.tsx`. Episodes are content files in `content/episodes/`.

- **Scheduling:** on **Joint sessions**, the therapist invites a pair marked suitable (family page)
  to an episode version in a time window of up to 14 days. Unapproved versions can only go to demo
  families; content approvers (an admin sets the flag) approve or retire versions under
  **Content review**.
- **Invitations:** each person answers on their own, with two equal buttons and no reason asked. If
  either says no, the other sees only "This session won't run this time".
- **Room:** server-owned state over a WebSocket at `/api/v1/joint/sessions/{id}/ws`. Private choices
  are revealed only when both have chosen. `both` steps wait for both people to be connected, and a
  reload or reconnect returns to the same step. **Pause** pauses for both, and either person can
  carry on. **I need to stop** holds the room (D75): the person who stopped sees Help, the partner
  sees "paused for now", and only the therapist can resume or end it.
- **After the session:** the shared outcome stores step ids and rubric tags only. The therapist
  summary shows check-in ratings and private reflections (D76, D77); opening it is audited.
- **Solo practice:** participants can run the placeholder episode alone; it is never shown to the
  partner.
- **Proxying:** the Vite dev proxy and `frontend/nginx/default.conf` forward WebSocket upgrades. The
  hub is in-process, so run a single API worker (D78).
- **Demo data:** `seed-demo` (or `seed-demo-activity` for an older database) marks Family A's pair
  suitable and adds one invitation to the placeholder episode.
- **E2E:** `frontend/e2e/joint.spec.ts` drives three browsers (therapist, teen and caregiver)
  through a decline, a full run with pause, reload and reveal, and "I need to stop".

## Research instrumentation and export (Phase 9)

Pseudonymous research data for the feasibility measures (Plan §5.10, §8.4). Code is in
`backend/app/research/` (event registry, export builder, data dictionary),
`backend/app/api/research.py`, `frontend/src/app/research.ts` and
`frontend/src/routes/admin/ResearchExportPage.tsx`.

- **Events:** sign-in, enrolment (codes issued and redeemed, onboarding finished), joint-room
  events, and browser usability reports. Usability reports are client errors by kind and screen,
  and whether a new diary card or onboarding was finished or abandoned. Every event type and
  property is declared in `app/research/events.py`; free text is refused. Other measures come from
  the feature tables (D84).
- **Export (admin):** **Research export** shows each file with its row count and downloads a zip
  of CSV files plus `data_dictionary.csv`. Every download is audited. From the command line:

  ```bash
  cd backend
  .venv/Scripts/python -m app.cli export-research --include-demo
  ```

  This writes to the git-ignored `exports/`. Never commit exports.
- **What the export guarantees:**
  - No free text and no direct identifiers.
  - Adolescent and caregiver data in separate folders.
  - Only records made while the person's research-export consent was on (D81).
  - Dates plus study day, no time of day (D82).
  - Demo data only when asked for.
- **Data dictionary:** `docs/research/DATA_DICTIONARY.md` is generated from the export spec.
  After changing the export, regenerate it:

  ```bash
  cd backend
  .venv/Scripts/python -m app.cli research-dictionary
  ```

  A test fails if the file is out of date.
- **Recruitment numbers:** therapists enter screened, eligible, approached and consented family
  counts per period on **Metrics**. These are the export's enrolment denominators.
- **Retention:** there is no retention setting or purge. The app never deletes original data
  (D83); retention is a governance decision (O14).
- **E2E:** `frontend/e2e/research.spec.ts` downloads the zip and checks it for demo names and
  times of day.

## Hardening and handover (Phase 10)

- **Security checklist:** [docs/dev/SECURITY_CHECKLIST.md](docs/dev/SECURITY_CHECKLIST.md) lists
  each Plan §5.12 control with its status and the test that guards it, plus items for the deployer.
- **Least-privilege database role:** the API connects as `familybridge_app` (migration
  `0011_least_privilege`) with data access only: no schema changes, and it cannot change or delete
  audit entries. Migrations run as the owner through `MIGRATION_DATABASE_URL`, and `migrate`
  creates or updates the role when `APP_DB_PASSWORD` is set. For local development outside Docker,
  `DATABASE_URL` may stay the owner URL.
- **Accessibility:** [docs/dev/ACCESSIBILITY_AUDIT.md](docs/dev/ACCESSIBILITY_AUDIT.md). axe-core
  (WCAG 2.2 A/AA) runs on every participant screen in both languages, plus keyboard and 320 px
  reflow checks, in `frontend/e2e/a11y.spec.ts`. A manual screen-reader pass was cancelled
  (O27, D90).
- **Adversarial benchmark:** [docs/dev/ADVERSARIAL_RESULTS.md](docs/dev/ADVERSARIAL_RESULTS.md),
  the full run against DeepSeek (80/81 passed; all high-severity cases passed).
- **Guides and demo script:** see the table at the top of this file.

## Tests and checks

Run everything CI runs (needs the `db` container):

```bash
bash scripts/check.sh
```

- Backend tests run against the `test_familybridge` database only. The suite refuses any database whose
  name does not start with `test_` (`backend/app/core/test_db_guard.py`).
- `python -m app.cli check-content` validates every file in `content/`.
- `python scripts/scan_repo.py` fails if `.env` files, the DBT manual, manual extracts, dumps or secrets
  would be committed.
- Frontend code is formatted with Prettier (`npm run format`); CI runs `npm run format:check`.

End-to-end tests (Playwright) run against a live, seeded stack: the API on port 8000 plus the dev server
on 5173 (or set `E2E_BASE_URL=http://localhost:8080` for the compose web container). From `frontend/`:

```bash
npx playwright install chromium
```
```bash
npm run e2e
```

The E2E suite (`e2e/onboarding.spec.ts`, `e2e/safety.spec.ts`) signs in with the demo admin from
`seed_output/` and creates its own therapist, group, family and participants with unique names on every
run. Code redemption is rate-limited per IP
(20 attempts per 5 minutes), so wait a few minutes between repeated runs against the same API process.

## Data hygiene

- Fictional/demo data only.
- Never commit `.env`, API keys, the DBT manual PDF or its extracted text, database dumps or exports.
  `.gitignore` and `scripts/scan_repo.py` enforce this.
- The DBT manual is copyrighted. It is used only as internal retrieval grounding, and users see only
  original paraphrases (decision D7).

## Troubleshooting

**Docker Desktop crash-loops on Windows with "…\*.sock: The file cannot be accessed by the system."**
Docker leaves stale socket files after an unclean exit, and some agent shells (including the Claude desktop
app's) cannot open socket files under `AppData` at all. Start Docker Desktop and any clean-up command as a
normal desktop process, not from an agent shell. For example, use `explorer.exe "<path to Docker Desktop.exe>"`,
or run a `.bat` file through `explorer.exe`. Do **not** use "Reset to factory defaults".
