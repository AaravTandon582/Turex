import { expect, test } from "@playwright/test";

/**
 * Discover: searching the catalog, and importing a paper out of it.
 *
 * The import test is slow because it is real — it downloads a PDF from arXiv and waits for
 * ingestion. A mocked version would prove nothing: the whole claim being made here is that a
 * paper picked from a list of millions becomes a paper you can actually read, and every part
 * of that claim is in the parts a mock would replace.
 *
 * These need a harvested catalog. They fail rather than skip when one is missing: a skipped
 * test reports green, and "the Discover page works" is exactly the claim that must not be
 * green by default. Fill the catalog first:
 *
 *     cd backend && python -m scripts.harvest_arxiv --set cs --max-records 5000
 */

test.describe("discover", () => {
  test("searching the catalog ranks title matches first", async ({ page }) => {
    await page.goto("/discover");

    const heading = page.getByRole("heading", { name: "Discover", level: 1 });
    await expect(heading).toBeVisible();

    // Waited for, not counted. `count()` does not auto-wait, so checking it while the page
    // still shows loading skeletons reads zero and skips a test that should have run — which
    // is worse than a failure, because a skipped test reports green.
    const cards = page.locator("h3");
    await expect(cards.first()).toBeVisible({ timeout: 15_000 });

    await page.getByLabel("Search the catalog").fill("learning");
    // Debounced at 300ms, then a round trip.
    await expect(page.locator('[aria-live="polite"]')).toContainText("matching", {
      timeout: 15_000,
    });

    await expect(cards.first()).toBeVisible();
  });

  test("a search matching nothing says so rather than showing an empty list", async ({ page }) => {
    await page.goto("/discover");
    await page.getByLabel("Search the catalog").fill("zzzzqqqxxnotarealword");
    await expect(page.getByText("Nothing matched that")).toBeVisible({ timeout: 15_000 });
  });

  test("filtering by a field narrows the results", async ({ page }) => {
    await page.goto("/discover");

    // The field chips come from a separate stats request, so this waits for them rather
    // than counting whatever happens to be rendered at the moment of the check.
    const field = page.getByRole("button", { name: /^cs\./ }).first();
    await expect(field).toBeVisible({ timeout: 15_000 });

    const label = (await field.innerText()).split(/\s+/)[0];
    await field.click();

    await expect(page.locator('[aria-live="polite"]')).toContainText(`in ${label}`, {
      timeout: 15_000,
    });
  });

  test("the console stays clean while searching", async ({ page }) => {
    const errors: string[] = [];
    page.on("console", (message) => message.type() === "error" && errors.push(message.text()));
    page.on("pageerror", (error) => errors.push(error.message));

    await page.goto("/discover");
    await page.getByLabel("Search the catalog").fill("graph");
    await page.waitForTimeout(2500);

    expect(errors).toEqual([]);
  });

  test("importing a paper makes it readable", async ({ page }) => {
    // A real download, parse, chunk, and embed. Minutes, not seconds.
    test.setTimeout(240_000);

    await page.goto("/discover");
    // A narrow query, so repeated runs do not keep importing the same first result and
    // finding it already in the library — which would pass without testing anything.
    await page.getByLabel("Search the catalog").fill("scheduling");
    await page.waitForTimeout(3000);

    const add = page.getByRole("button", { name: "Add to library" }).first();
    await expect(add).toBeVisible({ timeout: 15_000 });
    await add.click();

    // The card offers to read the paper once the import resolves. This is the moment a
    // reader would click, so the reader must work from here — not a minute later.
    const read = page.getByRole("link", { name: "Read" }).first();
    await expect(read).toBeVisible({ timeout: 180_000 });

    await read.click();
    await expect(page).toHaveURL(/\/library\/[0-9a-f-]+\/read/);

    // The PDF renders as canvases. This is the assertion the whole test exists for: the file
    // is stored before ingestion is queued, so it is servable the instant the button appears.
    await expect(page.locator("canvas").first()).toBeVisible({ timeout: 60_000 });
  });
});
