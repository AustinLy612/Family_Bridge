/** Shared E2E helpers. Fictional data only; demo credentials come from git-ignored seed_output/. */
import { expect as baseExpect, type Browser, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const expect = baseExpect;
export const RUN = Date.now().toString(36);
export const PASSWORD = "e2e-calm-river-stone-42";

export function demoAccount(username: string): { username: string; password: string } {
  const file = resolve(dirname(fileURLToPath(import.meta.url)), "../../seed_output/demo_credentials.json");
  const data = JSON.parse(readFileSync(file, "utf-8")) as {
    accounts: { username: string; password: string; role: string }[];
  };
  const account = data.accounts.find((a) => a.username === username);
  if (!account) throw new Error("run `python -m app.cli seed-demo` first");
  return account;
}

export const demoAdmin = () => demoAccount("demo-admin");

export async function english(page: Page) {
  await page.getByRole("radio", { name: "English" }).click();
}

export async function signIn(page: Page, username: string, password: string) {
  await page.goto("/");
  await english(page);
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
}

/** From the Portal (D95), open a module by its card's main link, e.g. "Family Bridge". */
export async function openModule(
  page: Page,
  module: "Family Bridge" | "Personal Learning" | "Administration",
) {
  await page.getByRole("link", { name: `Open ${module}` }).click();
}

export async function signOut(page: Page) {
  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
}

export async function readCode(page: Page): Promise<string> {
  const code = (await page.locator(".fb-code__value").textContent())?.trim() ?? "";
  expect(code).toMatch(/^[A-Z0-9]{4}(-[A-Z0-9]{4}){3}$/);
  await page.getByRole("button", { name: "I've noted it" }).click();
  await expect(page.locator(".fb-code__value")).toHaveCount(0);
  return code;
}

export async function redeem(browser: Browser, code: string, username: string, alias: string) {
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  await page.goto("/redeem");
  await english(page);
  await page.getByLabel("Code").fill(code.toLowerCase().replaceAll("-", " "));
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByLabel("Choose a username").fill(username);
  await page.getByLabel("Display name").fill(alias);
  await page.getByLabel("New password").fill(PASSWORD);
  await page.getByLabel("Type the password again").fill(PASSWORD);
  await page.getByRole("button", { name: "Create account" }).click();
  return page;
}

export async function completeOnboarding(page: Page, home: string) {
  await expect(page).toHaveURL(/\/onboarding$/);
  // Cannot be skipped: going to the home screen bounces back to onboarding.
  await page.goto(home);
  await expect(page).toHaveURL(/\/onboarding$/);
  await expect(page.getByText("not a crisis service")).toBeVisible();
  const research = page.getByRole("switch", { name: /Help improve FamilyBridge/ });
  await expect(research).toBeVisible();
  await expect(research).toHaveAttribute("aria-checked", "true"); // D32
  // Declining a required item does not complete onboarding.
  await page.getByRole("button", { name: "Agree and continue" }).click();
  await expect(page.getByRole("alert")).toContainText("talk to your therapist");
  await expect(page).toHaveURL(/\/onboarding$/);
  for (const name of [
    "Using FamilyBridge",
    "My group therapist can see my records",
    "AI-generated content",
  ]) {
    await page.getByRole("checkbox", { name }).check();
  }
  await page.getByRole("button", { name: "Agree and continue" }).click();
  // everyone lands on the shared Portal (D95); the role's screens keep their URLs
  await expect(page).toHaveURL(/\/portal$/);
  await expect(page.getByRole("link", { name: "Get help" })).toBeVisible();
  await page.goto(home);
}

/**
 * Sign in as a seeded demo account, switch it to English and finish first-run onboarding. Sign-in
 * lands on the Portal (D95); the helper then opens `home` so specs start on the role's screens.
 */
export async function signInDemo(page: Page, username: string, home: string) {
  const account = demoAccount(username);
  await signIn(page, account.username, account.password);
  await page.waitForURL(/\/(onboarding|portal|teen|caregiver|therapist|admin)(\/|$)/);
  if ((await page.locator("html").getAttribute("lang")) !== "en") {
    // demo accounts are saved in Chinese; the switch is stored on the account (ServerPrefsSync)
    const saved = page.waitForResponse(
      (r) => r.url().endsWith("/api/v1/me") && r.request().method() === "PATCH",
    );
    await page.getByRole("radio", { name: "English" }).first().click();
    await saved;
  }
  if (page.url().endsWith("/onboarding")) {
    // first sign-in of a demo participant: accept the required items (consent text is content)
    await page.getByRole("checkbox").first().waitFor();
    for (const box of await page.getByRole("checkbox").all()) await box.check();
    await page.getByRole("button", { name: "Agree and continue" }).click();
  }
  await page.waitForURL(/\/portal$/);
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await expect(page.getByRole("heading", { level: 1, name: "Portal" })).toBeVisible();
  if (home !== "/portal") await page.goto(home);
}

/**
 * As demo-therapist on the joint board: withdraw or end every open session from earlier runs,
 * then invite Family A (demo) to the placeholder episode. Returns the new session id.
 */
export async function scheduleJoint(page: Page): Promise<string> {
  await page.goto("/therapist/joint");
  await expect(page.getByRole("heading", { name: "Invite a pair" })).toBeVisible();
  const open = page.getByTestId("joint-session-row").getByRole("button", { name: /^(Withdraw|End)$/ });
  for (let n = await open.count(); n > 0; n = await open.count()) {
    await open.first().click();
    await expect(open).toHaveCount(n - 1);
  }
  await page.getByLabel("Family", { exact: true }).selectOption({ label: "Family A (demo)" });
  await page.getByLabel("Activity", { exact: true }).selectOption("demo-stub-episode@1");
  const created = page.waitForResponse(
    (r) => /\/joint-sessions$/.test(r.url()) && r.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Send invitation" }).click();
  const body = (await (await created).json()) as { id: string };
  await expect(page.getByText("Invitation sent.")).toBeVisible();
  return body.id;
}
