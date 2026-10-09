import { expect, test } from "@playwright/test";

import { apiFetch, ApiError } from "../src/lib/api";
import { ask } from "../src/lib/assistant";

const originalFetch = globalThis.fetch;
test.afterEach(() => { globalThis.fetch = originalFetch; });

test("Headers instances survive the API wrapper", async () => {
  let received: Headers | undefined;
  globalThis.fetch = async (_url, init) => {
    received = new Headers(init?.headers);
    return Response.json({ ok: true });
  };
  await apiFetch("/test", { headers: new Headers({ "x-request-id": "regression" }) });
  expect(received?.get("x-request-id")).toBe("regression");
});

test("invalid successful responses become API errors", async () => {
  globalThis.fetch = async () => new Response("not JSON", { status: 200 });
  await expect(apiFetch("/test")).rejects.toBeInstanceOf(ApiError);
});

test("cancelled requests preserve cancellation", async () => {
  const controller = new AbortController();
  controller.abort();
  globalThis.fetch = async () => { throw controller.signal.reason; };
  await expect(apiFetch("/test", { signal: controller.signal })).rejects.toMatchObject({ name: "AbortError" });
});

function streamResult() {
  return new Promise<string>((resolve) => {
    ask("conversation", "question", {
      onSources: () => {}, onText: () => {},
      onDone: (id) => resolve(`done:${id}`),
      onError: (message) => resolve(`error:${message}`),
    });
  });
}

test("an interrupted answer closes the UI's pending state", async () => {
  globalThis.fetch = async () => new Response('event: text\ndata: {"text":"partial"}\n\n');
  expect(await streamResult()).toContain("error:The answer was interrupted");
});

test("streaming refreshes expired sessions once", async () => {
  let attempts = 0;
  let refreshes = 0;
  globalThis.fetch = async (url) => {
    if (String(url).endsWith("/auth/refresh")) {
      refreshes++;
      return new Response(null, { status: 204 });
    }
    if (++attempts === 1) return new Response(null, { status: 401 });
    return new Response('event: done\ndata: {"message_id":"answer"}\n\n');
  };
  expect(await streamResult()).toBe("done:answer");
  expect(refreshes).toBe(1);
  expect(attempts).toBe(2);
});
