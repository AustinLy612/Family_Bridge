# Accessibility audit (Phase 10 task 2; Plan §5.11)

Carried out on 2026-11-09. Automated checks are in `frontend/e2e/a11y.spec.ts` and run with the
rest of the E2E suite, so a regression fails the build.

## Scope

axe-core 4.14 (`@axe-core/playwright`, rules tagged `wcag2a`, `wcag2aa`, `wcag21a`, `wcag21aa`,
`wcag22aa`), any violation fails the test:

| Area | Screens | Languages |
|---|---|---|
| Public | `/`, `/redeem`, `/reset` | default |
| Adolescent (`demo-teen-a`) | Home, Learn, Group review, Diary Card list and new entry, Joint sessions, Help, Who can see my data, Profile, Settings | en, zh-CN |
| Caregiver (`demo-carer-a`) | Home, Learn, Group review, Diary Card list and new entry, Joint sessions, Help, Who can see my data, Settings | en, zh-CN |
| Joint room | Lobby and a running step (adolescent view) | en |
| Therapist | Joint-session board | en |

Keyboard checks (same file):

- The first Tab stop is the skip link, and it moves focus to `#main`.
- **Pause** is reachable with Tab from the top of a page.
- The focused control has a visible focus indicator (outline or box shadow).

Earlier phases already test focus and keyboard use in their own flows (consent, lessons, diary
editing, the joint room) with Testing Library and Playwright.

## Results

- **One issue found and fixed:** `label-content-name-mismatch` on the brand link in the header
  (`AppShell.tsx`, `PublicFrame.tsx`). Its `aria-label` did not contain the visible text, so
  speech-input users could not activate it by name. The `aria-label` was removed; the visible text
  is the accessible name. The unused `shell.brand` string was removed.
- After the fix: **0 violations** on every screen above, in both languages.

## Not covered

- **Manual screen-reader pass: cancelled by the project lead (O27, D90).** Automated tools catch
  only part of WCAG, so screen-reader use (NVDA, VoiceOver) is untested by a person.
- Therapist and admin screens other than the joint board were not audited with axe (they are
  staff screens; Plan §5.11 targets participant screens).
- Colour contrast in images and the placeholder art (O18) is not checked by axe.
- Text zoom to 200% was not checked. Reflow is checked only as "no horizontal scrolling at
  320 CSS px" on the main adolescent and caregiver screens (WCAG 1.4.10; the reflow test in the same file).
