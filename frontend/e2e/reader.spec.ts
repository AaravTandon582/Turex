import { expect, test, type Page } from "@playwright/test";

/**
 * The parts of Turex that only exist in a browser.
 *
 * Everything else is covered by the API suite, which is faster and more precise. These cover
 * what it structurally cannot: whether the PDF actually paints, whether text can be selected
 * out of it, and whether a highlight survives the round trip. That gap was open for most of
 * this project's life, and it is exactly where a live demo breaks.
 *
 * Two things found on the first run: the PDF options object was rebuilt on every render, so
 * `react-pdf` reloaded the document and warned about it, and the equations and references
 * panels had never been rendered at all.
 */

async function openFirstPaperInReader(page: Page) {
  await page.goto("/library");
  await page.locator('a[href^="/library/"]').first().click();
  await page.waitForURL(/\/library\/[^/]+$/);
  await page.goto(`${page.url().replace(/\/$/, "")}/read`);
  // The canvas paints first and the text layer follows, so both are waited for — counting
  // spans the moment a canvas appears finds none, which looked like a missing text layer.
  await expect(page.locator("canvas").first()).toBeVisible({ timeout: 45_000 });
  await expect(page.locator("[class*='textLayer'] span").first()).toBeAttached({
    timeout: 45_000,
  });
}

/**
 * Select a few words near the start of the document.
 *
 * Done through the DOM because Playwright's drag does not reliably produce a range across the
 * absolutely-positioned spans a PDF text layer is made of. The mouseup must originate inside
 * the page container: the handler is there, and an event dispatched on `document` never
 * reaches it.
 */
async function selectEarlyText(page: Page) {
  await page.evaluate(() => {
    const spans = document.querySelectorAll("[class*='textLayer'] span");
    if (spans.length < 4) throw new Error("no text layer to select from");
    const range = document.createRange();
    range.setStart(spans[1].firstChild ?? spans[1], 0);
    range.setEnd(spans[3].firstChild ?? spans[3], (spans[3].textContent ?? "").length);
    const selection = window.getSelection();
    selection?.removeAllRanges();
    selection?.addRange(range);
    spans[3].dispatchEvent(new MouseEvent("mouseup", { bubbles: true, cancelable: true }));
  });
}

test.describe("the reader", () => {
  test("renders the PDF and its text layer", async ({ page }) => {
    await openFirstPaperInReader(page);

    expect(await page.locator("canvas").count()).toBeGreaterThan(0);
    // Without a text layer there is no selection, so no highlighting and no ask-about-this.
    expect(await page.locator("[class*='textLayer'] span").count()).toBeGreaterThan(100);
  });

  test("every sidebar panel renders", async ({ page }) => {
    await openFirstPaperInReader(page);

    for (const name of ["Outline", "Highlights", "Maths", "Refs", "Cite"]) {
      await page.getByRole("tab", { name }).click();
      // Either content or a stated empty state — never a blank panel.
      await expect(page.locator("main, aside").last()).not.toBeEmpty();
    }
  });

  test("selecting text offers to highlight it, and the highlight is saved", async ({ page }) => {
    await openFirstPaperInReader(page);

    await selectEarlyText(page);

    const swatch = page.locator('button[aria-label^="Highlight as"]').first();
    await expect(swatch).toBeVisible();
    await swatch.click();

    await page.getByRole("tab", { name: "Highlights" }).click();
    await expect(page.getByText(/no highlights/i)).toHaveCount(0);
  });

  test("the selection menu stays inside the page, and clickable", async ({ page }) => {
    await openFirstPaperInReader(page);

    // The regression this pins: the menu is centred on the selection and is about 410px wide,
    // so a selection near the left margin — where most lines start — put half of it outside
    // the page and underneath the sidebar. It still looked right, because the visible half was
    // the half over the text; what failed was clicking, since the sidebar sits above and
    // swallowed the press. The symptom was a highlight button that did nothing, on some
    // selections and not others.
    await selectEarlyText(page);

    const swatch = page.locator('button[aria-label^="Highlight as"]').first();
    await expect(swatch).toBeVisible();

    const geometry = await page.evaluate(() => {
      const button = document.querySelector<HTMLElement>('button[aria-label^="Highlight as"]');
      const menu = button?.closest<HTMLElement>('[role="toolbar"]');
      const pageBox = menu?.closest<HTMLElement>("[data-page]");
      if (!button || !menu || !pageBox) throw new Error("the selection menu is not on a page");

      const menuRect = menu.getBoundingClientRect();
      const pageRect = pageBox.getBoundingClientRect();
      const buttonRect = button.getBoundingClientRect();
      const hit = document.elementFromPoint(
        buttonRect.left + buttonRect.width / 2,
        buttonRect.top + buttonRect.height / 2,
      );

      return {
        overhangLeft: Math.round(pageRect.left - menuRect.left),
        overhangRight: Math.round(menuRect.right - pageRect.right),
        pressReachesTheButton: hit !== null && (hit === button || button.contains(hit)),
      };
    });

    expect(geometry.overhangLeft, "the menu hangs off the left of the page").toBeLessThanOrEqual(1);
    expect(geometry.overhangRight, "the menu hangs off the right of the page").toBeLessThanOrEqual(
      1,
    );
    expect(geometry.pressReachesTheButton, "something is covering the highlight button").toBe(true);

    await swatch.click();
    await page.getByRole("tab", { name: "Highlights" }).click();
    await expect(page.getByText(/no highlights/i)).toHaveCount(0);
  });

  test("the console stays clean", async ({ page }) => {
    const errors: string[] = [];
    page.on("console", (message) => message.type() === "error" && errors.push(message.text()));
    page.on("pageerror", (error) => errors.push(error.message));
    await openFirstPaperInReader(page);
    await page.waitForTimeout(2_000);

    expect(errors, errors.join("\n")).toHaveLength(0);
  });
});
