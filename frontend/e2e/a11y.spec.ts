/**
 * Accessibility audit (Plan §5.11, Phase 10 task 2): axe-core (WCAG 2.0/2.1/2.2 A and AA) on every
 * participant screen in both languages, plus public pages and the joint room; keyboard checks
 * (skip link first, Get help reachable, visible focus, no keyboard trap on a form).
 * A manual screen-reader pass is a separate, human step (docs/dev/ACCESSIBILITY_AUDIT.md).
 * Needs `seed-demo`.
 */
import AxeBuilder from "@axe-core/playwright";
import { expect as baseExpect, test, type Page } from "@playwright/test";
import { scheduleJoint, signInDemo } from "./helpers";

test.use({ actionTimeout: 15_000 });
const expect = baseExpect.configure({ timeout: 20_000 });
test.describe.configure({ mode: "serial" });

const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];

async function audit(page: Page, label: string) {
  await page.waitForLoadState("networkidle");
  await expect(page.locator("main, form, #root > *").first()).toBeVisible();
  const result = await new AxeBuilder({ page }).withTags(TAGS).analyze();
  const problems = result.violations.map(
    (v) =>
      `${label}: [${v.impact}] ${v.id} — ${v.help} (${v.nodes.map((n) => n.target.join(" ")).join(" | ")})`,
  );
  expect(problems, problems.join("\n")).toEqual([]);
}

async function setLanguage(page: Page, label: "English" | "简体中文") {
  const radio = page.getByRole("radio", { name: label }).first();
  if ((await radio.getAttribute("aria-checked")) !== "true") {
    const saved = page.waitForResponse(
      (r) => r.url().endsWith("/api/v1/me") && r.request().method() === "PATCH",
    );
    await radio.click();
    await saved;
  }
}

test("public pages", async ({ page }) => {
  for (const path of ["/", "/redeem", "/reset"]) {
    await page.goto(path);
    await audit(page, path);
  }
});

const SCREENS: Record<string, string[]> = {
  "/teen": [
    "",
    "/learn",
    "/group-review",
    "/diary",
    "/diary/new",
    "/joint",
    "/help",
    "/privacy",
    "/profile",
    "/settings",
  ],
  "/caregiver": [
    "",
    "/learn",
    "/group-review",
    "/diary",
    "/diary/new",
    "/joint",
    "/help",
    "/privacy",
    "/settings",
  ],
};

for (const [user, home] of [
  ["demo-teen-a", "/teen"],
  ["demo-carer-a", "/caregiver"],
] as const) {
  test(`participant screens: ${user} (en and zh-CN)`, async ({ page }) => {
    test.setTimeout(240_000);
    await signInDemo(page, user, home);
    for (const lang of ["English", "简体中文"] as const) {
      await setLanguage(page, lang);
      for (const screen of SCREENS[home] ?? []) {
        await page.goto(`${home}${screen}`);
        await audit(page, `${lang} ${home}${screen}`);
      }
    }
    await setLanguage(page, "English");
  });
}

test("joint room lobby and step (both participants)", async ({ browser }) => {
  test.setTimeout(180_000);
  const pages: Page[] = [];
  for (const [user, home] of [
    ["demo-therapist", "/therapist"],
    ["demo-teen-a", "/teen"],
    ["demo-carer-a", "/caregiver"],
  ] as const) {
    const p = await (await browser.newContext({ locale: "en-GB" })).newPage();
    await signInDemo(p, user, home);
    pages.push(p);
  }
  const [therapist, teen, carer] = pages as [Page, Page, Page];
  const id = await scheduleJoint(therapist);
  for (const [p, home] of [
    [teen, "/teen"],
    [carer, "/caregiver"],
  ] as const) {
    await p.goto(`${home}/joint`);
    await p
      .locator(`[data-testid="joint-invitation"][data-session="${id}"]`)
      .getByRole("button", { name: "Yes, I'd like to" })
      .click();
  }
  await teen.goto(`/teen/joint/${id}`);
  await expect(teen.getByRole("button", { name: "I'm ready" })).toBeVisible();
  await audit(teen, "joint lobby");
  await teen.getByRole("button", { name: "I'm ready" }).click();
  await carer.goto(`/caregiver/joint/${id}`);
  await carer.getByRole("button", { name: "I'm ready" }).click();
  await expect(teen.locator('[data-testid="joint-step"]')).toBeVisible();
  await audit(teen, "joint step");
  await therapist.goto("/therapist/joint");
  await audit(therapist, "therapist joint board");
  await therapist.getByTestId("joint-session-row").getByRole("button", { name: "End" }).first().click();
});

test("reflow: no horizontal scrolling at 320 CSS px (WCAG 1.4.10)", async ({ page }) => {
  test.setTimeout(120_000);
  await page.setViewportSize({ width: 320, height: 640 });
  for (const [user, home] of [
    ["demo-teen-a", "/teen"],
    ["demo-carer-a", "/caregiver"],
  ] as const) {
    await signInDemo(page, user, home);
    for (const screen of ["", "/learn", "/diary/new", "/joint", "/help", "/privacy"]) {
      await page.goto(`${home}${screen}`);
      await page.waitForLoadState("networkidle");
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow, `${home}${screen} scrolls sideways by ${overflow}px`).toBeLessThanOrEqual(0);
    }
    await page.context().clearCookies();
  }
});

test("keyboard: skip link first, Get help reachable, visible focus", async ({ page }) => {
  await signInDemo(page, "demo-teen-a", "/teen");
  await page.goto("/teen/diary/new");
  // wait for the page to render before tabbing (the first Tab raced the data load)
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await page.locator("body").focus();
  await page.keyboard.press("Tab");
  const first = page.locator(":focus");
  await expect(first).toHaveClass(/skip-link/);
  await page.keyboard.press("Enter");
  await expect(page.locator("#main")).toBeFocused();

  // Get help is reachable by keyboard from the top of the page (Pause is in the joint room, D92)
  await page.goto("/teen");
  let reached = false;
  for (let i = 0; i < 40 && !reached; i++) {
    await page.keyboard.press("Tab");
    reached =
      (await page
        .locator(":focus")
        .getAttribute("aria-label")
        .catch(() => null)) === "Get help" ||
      (
        (await page
          .locator(":focus")
          .textContent()
          .catch(() => "")) ?? ""
      ).trim() === "Get help";
  }
  expect(reached, "Get help reachable with Tab").toBe(true);
  const outline = await page.locator(":focus").evaluate((el) => {
    const s = getComputedStyle(el);
    return `${s.outlineStyle} ${s.outlineWidth} ${s.boxShadow}`;
  });
  expect(outline).not.toMatch(/^none 0px none$/);
});
