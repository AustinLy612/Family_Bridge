/**
 * End-to-end tests (Plan §7.1). They run against a live stack:
 *   - default: the Vite dev server (http://localhost:5173), which proxies /api to the API on :8000;
 *   - or set E2E_BASE_URL, e.g. http://localhost:8080 for the docker compose web container.
 * The database must be migrated and seeded (`python -m app.cli seed-demo`); the tests sign in
 * with the demo admin from the git-ignored seed_output/ file and create everything else.
 */
import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:5173",
    locale: "en-GB",
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
