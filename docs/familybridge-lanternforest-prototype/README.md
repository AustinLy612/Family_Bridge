# GenAI-DBT FamilyBridge Lantern Forest

A locally runnable, therapist-supervised research prototype for a fantasy-based parent–adolescent DBT skills adventure. The current build contains a polished solo Level 1 and a server-authoritative, two-device cooperative Level 2.

This is a research prototype. It is not clinical treatment, clinical authentication, crisis monitoring, or a crisis-response system. Use only fictional/demo data.

## What is implemented

- Original 2D storybook forest art built with SVG and CSS: layered near/mid/far scenery, moonbeams, path lights, lantern glow, mist, fireflies, gentle leaf drift, and subtle parallax.
- Solo Level 1: emotion recognition, three response styles, deterministic DBT feedback, retry, and a fictional transfer exercise.
- Cooperative Level 2: short-code rooms, adolescent/caregiver roles, separate confirmation, private clues, private choices, controlled perspective reveal, equal shared-reply contributions, feedback, and transfer practice.
- Authoritative TypeScript state machine with all requested states.
- Socket.IO synchronization, disconnect status, safe same-tab reconnection, pause/resume, participant end, therapist pause/resume/end/reset, and new-session creation.
- Role-separated fictional Diary Cards.
- Live therapist demo dashboard with participation, progress, learning summary, and controls.
- Expressive Moss character reactions using posture, ears, brows, gaze, lantern flame, and nonjudgmental reaction cues.
- Story-action choices and light-ribbon response fragments that reduce the appearance of ordinary web forms.
- A two-wick cooperative lantern that shows each participant’s equal contribution before weaving both responses into shared light.
- Reduce Motion, enhanced text contrast, and optional gentle sound effects. Sound is off by default; there is no background music.
- A typed `GenAIDBTService` interface and a local, deterministic mock implementation.
- Unit tests for room/state/privacy/control rules and a two-browser Playwright smoke test.

## Requirements

- Node.js 20 or newer
- pnpm 9 or newer

No database, API key, paid service, or external media asset is required.

## One-click start on macOS

After dependencies have been installed once, you can start the complete frontend and backend without typing Terminal commands:

1. Double-click **`Start FamilyBridge.command`** in the project folder.
2. Keep the Terminal window open while using the game.
3. The launcher waits for the verified FamilyBridge health check and opens the game in your default browser.
4. To stop, double-click **`Stop FamilyBridge.command`** or press **Control-C** in the launcher Terminal window.

The launcher locates the project relative to itself, so the whole project folder can be moved. It uses the configured Vite port `5173` and backend port `3001`, verifies the FamilyBridge health response before opening a browser, and refuses to start if either port belongs to another application. The stop launcher targets only the process tree recorded by the start launcher; it does not stop unrelated Node.js applications.

If macOS blocks the launcher the first time, Control-click the `.command` file, choose **Open**, then confirm **Open** once. If a downloaded or copied file loses its executable permission, run:

```bash
chmod +x "Start FamilyBridge.command" "Stop FamilyBridge.command"
```

If the launcher reports missing dependencies, open Terminal in this project folder and run:

```bash
pnpm install
```

Node.js 20 or newer and pnpm 9 or newer are still required. The launcher loads `$HOME/.nvm/nvm.sh` automatically when it exists.

## Install and run

```bash
pnpm install
pnpm run dev
```

The command starts both services:

- Storybook client: `http://localhost:5173`
- Socket.IO/Express server: `http://localhost:3001`

Open `http://localhost:5173` in a browser. Press `Ctrl+C` in the terminal to stop both services.

### Production-style local build

```bash
pnpm run build
pnpm start
```

Then open `http://localhost:3001`. Express serves the compiled client and Socket.IO from one process.

## Test Level 1

1. Open `http://localhost:5173`.
2. Choose **Start solo practice**.
3. Notice one or two possible emotions.
4. Try each response style to compare validation, immediate problem-solving, and minimizing.
5. Continue to the fox transfer scene and complete the practice.

Level 1 never assigns a punitive score. The player can retry any response.

## Test Level 2 in two browser windows

1. In window or tab A, choose **Play as Adolescent** → **Create room**.
2. Copy the four-letter room code.
3. In window or tab B, choose **Play as Caregiver**, enter the code, and join.
4. Confirm participation separately on both screens.
5. Advance both roles through their private clue, private response, controlled reveal, shared reply, feedback, and transfer scene.

Separate ordinary tabs work because the demo identity is tab-scoped. A private/incognito window is also fine.

### Test on two devices on the same network

