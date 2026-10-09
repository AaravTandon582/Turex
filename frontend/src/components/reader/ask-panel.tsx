"use client";

import { X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Answer } from "@/components/assistant/answer";
import { Button } from "@/components/ui/button";
import { ask, assistant, type AssistantMode, type Conversation, type Message, type StreamedSource } from "@/lib/assistant";
import { describe } from "@/lib/use-async";

export interface AskRequest {
  question: string;
  mode: AssistantMode;
  quotedText: string;
}

/** Restore the paper's saved transcript without sending its questions to the model again. */
export function AskPanel({ paperId, request }: { paperId: string; request: AskRequest | null }) {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [ready, setReady] = useState(false);
  const [open, setOpen] = useState(true);
  const [pendingQuestion, setPendingQuestion] = useState<string | null>(null);
  const [answer, setAnswer] = useState("");
  const [sources, setSources] = useState<StreamedSource[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [reload, setReload] = useState(0);
  const conversationRef = useRef<string | null>(null);
  const handledRequest = useRef<AskRequest | null>(null);
  const abortRef = useRef<(() => void) | null>(null);
  const generation = useRef(0);

  useEffect(() => {
    let active = true;
    setReady(false);
    void (async () => {
      try {
        const saved = await assistant.listConversations(paperId);
        const latest = saved.find((entry) => entry.message_count > 0) ?? saved[0];
        const transcript = latest ? await assistant.messages(latest.id) : [];
        if (!active) return;
        setConversations(saved);
        conversationRef.current = latest?.id ?? null;
        setConversationId(latest?.id ?? null);
        setMessages(transcript);
        setError(null);
        setReady(true);
      } catch (caught) {
        if (active) setError(`Couldn't load saved questions. ${describe(caught)}`);
      }
    })();
    return () => { active = false; };
  }, [paperId, reload]);

  useEffect(() => () => {
    generation.current++;
    abortRef.current?.();
  }, []);

  useEffect(() => {
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("keydown", close);
    return () => document.removeEventListener("keydown", close);
  }, []);

  useEffect(() => {
    if (!ready || !request || handledRequest.current === request) return;
    handledRequest.current = request;
    abortRef.current?.();
    const current = ++generation.current;
    const active = () => generation.current === current;
    setOpen(true);
    setBusy(true);
    setError(null);
    setAnswer("");
    setSources([]);
    setPendingQuestion(request.question);

    void (async () => {
      try {
        let id = conversationRef.current;
        if (!id) {
          const created = await assistant.createConversation({ mode: request.mode, paper_id: paperId });
          if (!active()) return;
          id = created.id;
          conversationRef.current = id;
          setConversationId(id);
          setConversations((saved) => [created, ...saved]);
        }
        // A previous request may have been interrupted. Read what the server saved first.
        const transcript = await assistant.messages(id);
        if (!active()) return;
        setMessages(transcript);
        const savedId = id;
        abortRef.current = ask(id, request.question, {
          onSources: (value) => { if (active()) setSources(value); },
          onText: (fragment) => { if (active()) setAnswer((value) => value + fragment); },
          onDone: () => {
            void assistant.messages(savedId).then((saved) => {
              if (!active()) return;
              setMessages(saved);
              setPendingQuestion(null);
              setAnswer("");
              setBusy(false);
            }).catch((caught) => {
              if (active()) { setError(describe(caught)); setBusy(false); }
            });
          },
          onError: (message) => {
            if (active()) { setError(message); setBusy(false); }
          },
        }, request.mode);
      } catch (caught) {
        if (active()) { setError(describe(caught)); setBusy(false); }
      }
    })();
  }, [paperId, ready, request]);

  async function selectConversation(id: string) {
    const current = ++generation.current;
    abortRef.current?.();
    setBusy(true);
    setError(null);
    try {
      const saved = await assistant.messages(id);
      if (current !== generation.current) return;
      conversationRef.current = id;
      setConversationId(id);
      setMessages(saved);
      setPendingQuestion(null);
      setAnswer("");
    } catch (caught) {
      if (current === generation.current) setError(describe(caught));
    } finally {
      if (current === generation.current) setBusy(false);
    }
  }

  if (!request && !messages.length && !error) return null;
  if (!open) {
    return <Button variant="ghost" size="sm" onClick={() => setOpen(true)}>Show saved questions</Button>;
  }

  return (
    <section aria-label="Turex answer" className="border-t border-border bg-surface">
      <div className="flex items-center justify-between gap-3 border-b border-border px-3 py-2">
        <p className="text-[12px] font-semibold text-ink-muted">Questions about this paper</p>
        <button type="button" onClick={() => setOpen(false)} aria-label="Close answer"
          className="shrink-0 rounded-sm p-1 text-ink-subtle hover:text-ink">
          <X className="size-3.5" aria-hidden />
        </button>
      </div>
      {conversations.length > 1 && (
        <select aria-label="Saved conversations" value={conversationId ?? ""} disabled={busy}
          onChange={(event) => void selectConversation(event.target.value)}
          className="m-2 w-[calc(100%-1rem)] rounded border border-border bg-surface p-1 text-xs">
          {conversations.map((entry) => <option key={entry.id} value={entry.id}>
            {entry.title ?? "Questions"}
          </option>)}
        </select>
      )}
      <div className="scrollbar-slim max-h-80 space-y-3 overflow-y-auto p-3" aria-live="polite">
        {messages.map((message) => (
          <div key={message.id} className="text-[13px]">
            {message.role === "user" ? (
              <p className="whitespace-pre-wrap font-medium text-ink">{message.content}</p>
            ) : (
              <Answer text={message.content} sources={message.citations} />
            )}
            {message.error_message && <p role="alert" className="text-danger">{message.error_message}</p>}
          </div>
        ))}
        {pendingQuestion && <p className="whitespace-pre-wrap text-[13px] font-medium text-ink">{pendingQuestion}</p>}
        {answer && <Answer text={answer} sources={sources} />}
        {busy && <p role="status" className="text-[13px] text-ink-muted">Looking through this paper…</p>}
        {error && <p role="alert" className="text-[13px] text-danger">{error}</p>}
        {!ready && error && <Button size="sm" onClick={() => setReload((value) => value + 1)}>Retry loading questions</Button>}
        {ready && !busy && messages.at(-1)?.role === "user" && !pendingQuestion && (
          <p className="text-xs text-ink-muted">This question was saved, but its answer did not finish. Select the passage to ask again.</p>
        )}
      </div>
    </section>
  );
}
