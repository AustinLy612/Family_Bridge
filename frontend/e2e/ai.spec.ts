/**
 * Phase 4 E2E: the admin AI-layer status page against the real API. Read-only; it shows counts
 * and codes only, never participant text or AI output.
 */
import { expect, test } from "@playwright/test";
import { demoAdmin, signIn } from "./helpers";

test("admin sees the AI layer status, read-only", async ({ page }) => {
  const admin = demoAdmin();
  await signIn(page, admin.username, admin.password);
  await page.getByRole("link", { name: "AI layer" }).click();
  await expect(page).toHaveURL(/\/admin\/ai$/);
  await expect(page.getByRole("heading", { name: "AI layer", level: 1 })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Provider" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Prompts" })).toBeVisible();
  await expect(page.getByText(/\d+ prompts in use/)).toBeVisible();
  await expect(page.getByRole("button", { name: /run|delete|regenerate/i })).toHaveCount(0);
});
