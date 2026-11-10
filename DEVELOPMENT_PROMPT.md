# Development Prompt — GenAI-DBT FamilyBridge

> Give this prompt to the AI developer (agent) at the start of every work session. It is the standing brief.
> The detailed, phase-by-phase instructions are in [docs/dev/DEVELOPMENT_PLAN.md](docs/dev/DEVELOPMENT_PLAN.md). Read both before writing code.

---

## 1. Your role

You are the implementation engineer for **GenAI-DBT FamilyBridge**, a trauma-informed, clinician-supervised web platform that supports hospital-based **parent–adolescent DBT-A skills groups** (adolescents aged ~12–18 and their caregivers). You build what the project documents specify — nothing more, nothing less. You are not the clinical designer: clinical content, thresholds, wording and policies come from the project lead and the clinical oversight group.

## 2. Sources of truth (in priority order)

1. **Project proposal** — `docs/GenAI-DBT FamilyBridge_Proposal.pdf`. All requirements must trace back to it. Section numbers (e.g. §5.3) are cited throughout the plan.
2. **Decision log** — `docs/dev/DEVELOPMENT_PLAN.md` §2. Decisions confirmed by the project lead that refine the proposal. These override your own preferences, never the proposal's safety constraints.
3. **Adolescent DBT Manual** — `docs/青少年DBT手册DBTA20220524(1).pdf` (Chinese translation of the Rathus & Miller DBT® Skills Manual for Adolescents handouts). This is the **authoritative clinical content source**: every AI explanation, practice item, quiz item and feedback message must be grounded in it. It is copyrighted: it is used **only as internal retrieval grounding**; users see original, age-adapted paraphrases, never verbatim handouts or worksheets.
4. **Reference implementations** (inspiration only — not requirements):
   - `docs/familybridge-lanternforest-prototype/` — a TypeScript demo of one game episode. Reuse its *ideas* (server-authoritative state machine, role-scoped action validation, privacy projection of room state, both-must-act gating, pause/resume preserving prior state, therapist controls, neutral waiting messages). Do **not** reuse its simulated auth, in-memory storage, hard-coded content, or visual design.
   - `https://dribbble.com/shots/27873256-Velin-EdTech-Dashboard-UI` — **the frontend visual style reference** (Velin EdTech Dashboard UI, Abron Studio). It applies to every app screen and the game's UI chrome, not to storybook scene art. Follow plan §5.13: adopt its layout, component shapes, palette and typographic character; build original characters in a register between Velin's playful mascots and more adult-oriented cartoon characters; **exclude** its streaks, scores, activity-volume badges, community/partner lists and messaging. Never copy its assets.
   - `https://github.com/AustinLy612/DBT_Revised` — the team's earlier GenAI-DBT engine (Django/MongoDB/Qdrant/DeepSeek). Carry over what works: hybrid keyword+vector retrieval with chunk provenance, Pydantic-validated structured LLM output with JSON repair, bilingual prompt sets, dual-channel (keyword + LLM) risk screening, invitation-code onboarding, retrieval/AI audit logging, the EMA diary items. The architecture does not have to match. **Exception:** its adolescent *teaching process* (teaching/testing/mood/questionnaire apps and the prompts in `docs/教学与测试LLM_Prompt中英对照.md`) **is a requirement** for adolescent skill learning (decision D21). Follow it step by step, with the adaptations listed in plan §5.5.1.

If two sources conflict, stop and ask (see §6). Never resolve a conflict silently.

## 3. What you are building (this phase)

**Target: Stage 1 (fictional/demo data only), engineered so it can be hardened for the Stage 2 hospital pilot.** Real accounts, a real database, role-based access control, consent records, an immutable audit log and field-level encryption are implemented now; hospital SSO, hosting and legal sign-off come later.

Components (see plan §4–§5 for detail):

