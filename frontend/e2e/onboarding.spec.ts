/**
 * Phase 1 E2E: onboarding per role (Plan §7.1).
 * admin → therapist code → therapist redeems → group, family, teen + caregiver codes →
 * each participant redeems in their own browser, cannot skip onboarding, completes it
 * separately, and sees who can see their data. Fictional data only; unique names per run.
 */
import { expect, test } from "@playwright/test";
import { RUN, completeOnboarding, demoAdmin, english, readCode, redeem, signIn, signOut } from "./helpers";

test("onboarding for every role, end to end", async ({ page, browser }) => {
  const admin = demoAdmin();

  // Admin issues a therapist code.
  await signIn(page, admin.username, admin.password);
  await expect(page).toHaveURL(/\/portal$/);
  await page.getByRole("link", { name: "Open Administration" }).click();
  await expect(page).toHaveURL(/\/admin$/);
  await page.getByRole("button", { name: "New therapist code" }).click();
  const therapistCode = await readCode(page);
  await signOut(page);

  // Therapist redeems (staff skip participant consent), creates a group and a family.
  const tPage = await redeem(browser, therapistCode, `e2e-t-${RUN}`, `Dr E2E ${RUN}`);
  await expect(tPage).toHaveURL(/\/portal$/);
  await tPage.getByRole("link", { name: "Open Family Bridge" }).click();
  await expect(tPage).toHaveURL(/\/therapist$/);
  await tPage.getByLabel("New group name").fill(`E2E group ${RUN}`);
  await tPage.getByRole("button", { name: "Create" }).click();
  await tPage.getByRole("link", { name: new RegExp(`E2E group ${RUN}`) }).click();
  await tPage.getByLabel("New family label").fill(`E2E family ${RUN}`);
  await tPage.getByRole("button", { name: "Create" }).click();
  await tPage.getByRole("link", { name: new RegExp(`E2E family ${RUN}`) }).click();

  await tPage.getByLabel("Account type").selectOption("adolescent");
  await tPage.getByRole("button", { name: "Generate code" }).click();
  const teenCode = await readCode(tPage);
  // Only one teen per family: the option disappears.
  await expect(tPage.getByLabel("Account type").locator("option")).toHaveCount(1);
  await tPage.getByLabel("Relationship (optional)").fill("aunt");
  await tPage.getByRole("button", { name: "Generate code" }).click();
  const carerCode = await readCode(tPage);

  // Each participant onboards separately, in their own browser.
  const teen = await redeem(browser, teenCode, `e2e-teen-${RUN}`, `Teen ${RUN}`);
  await completeOnboarding(teen, "/teen");
  const carer = await redeem(browser, carerCode, `e2e-carer-${RUN}`, `Carer ${RUN}`);
  await completeOnboarding(carer, "/caregiver");

  // A code works once only.
  const again = await browser.newPage();
  await again.goto("/redeem");
  await english(again);
  await again.getByLabel("Code").fill(teenCode);
  await again.getByRole("button", { name: "Continue" }).click();
  await expect(again.getByRole("alert")).toContainText("can't be used");

  // Transparency: the caregiver sees the real viewers; the teen is listed as family only.
  await carer.goto("/caregiver/settings");
  await carer.getByRole("link", { name: "View", exact: true }).click();
  const list = carer.getByRole("list", { name: "People and services that can see your data" });
  await expect(list).toContainText(`Dr E2E ${RUN} (Therapist)`);
  await expect(list).toContainText(`Teen ${RUN} (Teen)`);

  // The therapist sees both members as onboarded and can record suitability.
  await tPage.reload();
  await expect(tPage.getByText("Onboarded", { exact: true })).toHaveCount(2);
  await tPage.getByLabel("Decision").selectOption("suitable");
  await tPage.getByRole("button", { name: "Save" }).last().click();
  await expect(tPage.getByText("Saved.")).toBeVisible();

  // A caregiver calling a staff API is refused by the server.
  const status = await carer.evaluate(async () => (await fetch("/api/v1/groups")).status);
  expect(status).toBe(403);
});
