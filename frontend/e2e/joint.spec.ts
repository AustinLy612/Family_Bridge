/**
 * Joint sessions (Plan §5.9, Phase 8 acceptance): demo-therapist invites Family A (demo) to the
 * placeholder episode; demo-teen-a and demo-carer-a each answer and play it in their own browser.
 * Covers a neutral decline, private choices before the reveal, pause by one and resume by the
 * other, a reload mid-step, "I need to stop" (D75) with the therapist resuming from the board,
 * completion, and the therapist summary. Needs `seed-demo` (Family A marked suitable).
 */
import { expect as baseExpect, test, type Browser, type Page } from "@playwright/test";
import { scheduleJoint, signInDemo } from "./helpers";

test.use({ actionTimeout: 15_000 });
const expect = baseExpect.configure({ timeout: 20_000 });
test.describe.configure({ mode: "serial" });

let therapist: Page;
let teen: Page;
let carer: Page;

async function newPage(browser: Browser) {
  return (await browser.newContext({ locale: "en-GB" })).newPage();
}

test.beforeAll(async ({ browser }) => {
  test.setTimeout(180_000);
  therapist = await newPage(browser);
  teen = await newPage(browser);
  carer = await newPage(browser);
  await signInDemo(therapist, "demo-therapist", "/therapist");
  await signInDemo(teen, "demo-teen-a", "/teen");
  await signInDemo(carer, "demo-carer-a", "/caregiver");
});

const card = (page: Page, id: string) =>
  page.locator(`[data-testid="joint-invitation"][data-session="${id}"]`);

async function accept(page: Page, home: string, id: string) {
  await page.goto(`${home}/joint`);
  await card(page, id).getByRole("button", { name: "Yes, I'd like to" }).click();
}

async function joinAndReady(page: Page, home: string, id: string) {
  await page.goto(`${home}/joint`);
  await card(page, id).getByRole("link", { name: "Join" }).click();
  await expect(page).toHaveURL(new RegExp(`${home}/joint/${id}$`));
  await page.getByRole("radio", { name: "At the hospital" }).click();
  await page.getByRole("button", { name: "I'm ready" }).click();
}

const step = (page: Page, id: string) => page.locator(`[data-testid="joint-step"][data-step="${id}"]`);

async function startRoom(): Promise<string> {
  const id = await scheduleJoint(therapist);
  await accept(teen, "/teen", id);
  await accept(carer, "/caregiver", id);
  await joinAndReady(teen, "/teen", id);
  await joinAndReady(carer, "/caregiver", id);
  await expect(step(teen, "s1")).toBeVisible();
  await expect(step(carer, "s1")).toBeVisible();
  return id;
}

test("a decline is neutral: the partner sees only that it won't run", async () => {
  const id = await scheduleJoint(therapist);
  await teen.goto("/teen/joint");
  await card(teen, id).getByRole("button", { name: "Not this time" }).click();
  await expect(teen.getByRole("main").getByText("You said not this time").first()).toBeVisible();

  await carer.goto("/caregiver/joint");
  await expect(card(carer, id)).toHaveCount(0);
  await expect(carer.getByRole("main").getByText("This session won't run this time").first()).toBeVisible();
  await expect(carer.getByRole("main")).not.toContainText(/declin|Maple|because/i);

  await therapist.reload();
  await expect(therapist.getByTestId("joint-session-row").first()).toContainText("Declined");
});