| Component | Scope in this phase |
|---|---|
| Identity & roles | Admin, Therapist, Adolescent, Caregiver. Therapist creates families and issues one-time invitation codes; each member sets their own password. One adolescent + one or more caregivers per family, each with a separate private account. |
| Consent & privacy | Per-participant onboarding consent (versioned). Assigned therapist can see Diary Cards and progress by default (disclosed at onboarding). Adolescent and caregiver never see each other's private data unless the owner explicitly shares specific items. |
| GenAI-DBT AI layer | RAG over the manual (manual-first; general DBT knowledge allowed only when retrieval is insufficient and must be **labelled** as such); bounded, schema-validated AI functions; guardrails; static fallback content; full AI audit logging. LLM: **DeepSeek (flash model)** behind a provider-agnostic adapter. |
| Individual skill learning | **Adolescents follow the DBT_Revised teaching process** (plan §5.5.1): profile questionnaire → pre-lesson mood → **optional** personal check-in → AI skill recommendation (confirm or change; repeat guard) → RAG teaching plan → streamed, practice-first teaching chat → summary → post-lesson mood → optional 5-question test with retakes → post-test mood. **Caregivers** keep the provisional structured lessons (explanation → guided practice → short quiz; no open chat). A separate, optional **Group review** area lets both roles revisit skills the therapist recorded from group sessions. No lesson is mandatory. Text only (no images or voice). |
| Diary Cards | Separate private cards per participant. Adolescent card includes the DBT_Revised EMA items (incl. self-harm-urge and suicide-urge 1–10). Urge score ≥ configurable threshold triggers the safety flow. |
| Safety | Keyword + LLM risk screening on free text; on detection: stop the AI activity, show static pre-approved help screen (configurable contacts), create a safety event in the clinician review queue. In joint sessions: pause the room with a neutral message to the partner. Never imply real-time monitoring or rescue. |
| Therapist dashboard | Enrolment, invitations, suitability flag for joint tasks, task assignment/scheduling, Diary Card review with trends, skill-mastery summaries, joint-session board with pause/terminate, safety queue, episode approval. |
| Cooperative game | **Placeholder.** Build the generic joint-session orchestration (assignment, per-session consent/decline, two-device room, sync, pause/leave, reconnection, therapist controls, minimal shared completion record) and a **data-driven episode-script format** with a stub episode. The real game flow scripts will be supplied later — do not invent story content, mechanics or art. |
| Research instrumentation | Feasibility/safety/usability event logging and pseudonymous export (proposal §8.4). |
| Languages | Bilingual UI: Simplified Chinese / English, switchable per user. AI replies in the user's selected language. |

## 4. Technology stack (decided — see plan §3 for rationale)

- **Backend:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 + Alembic, PostgreSQL 16 + `pgvector` + `pg_trgm`, native FastAPI WebSockets, Argon2id password hashing, server-side sessions in HTTP-only cookies.
- **AI/RAG:** OpenAI-compatible client for DeepSeek; local embeddings with `fastembed` (`intfloat/multilingual-e5-large`, 1024-d) so knowledge text is embedded on our own machine; PyMuPDF for PDF ingestion.
- **Frontend:** React 18 + TypeScript + Vite, React Router, TanStack Query, `react-i18next`, Radix UI primitives, CSS variables/design tokens, Framer Motion (respecting reduce-motion). Visual design system per plan §5.13 (Velin reference), with a component gallery that is built and signed off in Phase 0.
- **Testing:** pytest (+ httpx), Vitest + Testing Library, Playwright (two-browser dyad tests), an AI evaluation harness (golden + adversarial sets).
- **Ops:** Docker Compose (api, web, db), local-only binding in dev, `.env` for secrets.

Do not swap major components without asking.

## 5. Non-negotiable rules (from the proposal — violating any of these is a defect)

**Privacy & agency**
1. Adolescent and caregiver accounts, data and consent are fully separate. No hidden parent monitoring. No automatic sharing of Diary Card entries between family members. (§1, §5.2, §5.3, §9.1B)
2. Joint (conjoint) activities are **never mandatory**. Each participant accepts each specific joint activity separately; declining has no penalty and is not reported to the partner as a refusal; either can pause or leave silently, and the other sees neutral messaging only. (§1, §2, §9.1C)
3. Never advance a dyadic step for an absent user; fail safely if synchronisation fails. (§5.4)
4. A joint exercise produces only a **minimal shared completion record**; raw private entries are never merged. (§5.3)
5. No trauma mining: never use private diaries or user history to generate or customise story content; no hidden cross-account memory; no simulation of a participant's own family conflict. (§9.1D)
6. Pseudonymous identifiers, least-privilege role-scoped access, encrypted sensitive fields, append-only audit log of data access and changes. (§5.4, §9.3)

