# FamilyBridge content-authoring guide

For clinicians and content editors. 中文版: [CONTENT_AUTHORING.zh-CN.md](CONTENT_AUTHORING.zh-CN.md).

Everything participants read — help text, consent, diary templates, prompts, fallbacks,
episodes, safety lists — is a versioned file in [`content/`](../../content/README.md), never in
the code. The API checks every file when it starts and **refuses to start** if any file is
invalid.

## 1. The one rule: never copy the manual

The DBT-A manual is copyrighted. It is used only behind the scenes, to ground AI answers.
Participants see **original wording only** (D7).

- Write in your own words. Do not paste, translate line by line, or lightly reword manual text.
- An automatic check compares every committable file with fingerprints of the manual and fails
  if any file shares 20 or more consecutive characters with it (`scripts/scan_repo.py`).
- Never add the manual PDF or extracts to the repository.

## 2. Where things live

| Folder | What you edit |
|---|---|
| `help/{zh,en}.md` | Help screen text. Contacts and hours come from Site settings, not this file. |
| `consent/` | Consent documents, per role and language. |
| `diary/{role}/` | Diary Card templates (items, scales, wording). |
| `episodes/` | Joint-session episodes: `catalog.yaml` and `{id}/vN.yaml`. |
| `prompts/{function}/{role}/{lang}/vN.md` | AI instructions. |
| `fallbacks/` | Reviewed static text shown when the AI is unavailable or fails a check. |
| `safety/` | Risk keywords, forbidden phrases, output rules. |
| `skills/taxonomy.yaml` | Skill names and handout references. |
| `eval/` | Test questions for retrieval and the AI (not shown to participants). |

Every text a participant sees must exist in **both zh-CN and en**.

## 3. Approval status

Each file has an approval block:

```yaml
approval: { status: draft, approved_by: null, approved_at: null }
```

| Status | Meaning |
|---|---|
| `demo` | Fictional example for demos and tests only. |
| `draft` | Being written or reviewed. Usable only with demo/test families. |
| `approved` | Clinically reviewed. Needs `approved_by` and `approved_at`. Usable with real families. |
| `retired` | No longer offered; kept for the record. |

Content that is not `approved` is never offered to a real family.

## 4. Changing a file

1. **Never edit an approved version in place.** Copy it to the next version (`v2.yaml`,
   `v2.md`), set `status: draft`, and edit the copy. Old versions stay so past records still make
   sense.
2. Keep the tone: warm, plain, non-judgemental; no blame, no pressure, nothing "overdue" or
   "failed"; no scores, streaks or badges.
3. **Never promise monitoring, contact or rescue** (for example "we will call you" or "someone is
   watching"). `safety/forbidden_phrases.yaml` blocks such text in help and consent files, and a
   test checks every app string.
4. Check the files (from `backend/`):

   ```bash
   .venv/Scripts/python -m app.cli check-content
   ```

   It prints `content OK` or the file and field at fault.
5. Ask a developer to run the full checks (`bash scripts/check.sh`) and deploy.
6. After clinical review, set `status: approved`, `approved_by` (name or role) and `approved_at`
   (date).

## 5. Episodes

Episode versions are also approved inside the app: an admin, or a therapist with the
**content approver** flag, approves or retires a version under **Content review**. An unapproved
version can be scheduled only for demo families. Each step should say why it is there (the
skill it practises), so a therapist can explain it.

## 6. Prompts and safety lists

- Changing a prompt changes AI behaviour. After a change, a developer re-runs the adversarial
  benchmark (`python -m app.cli ai eval`) and a sweep, and records the results
  (`docs/dev/ADVERSARIAL_RESULTS.md`).
- Changes to risk keywords need clinical sign-off. A missing keyword means a risky message may
  not open Help; an over-broad keyword stops lessons that are fine.
- The diary-card urge threshold is configuration (`DIARY_URGE_THRESHOLD`, or the
  `safety.diary_urge_threshold` setting), not a content file. It is a placeholder (O3).
