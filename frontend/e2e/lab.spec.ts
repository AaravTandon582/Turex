import { expect, test } from "@playwright/test";

/**
 * The lab notebook, and taking a project out of Turex.
 *
 * The notebook's whole value is that an entry cannot be changed after the fact, so what is
 * checked here is the promise the interface makes: it says so before you write, the entry's
 * hash is on screen where it can be copied out, and verification reports on the record as a
 * whole.
 */

test.describe("the lab notebook", () => {
  test("says an entry is permanent before it is written, not after", async ({ page }) => {
    await page.goto("/lab");
    await expect(page.getByRole("heading", { name: "Lab notebook", level: 1 })).toBeVisible();

    // Someone who expects to be able to edit writes differently from someone who knows they
    // cannot, which is why this belongs on the composer rather than in an error afterwards.
    await expect(page.getByText("cannot be changed or removed")).toBeVisible();
  });

  test("recording an entry shows it with its hash", async ({ page }) => {
    await page.goto("/lab");

    const unique = `Observation ${Date.now()}`;
    await page.getByLabel("Entry", { exact: true }).fill(`${unique}. Latency $= 18$ms.`);
    await page.getByRole("button", { name: "Record", exact: true }).click();

    await expect(page.getByText(unique, { exact: false })).toBeVisible({ timeout: 15_000 });

    // The maths is rendered, and the hash is on screen — evidence nobody can copy out and
    // check for themselves is not evidence.
    await expect(page.locator(".katex").first()).toBeVisible();
    await expect(page.locator("li").first().locator("p.font-mono")).toHaveText(/^[0-9a-f]{64}$/);
  });

  test("verification reports on the whole record", async ({ page }) => {
    await page.goto("/lab");
    await page.getByRole("button", { name: "Check the record" }).click();

    await expect(page.getByText(/verif|altered/i).first()).toBeVisible({ timeout: 20_000 });

    // The claim is bounded on purpose: the chain shows nothing was rewritten, and says
    // nothing about when anything was written.
    await expect(page.getByText("does not prove when anything was written")).toBeVisible();
  });

  test("a project exports as a folder of plain files", async ({ page }) => {
    await page.goto("/projects");

    // Waited for, not counted. `count()` does not auto-wait, so checking it while the list is
    // still loading reads zero and skips a test that should have run — and a skipped test
    // reports green, which is worse than a failure.
    const project = page.locator('a[href^="/projects/"]').first();
    await expect(project).toBeVisible({ timeout: 15_000 });
    await project.click();

    const download = page.waitForEvent("download", { timeout: 60_000 });
    await page.getByRole("link", { name: "Export the project" }).click();
    const file = await download;

    expect(file.suggestedFilename()).toMatch(/\.zip$/);
    expect(await file.path()).not.toBeNull();
  });
});
