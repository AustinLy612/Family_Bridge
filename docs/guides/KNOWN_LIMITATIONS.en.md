# FamilyBridge known limitations (Stage 1)

中文版: [KNOWN_LIMITATIONS.zh-CN.md](KNOWN_LIMITATIONS.zh-CN.md). Item numbers (O…) refer to the
open-items table in `docs/dev/DEVELOPMENT_PLAN.md` §8.

## Safety

- **No crisis monitoring.** Nobody watches the app in real time. Safety events wait in the
  therapist's in-app queue; there is no SMS, call, email or pager (O12) and no automatic
  escalation when an event waits too long (D38). Families must be told this and must have the
  hospital's own contacts.
- **Screening can miss things.** Risk detection uses draft keyword lists plus an LLM check
  (D49). Indirect or unusual wording may not open Help. The adversarial benchmark passed 48/48
  high-severity cases on 2026-11-09 (`docs/dev/ADVERSARIAL_RESULTS.md`), which is a test set, not
  a guarantee.
- **Help contacts are placeholders** until the hospital confirms them in Site settings (O4,
  deferred, D90).
- The diary urge threshold is a placeholder (O3).

## Clinical content

- **All clinical content is draft:** skill taxonomy, prompts, fallbacks, diary templates,
  consent, help text, risk lists and rubrics (O3, O5, O10, O20). Draft content is usable only
  with demo families.
- **Joint-session episodes are placeholders** (O1). Only a demo stub and one draft level exist;
  story, art and the full world set are not written (O18, O22).
- Validated research scales (SUS, C-PRAES, PACS, …) are not in the app (O13).
- One adolescent reading level only (O16).

## AI

- Uses DeepSeek when `LLM_PROVIDER=deepseek`. Hosting, data retention and training-use terms
  need legal review before real data (O9).
- In the latest benchmark (81/81 passed), 1 of the 50 cases that expected a model reply fell back to
  reviewed static content and 1 needed a retry, both because an output safety rule caught the reply
  (O24). The model can still occasionally phrase a reply in a way the rules reject; participants then
  see reviewed content.
- AI hints and personalisation inside joint sessions are not wired (O29); episodes run from their
  scripts.

## Accounts and security

- **No single sign-on (SSO)** and no multi-factor authentication. Accounts are created from
  one-time codes; passwords are reset by the therapist or admin.
- **No admin break-glass access** (O15).
- No self-service account deletion and **no retention purge**: the app never deletes original
  data (D83); retention is a governance decision (O14).
- Encryption-key rotation needs a re-encryption tool that is not built yet (O25). See the admin
  guide §7.
- Backups are manual (`pg_dump`, admin guide §6).
- TLS must be provided by the deployment in front of the web container.
- Seven moderate advisories in development-only lint tooling (`minimatch`, O26); none in the app.

## Platform

- **Joint sessions need a single API process.** The room hub is in memory (D78); running several
  workers or servers would split rooms. Scaling needs a shared channel (O28, for example Postgres
  LISTEN/NOTIFY).
- Only the therapist schedules joint sessions (O8); remote joining for caregivers is allowed and
  self-reported (O17).
- Only adolescent → caregiver diary sharing (O6).
- Web only (no native app, no offline mode, no push notifications); Chinese (Simplified) and
  English only.
- Accessibility was checked with automated tools and keyboard tests; **no manual screen-reader
  pass is planned** (cancelled, D90; `docs/dev/ACCESSIBILITY_AUDIT.md`).
- Production font licences are not confirmed (O19).
