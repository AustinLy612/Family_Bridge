/**
 * Usability walkthrough scripts (Plan §7.4; docs/dev/USABILITY_WALKTHROUGH.md), run against the
 * demo seed (`seed-demo`, or `seed-demo-activity` for an older demo database). This checks that
 * each scripted task can still be completed with the shipped UI; it is not a usability measure.
 * Demo participants complete onboarding on first sign-in. The run switches demo accounts to
 * English, and it adds a diary entry and a finished lesson each time.
 */
import { expect as baseExpect, test, type Page } from "@playwright/test";
import { scheduleJoint, signInDemo } from "./helpers";

test.use({ actionTimeout: 15_000 });
const expect = baseExpect.configure({ timeout: 20_000 });
const REVIEW_LIMIT_MS = 10 * 60 * 1000; // D72: placeholder target

test.describe.configure({ mode: "serial" });

test.describe("adolescent tasks (demo-teen-a)", () => {
  let page: Page;
  test.beforeAll(async ({ browser }) => {
    page = await browser.newPage();
    await signInDemo(page, "demo-teen-a", "/teen");
  });

  test("W1 distinguish private and shared data", async () => {
    await page.goto("/teen/diary");
    await expect(page.getByRole("status", { name: "Who can see this?" })).toContainText(
      "Your therapist can see",
    );
    await page.getByRole("link", { name: "Who can see my data" }).click();
    await expect(page.getByText("Your Diary Cards").first()).toBeVisible();
    await expect(page.getByText("Only what you choose to share").first()).toBeVisible();
  });

  test("W2 find the pause control immediately", async () => {
    await page.goto("/teen");
    await expect(page.getByRole("button", { name: "Pause" })).toBeInViewport();
  });

  test("W3 decline a joint invitation", async ({ browser }) => {
    // the therapist invites Family A to the placeholder activity; the teen says "Not this time"
    const therapist = await browser.newPage();
    await signInDemo(therapist, "demo-therapist", "/therapist");
    const id = await scheduleJoint(therapist);
    await therapist.close();
    await page.goto("/teen/joint");
    const card = page.locator(`[data-testid="joint-invitation"][data-session="${id}"]`);
    await expect(card).toContainText("You can say no, or stop at any time");
    await card.getByRole("button", { name: "Not this time" }).click();
    await expect(page.getByRole("main").getByText("You said not this time").first()).toBeVisible();
    await expect(page.getByRole("main")).not.toContainText(/\bwhy\b|because/i);
  });

  test("W4 complete a lesson", async () => {
    test.setTimeout(180_000);
    // a lesson needs a profile (age and grade); fill it the first time
    await page.goto("/teen/profile");
    await expect(page.getByRole("spinbutton", { name: "Age" })).toHaveValue(/\d/);
    const grade = page.getByLabel("Grade");
    if ((await grade.inputValue()) === "") {
      await grade.selectOption("grade_9");
      await page.getByRole("button", { name: "Music" }).click();
      await page.getByRole("button", { name: "Sleep troubles" }).click();
      await page.getByRole("button", { name: "Save" }).click();
      await expect(page.getByRole("main").getByText("Saved.")).toBeVisible();
    }
    await page.goto("/teen/group-review");
    await page
      .getByRole("button", { name: /TIPP skills/ })
      .first()
      .click();
    await page.getByRole("radio", { name: "Okay" }).click();
    await page.getByRole("button", { name: "Next" }).click();
    for (const text of ["(demo) I tried cold water.", "(demo) It helped a bit."]) {
      await page.getByLabel("Your reply").fill(text);
      await page.getByRole("button", { name: "Send" }).click();
      await expect(page.getByLabel("Your reply")).toHaveValue("");
    }
    await expect(page.getByTestId("lesson-summary")).toBeVisible();
    await page.getByRole("radio", { name: "Pretty good" }).click();
    await page.getByRole("button", { name: "Finish" }).click();
    await expect(page.getByText("Finished").first()).toBeVisible();
  });

  test("W5 complete a diary entry and tick homework", async () => {
    await page.goto("/teen/diary/new");
    await page.getByRole("radiogroup", { name: "Sad" }).getByRole("radio", { name: "4" }).click();
    const homework = page.getByRole("checkbox", { name: /\(demo\)/ });
    if ((await homework.count()) > 0) await homework.first().check();
    await page.getByRole("button", { name: "Save entry" }).click();
    await expect(page.getByText("Saved.")).toBeVisible();
  });
});

test("W6 therapist reviews a family within the target time", async ({ page }) => {
  test.setTimeout(REVIEW_LIMIT_MS + 60_000);
  await signInDemo(page, "demo-therapist", "/therapist");
  const started = Date.now();
  await page.getByRole("link", { name: /Demo DBT-A group/ }).click();
  await page.getByRole("link", { name: /Family A \(demo\)/ }).click();
  const familyUrl = page.url();

  await page.getByRole("main").getByRole("link", { name: "Diary review" }).click();
  await expect(page.getByTestId("diary-panel-adolescent").getByTestId("review-entry").first()).toBeVisible();
  await expect(page.getByTestId("diary-panel-caregiver")).toBeVisible();

  await page.goto(familyUrl);
  await page.getByRole("main").getByRole("link", { name: "Learning review" }).click();
  await expect(page.getByTestId("learning-panel-adolescent")).toBeVisible();

  await page.getByRole("link", { name: "Schedule" }).click();
  await expect(page.getByTestId("task").filter({ hasText: "(demo)" }).first()).toBeVisible();

  const elapsed = Date.now() - started;
  test.info().annotations.push({ type: "review-ms", description: String(elapsed) });
  expect(elapsed).toBeLessThan(REVIEW_LIMIT_MS);
});
