"use client";

import { AlertCircle, ArrowUp, MessagesSquare, Plus, Square, Trash2 } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { Answer, SourceList, type AnySource } from "@/components/assistant/answer";
import { LevelPicker } from "@/components/assistant/level-picker";
import { ModePicker } from "@/components/assistant/mode-picker";
import { PageContainer } from "@/components/layout/page-container";
import { Button } from "@/components/ui/button";
import { Badge, Card, EmptyState, Skeleton } from "@/components/ui/primitives";
import { ApiError } from "@/lib/api";
import { describe } from "@/lib/use-async";
import { cn } from "@/lib/cn";
import {
  ask,
  assistant,
  type AssistantMode,
  type ExplanationLevel,
  type AssistantStatus,
  type Conversation,
  type Message,
  type StreamedSource,
} from "@/lib/assistant";

/** The answer currently being streamed, before it becomes a stored message. */
interface Draft {
  question: string;
  text: string;
  sources: StreamedSource[];
  error: string | null;
}

export default function AssistantPage() {
  const [status, setStatus] = useState<AssistantStatus | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [mode, setMode] = useState<AssistantMode>("research");
  const [level, setLevel] = useState<ExplanationLevel | null>(null);
  const [question, setQuestion] = useState("");
  const [loadError, setLoadError] = useState<string | null>(null);

  const abortRef = useRef<(() => void) | null>(null);
  const threadRef = useRef<HTMLDivElement>(null);
  const streaming = draft !== null && draft.error === null;

  // -- loading -----------------------------------------------------------------

  useEffect(() => {
    void (async () => {
      try {
        const [loadedStatus, loadedConversations] = await Promise.all([
          assistant.status(),
          assistant.listConversations(),
        ]);
        setStatus(loadedStatus);
        setConversations(loadedConversations);
      } catch (caught) {
        setLoadError(
          caught instanceof ApiError
            ? caught.message
            : "Turex couldn't load the assistant. Try again.",
        );
      }
    })();
  }, []);

  useEffect(() => {
    if (!activeId) {
      setMessages([]);
      return;
    }
    void assistant
      .messages(activeId)
      .then((loaded) => {
        setMessages(loaded);
        setLoadError(null);
      })
      // An empty transcript and an unreachable server look identical otherwise, and one of
      // them means the conversation the reader is looking for is still there.
      .catch((caught: unknown) => setLoadError(describe(caught)));
  }, [activeId]);

  // Keep the newest turn in view as it streams.
  useEffect(() => {
    threadRef.current?.scrollTo({ top: threadRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, draft?.text]);

  // Stop generating when the user navigates away — the answer would otherwise keep
  // running, and keep costing, with nobody reading it.
  useEffect(() => () => abortRef.current?.(), []);

  // -- asking ------------------------------------------------------------------

  const send = useCallback(async () => {
    const text = question.trim();
    if (!text || streaming) return;

    let conversationId = activeId;
    try {
      if (!conversationId) {
        const created = await assistant.createConversation({ mode });
        conversationId = created.id;
        setActiveId(created.id);
        setConversations((current) => [created, ...current]);
      }
    } catch (caught) {
      setDraft({
        question: text,
        text: "",
        sources: [],
        error:
          caught instanceof ApiError
            ? caught.message
            : "Turex couldn't start that conversation.",
      });
      return;
    }

    setQuestion("");
    setDraft({ question: text, text: "", sources: [], error: null });

    abortRef.current = ask(
      conversationId,
      text,
      {
        onSources: (sources) =>
          setDraft((current) => (current ? { ...current, sources } : current)),
        onText: (fragment) =>
          setDraft((current) =>
            current ? { ...current, text: current.text + fragment } : current,
          ),
        onDone: async () => {
          // Reload from the server so the rendered turn is the persisted one, with the
          // citations the server actually recorded rather than the streamed preview.
          if (conversationId) setMessages(await assistant.messages(conversationId));
          setDraft(null);
          abortRef.current = null;
          setConversations(await assistant.listConversations());
        },
        onError: (message) =>
          setDraft((current) => (current ? { ...current, error: message } : current)),
      },
      mode,
      level ?? undefined,
    );
  }, [question, streaming, activeId, mode, level]);

  function stop() {
    abortRef.current?.();
    abortRef.current = null;
    setDraft((current) => (current ? { ...current, error: "You stopped this answer." } : null));
  }

  async function startNew() {
    abortRef.current?.();
    setActiveId(null);
    setMessages([]);
    setDraft(null);
  }

  async function removeConversation(id: string) {
    await assistant.deleteConversation(id).catch(() => undefined);
    setConversations((current) => current.filter((conversation) => conversation.id !== id));
    if (activeId === id) void startNew();
  }

  // -- render ------------------------------------------------------------------

  if (loadError) {
    return (
      <PageContainer>
        <div role="alert" className="rounded-lg border border-danger/25 bg-danger-soft p-4">
          <p className="text-sm text-ink">{loadError}</p>
        </div>
      </PageContainer>
    );
  }

  if (!status) {
    return (
      <PageContainer>
        <Skeleton className="h-7 w-56" />
        <Skeleton className="mt-3 h-4 w-80" />
        <Skeleton className="mt-8 h-64 w-full rounded-lg" />
        <span className="sr-only">Loading the assistant</span>
      </PageContainer>
    );
  }

  const empty = messages.length === 0 && draft === null;

  return (
    <div className="flex h-[calc(100dvh-3.5rem)] md:h-dvh">
      <ConversationList
        conversations={conversations}
        activeId={activeId}
        onSelect={setActiveId}
        onNew={startNew}
        onDelete={removeConversation}
      />

      <div className="flex min-w-0 flex-1 flex-col">
        {!status.chat_available && <NotConfiguredNotice />}

        <div ref={threadRef} className="scrollbar-slim flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-3xl px-5 py-6 sm:px-8">
            {empty ? (
              <Welcome indexed={status.indexed_chunks} />
            ) : (
              <ol className="space-y-7">
                {messages.map((message) => (
                  <li key={message.id}>
                    <Turn message={message} />
                  </li>
                ))}
                {draft && (
                  <li>
                    <DraftTurn draft={draft} />
                  </li>
                )}
              </ol>
            )}
          </div>
        </div>

        <Composer
          value={question}
          onChange={setQuestion}
          onSend={send}
          onStop={stop}
          streaming={streaming}
          disabled={!status.chat_available}
          mode={mode}
          modes={status.modes}
          onModeChange={setMode}
          level={level}
          onLevelChange={setLevel}
        />
      </div>
    </div>
  );
}

function ConversationList({
  conversations,
  activeId,
  onSelect,
  onNew,
  onDelete,
}: {
  conversations: Conversation[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
}) {
  return (
    <aside className="hidden w-64 shrink-0 flex-col border-r border-border bg-surface-sunken lg:flex">
      <div className="p-3">
        <Button variant="secondary" size="sm" className="w-full" onClick={onNew}>
          <Plus aria-hidden />
          New conversation
        </Button>
      </div>
      <nav aria-label="Conversations" className="scrollbar-slim flex-1 overflow-y-auto px-2 pb-3">
        {conversations.length === 0 ? (
          <p className="px-2 py-3 text-[12px] text-ink-subtle">
            Your conversations will appear here.
          </p>
        ) : (
          <ul className="space-y-0.5">
            {conversations.map((conversation) => (
              <li key={conversation.id} className="group relative">
                <button
                  type="button"
                  onClick={() => onSelect(conversation.id)}
                  aria-current={conversation.id === activeId ? "true" : undefined}
                  className={cn(
                    "w-full rounded-md px-2.5 py-2 pr-8 text-left text-[13px] transition-colors",
                    conversation.id === activeId
                      ? "bg-surface-hover font-medium text-ink"
                      : "text-ink-muted hover:bg-surface-hover hover:text-ink",
                  )}
                >
                  <span className="block truncate">
                    {conversation.title ?? "New conversation"}
                  </span>
                </button>
                <button
                  type="button"
                  onClick={() => onDelete(conversation.id)}
                  aria-label={`Delete ${conversation.title ?? "conversation"}`}
                  className="absolute top-1/2 right-1.5 -translate-y-1/2 rounded-sm p-1 text-ink-subtle opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100 hover:text-danger"
                >
                  <Trash2 className="size-3.5" aria-hidden />
                </button>
              </li>
            ))}
          </ul>
        )}
      </nav>
    </aside>
  );
}

function NotConfiguredNotice() {
  return (
    <div className="border-b border-border bg-warning-soft px-5 py-2.5 sm:px-8">
      <p className="text-[13px] text-ink">
        No language model is configured on this Turex instance, so the assistant can&rsquo;t
        answer yet. Semantic search over your library still works.{" "}
        <Link href="/library" className="font-medium text-accent hover:underline">
          Go to your library
        </Link>
      </p>
    </div>
  );
}

function Welcome({ indexed }: { indexed: number }) {
  return (
    <EmptyState
      icon={<MessagesSquare />}
      title="Ask about your library"
      description={
        indexed > 0
          ? "Every answer is built from passages retrieved from your own papers, and every claim links back to the page it came from."
          : "Add a paper to your library first. Turex answers from what you have read, not from the open internet."
      }
      className="mt-10"
    />
  );
}

function Turn({ message }: { message: Message }) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <p className="max-w-[85%] rounded-lg rounded-br-sm bg-accent-soft px-3.5 py-2 text-[15px] text-ink">
          {message.content}
        </p>
      </div>
    );
  }

  if (message.error_message) {
    return (
      <div
        role="alert"
        className="flex items-start gap-2.5 rounded-md border border-danger/25 bg-danger-soft px-3 py-2.5 text-[13px] text-danger"
      >
        <AlertCircle className="mt-px size-4 shrink-0" aria-hidden />
        <span>{message.error_message}</span>
      </div>
    );
  }

  return (
    <div>
      {message.mode && (
        <Badge tone="accent" className="mb-2">
          {message.mode}
        </Badge>
      )}
      <Answer text={message.content} sources={message.citations as AnySource[]} />
      <SourceList sources={message.citations as AnySource[]} />
    </div>
  );
}