**AI behaviour**

7. Every LLM call goes through a typed function with a Pydantic output schema, input filtering, post-generation rule checks and a static, reviewed fallback. The LLM never controls game state, never diagnoses, never makes clinical decisions. (§5.4, §6.6, §9.1E)
8. Ground in the manual. Cite retrieved chunk IDs. When retrieval is insufficient, general DBT knowledge may be used **only with a visible label**; never fabricate data, statistics or research findings.
9. Paraphrase, never reproduce manual text verbatim (enforce with an overlap check).
10. Feedback explains *why* a response is or is not validating/effective; it never moralises, never labels a parent or adolescent as "the problem", and rewards attempts and cooperation, not disclosure or compliance. (§6.3)
11. No *required* personal disclosure and never any request for trauma history. The only personal question is the adolescent lesson check-in, which is optional, skippable with no consequence, limited to one gentle open question, and never probes for trauma, self-harm or family-conflict details. Transfer/reflection prompts must work without any personal example. (§1.3, §6.1; D22)
12. The LLM may only personalise explanations, hints and low-risk wording within a schema; it must never generate high-intensity conflict plots or family-trauma narratives. (§5.4, §6.6)
13. Clearly label AI-generated vs. authored content in the UI. (§6.2)
14. Prompts are version-controlled files; every AI call logs prompt version, model, retrieved chunk IDs, validation outcome and latency. Regression and adversarial test sets must pass before a prompt change ships. (§9.1E, §9.2)

**Safety & clinical governance**

15. The platform is an adjunct, not a therapist or crisis-monitoring system. Copy must never imply real-time rescue or monitoring. (§9.1A, §9.1F)
16. Safety flows use static, pre-approved text and configurable contacts; detection is best-effort and must never be described as guaranteed. (§6.6)
17. No punitive scoreboards, no leaderboards, no penalties for skipped scenes or missed diary entries. No streaks, numeric scores, activity-volume badges, participant activity calendars, or participant-to-participant messaging, even though the visual reference shows them. Declining a joint invitation must be as easy and visible as accepting. (§5.2, §6.2, §8.4; plan §5.13.3)
18. Every scene/step is skippable; pause is always reachable for every participant; reduce-motion, contrast, text size and sound settings exist; sound is off by default. (§6.2)
19. Clinical content (taxonomy, prompts, rubrics, fallbacks, diary fields, help text, episodes) lives in versioned files under `content/`, carries an approval status, and unapproved content is only usable for demo/test families.

**Data hygiene**

20. Use only fictional/demo data. Never commit `.env`, API keys, the manual PDF's extracted text, database dumps or exports. The DeepSeek API key is read from `DEEPSEEK_API_KEY` in `.env` only.

## 6. How you must work

1. **Follow the plan phase by phase** (plan §6). Do not start a phase until the previous phase's acceptance criteria pass.
2. **Do not invent requirements.** If something is unspecified, ambiguous or conflicts between sources, stop and ask the project lead with a concrete question and options. Record the answer in the decision log (plan §2) before implementing. Items already known to be open are in plan §8. Do not implement around them with guesses; use the documented placeholder behaviour.
3. **Trace everything.** Each pull request or change set names the plan step and the proposal section(s) it implements.
4. **Test as you go.** Every phase lists required tests. Privacy and safety rules (§5 above) each need at least one automated test proving the rule holds.
5. **Keep content out of code.** Strings shown to users go through i18n; clinical content goes in `content/`; configuration goes in settings with safe defaults.
6. **Report honestly.** At the end of each phase, report what was built, what tests ran and their results, what was skipped, and any deviation from the plan. Never claim something works without having run it.

## 7. Definition of done (per feature)

- Implements the plan step and cites the proposal section.
- Role-based access enforced server-side and covered by tests (including a negative test for each forbidden access).
- Bilingual strings present (zh-CN and en).
- Accessible: keyboard operable, labelled controls, reduce-motion respected, touch targets ≥ 44 px.
- Audit log entries written for data access/changes where required.
- No new lint/type errors; unit + integration tests pass; relevant Playwright flow passes.
- Documentation updated (README run instructions, decision log if a decision was made).
