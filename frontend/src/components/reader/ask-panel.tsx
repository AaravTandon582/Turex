"use client";

import { X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Answer, type AnySource } from "@/components/assistant/answer";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import { ask, assistant, type AssistantMode, type StreamedSource } from "@/lib/assistant";

export interface AskRequest {
  question: string;
  mode: AssistantMode;
  /** The passage the question is about, shown above the answer for context. */
  quotedText: string;
}

/**
 * Answers a question about the passage the reader just selected.
 *
 * Uses a conversation scoped to this paper, so retrieval never wanders into other papers
 * while the user is reading one. The conversation is created lazily and reused for the
 * session, which keeps follow-up questions in context.
 */
export function AskPanel({
  paperId,
  request,
  onClose,
}: {
  paperId: string;
  request: AskRequest;
  onClose: () => void;
}) {
  const [answer, setAnswer] = useState("");
  const [sources, setSources] = useState<StreamedSource[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const conversationRef = useRef<string | null>(null);
  const abortRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    let cancelled = false;
    setAnswer("");
    setSources([]);
    setError(null);
    setDone(false);

    void (async () => {
      try {
        conversationRef.current ??= (
          await assistant.createConversation({ mode: request.mode, paper_id: paperId })
        ).id;
      } catch (caught) {
        if (!cancelled) {
          setError(
            caught instanceof ApiError
              ? caught.message
              : "Turex couldn't start that conversation.",
          );
        }
        return;
      }

      if (cancelled) return;

      abortRef.current = ask(
        conversationRef.current,
        request.question,
        {
          onSources: setSources,
          onText: (fragment) => setAnswer((current) => current + fragment),
          onDone: () => setDone(true),
          onError: (message) => setError(message),
        },
        request.mode,
      );
    })();

    return () => {
      cancelled = true;
      // Stop generating when the panel closes or the question changes — otherwise the
      // previous answer keeps streaming into a component nobody is reading.
      abortRef.current?.();
      abortRef.current = null;
    };
  }, [paperId, request]);

  return (
    <section
      aria-label="Turex answer"
      className="animate-[var(--animate-rise)] border-t border-border bg-surface"
    >
      <div className="flex items-start justify-between gap-3 border-b border-border px-3 py-2">
        <div className="min-w-0">
          <p className="text-[11px] font-semibold tracking-wide text-ink-muted uppercase">
            {request.mode}
          </p>
          <p className="mt-0.5 line-clamp-2 text-[12px] text-ink-subtle italic">
            &ldquo;{request.quotedText}&rdquo;
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close answer"
          className="shrink-0 rounded-sm p-1 text-ink-subtle hover:text-ink"
        >
          <X className="size-3.5" aria-hidden />
        </button>
      </div>

      <div className="scrollbar-slim max-h-72 overflow-y-auto p-3" aria-live="polite">
        {error ? (
          <p role="alert" className="text-[13px] text-danger">
            {error}
          </p>
        ) : answer ? (
          <>
            <Answer text={answer} sources={sources as AnySource[]} />
            {!done && (
              <span className="ml-0.5 inline-block h-3.5 w-1.5 animate-pulse bg-accent align-text-bottom" />
            )}
          </>
        ) : (
          <p className="flex items-center gap-2 text-[13px] text-ink-muted">
            <span
              className="inline-block size-1.5 animate-pulse rounded-full bg-accent"
              aria-hidden
            />
            {sources.length > 0
              ? `Reading ${sources.length} ${sources.length === 1 ? "passage" : "passages"}…`
              : "Looking through this paper…"}
          </p>
        )}
      </div>

      {done && (
        <div className="border-t border-border px-3 py-2">
          <Button variant="ghost" size="sm" onClick={onClose}>
            Back to reading
          </Button>
        </div>
      )}
    </section>
  );
}