function DraftTurn({ draft }: { draft: Draft }) {
  return (
    <div className="space-y-6">
      <div className="flex justify-end">
        <p className="max-w-[85%] rounded-lg rounded-br-sm bg-accent-soft px-3.5 py-2 text-[15px] text-ink">
          {draft.question}
        </p>
      </div>

      <div aria-live="polite">
        {draft.error ? (
          <div
            role="alert"
            className="flex items-start gap-2.5 rounded-md border border-danger/25 bg-danger-soft px-3 py-2.5 text-[13px] text-danger"
          >
            <AlertCircle className="mt-px size-4 shrink-0" aria-hidden />
            <span>{draft.error}</span>
          </div>
        ) : draft.text ? (
          <>
            <Answer text={draft.text} sources={draft.sources as AnySource[]} />
            <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse bg-accent align-text-bottom" />
          </>
        ) : (
          <RetrievingIndicator count={draft.sources.length} />
        )}
      </div>
    </div>
  );
}

/**
 * Shown between the question and the first token.
 *
 * Reports what Turex is doing rather than spinning: once sources arrive the reader can see
 * how many passages the answer will be built from, before a word of it exists.
 */
function RetrievingIndicator({ count }: { count: number }) {
  return (
    <p className="flex items-center gap-2 text-[13px] text-ink-muted">
      <span className="inline-block size-1.5 animate-pulse rounded-full bg-accent" aria-hidden />
      {count > 0
        ? `Reading ${count} ${count === 1 ? "passage" : "passages"} from your library…`
        : "Searching your library…"}
    </p>
  );
}

