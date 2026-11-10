/**
 * Phase 3 E2E: the admin knowledge-base status page against the real API. Works whether or not
 * the manual has been ingested on this machine (the manual is never committed, D7).
 * The page must never show manual text; the API test checks that against chunk text.
 */
import { expect, test } from "@playwright/test";
import { demoAdmin, signIn } from "./helpers";

test("admin sees the knowledge-base status, read-only", async ({ page }) => {
  const admin = demoAdmin();
  await signIn(page, admin.username, admin.password);
  await page.getByRole("link", { name: "Knowledge base" }).click();
  await expect(page).toHaveURL(/\/admin\/knowledge$/);
  await expect(page.getByRole("heading", { name: "Knowledge base", level: 1 })).toBeVisible();
  const active = page.getByRole("heading", { name: /Active version \d+/ });
  const empty = page.getByText(/The knowledge base is empty/);
  await expect(active.or(empty)).toBeVisible();
  if (await active.isVisible()) {
    await expect(page.getByRole("table", { name: "Chunks by module" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Page header checks" })).toBeVisible();
  }
  await expect(page.getByRole("button", { name: /ingest|delete|search/i })).toHaveCount(0);
});
