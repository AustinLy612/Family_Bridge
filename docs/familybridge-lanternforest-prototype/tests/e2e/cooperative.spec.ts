import { expect, test } from "@playwright/test";

test("adolescent and caregiver join from separate browser contexts", async ({ browser }) => {
  const adolescentContext = await browser.newContext();
  const caregiverContext = await browser.newContext();
  const adolescent = await adolescentContext.newPage();
  const caregiver = await caregiverContext.newPage();

  await adolescent.goto("/");
  await adolescent.getByRole("button", { name: /Play as Adolescent/i }).click();
  await adolescent.getByRole("button", { name: "Create room" }).click();
  const code = (await adolescent.locator(".room-code-display strong").innerText()).trim();
  expect(code).toMatch(/^[A-Z]{4}$/);

  await caregiver.goto("/");
  await caregiver.getByRole("button", { name: /Play as Caregiver/i }).click();
  await caregiver.getByLabel("Four-letter room code").fill(code);
  await caregiver.getByRole("button", { name: "Join room" }).click();

  await expect(adolescent.getByText("Present · confirming")).toHaveCount(2);
  await Promise.all([
    adolescent.getByRole("button", { name: "Confirm participation" }).click(),
    caregiver.getByRole("button", { name: "Confirm participation" }).click(),
  ]);

  await expect(adolescent.getByText("Private clue · adolescent view")).toBeVisible();
  await expect(caregiver.getByText("Private clue · caregiver view")).toBeVisible();
  await expect(adolescent.getByText(/spark stone/)).toHaveCount(0);
  await expect(caregiver.getByText(/failed attempt will feel unbearable/)).toHaveCount(0);

  await adolescentContext.close();
  await caregiverContext.close();
});
