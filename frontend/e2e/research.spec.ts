/**
 * Research export and recruitment denominators (Plan §5.10, Phase 9). Needs `seed-demo`.
 * The admin previews and downloads the pseudonymous zip (including demo data, since the seed is
 * demo-only); the demo therapist records recruitment numbers for the demo group.
 */
import { readFileSync } from "node:fs";
import { inflateRawSync } from "node:zlib";
import { expect as baseExpect, test } from "@playwright/test";
import { signInDemo } from "./helpers";

test.use({ actionTimeout: 15_000 });
const expect = baseExpect.configure({ timeout: 20_000 });

/** Minimal zip reader (central directory), enough to read our own export. */
function unzip(buf: Buffer): Map<string, string> {
  const out = new Map<string, string>();
  const eocd = buf.lastIndexOf(Buffer.from([0x50, 0x4b, 0x05, 0x06]));
  const count = buf.readUInt16LE(eocd + 10);
  let p = buf.readUInt32LE(eocd + 16);
  for (let i = 0; i < count; i++) {
    const method = buf.readUInt16LE(p + 10);
    const size = buf.readUInt32LE(p + 20);
    const nameLen = buf.readUInt16LE(p + 28);
    const extra = buf.readUInt16LE(p + 30);
    const comment = buf.readUInt16LE(p + 32);
    const local = buf.readUInt32LE(p + 42);
    const name = buf.subarray(p + 46, p + 46 + nameLen).toString("utf-8");
    const start = local + 30 + buf.readUInt16LE(local + 26) + buf.readUInt16LE(local + 28);
    const raw = buf.subarray(start, start + size);
    out.set(name, (method === 8 ? inflateRawSync(raw) : raw).toString("utf-8"));
    p += 46 + nameLen + extra + comment;
  }
  return out;
}

test("admin downloads a pseudonymous export; files are split by role", async ({ page }) => {
  await signInDemo(page, "demo-admin", "/admin");
  await page.getByRole("link", { name: "Research export" }).click();
  await expect(page.getByText("separate folders")).toBeVisible();
  await expect(page.getByRole("link", { name: /Retention/ })).toHaveCount(0);
  await page.getByRole("checkbox", { name: "Include demo groups and accounts" }).check();
  await expect(page.getByTestId("export-adolescent")).toContainText("adolescent/participants.csv");

  const downloading = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download export" }).click();
  const download = await downloading;
  expect(download.suggestedFilename()).toMatch(/^familybridge-research-\d{4}-\d{2}-\d{2}\.zip$/);
  await expect(page.getByText(/^Export downloaded/)).toBeVisible();

  const files = unzip(readFileSync(await download.path()));
  expect([...files.keys()]).toEqual(
    expect.arrayContaining([
      "adolescent/participants.csv",
      "caregiver/participants.csv",
      "shared/joint_sessions.csv",
      "data_dictionary.csv",
    ]),
  );
  const data = [...files.entries()]
    .filter(([name]) => !["data_dictionary.csv", "event_types.csv", "README.txt"].includes(name))
    .map(([, text]) => text)
    .join("\n");
  for (const secret of ["demo-teen-a", "demo-carer-a", "Maple", "River", "Family A (demo)", "(demo) "]) {
    expect(data).not.toContain(secret);
  }
  expect(data).not.toMatch(/\d{2}:\d{2}:\d{2}/); // no times of day (D82)
  expect(files.get("adolescent/participants.csv")).not.toContain("caregiver");
});

test("therapist records recruitment numbers for the demo group", async ({ page }) => {
  await signInDemo(page, "demo-therapist", "/therapist");
  await page.goto("/therapist/metrics");
  await page.getByLabel("Period start").fill("2026-10-01");
  await page.getByLabel("Period end").fill("2026-10-31");
  for (const [label, value] of [
    ["Screened", "12"],
    ["Eligible", "9"],
    ["Approached", "8"],
    ["Consented", "5"],
  ] as const) {
    await page.getByLabel(label, { exact: true }).fill(value);
  }
  await page.getByRole("button", { name: "Save numbers" }).click();
  await expect(page.getByRole("main").getByText("Saved.")).toBeVisible();
  await expect(page.getByTestId("recruitment-table")).toContainText("2026-10-01 – 2026-10-31");
});
