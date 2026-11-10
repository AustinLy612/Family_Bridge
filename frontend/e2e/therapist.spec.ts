/**
 * Phase 7 E2E: therapist dashboard (Plan §5.8; Phase 7 acceptance), on the mock LLM.
 * A therapist enrols a family, records group-session skills, sets homework and a diary
 * expectation, reviews learning summaries (the participant's words only on request) and diaries,
 * and handles a safety event end-to-end without reading a transcript. Content review and
 * metrics load for their own group. One therapist and family per run (codes are rate-limited).
 */
import { expect as baseExpect, test, type Browser, type Page } from "@playwright/test";
import { RUN, completeOnboarding, demoAdmin, readCode, redeem, signIn, signOut } from "./helpers";

test.use({ actionTimeout: 15_000 });
const expect = baseExpect.configure({ timeout: 20_000 });
const NEGATIVE = /\b(overdue|you missed|behind|streak|failed|incomplete|score)\b|逾期|未完成/i;

interface World {
  therapist: Page;
  familyUrl: string;
  teen: Page;
  teenAlias: string;
  carer: Page;
  homework: string;
}

async function setUp(browser: Browser): Promise<World> {
  const id = `${RUN}-t`;
  const page = await browser.newPage();
  const admin = demoAdmin();
  await signIn(page, admin.username, admin.password);
  await page.getByRole("button", { name: "New therapist code" }).click();
  const therapistCode = await readCode(page);
  await signOut(page);
  await page.close();

  const therapist = await redeem(browser, therapistCode, `e2e-dash-${id}`, `Dr Dash ${id}`);
  await therapist.getByLabel("New group name").fill(`Dash group ${id}`);
  await therapist.getByRole("button", { name: "Create" }).click();
  await therapist.getByRole("link", { name: new RegExp(`Dash group ${id}`) }).click();

  // record the skills covered in a group session (Plan §5.5.3)
  await expect(therapist.getByRole("heading", { name: "Skills covered in group sessions" })).toBeVisible();
  await therapist.getByText("Distress tolerance", { exact: true }).click();
  await therapist.getByRole("checkbox", { name: "TIPP skills" }).check();
  await therapist.getByRole("button", { name: "Add record" }).click();
  await expect(therapist.getByText(/TIPP skills/).first()).toBeVisible();

  // enrol a family
  await therapist.getByLabel("New family label").fill(`Dash family ${id}`);
  await therapist.getByRole("button", { name: "Create" }).click();
  await therapist.getByRole("link", { name: new RegExp(`Dash family ${id}`) }).click();
  const familyUrl = therapist.url();
  await therapist.getByLabel("Account type").selectOption("adolescent");
  await therapist.getByRole("button", { name: "Generate code" }).click();
  const teenCode = await readCode(therapist);
  await therapist.getByRole("button", { name: "Generate code" }).click();
  const carerCode = await readCode(therapist);
  const teenAlias = `Teen ${id}`;
  const teen = await redeem(browser, teenCode, `e2e-dteen7-${id}`, teenAlias);
  await completeOnboarding(teen, "/teen");
  const carer = await redeem(browser, carerCode, `e2e-dcarer7-${id}`, `Carer ${id}`);
  await completeOnboarding(carer, "/caregiver");
  return { therapist, familyUrl, teen, teenAlias, carer, homework: `Try TIPP once (${id})` };
}

test.describe.configure({ mode: "serial" });
let w: World;
test.beforeAll(async ({ browser }) => {
  test.setTimeout(180_000);
  w = await setUp(browser);
});

test("homework and diary expectation: set, seen on Home, ticked in the diary", async () => {
  const { therapist, teen, carer } = w;
  await therapist.goto("/therapist/schedule");
  const days = therapist.getByRole("radiogroup", { name: "Days per week" });
  await days.getByRole("radio", { name: "3" }).click();
  await expect(days.getByRole("radio", { name: "3" })).toHaveAttribute("aria-checked", "true");
  await therapist.getByLabel("What to do").fill(w.homework);
  await therapist.getByRole("button", { name: "Add homework" }).click();
  const task = therapist.getByTestId("task").filter({ hasText: w.homework });
  await expect(task.getByRole("row")).toHaveCount(3); // header + teen + caregiver
  await expect(task).toContainText("Not yet");

  // Home lists it read-only, with no negative copy
  await teen.goto("/teen");
  const list = teen.getByRole("list", { name: "This week's homework" });
  await expect(list).toContainText(w.homework);
  await expect(teen.locator("body")).not.toContainText(NEGATIVE);
  await carer.goto("/caregiver");
  await expect(carer.getByRole("list", { name: "This week's homework" })).toContainText(w.homework);

  // the teen ticks it in a diary entry; an urge at the threshold opens Help after saving
  await teen.goto("/teen/diary/new");
  await teen.getByRole("radiogroup", { name: "Sad" }).getByRole("radio", { name: "6" }).click();
  await teen
    .getByRole("radiogroup", { name: "Urge to harm yourself" })
    .getByRole("radio", { name: "8" })
    .click();
  await teen.getByRole("checkbox", { name: new RegExp(w.homework.replace(/[()]/g, "\\$&")) }).check();
  await teen.getByRole("button", { name: "Save entry" }).click();
  await expect(teen).toHaveURL(/\/teen\/help$/);

  await therapist.reload();
  const row = therapist
    .getByTestId("task")
    .filter({ hasText: w.homework })
    .getByRole("row", { name: new RegExp(w.teenAlias) });
  await expect(row).toContainText("Done");
});

