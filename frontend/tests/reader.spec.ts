import { expect, test, type Page } from "@playwright/test";
import { readerPdf } from "./fixtures/pdf";

async function setup(page: Page) {
  const highlights: object[] = [];
  const messages: object[] = [];
  let asked = 0;
  const conversation = { id: "conversation-1", paper_id: "paper-1", mode: "explain", title: "Saved question", message_count: 0 };
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    if (path.endsWith("/auth/me")) return route.fulfill({ json: { id: "reader", full_name: "Reader", email: "reader@example.edu" } });
    if (path.endsWith("/file")) return route.fulfill({ contentType: "application/pdf", body: readerPdf() });
    if (path.endsWith("/papers/paper-1")) return route.fulfill({ json: { id: "paper-1", status: "ready", display_title: "Persistence test" } });
    if (path.endsWith("/annotations")) {
      if (route.request().method() === "POST") {
        const input = route.request().postDataJSON();
        const saved = { ...input, id: `annotation-${highlights.length}`, paper_id: "paper-1", text_length: input.selected_text.length };
        highlights.push(saved);
        return route.fulfill({ status: 201, json: saved });
      }
      return route.fulfill({ json: highlights });
    }
    if (path.endsWith("/conversations")) {
      if (route.request().method() === "POST") return route.fulfill({ status: 201, json: conversation });
      expect(url.searchParams.get("paper_id")).toBe("paper-1");
      return route.fulfill({ json: messages.length ? [{ ...conversation, message_count: messages.length }] : [] });
    }
    if (path.endsWith("/messages")) return route.fulfill({ json: messages });
    if (path.endsWith("/ask")) {
      asked++;
      messages.push({ id: "question-1", role: "user", content: route.request().postDataJSON().question, mode: "explain", citations: [] });
      messages.push({ id: "answer-1", role: "assistant", content: "This answer stays saved after refresh.", mode: "explain", citations: [] });
      return route.fulfill({ contentType: "text/event-stream", body: 'event: text\ndata: {"text":"This answer stays saved after refresh."}\n\nevent: done\ndata: {"message_id":"answer-1"}\n\n' });
    }
    return route.fulfill({ json: [] });
  });
  return { highlights, get asked() { return asked; } };
}

async function selectText(page: Page) {
  await expect(page.locator(".react-pdf__Page__textContent span").first()).toBeAttached();
  await page.locator(".react-pdf__Page__textContent span").first().evaluate((span) => {
    const range = document.createRange();
    range.setStart(span.firstChild!, 0);
    range.setEnd(span.firstChild!, 22);
    const selection = window.getSelection()!;
    selection.removeAllRanges();
    selection.addRange(range);
    span.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
  });
}

for (const colour of ["important", "question"]) {
  test(`${colour} highlights remain visible after refresh and zoom`, async ({ page }) => {
    await setup(page);
    await page.goto("/library/paper-1/read");
    await selectText(page);
    await page.getByRole("button", { name: `Highlight as ${colour}`, exact: true }).click();
    const marker = page.locator("[data-annotation-id]").first();
    await expect(marker).toBeVisible();
    await page.reload();
    await expect(marker).toBeVisible();
    const before = await marker.boundingBox();
    await page.getByRole("button", { name: "Zoom in", exact: true }).click();
    await expect.poll(async () => (await marker.boundingBox())?.width ?? 0).toBeGreaterThan(before!.width * 1.1);
    await page.getByRole("tab", { name: "Highlights" }).click();
    await expect(page.getByText("A persistent highlight", { exact: true })).toBeVisible();
  });
}

test("saved questions and answers restore without another model request", async ({ page }) => {
  const state = await setup(page);
  await page.goto("/library/paper-1/read");
  await selectText(page);
  await page.getByRole("button", { name: "Explain", exact: true }).click();
  const panel = page.getByRole("region", { name: "Turex answer" });
  await expect(panel.getByText("This answer stays saved after refresh.")).toBeVisible();
  await page.reload();
  await expect(panel.getByText("This answer stays saved after refresh.")).toBeVisible();
  await expect(panel).toContainText("Explain this passage");
  await page.getByRole("button", { name: "Hide panel", exact: true }).click();
  await page.getByRole("button", { name: "Show panel", exact: true }).click();
  await expect(panel.getByText("This answer stays saved after refresh.")).toBeVisible();
  expect(state.asked).toBe(1);
});

test("failed highlight saves are visible and keep the selection available", async ({ page }) => {
  await setup(page);
  await page.route("**/papers/paper-1/annotations", async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    return route.fulfill({ status: 503, json: { error: { code: "unavailable", message: "Could not save highlight." } } });
  });
  await page.goto("/library/paper-1/read");
  await selectText(page);
  await page.getByRole("button", { name: "Highlight as important", exact: true }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Could not save highlight." })).toBeVisible();
  await expect(page.getByRole("button", { name: "Highlight as important", exact: true })).toBeVisible();
});
