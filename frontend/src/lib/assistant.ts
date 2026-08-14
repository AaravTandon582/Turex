import { api, API_BASE_URL, ApiError } from "@/lib/api";

/** How much the reader already knows. Sent per turn; the server pitches the answer to it. */
export type ExplanationLevel = "beginner" | "intermediate" | "advanced";

export type AssistantMode =
  | "explain"
  | "research"
  | "critique"
  | "ideate"
  | "experiment"
  | "study"
  | "write";

export interface ModeInfo {
  value: AssistantMode;
  label: string;
  description: string;
}

export interface AssistantStatus {
  chat_available: boolean;
  embeddings_available: boolean;
  indexed_chunks: number;
  total_chunks: number;
  modes: ModeInfo[];
}

export interface Citation {
  marker: number;
  chunk_id: string | null;
  paper_id: string | null;
  paper_title: string;
  locator: string;
  quoted_text: string;
  page_start: number | null;
  page_end: number | null;
  used_in_answer: boolean;
}

/** A source as it arrives on the stream, before the turn is persisted. */
export interface StreamedSource {
  marker: number;
  chunk_id: string;
  paper_id: string;
  paper_title: string;
  locator: string;
  page_start: number | null;
  page_end: number | null;
  quoted_text: string;
  found_by: "meaning" | "keyword" | "both";
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  mode: AssistantMode | null;
  error_message: string | null;
  citations: Citation[];
  created_at: string;
}

export interface Conversation {
  id: string;
  title: string | null;
  mode: AssistantMode;
  paper_id: string | null;
  message_count: number;
  created_at: string;
  updated_at: string;
}

export interface SearchResult {
  chunk_id: string;
  paper_id: string;
  paper_title: string;
  content: string;
  locator: string;
  page_start: number | null;
  page_end: number | null;
  section_title: string | null;
  score: number;
  found_by: "meaning" | "keyword" | "both";
}

export const assistant = {
  status: () => api.get<AssistantStatus>("/assistant/status"),

  listConversations: () => api.get<Conversation[]>("/assistant/conversations"),

  createConversation: (input: { mode?: AssistantMode; paper_id?: string } = {}) =>
    api.post<Conversation>("/assistant/conversations", input),

  messages: (id: string) => api.get<Message[]>(`/assistant/conversations/${id}/messages`),

  deleteConversation: (id: string) => api.delete<void>(`/assistant/conversations/${id}`),

  search: (query: string, options: { limit?: number; paperId?: string } = {}) => {
    const params = new URLSearchParams({ q: query });
    if (options.limit) params.set("limit", String(options.limit));
    if (options.paperId) params.set("paper_id", options.paperId);
    return api.get<{ query: string; results: SearchResult[] }>(
      `/assistant/search?${params.toString()}`,
    );
  },
};

export interface AskHandlers {
  onSources: (sources: StreamedSource[]) => void;
  onText: (fragment: string) => void;
  onDone: (messageId: string) => void;
  onError: (message: string) => void;
}

/**
 * Ask a question and consume the streamed answer.
 *
 * `fetch` with a readable stream rather than `EventSource`, because the browser's SSE client
 * can only issue GET requests and a question does not belong in a URL.
 *
 * Returns an abort function. Cancelling matters: the answer keeps generating — and keeps
 * costing — until the connection closes, so leaving the page must stop it.
 */
export function ask(
  conversationId: string,
  question: string,
  handlers: AskHandlers,
  mode?: AssistantMode,
  level?: ExplanationLevel,
): () => void {
  const controller = new AbortController();

  void (async () => {
    let response: Response;
    try {
      response = await fetch(`${API_BASE_URL}/assistant/conversations/${conversationId}/ask`, {
        method: "POST",
        credentials: "include",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ question, mode, level }),
        signal: controller.signal,
      });
    } catch {
      if (!controller.signal.aborted) {
        handlers.onError("Atlas can't reach the server. Check your connection.");
      }
      return;
    }

    if (!response.ok || !response.body) {
      // A failure before the stream opened still arrives as a normal error envelope.
      let message = "Atlas couldn't answer that. Try again.";
      try {
        const body = (await response.json()) as { error?: { message?: string } };
        message = body.error?.message ?? message;
      } catch {
        // Non-JSON body; the default message stands.
      }
      handlers.onError(message);
      return;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        // Frames are separated by a blank line. A partial frame stays in the buffer until
        // its terminator arrives — a chunk boundary can fall anywhere.
        let separator = buffer.indexOf("\n\n");
        while (separator !== -1) {
          dispatchFrame(buffer.slice(0, separator), handlers);
          buffer = buffer.slice(separator + 2);
          separator = buffer.indexOf("\n\n");
        }
      }
    } catch {
      if (!controller.signal.aborted) {
        handlers.onError("The answer was interrupted. Try again.");
      }
    }
  })();

  return () => controller.abort();
}

function dispatchFrame(frame: string, handlers: AskHandlers): void {
  let event = "message";
  const dataLines: string[] = [];

  for (const line of frame.split("\n")) {
    if (line.startsWith("event: ")) event = line.slice(7).trim();
    else if (line.startsWith("data: ")) dataLines.push(line.slice(6));
  }

  if (dataLines.length === 0) return;

  let payload: Record<string, unknown>;
  try {
    payload = JSON.parse(dataLines.join("\n")) as Record<string, unknown>;
  } catch {
    return; // A malformed frame is dropped rather than breaking the stream.
  }

  switch (event) {
    case "sources":
      handlers.onSources((payload.sources as StreamedSource[]) ?? []);
      break;
    case "text":
      handlers.onText((payload.text as string) ?? "");
      break;
    case "done":
      handlers.onDone((payload.message_id as string) ?? "");
      break;
    case "error":
      handlers.onError(
        (payload.message as string) ?? "Atlas couldn't finish that answer. Try again.",
      );
      break;
  }
}

export { ApiError };
