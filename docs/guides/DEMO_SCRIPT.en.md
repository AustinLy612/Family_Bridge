# Co-design demo script

For facilitators running co-design sessions with adolescents, caregivers and clinicians. 中文版:
[DEMO_SCRIPT.zh-CN.md](DEMO_SCRIPT.zh-CN.md). About 45 minutes. Everything shown is fictional.

It covers: **pairing, private vs shared, joint session, reconnection, role switching,
completion, and error recovery.**

## Before the session

1. Start the stack (`docker compose up -d --build`) on a fresh database, then seed it (from
   `backend/`):

   ```bash
   .venv/Scripts/python -m app.cli seed-demo
   ```

   Usernames and passwords are in `seed_output/demo_credentials.json` (git-ignored). Do not
   show this file on screen, and do not put it in slides or notes.
2. Open **three separate browser windows that do not share cookies** (for example three browser
   profiles, or one normal window plus two private windows from different browsers). One account
   per window. Label them on screen:

   | Window | Account | Who |
   |---|---|---|
   | T | `demo-therapist` | Dr Lin (therapist) |
   | A | `demo-teen-a` | Maple (adolescent) |
   | C | `demo-carer-a` | Maple's mum (caregiver) |

3. Set the language per account under **Settings** to match the audience.
4. Say at the start: *"This is a prototype with made-up people. It is not watched in real time.
   If anything today feels hard, you can stop at any time."*

> **Do not** type real risk statements during a demo. Use the scripted steps below.

## 1. Pairing (5 min)

Show how a family is set up. No one can sign up on their own.

1. **T → Groups & families:** open the demo group and Family A. Point out the teen and
   caregiver are separate people with separate accounts.
2. **T:** show **Generate code** for a caregiver (do not redeem it). Explain: the code is shown
   once, is single-use and expires; each person redeems their own code at `/redeem` and goes
   through consent on their own.
3. **T:** on Family A, show the pair's joint-session status, **Suitable**. Joint activities stay
   closed until the therapist marks a pair suitable.

*Discussion prompt:* "How should a family receive their codes?"

## 2. Private vs shared (10 min)

1. **A → Who can see my data:** read the list together. Caregivers see nothing unless Maple
   shares.
2. **A → Diary Card → New entry:** fill a few items with made-up values; **Save entry**.
3. **C → Diary Card:** "Nothing has been shared with you."
4. **A:** on the saved entry, choose **Share**, tick two items and Maple's mum, then
   **Preview**. Show that the preview is exactly what will be sent. Confirm **Share**.
5. **C:** reload; the two items appear, nothing else.
6. **A:** **Stop sharing**. **C:** reload; the items are gone at once.

*Discussion prompt:* "What would you want to share, and when?"

## 3. Joint session and role switching (10 min)

1. **T → Joint sessions:** schedule Family A for the demo episode, window today.
2. **A** and **C → Joint sessions:** each answers the invitation on their own with
   **Yes, I'd like to**. (Mention: if either chose **Not this time**, the other would see only
   "This session won't run this time", with no reason.)
3. **A** and **C:** **Join**, then **I'm ready**. Switch between windows so the room sees both
   views of the same step.
4. **Private choice:** at a choice step, **A** chooses and presses **Choose**; **A** sees
   "Waiting for your family member to choose." Then **C** chooses. Only now are both choices
   revealed to both.
5. **T:** keep the board visible: it shows **step progress only**, not what anyone chose or wrote.
6. **Pause:** **C** presses **Pause**; both are paused. **A** presses **Carry on**.

## 4. Reconnection (5 min)

1. **A:** reload the page mid-step. It shows "Reconnecting… your place is saved." and returns to
   the same step.
2. **A:** close the window. **C** sees "Your family member's connection dropped. Their place is
   saved." After about a minute (`ROOM_DISCONNECT_PAUSE_SECONDS`) the room pauses by itself.
3. Open window A again, sign in if needed, go to **Joint sessions** and **Join**. Either person
   presses **Carry on**; the room continues from the same step.

## 5. Completion (5 min)

1. Finish the remaining steps in **A** and **C**. Both see "You finished together."
2. **T → Joint sessions:** open the summary. It shows check-in ratings and private reflections.
   Say clearly that the therapist sees reflections, and that opening the summary is recorded.

## 6. Error recovery (10 min)

1. **Declining:** schedule a second session; **C** chooses **Not this time**. **A** sees only
   "This session won't run this time."
2. **"I need to stop":** schedule and start another session. **A** presses **I need to stop**.
   - **A** sees the Help screen (contacts and staffed hours; placeholders in the demo).
   - **C** sees "The session is paused for now"; it cannot be continued by either participant.
   - **T:** the board shows the room is held, and a low-severity event appears in the **Safety
     queue**. **T** presses **Resume** (after "checking in") or **End**.
3. **AI fallback** (only with `LLM_PROVIDER=mock`): in a lesson in **A**, send a message
   containing `[[mock:rule-violation]]`. The blocked sentence never appears; reviewed text is
   shown instead.
4. **Lost connection:** turn off the network in window **C** for a few seconds, then back on.
   The room reconnects to the same step.

*Discussion prompt:* "When you need to stop, what should happen next, and who should know?"

## After the session

- Sign out in all three windows. Close the private windows.
- Codes and joint sessions used in the demo cannot be reused. For the next session, start
  again from a fresh database and `seed-demo`.
- Record feedback in the co-design notes. Do not record names of participants in the app.
