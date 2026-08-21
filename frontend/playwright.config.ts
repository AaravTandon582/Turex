import { defineConfig, devices } from "@playwright/test";

/**
 * Browser tests, kept apart from the unit suite.
 *
 * They need both servers running and the seeded demo account, so they are not part of
 * `npm test` — a test that cannot run on a fresh checkout without setup gets skipped, then
 * rots. Run them deliberately with `npm run e2e`; `docs/development.md` says what has to be up.
 *
 * A setup project signs in once and every test reuses that session. Signing in per test meant
 * eighteen logins a minute, which the account's own rate limit refused — correctly.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  timeout: 90_000,
  expect: { timeout: 20_000 },
  reporter: [["list"]],
  use: {
    baseURL: process.env.TUREX_WEB_URL ?? "http://localhost:3000",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  projects: [
    { name: "setup", testMatch: /auth\.setup\.ts/ },
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"], storageState: "e2e/.session.json" },
      dependencies: ["setup"],
    },
  ],
});
