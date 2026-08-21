import { expect, test } from "@playwright/test";

import pkg from "../package.json";
import { PYODIDE_VERSION } from "../src/lib/python-runtime";

/**
 * The workstation: Python running in the browser.
 *
 * These are slow because they are real. The interpreter is 13MB of WebAssembly and the science
 * packages another sixty, fetched once per browser — a mocked version would assert nothing,
 * because the claim being tested is precisely that a person can type numpy into this page and
 * get a number back.
 */

test.describe("the workstation", () => {
  test("the vendored runtime and the package CDN are the same version", () => {
    // A mismatch fetches wheels built against a different ABI, which fails at import with an
    // error that never mentions versions. Cheaper to catch here than to debug there.
    expect(PYODIDE_VERSION).toBe(pkg.dependencies.pyodide.replace(/^[^0-9]*/, ""));
  });

  test("the page offers somewhere to write code", async ({ page }) => {
    await page.goto("/workstation");
    await expect(page.getByRole("heading", { name: "Workstation", level: 1 })).toBeVisible();

    await page.getByRole("button", { name: "New analysis" }).click();
    await expect(page.locator('[data-editor="python"]').first()).toBeVisible({ timeout: 15_000 });

    // The starter cell is a working example rather than a comment, because the first question
    // a computational notebook has to answer is whether it actually runs.
    await expect(page.locator(".cm-content").first()).toContainText("numpy");
  });

  test("running a cell computes a real answer", async ({ page }) => {
    // The interpreter and its packages are downloaded on first use.
    test.setTimeout(300_000);

    await page.goto("/workstation");
    await page.getByRole("button", { name: "New analysis" }).click();

    const editor = page.locator('[data-editor="python"] .cm-content').first();
    await expect(editor).toBeVisible({ timeout: 15_000 });
    await editor.click();
    await page.keyboard.press("ControlOrMeta+a");
    await page.keyboard.press("Delete");
    await editor.pressSequentially("print(6 * 7)", { delay: 5 });

    // Ctrl/Cmd-Enter is the shortcut every notebook has and the one people try first.
    await page.keyboard.press("ControlOrMeta+Enter");

    await expect(page.locator("pre").first()).toContainText("42", { timeout: 280_000 });
  });

  test("an error shows the traceback, without the harness in it", async ({ page }) => {
    test.setTimeout(300_000);

    await page.goto("/workstation");
    await page.getByRole("button", { name: "New analysis" }).click();

    const editor = page.locator('[data-editor="python"] .cm-content').first();
    await expect(editor).toBeVisible({ timeout: 15_000 });
    await editor.click();
    await page.keyboard.press("ControlOrMeta+a");
    await page.keyboard.press("Delete");
    await editor.pressSequentially("1 / 0", { delay: 5 });
    await page.keyboard.press("ControlOrMeta+Enter");

    await expect(page.getByText("ZeroDivisionError")).toBeVisible({ timeout: 280_000 });

    // The frames belonging to the runner are trimmed, so the traceback is about the reader's
    // own code — the only part they can act on.
    await expect(page.locator("body")).not.toContainText("__atlas_run");
  });

  test("editing a cell that has run marks it stale", async ({ page }) => {
    test.setTimeout(300_000);

    await page.goto("/workstation");
    await page.getByRole("button", { name: "New analysis" }).click();

    const editor = page.locator('[data-editor="python"] .cm-content').first();
    await expect(editor).toBeVisible({ timeout: 15_000 });
    await editor.click();
    await page.keyboard.press("ControlOrMeta+a");
    await page.keyboard.press("Delete");
    await editor.pressSequentially("print(1)", { delay: 5 });
    await page.keyboard.press("ControlOrMeta+Enter");
    await expect(page.locator("pre").first()).toContainText("1", { timeout: 280_000 });

    // The output now says 1 while the code says 2. Presenting that as current is how a wrong
    // number reaches a write-up, so the cell has to say so.
    await editor.click();
    await page.keyboard.press("ControlOrMeta+a");
    await page.keyboard.press("Delete");
    await editor.pressSequentially("print(2)", { delay: 5 });

    await expect(page.getByText("Stale")).toBeVisible({ timeout: 20_000 });
  });
});