test("two browsers play the placeholder episode to the end", async () => {
  test.setTimeout(240_000);
  const id = await startRoom();
  await expect(teen.getByTestId("partner-presence")).toContainText("is here");

  // s1 narration: both continue
  for (const p of [teen, carer]) await step(p, "s1").getByRole("button", { name: "Continue" }).click();

  // s2 check-in: private, one rates and one skips
  await step(teen, "s2").getByRole("radio", { name: "3" }).click();
  await step(carer, "s2").getByRole("button", { name: "Skip" }).click();

  // s3 private choice: the carer cannot see the teen's pick before the reveal
  await step(teen, "s3").getByRole("radio", { name: "A book" }).click();
  await step(teen, "s3").getByRole("button", { name: "Choose" }).click();
  await expect(step(carer, "s3")).toContainText("Your family member has chosen.");
  await expect(carer.getByRole("main")).not.toContainText("A book");
  await expect(carer.getByTestId("joint-reveal")).toHaveCount(0);

  // pause by one participant, carry on by the other
  await carer.getByRole("button", { name: "Pause" }).click();
  await expect(teen.getByTestId("room-paused")).toContainText("Paused");
  await teen.getByTestId("room-paused").getByRole("button", { name: "Carry on" }).click();
  await expect(step(carer, "s3")).toBeVisible();

  // a reload rejoins the same step, the earlier pick still private
  await carer.reload();
  await expect(step(carer, "s3")).toBeVisible();
  await expect(carer.getByRole("main")).not.toContainText("A book");
  await step(carer, "s3").getByRole("radio", { name: "A map" }).click();
  await step(carer, "s3").getByRole("button", { name: "Choose" }).click();

  // the declared reveal: both answers, labelled from each person's view
  for (const p of [teen, carer]) {
    await expect(p.getByTestId("joint-reveal")).toContainText("A book");
    await expect(p.getByTestId("joint-reveal")).toContainText("A map");
  }
  await expect(teen.getByTestId("joint-reveal")).toContainText(/You\s*A book/);
  await expect(carer.getByTestId("joint-reveal")).toContainText(/You\s*A map/);
  for (const p of [teen, carer]) await step(p, "s3").getByRole("button", { name: "Continue" }).click();

  // s4 compose together, s5 shared feedback
  await step(teen, "s4").getByRole("button", { name: "we can see your flowers have opened," }).click();
  await step(teen, "s4").getByRole("button", { name: "Add my pieces" }).click();
  await step(carer, "s4").getByRole("button", { name: "how is your day going?" }).click();
  await step(carer, "s4").getByRole("button", { name: "Add my pieces" }).click();
  for (const p of [teen, carer]) {
    await expect(step(p, "s5").getByTestId("joint-feedback")).toContainText("You noticed and you asked");
    await step(p, "s5").getByRole("button", { name: "Continue" }).click();
  }

  // s6 another go: both skip; s7 a new scene
  for (const p of [teen, carer]) await step(p, "s6").getByRole("button", { name: "Skip" }).click();
  for (const p of [teen, carer]) {
    await step(p, "s7")
      .getByRole("radio", { name: /Sounds like a tiring day/ })
      .click();
    await step(p, "s7").getByRole("button", { name: "Choose" }).click();
  }

  // s8 private reflection: the teen writes, the carer skips
  await step(teen, "s8").getByLabel("Your thoughts (optional)").fill("(demo) The garden was calm today.");
  await step(teen, "s8").getByRole("button", { name: "Save" }).click();
  await step(carer, "s8").getByRole("button", { name: "Skip" }).click();
  for (const p of [teen, carer]) await expect(p.getByText("You finished together.")).toBeVisible();
  await expect(carer.getByRole("main")).not.toContainText("garden was calm");

  // the therapist summary has the reflection; the shared outcome has no private fields
  await therapist.goto(`/therapist/joint/${id}`);
  const summary = therapist.getByTestId("joint-summary");
  await expect(summary).toContainText("Completed");
  await expect(therapist.getByTestId("joint-reflection")).toContainText("(demo) The garden was calm today.");
});

test("'I need to stop' opens Help, holds the room, and only the therapist picks it up", async () => {
  test.setTimeout(180_000);
  const id = await startRoom();
  await teen.getByRole("button", { name: "I need to stop" }).click();
  await expect(teen).toHaveURL(/\/teen\/help$/);

  const held = carer.getByTestId("room-paused");
  await expect(held).toContainText("paused for now");
  await expect(held.getByRole("button", { name: "Carry on" })).toHaveCount(0);
  await expect(carer.getByRole("main")).not.toContainText(/safety|crisis|risk|Maple/i);

  await therapist.goto("/therapist/joint");
  const row = therapist.getByTestId("joint-session-row").filter({ hasText: "Safety pause" });
  await expect(row).toContainText("needs you to resume or end");
  await row.getByRole("button", { name: "Resume" }).click();

  await teen.goto(`/teen/joint/${id}`);
  for (const p of [teen, carer]) await expect(step(p, "s1")).toBeVisible();

  await therapist.getByTestId("joint-session-row").getByRole("button", { name: "End" }).first().click();
  for (const p of [teen, carer]) await expect(p.getByText("This session has ended for now.")).toBeVisible();
});
