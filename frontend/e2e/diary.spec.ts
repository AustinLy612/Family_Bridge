/**
 * Phase 6 E2E: Diary Cards (Plan §5.6; Phase 6 acceptance).
 * - The caregiver sees nothing of the adolescent's card until a share; stopping the share removes
 *   it at once.
 * - An urge at the threshold opens Help after saving and reaches the therapist's queue.
 * - Edits keep earlier versions; missing days get no negative copy.
 * - The therapist review keeps each person's card separate.
 * One therapist and family per run (invitation codes are rate-limited per IP).
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
}

async function setUp(browser: Browser): Promise<World> {
  const id = `${RUN}-d`;
  const page = await browser.newPage();
  const admin = demoAdmin();
  await signIn(page, admin.username, admin.password);
  await page.getByRole("button", { name: "New therapist code" }).click();
  const therapistCode = await readCode(page);
  await signOut(page);
  await page.close();

  const therapist = await redeem(browser, therapistCode, `e2e-dt-${id}`, `Dr Diary ${id}`);
  await therapist.getByLabel("New group name").fill(`Diary group ${id}`);
  await therapist.getByRole("button", { name: "Create" }).click();
  await therapist.getByRole("link", { name: new RegExp(`Diary group ${id}`) }).click();
  await therapist.getByLabel("New family label").fill(`Diary family ${id}`);
  await therapist.getByRole("button", { name: "Create" }).click();
  await therapist.getByRole("link", { name: new RegExp(`Diary family ${id}`) }).click();
  const familyUrl = therapist.url();
  await therapist.getByLabel("Account type").selectOption("adolescent");
  await therapist.getByRole("button", { name: "Generate code" }).click();
  const teenCode = await readCode(therapist);
  await therapist.getByRole("button", { name: "Generate code" }).click();
  const carerCode = await readCode(therapist);

  const teenAlias = `Teen ${id}`;
  const teen = await redeem(browser, teenCode, `e2e-dteen-${id}`, teenAlias);
  await completeOnboarding(teen, "/teen");
  const carer = await redeem(browser, carerCode, `e2e-dcarer-${id}`, `Carer ${id}`);
  await completeOnboarding(carer, "/caregiver");
  return { therapist, familyUrl, teen, teenAlias, carer };
}

async function pick(page: Page, group: string, option: string) {
  await page.getByRole("radiogroup", { name: group }).getByRole("radio", { name: option }).click();
}

async function save(page: Page) {
  await page.getByRole("button", { name: "Save entry" }).click();
}

test.describe.configure({ mode: "serial" });
let w: World;
test.beforeAll(async ({ browser }) => {
  test.setTimeout(180_000);
  w = await setUp(browser);
});

test("diary entry, share chosen items, stop sharing, edit with versions", async () => {
  const { teen, carer } = w;
  await teen.goto("/teen/diary");
  await expect(teen.getByText("Missed entries are okay — add one when you can.")).toBeVisible();
  await expect(teen.locator("body")).not.toContainText(NEGATIVE);

  // a new entry; the skill question's follow-ups appear after "Yes"
  await teen.getByRole("link", { name: "New entry" }).click();
  await pick(teen, "Sad", "6");
  await pick(teen, "Urge to harm yourself", "2");
  await pick(teen, "Have you used a DBT skill since your last entry?", "Yes");
  await teen.getByText("Distress tolerance", { exact: true }).click();
  await teen.getByRole("checkbox", { name: "TIPP skills" }).check();
  await pick(teen, "How helpful was it?", "7");
  await teen
    .getByLabel("Anything else you want to note (optional)")
    .fill("Fictional: a calm walk after school.");
  await save(teen);
  await expect(teen.getByText("Saved.")).toBeVisible();
  await expect(teen).toHaveURL(/\/teen\/diary\/[0-9a-f-]{36}$/);
  const entryUrl = teen.url();

  // the caregiver sees nothing yet
  await carer.goto("/caregiver/diary");
  await expect(carer.getByText("Nothing has been shared with you.")).toBeVisible();

  // share two items: choose, preview, share
  const panel = teen.getByTestId("share-panel");
  await panel.getByRole("radio", { name: /Carer/ }).click();
  await panel.getByRole("checkbox", { name: "Sad" }).check();
  await panel.getByRole("checkbox", { name: "Anything else you want to note (optional)" }).check();
  await panel.getByRole("button", { name: "Preview" }).click();
  const preview = panel.getByTestId("share-preview");
  await expect(preview).toContainText("6 (1–10)");
  await expect(preview).toContainText("a calm walk");
  await expect(preview).not.toContainText("Urge");
  await panel.getByRole("button", { name: "Share", exact: true }).click();
  await expect(panel.getByRole("button", { name: "Stop sharing" })).toBeVisible();

  await carer.reload();
  const item = carer.getByTestId("shared-item");
  await expect(item).toContainText(`From ${w.teenAlias}`);
  await expect(item).toContainText("6 (1–10)");
  await expect(item).toContainText("a calm walk");
  await expect(item).not.toContainText("Urge");
  await expect(item).not.toContainText("TIPP");

  // stop sharing: access ends at once
  await panel.getByRole("button", { name: "Stop sharing" }).click();
  await expect(panel.getByText(/Stopped sharing with/)).toBeVisible();
  await carer.reload();
  await expect(carer.getByText("Nothing has been shared with you.")).toBeVisible();
  await expect(carer.getByTestId("shared-item")).toHaveCount(0);

  // edit: the earlier version is kept
  await teen.goto(entryUrl);
  await pick(teen, "Sad", "3");
  await save(teen);
  await expect(teen.getByText("Saved.")).toBeVisible();
  await teen.getByText("Saved versions (2)").click();
  await expect(teen.getByText(/Version 1 ·/)).toBeVisible();
});

test("caregiver card in Chinese, and an urge at the threshold opens Help", async () => {
  const { teen, carer, therapist } = w;
  // caregiver card: own emotions and responses, in zh-CN
  await carer.goto("/caregiver/diary/new");
  const saved = carer.waitForResponse(
    (r) => r.url().endsWith("/api/v1/me") && r.request().method() === "PATCH",
  );
  await carer.getByRole("radio", { name: "简体中文" }).first().click();
  await saved;
  await carer.reload();
  await pick(carer, "我以认可的方式回应", "经常");
  await pick(carer, "难过", "4");
  await carer.getByRole("button", { name: "保存记录" }).click();
  await expect(carer.getByText("已保存。")).toBeVisible();
  await expect(carer.getByRole("radiogroup", { name: "伤害自己的冲动" })).toHaveCount(0);

  // adolescent: urge at the placeholder threshold (7) -> Help; the entry is saved
  await teen.goto("/teen/diary/new");
  await pick(teen, "Urge to harm yourself", "8");
  await save(teen);
  await expect(teen).toHaveURL(/\/teen\/help$/);
  await teen.goto("/teen/diary");
  await expect(teen.getByRole("link", { name: /Entry for/ })).toHaveCount(2);

  await therapist.goto("/therapist/safety");
  await expect(therapist.getByText(w.teenAlias).first()).toBeVisible();
});

test("therapist review keeps each card separate", async () => {
  const { therapist } = w;
  await therapist.goto(`${w.familyUrl}/diary`);
  const teenPanel = therapist.getByTestId("diary-panel-adolescent");
  const carerPanel = therapist.getByTestId("diary-panel-caregiver");
  await expect(teenPanel.getByTestId("review-entry")).toHaveCount(2);
  await expect(carerPanel.getByTestId("review-entry")).toHaveCount(1);
  await expect(teenPanel.getByRole("img", { name: /Urges/ })).toBeVisible();
  await expect(carerPanel.getByRole("img", { name: /Urges/ })).toHaveCount(0);
  await expect(teenPanel).toContainText("TIPP skills: 1");
  await expect(teenPanel).toContainText(/Stopped sharing with/);
  await expect(carerPanel).toContainText("Often");
  await expect(carerPanel).not.toContainText("a calm walk");
});
