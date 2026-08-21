import { expect, test } from "@playwright/test";

/**
 * Every screen, on a desktop and on a phone.
 *
 * Deliberately shallow: this asserts that each page renders something, says something, and
 * does not spill off the side of a phone. Depth belongs in the API suite, which can check what
 * a page *means* far more precisely than a browser can.
 *
 * The value is coverage of the thing type-checking cannot see — that a page runs at all.
 */

const PAGES = [
  "/dashboard",
  "/library",
  "/discover",
  "/search",
  "/projects",
  "/workstation",
  "/notebook",
  "/graph",
  "/study",
  "/assistant",
] as const;

test.describe("every page", () => {
  for (const path of PAGES) {
    test(`${path} renders without console errors`, async ({ page }) => {
      const errors: string[] = [];
      page.on("console", (message) => message.type() === "error" && errors.push(message.text()));
      page.on("pageerror", (error) => errors.push(error.message));
      await page.goto(path);
      await page.waitForLoadState("networkidle");

      const body = await page.locator("body").innerText();
      expect(body.trim().length, `${path} rendered almost nothing`).toBeGreaterThan(80);
      expect(errors, errors.join("\n")).toHaveLength(0);
    });

    test(`${path} does not scroll sideways on a phone`, async ({ page }) => {
      await page.setViewportSize({ width: 390, height: 844 });
      await page.goto(path);
      await page.waitForLoadState("networkidle");

      // A page wider than the viewport is the classic responsive failure: everything looks
      // fine until a table or a fixed-width panel pushes the whole layout sideways.
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow, `${path} overflows by ${overflow}px`).toBeLessThanOrEqual(4);
    });
  }
});

test.describe("the notebook", () => {
  test("renders Markdown, LaTeX, tables, and code — the things it promises", async ({ page }) => {
    await page.goto("/notebook");

    // Open a note, creating one if the account has none. The list loads asynchronously, so
    // this waits for it rather than checking a count that is zero simply because the request
    // has not come back yet — which is what made this fail intermittently.
    const notes = page.locator("nav[aria-label='Notes'] button");
    await page.waitForLoadState("networkidle");
    if ((await notes.count()) === 0) {
      await page.getByRole("button", { name: /new note/i }).click();
    } else {
      await notes.first().click();
    }

    const body = page.getByLabel("Note content");
    await expect(body).toBeVisible();
    await body.fill(
      "# Rendered heading\n\nInline $E = mc^2$.\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n```python\nprint('x')\n```",
    );

    await page.getByRole("tab", { name: "read" }).click();

    await expect(page.getByRole("heading", { name: "Rendered heading" })).toBeVisible();
    await expect(page.locator("table")).toBeVisible();
    await expect(page.locator(".katex").first()).toBeVisible();
    await expect(page.locator("pre code")).toBeVisible();
  });
});
