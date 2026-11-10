/**
 * Phase 2 E2E: safety core (Plan §5.7, §7.1).
 * A new therapist records a safety event by hand for a teen in their own family, then walks it
 * through acknowledge → resolve (follow-up required). The teen can reach the help screen from
 * the header, sees no safety events, and is refused by the queue API. The admin sees the event
 * read-only. The automated "safety stop" E2E lands with the first free-text feature (Phase 5/6).
 */
import { expect, test } from "@playwright/test";
import { RUN, completeOnboarding, demoAdmin, readCode, redeem, signIn, signOut } from "./helpers";

test("manual safety event, clinician workflow, participant help and admin oversight", async ({
  page,
  browser,
}) => {
  const admin = demoAdmin();
  await signIn(page, admin.username, admin.password);
  await page.getByRole("button", { name: "New therapist code" }).click();
  const therapistCode = await readCode(page);
  await signOut(page);

  const t = await redeem(browser, therapistCode, `e2e-st-${RUN}`, `Dr Safety ${RUN}`);
  await expect(t).toHaveURL(/\/therapist$/);
  await t.getByLabel("New group name").fill(`Safety group ${RUN}`);
  await t.getByRole("button", { name: "Create" }).click();
  await t.getByRole("link", { name: new RegExp(`Safety group ${RUN}`) }).click();
  await t.getByLabel("New family label").fill(`Safety family ${RUN}`);
  await t.getByRole("button", { name: "Create" }).click();
  await t.getByRole("link", { name: new RegExp(`Safety family ${RUN}`) }).click();
  await t.getByLabel("Account type").selectOption("adolescent");
  await t.getByRole("button", { name: "Generate code" }).click();
  const teenCode = await readCode(t);

  const teen = await redeem(browser, teenCode, `e2e-steen-${RUN}`, `Willow ${RUN}`);
  await completeOnboarding(teen, "/teen");

  // Help is one click away on every participant screen.
  await teen.getByRole("link", { name: "Get help" }).click();
  await expect(teen).toHaveURL(/\/teen\/help$/);
  await expect(teen.getByText("FamilyBridge is not monitored in real time.").first()).toBeVisible();
  await expect(teen.locator('a[href^="tel:"]').first()).toBeVisible();

  // Therapist records an event from a group session.
  await t.getByRole("link", { name: "Safety queue" }).click();
  await expect(t.getByText("No open safety events.")).toBeVisible();
  await t.getByLabel("Participant").selectOption({ label: `Willow ${RUN} (Teen) · Safety family ${RUN}` });
  await t.getByLabel("Type of event").selectOption("suspected_abuse");
  await t.getByLabel("Severity").selectOption("high");
  await t.getByLabel("What happened").fill("(e2e) Raised in group; follow up with the safeguarding lead.");
  await t.getByRole("button", { name: "Record event" }).click();
  await expect(t.getByRole("heading", { name: "Suspected abuse", level: 1 })).toBeVisible();
  await expect(t.getByText("(e2e) Raised in group")).toBeVisible();

  await t.getByRole("button", { name: "Acknowledge" }).click();
  await expect(t.getByRole("button", { name: "Start review" })).toBeVisible();
  const resolve = t.getByRole("button", { name: "Resolve" });
  await expect(resolve).toBeDisabled();
  await t.getByLabel("Follow-up action").fill("(e2e) Safeguarding lead informed; plan agreed.");
  await resolve.click();
  await expect(t.getByText("(e2e) Safeguarding lead informed; plan agreed.")).toBeVisible();
  await expect(t.getByRole("button", { name: "Resolve" })).toHaveCount(0);

  // The teen never sees safety events, even about themself.
  const status = await teen.evaluate(async () => (await fetch("/api/v1/safety/events")).status);
  expect(status).toBe(403);
  await expect(teen.getByText("Suspected abuse")).toHaveCount(0);

  // Admin oversight: read-only (D39).
  await signIn(page, admin.username, admin.password);
  await page.getByRole("link", { name: "Safety oversight" }).click();
  await page.getByRole("radio", { name: "Resolved" }).click();
  await page.getByRole("link", { name: new RegExp(`Suspected abuse · Willow ${RUN}`) }).click();
  await expect(page.getByText(/Read-only oversight view/)).toBeVisible();
  await expect(page.getByText("(e2e) Raised in group")).toBeVisible();
  await expect(page.getByRole("button", { name: "Acknowledge" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Save note" })).toHaveCount(0);
});