function Composer({
  value,
  onChange,
  onSend,
  onStop,
  streaming,
  disabled,
  mode,
  modes,
  onModeChange,
  level,
  onLevelChange,
}: {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  onStop: () => void;
  streaming: boolean;
  disabled: boolean;
  mode: AssistantMode;
  modes: { value: AssistantMode; label: string; description: string }[];
  onModeChange: (mode: AssistantMode) => void;
  level: ExplanationLevel | null;
  onLevelChange: (level: ExplanationLevel | null) => void;
}) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Grow with the question, up to a ceiling — a long question should be readable while
  // being written, but must not push the thread off screen.
  useEffect(() => {
    const element = textareaRef.current;
    if (!element) return;
    element.style.height = "auto";
    element.style.height = `${Math.min(element.scrollHeight, 200)}px`;
  }, [value]);

  return (
    <div className="border-t border-border bg-canvas px-5 py-3 sm:px-8">
      <div className="mx-auto max-w-3xl">
        <Card className="flex items-end gap-2 p-2">
          <textarea
            ref={textareaRef}
            rows={1}
            value={value}
            disabled={disabled}
            onChange={(event) => onChange(event.target.value)}
            onKeyDown={(event) => {
              // Enter sends; Shift+Enter is a newline. Matches every chat interface, so it
              // needs no explanation.
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                onSend();
              }
            }}
            placeholder={
              disabled ? "The assistant isn't configured" : "Ask about your papers…"
            }
            aria-label="Your question"
            className="max-h-50 min-h-9 flex-1 resize-none bg-transparent px-2 py-1.5 text-[15px] text-ink placeholder:text-ink-subtle focus:outline-none disabled:opacity-60"
          />

          {streaming ? (
            <Button variant="secondary" size="sm" onClick={onStop}>
              <Square aria-hidden />
              Stop
            </Button>
          ) : (
            <Button
              size="sm"
              onClick={onSend}
              disabled={disabled || !value.trim()}
              aria-label="Send"
            >
              <ArrowUp aria-hidden />
            </Button>
          )}
        </Card>

        <div className="mt-2 flex items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <ModePicker
              modes={modes}
              value={mode}
              onChange={onModeChange}
              disabled={disabled || streaming}
            />
            <LevelPicker value={level} onChange={onLevelChange} disabled={disabled || streaming} />
          </div>
          <p className="hidden text-[12px] text-ink-subtle sm:block">
            Answers cite your papers. Turex says so when it doesn&rsquo;t know.
          </p>
        </div>
      </div>
    </div>
  );
}