1. Connect both devices to the same trusted local network.
2. Start `pnpm run dev` on the host computer.
3. Use the `Network` URL printed by Vite, for example `http://192.168.1.20:5173`.
4. Open that same URL on both devices and follow the two-window steps above.
5. If another device cannot connect, allow local incoming connections for Node in the host firewall and verify that the devices can reach one another.

Do not expose this unauthenticated research demo directly to the public internet.

## Therapist dashboard and reset

Choose **Therapist demo dashboard** on the welcome screen, or open:

`http://localhost:5173/therapist`

The prototype uses an intentionally visible simulated therapist key. The dashboard can pause, resume, end, or reset a demo room. **Reset** returns the existing room and participants to onboarding. Restarting the server clears every in-memory room.

## Automated checks

```bash
pnpm run check
pnpm test
pnpm run build
```

The unit suite covers:

- room creation and joining;
- role assignment and duplicate-role rejection;
- separate confirmation;
- private response protection;
- server-controlled progression;
- both participants contributing;
- disconnect and reconnect;
- participant pause and termination;
- therapist permission checks; and
- demo reset.

Optional two-context browser smoke test (uses an installed Google Chrome):

```bash
pnpm run test:e2e
```

## Project structure

```text
.
├── server/
│   ├── GameRoomStore.ts          # authoritative room store and state machine
│   ├── GameRoomStore.test.ts     # multiplayer/privacy/control tests
│   └── index.ts                  # Express + Socket.IO transport
├── shared/
│   ├── content.ts                # story content and clinical feedback rubric
│   └── types.ts                  # shared game/network types
├── src/
│   ├── components/               # SVG forest, character, scene UI, settings
│   ├── hooks/                    # Socket.IO room client and optional chime
│   ├── screens/                  # welcome, solo, cooperative, diary, dashboard
│   ├── services/                 # GenAIDBTService and deterministic mock
│   ├── App.tsx
│   └── styles.css
├── tests/e2e/                    # two-browser Playwright smoke test
├── index.html
├── package.json
├── playwright.config.ts
└── vite.config.ts
```

## State machine

The server owns transitions through:

`WELCOME → STORY_INTRO → EMOTION_RECOGNITION → INDIVIDUAL_RESPONSE → WAITING_FOR_PARTNER → COOPERATIVE_TASK → SKILL_FEEDBACK → TRANSFER_REFLECTION → COMPLETED`

`PAUSED` preserves the prior state, and `TERMINATED` ends a room. Clients cannot advance by sending an arbitrary next state; they can only submit validated actions accepted for the current state and assigned role.

## GenAI-DBT integration point

`src/services/GenAIDBTService.ts` defines:

- `explainSkill()`
- `generateHint()`
- `evaluateSkillResponse()`
- `generateTransferScenario()`

The current `LocalMockGenAIDBTService` returns deterministic, reviewable content. A production adapter should return schema-validated, versioned, clinically reviewed results. It should personalize teaching and wording only; it must not control state transitions, diagnose users, merge private participant data, or generate unrestricted trauma narratives.

## Mocked or simulated

- Therapist and participant authentication.
- In-memory room persistence.
- GenAI/RAG calls and all adaptive feedback.
- Diary Card persistence and consent-governed clinician access.
- Clinical content approval workflow, audit logging, encryption, and safety escalation.

## Known limitations

- Rooms disappear when the server restarts and are not shared across multiple server processes.
- Reconnection is based on a tab-scoped demo identifier, not secure identity.
- The therapist key is deliberately visible and must never be treated as real access control.
- The clinical wording is a prototype rubric and still requires review by qualified DBT clinicians and adolescent co-design participants.
- The app has no crisis detection, risk prediction, clinical alerts, or emergency response.
- No production privacy, consent, retention, accessibility certification, localization, analytics, or hospital security controls are included.

## Suggested next steps

1. Clinician-review and version the story content, transfer probes, and validation rubric.
2. Replace simulated identity with institution-approved authentication and least-privilege authorization.
3. Add a persistent, encrypted store with role-scoped Diary Cards, consent records, audit trails, and retention rules.
4. Implement a bounded production `GenAIDBTService` adapter with structured output validation, static fallback content, provenance, and adversarial regression tests.
5. Conduct separate adolescent, caregiver, and therapist co-design/usability sessions, including sensory and accessibility testing.
6. Add therapist-approved session assignment and explicit, neutral opt-in/decline flows for every joint activity.

## Artwork and content

All game artwork in this repository is original SVG/CSS created for this prototype. No third-party game artwork or continuous background music is bundled.