test("learning summaries without transcripts; the participant's words only on request", async () => {
  const { teen, therapist } = w;
  // a group-review lesson (the skill is fixed by the group record)
  await teen.goto("/teen/learn");
  await teen.getByRole("link", { name: "Fill in my profile" }).click();
  await teen.getByLabel("Grade").selectOption("grade_9");
  await teen.getByRole("button", { name: "Music" }).click();
  await teen.getByRole("button", { name: "Sleep troubles" }).click();
  await teen.getByRole("button", { name: "Save" }).click();
  await expect(teen.getByText("Saved.")).toBeVisible();
  await teen.goto("/teen/group-review");
  await teen.getByRole("button", { name: /TIPP skills/ }).click();
  await teen.getByRole("radio", { name: "Okay" }).click();
  await teen.getByRole("button", { name: "Next" }).click();
  for (const text of ["Fictional: cold water helps me.", "Fictional: I will try it this week."]) {
    await teen.getByLabel("Your reply").fill(text);
    await teen.getByRole("button", { name: "Send" }).click();
    await expect(teen.getByLabel("Your reply")).toHaveValue("");
  }
  await expect(teen.getByTestId("lesson-summary")).toBeVisible();
  await teen.getByRole("radio", { name: "Pretty good" }).click();
  await teen.getByRole("button", { name: "Finish" }).click();

  await therapist.goto(w.familyUrl);
  await therapist.getByRole("link", { name: "Learning review" }).click();
  const panel = therapist.getByTestId("learning-panel-adolescent");
  const lesson = panel.getByTestId("learning-lesson").first();
  await expect(lesson).toContainText("TIPP skills");
  await expect(lesson).toContainText("Group review");
  await expect(lesson).toContainText("3 → 4");
  await expect(therapist.locator("body")).not.toContainText("cold water helps me");
  await lesson.getByRole("button", { name: "Show their own words" }).click();
  await expect(therapist.getByTestId("lesson-detail")).toContainText("cold water helps me");

  // coverage map: practised skills, no totals or ranking
  await therapist.goto("/therapist/progress");
  const map = therapist.getByTestId("coverage-map");
  await expect(map.getByRole("row", { name: /TIPP skills/ })).toContainText("1");
  await expect(map).not.toContainText(/total|rank/i);
});

test("diary review uses the expectation; a safety event is handled without transcripts", async () => {
  const { therapist } = w;
  await therapist.goto(`${w.familyUrl}/diary`);
  const teenPanel = therapist.getByTestId("diary-panel-adolescent");
  await expect(teenPanel).toContainText("at 3 a week");
  await expect(teenPanel).toContainText(`Homework ticked: ${w.homework}`);
  await expect(therapist.getByTestId("diary-panel-caregiver")).toBeVisible();

  // the urge at the threshold is in the queue; acknowledge, review, resolve
  await therapist.getByRole("link", { name: "Safety queue" }).click();
  await therapist
    .getByRole("link", { name: new RegExp(w.teenAlias) })
    .first()
    .click();
  await expect(therapist.getByRole("heading", { level: 1 })).toContainText("Diary urge above threshold");
  await therapist.getByRole("button", { name: "Acknowledge" }).click();
  await therapist.getByRole("button", { name: "Start review" }).click();
  await therapist.getByLabel("Follow-up action").fill("(e2e) Called the family; safety plan reviewed.");
  await therapist.getByRole("button", { name: "Resolve" }).click();
  await expect(therapist.getByRole("button", { name: "Resolve" })).toHaveCount(0);
  await expect(therapist.locator("body")).not.toContainText("cold water helps me");

  // content review and metrics for the therapist's own group
  await therapist.getByRole("link", { name: "Content review" }).click();
  await expect(therapist.getByRole("radiogroup", { name: "Show" })).toBeVisible();
  await therapist.getByRole("link", { name: "Metrics" }).click();
  await expect(therapist.getByRole("row", { name: /Teen: days with an entry/ })).toContainText("1 /");
  await expect(therapist.getByRole("row", { name: /Ticked \/ assigned/ })).toContainText("1 / 2");
  await expect(therapist.getByRole("row", { name: /Acknowledged within/ })).toContainText("1 / 1");
});
