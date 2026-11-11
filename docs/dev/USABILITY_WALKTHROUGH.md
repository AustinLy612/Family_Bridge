# Usability walkthrough scripts (Plan §7.4)

Scripted tasks for co-design and usability sessions (proposal §7.2 E, §7.3). The research team
runs them with participants; developers keep them runnable against the demo seed. The automated
version is `frontend/e2e/walkthrough.spec.ts`. It checks that every task can still be completed
with the shipped UI. It is not a usability measure.

**Setup.** Use local, fictional demo data only.

```bash
cd backend
.venv/Scripts/python -m app.cli seed-demo           # fresh database
.venv/Scripts/python -m app.cli seed-demo-activity  # older demo database: adds Phase 7 activity
```

- Credentials are in the git-ignored `seed_output/demo_credentials.json`. Never paste them into
  notes or recordings.
- On first sign-in, demo participants complete onboarding. That step is part of the session,
  not one of the scripted tasks below.

**For each task, the facilitator records:** success (yes / with help / no), time on task, the
path taken, and the participant's own words. Read the prompt aloud. Do not demonstrate.

| # | Account | Prompt to the participant | Success criterion |
|---|---|---|---|
| W1 | `demo-teen-a` | "Find out who can see your Diary Card, and what your mum can see." | Opens *Who can see my data* (in Settings since D92) or the diary's *Who can see this?* note, and says that the therapist sees the card and the caregiver sees only what is shared. |
| W2 | `demo-teen-a` | "Imagine you need help right now. Show me where you would go." | Finds **Get help** in the header without scrolling or opening a menu. (Was "find Pause"; Pause is in the joint room only since D92.) |
| W3 | `demo-teen-a` | "You have been invited to a joint activity. Decline it." | Joint sessions → the invitation card → "Not this time". No reason is asked; the card moves to Earlier as "You said not this time". In the automated run, `demo-therapist` sends the invitation first. |
| W4 | `demo-teen-a` | "Your group covered a skill this week. Do a short lesson on it." | Starts a lesson from *Group review*, replies, and finishes it (mood after). |
| W5 | `demo-teen-a` | "Fill in today's Diary Card and tick the homework you did." | Saves an entry with at least one item and a homework tick, and sees "Saved." |
| W6 | `demo-therapist` | "Check how Family A is doing this week." | Within **10 minutes** (D72, a placeholder target), opens Family A's diary review, learning review and the schedule's homework status, and states one observation from each. Transcripts are not needed. |

**Notes for facilitators**

- Missed diary days and unticked homework never get negative wording. If a participant reads
  anything as a reprimand, record the exact text.
- W6 measures therapist burden (§1.2, §2). Record the time per screen and any back-tracking.
  The dashboard also logs focus time per family (Metrics → *Therapist time per family*).
- Open items that affect the scripts: joint sessions (Phase 8, O8); final art and copy (O18);
  clinical sign-off on diary wording and the urge threshold (O3).
