import { expect, test, type Page } from "@playwright/test";

const notebook = {
  id: "analysis-1", title: "First analysis", description: null,
  project_id: null, experiment_id: null, last_run_at: null,
  created_at: "2026-01-01T00:00:00Z",
  cells: [{
    id: "cell-1", ordinal: 0, kind: "code", source: "print(0)",
    output: null, image: null, error: null, status: "idle",
    duration_ms: null, executed_at: null,
  }],
};

async function setup(page: Page, loadPython = false) {
  const current = structuredClone(notebook);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  if (!loadPython) await page.route("**/pyodide/**", (route) => route.abort());
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/auth/me")) {
      await route.fulfill({ json: {
        id: "user-1", full_name: "Test Researcher", email: "test@example.edu",
        created_at: "2026-01-01T00:00:00Z",
      } });
    } else if (path.endsWith("/analyses")) {
      await route.fulfill({ json: [current] });
    } else if (path.endsWith("/analyses/analysis-1")) {
      await route.fulfill({ json: current });
    } else {
      await route.fulfill({ json: [] });
    }
  });
  return { current, errors };
}

test("late autosave responses preserve newer typing", async ({ page }) => {
  const { current, errors } = await setup(page);
  let release!: () => void;
  const held = new Promise<void>((resolve) => { release = resolve; });
  const writes: string[] = [];
  await page.route("**/analyses/analysis-1/cells/cell-1", async (route) => {
    const source = route.request().postDataJSON().source as string;
    writes.push(source);
    if (writes.length === 1) await held;
    current.cells[0].source = source;
    await route.fulfill({ json: current.cells[0] });
  });
  await page.goto("/workstation");
  const editor = page.locator(".cm-content");
  await expect(editor).toHaveText("print(0)");
  await editor.fill("print(1)");
  await expect.poll(() => writes.length).toBe(1);
  await editor.fill("print(2)");
  release();
  await expect.poll(() => writes.at(-1)).toBe("print(2)");
  await expect(editor).toHaveText("print(2)");
  expect(errors).toEqual([]);
});

for (const action of ["Code", "Move cell 1 up", "Delete this analysis"]) {
  test(`failed ${action} displays an error without an unhandled rejection`, async ({ page }) => {
    const { errors } = await setup(page);
    await page.route("**/analyses/analysis-1**", async (route) => {
      if (route.request().method() === "GET") return route.fallback();
      await route.fulfill({ status: 503, json: {
        error: { code: "internal_error", message: "Please retry this operation." },
      } });
    });
    await page.goto("/workstation");
    await expect(page.locator(".cm-content")).toBeVisible();
    await page.getByRole("button", { name: action, exact: true }).click();
    await expect(page.getByRole("alert").filter({ hasText: "Please retry this operation." })).toBeVisible();
    expect(errors).toEqual([]);
  });
}

test("a rejected title save is visible", async ({ page }) => {
  const { errors } = await setup(page);
  await page.route("**/analyses/analysis-1", async (route) => {
    if (route.request().method() !== "PATCH") return route.fallback();
    await route.fulfill({ status: 422, json: {
      error: { code: "validation_failed", message: "Give the analysis a title." },
    } });
  });
  await page.goto("/workstation");
  await page.getByRole("textbox", { name: "Analysis title" }).fill("");
  await page.getByRole("textbox", { name: "Analysis title" }).press("Tab");
  await expect(page.getByRole("alert").filter({ hasText: "Give the analysis a title." })).toBeVisible();
  expect(errors).toEqual([]);
});

test("deleting the last analysis does not reopen it", async ({ page }) => {
  const { errors } = await setup(page);
  let deleted = false;
  let readsAfterDelete = 0;
  await page.route("**/analyses/analysis-1", async (route) => {
    if (route.request().method() === "DELETE") {
      deleted = true;
      return route.fulfill({ status: 204 });
    }
    if (deleted) readsAfterDelete++;
    return route.fallback();
  });
  await page.goto("/workstation");
  await page.getByRole("button", { name: "Delete this analysis" }).click();
  await expect(page.getByText("No analysis open", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "First analysis" })).toHaveCount(0);
  expect(readsAfterDelete).toBe(0);
  expect(errors).toEqual([]);
});


test("real Python computes, plots, and saves using local science packages", async ({ page }) => {
  test.setTimeout(90_000);
  const { current, errors } = await setup(page, true);
  const packageRequests: string[] = [];
  page.on("request", (request) => {
    if (request.url().includes(".whl")) packageRequests.push(request.url());
  });
  // No external CDN may be necessary for the standard workstation libraries.
  await page.route("https://**", (route) => route.abort());
  await page.route("**/analyses/analysis-1/cells/cell-1", async (route) => {
    current.cells[0].source = route.request().postDataJSON().source;
    await route.fulfill({ json: current.cells[0] });
  });
  await page.route("**/analyses/analysis-1/cells/cell-1/run", async (route) => {
    Object.assign(current.cells[0], route.request().postDataJSON(), { status: "ok" });
    await route.fulfill({ json: current.cells[0] });
  });
  await page.goto("/workstation");
  const editor = page.locator(".cm-content");
  await editor.fill("print(6 * 7)");
  await editor.press("ControlOrMeta+Enter");
  await expect(page.locator("pre").first()).toHaveText("42\n", { timeout: 45_000 });
  expect(packageRequests).toHaveLength(0);
  await expect(page.getByRole("button", { name: "Run", exact: true })).toBeEnabled();

  await editor.fill("import numpy as np\nimport pandas as pd\nfrom scipy import stats\nimport matplotlib.pyplot as plt\nprint(pd.Series(np.arange(5)).mean())\nprint(stats.norm.cdf(0))\nplt.plot([1, 2, 3], [1, 4, 9])\nplt.show()");
  await editor.press("ControlOrMeta+Enter");
  await expect(page.locator("pre").first()).toContainText("2.0\n0.5", { timeout: 60_000 });
  await expect(page.getByRole("img", { name: /Figure produced by cell/i })).toBeVisible();
  expect(packageRequests.length).toBeGreaterThan(0);
  expect(packageRequests.every((url) => url.startsWith("http://127.0.0.1:3101/pyodide/"))).toBe(true);
  await page.reload();
  await expect(page.locator("pre").first()).toContainText("2.0\n0.5");
  await expect(page.getByRole("img", { name: /Figure produced by cell/i })).toBeVisible();
  expect(errors).toEqual([]);
});


test("stalled Python startup stops loading and allows another run", async ({ page }) => {
  await setup(page, true);
  await page.clock.install();
  await page.route("**/pyodide/pyodide.mjs", (route) => route.fulfill({
    contentType: "text/javascript",
    body: "await new Promise(() => {}); export async function loadPyodide() {}",
  }));
  await page.goto("/workstation");
  const editor = page.locator(".cm-content");
  await expect(editor).toBeVisible();
  await editor.press("ControlOrMeta+Enter");
  await expect(page.getByText("Downloading Python…", { exact: true })).toBeVisible();
  await page.clock.fastForward(46_000);
  await expect(page.getByRole("alert").filter({ hasText: "Python took too long to start" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Run", exact: true })).toBeEnabled();
});
