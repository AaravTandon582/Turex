import { expect, test as setup } from "@playwright/test";

/**
 * Sign in once, and let every test reuse the session.
 *
 * Not only for speed. Signing in per test meant eighteen logins in a minute, which the
 * account's own rate limit correctly refused — the browser suite was unrunnable against a
 * correctly configured server. Reusing the session is how these tests should have been written
 * anyway: they are testing pages, not the login form, which has its own tests.
 */

const DEMO = { email: "demo@turex.dev", password: "turex-demo-account-2026" };
export const SESSION = "e2e/.session.json";

setup("authenticate", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel(/email/i).fill(DEMO.email);
  await page.getByLabel(/password/i).fill(DEMO.password);
  await page.getByRole("button", { name: /sign in/i }).click();

  await page.waitForURL("**/dashboard");
  await expect(page.getByText(/welcome back/i)).toBeVisible();

  await page.context().storageState({ path: SESSION });
});
