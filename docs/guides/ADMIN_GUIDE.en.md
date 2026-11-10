# FamilyBridge admin guide

For the site administrator. 中文版: [ADMIN_GUIDE.zh-CN.md](ADMIN_GUIDE.zh-CN.md).

FamilyBridge is an adjunct to clinician-led DBT-A groups. It is **not monitored in real time** and
sends no SMS, calls or email. Stage 1 uses fictional/demo data only. Read
[KNOWN_LIMITATIONS.en.md](KNOWN_LIMITATIONS.en.md) before any real use.

An admin manages accounts and the site. An admin **cannot** read participants' diary cards,
lessons, reflections or joint-session content; there is no break-glass access.

## 1. First setup

1. Copy `.env.example` to `.env` and replace every placeholder (`change-me…`) with a strong,
   unique value. Never commit `.env`.
   - `SECRET_KEY`: random, at least 32 characters.
   - `FIELD_ENCRYPTION_KEY`: 32 random bytes, base64-encoded, e.g.
     `python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"`.
   - `POSTGRES_PASSWORD` (database owner, used only for migrations) and `APP_DB_PASSWORD` (the
     API's own restricted role, `familybridge_app`). Use two different values.
   - `APP_ENV=production` for anything other than a developer machine. Production refuses an
     invalid encryption key, refuses demo data and sends HSTS.
   - `LLM_PROVIDER` and `DEEPSEEK_API_KEY`: see §5.
2. Start the stack: `docker compose up -d --build`. The API applies migrations as the owner,
   creates or updates the `familybridge_app` role, then serves requests as that role.
3. Create the first admin (from `backend/`; prompts for the password):

   ```bash
   .venv/Scripts/python -m app.cli create-admin --username site-admin
   ```

4. Sign in at the web address and fill in **Site settings** (§2) before inviting anyone.

## 2. Site settings

**Site settings** holds the site name, time zone, help contacts and staffed hours.

- Each help contact needs a label in both Chinese and English.
- The time zone is used for "today" in diary cards and for research-export dates.
- Until you mark the contacts **confirmed by the hospital**, participant Help screens say the
  contacts are placeholders. Only confirm after the hospital has checked every number and the
  hours (open item O4).
- Every change is recorded in the audit log.

## 3. Therapist accounts

**Therapists** lists therapist accounts with status, last sign-in and number of groups.

- **Invite:** issue a one-time code and give it to the therapist in person or by a hospital
  channel. It is shown once, is single-use and expires after `INVITATION_TTL_DAYS` (14). The
  therapist redeems it at `/redeem`.
- **Reset password:** issue a reset code (expires after `RESET_CODE_TTL_HOURS`, 48). Redeeming it
  signs the therapist out everywhere. Therapists reset their own participants' passwords.
- **Disable:** signs the account out at once and blocks sign-in. Re-enable restores access.
- **Content approver:** allows a therapist to approve or retire joint-session episode versions
  (see the content-authoring guide).

## 4. Safety oversight

**Safety oversight** shows all safety events read-only. Therapists work the queue for their own
groups (new → acknowledged → in review → resolved). Every admin read is audited. There is no
automatic escalation (D38): agree a manual review routine with the clinical lead.

## 5. Knowledge base and AI layer

- **Knowledge base** shows the active manual index version, counts, header checks and the last
  retrieval evaluation. It never shows manual text. Ingestion is a developer task (README,
  "Knowledge base").
- **AI layer** shows the provider, circuit breaker, per-function calls and fallbacks, rejection
  codes, prompt approval and evaluation runs. Counts and codes only; no participant text.
- `LLM_PROVIDER=mock` runs without any external calls. `LLM_PROVIDER=deepseek` sends pseudonymous
  lesson context (no names) to DeepSeek. The key lives only in `DEEPSEEK_API_KEY` in `.env`.
  Keep the key out of the repository, chat and tickets.
- If the provider fails, the breaker opens and participants see reviewed static content.

## 6. Backups

Backups are not automated in Stage 1. Use `pg_dump` as the database owner. **A dump contains
encrypted fields and keyed hashes; it is useless without `.env`, and `.env` makes it readable.
Store the dump and `.env` apart, both encrypted, with access limited to named people.** Never put
dumps in the repository (`scripts/scan_repo.py` refuses them).

Back up (custom format, compressed):

```bash
docker compose exec -T db pg_dump -U familybridge -d familybridge -Fc > familybridge-YYYYMMDD.dump
```

Restore into an empty database (stop the API first):

```bash
docker compose stop api
```
```bash
docker compose exec -T db dropdb -U familybridge --if-exists familybridge
```
```bash
docker compose exec -T db createdb -U familybridge familybridge
```
```bash
docker compose exec -T db pg_restore -U familybridge -d familybridge --no-owner < familybridge-YYYYMMDD.dump
```
```bash
docker compose up -d api
```

The API start re-applies grants for `familybridge_app`. After a restore, check the audit chain:

```bash
docker compose exec api python -m app.cli verify-audit
```

Restore requires the **same** `SECRET_KEY` and `FIELD_ENCRYPTION_KEY` as when the dump was taken.
Test a restore on a separate machine at least once before relying on backups.

## 7. Encryption key and secret key

- `FIELD_ENCRYPTION_KEY` encrypts sensitive free text (AES-256-GCM). Values are stored with a
  `v1:` version prefix.
- **Do not change `FIELD_ENCRYPTION_KEY` on a database that holds data.** The app currently reads
  only one key version, so existing values would become unreadable. Rotation needs a
  re-encryption tool that reads `v1:` and writes `v2:`; it is not built yet (open item O25).
  Until then, if the key may have leaked: stop the API, take a backup (§6), and ask the developer
  team to run a supervised re-encryption.
- `SECRET_KEY` keys the hashes of one-time codes and session tokens and the pseudonymous codes in
  research exports. Changing it signs everyone out, voids unused codes, and gives new export codes
  (earlier exports can no longer be linked). Change it only between study waves, and record the
  date.
- Keep both keys out of chat, email and tickets. Store them in the hospital's secret store.

## 8. Research export

**Research export** previews each CSV file with its row count and downloads a zip with
`data_dictionary.csv`. The export has no free text and no direct identifiers, keeps adolescent and
caregiver files apart, includes only records made while each person's research consent was on,
and uses dates plus study day without times. Every download is audited. Store exports only in the
study's secure storage; never in the repository. Demo data is excluded unless asked for on the
command line.

## 9. Audit log

Every account, setting, export and sensitive read is written to an append-only, hash-chained
audit log. The database role used by the API cannot change or delete it. Check the chain
regularly and after any restore:

```bash
docker compose exec api python -m app.cli verify-audit
```

A non-zero exit means an entry was changed or removed: stop and contact the security lead.

## 10. Routine checklist

| When | Task |
|---|---|
| Weekly | Review Safety oversight with the clinical lead; check AI layer fallbacks |
| Weekly | Take a backup (§6); run `verify-audit` |
| Monthly | Disable accounts of people who left; check unused codes |
| Each study wave | Run the research export; record the export date |
| Before real use | Confirm help contacts; set production secrets |
