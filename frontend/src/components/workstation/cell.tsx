"use client";

import { AlertTriangle, ChevronDown, ChevronUp, Loader2, Play, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { CodeEditor } from "@/components/workstation/code-editor";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/primitives";
import { Prose } from "@/components/ui/prose";
import type { AnalysisCell } from "@/lib/analyses";
import { cn } from "@/lib/cn";

const SAVE_DEBOUNCE_MS = 800;

interface CellProps {
  cell: AnalysisCell;
  index: number;
  running: boolean;
  busy: boolean;
  progress: string | null;
  onSave: (source: string) => void;
  /** Handed the editor's *current* text, not the server's copy. See below. */
  onRun: (source: string) => void;
  onMove: (offset: -1 | 1) => void;
  onDelete: () => void;
  canDelete: boolean;
}

/**
 * One cell: an editor, and whatever it last produced.
 *
 * The status badge is the part that matters. A cell whose source changed after it ran shows
 * **stale**, because the output beside it no longer corresponds to the code above it — a
 * number that looks checked and is not is worse than no number, and it is how a wrong figure
 * ends up in a write-up.
 */
export function Cell({
  cell,
  index,
  running,
  busy,
  progress,
  onSave,
  onRun,
  onMove,
  onDelete,
  canDelete,
}: CellProps) {
  const [source, setSource] = useState(cell.source);

  const previousSource = useRef(cell.source);
  // An autosave acknowledgement may arrive after more typing. Only replace a clean editor.
  useEffect(() => {
    const previous = previousSource.current;
    setSource((current) => current === previous ? cell.source : current);
    previousSource.current = cell.source;
  }, [cell.id, cell.source]);

  /**
   * Saved on a pause rather than on every keystroke.
   *
   * The callback is held in a ref written from an effect, not during render: writing a ref
   * while rendering is a side effect in a function React may call twice or abandon, and it is
   * the reason the timer must not depend on the callback's identity — a new closure each
   * render would restart the debounce forever and never save at all.
   */
  const save = useRef(onSave);
  useEffect(() => {
    save.current = onSave;
  });

  useEffect(() => {
    if (source === cell.source) return;
    const timer = setTimeout(() => save.current(source), SAVE_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [source, cell.source]);

  const isMarkdown = cell.kind === "markdown";

  /**
   * Run what is on screen.
   *
   * Saving is debounced, so for the first second after a keystroke the server's copy is the
   * *previous* source. Running from that copy meant pressing Run right after typing executed
   * the old code and displayed its output underneath the new code — a result that does not
   * match what you are looking at, which is the exact failure the stale badge exists to
   * prevent, arriving by a different route.
   */
  const runCurrent = () => {
    if (!busy) onRun(source);
  };

  return (
    <div
      className={cn(
        "group rounded-md border bg-surface transition-colors",
        cell.status === "error" ? "border-danger/40" : "border-border",
      )}
    >
      <div className="flex items-center gap-2 border-b border-border px-2 py-1.5">
        <span className="font-mono text-[11px] text-ink-subtle" data-tabular>
          [{index + 1}]
        </span>

        <Badge tone={isMarkdown ? "neutral" : "accent"}>{isMarkdown ? "Text" : "Python"}</Badge>

        {cell.status === "stale" && (
          <Badge tone="warning" title="The code changed after this output was produced">
            Stale
          </Badge>
        )}
        {cell.status === "error" && <Badge tone="danger">Error</Badge>}
        {cell.status === "ok" && cell.duration_ms !== null && (
          <span className="text-[11px] text-ink-subtle" data-tabular>
            {cell.duration_ms} ms
          </span>
        )}

        <div className="ml-auto flex items-center gap-0.5 opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100">
          <button
            type="button"
            onClick={() => onMove(-1)}
            disabled={busy}
            aria-label={`Move cell ${index + 1} up`}
            className="rounded-sm p-1.5 text-ink-subtle hover:bg-surface-hover hover:text-ink"
          >
            <ChevronUp aria-hidden className="size-3.5" />
          </button>
          <button
            type="button"
            onClick={() => onMove(1)}
            disabled={busy}
            aria-label={`Move cell ${index + 1} down`}
            className="rounded-sm p-1.5 text-ink-subtle hover:bg-surface-hover hover:text-ink"
          >
            <ChevronDown aria-hidden className="size-3.5" />
          </button>
          <button
            type="button"
            onClick={onDelete}
            disabled={busy || !canDelete}
            aria-label={`Delete cell ${index + 1}`}
            className="rounded-sm p-1.5 text-ink-subtle hover:bg-surface-hover hover:text-danger disabled:opacity-30"
          >
            <Trash2 aria-hidden className="size-3.5" />
          </button>
        </div>

        {!isMarkdown && (
          <Button size="sm" variant="ghost" onClick={runCurrent} disabled={busy}>
            {running ? (
              <Loader2 aria-hidden className="size-3.5 animate-spin" />
            ) : (
              <Play aria-hidden className="size-3.5" />
            )}
            {running ? "Running" : "Run"}
          </Button>
        )}
      </div>

      <div className="px-2">
        <CodeEditor
          value={source}
          onChange={setSource}
          onRun={isMarkdown ? undefined : runCurrent}
          language={isMarkdown ? "markdown" : "python"}
          ariaLabel={`${isMarkdown ? "Text" : "Python"} cell ${index + 1}`}
          placeholder={isMarkdown ? "Notes, in Markdown and LaTeX…" : "# Python…"}
        />
      </div>

      {isMarkdown && source.trim() && (
        <div className="border-t border-border px-3 py-2">
          <Prose density="tight" className="text-[14px] leading-relaxed text-ink">
            {source}
          </Prose>
        </div>
      )}

      {running && progress && (
        <div className="flex items-center gap-2 border-t border-border px-3 py-2 text-[12px] text-ink-muted">
          <Loader2 aria-hidden className="size-3.5 animate-spin" />
          {progress}
        </div>
      )}

      {!isMarkdown && (cell.output || cell.error || cell.image) && (
        <div className="border-t border-border">
          {cell.output && (
            <pre className="scrollbar-slim overflow-x-auto px-3 py-2 font-mono text-[12px] leading-relaxed whitespace-pre-wrap text-ink">
              {cell.output}
            </pre>
          )}

          {cell.image && (
            // A data URI produced by matplotlib inside the sandbox. Rendered as an image and
            // never as markup — the `src` is checked to be a PNG data URI, so a value that is
            // anything else, however it got into the row, cannot become a script.
            /^data:image\/png;base64,[A-Za-z0-9+/=]+$/.test(cell.image) ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={cell.image}
                alt={`Figure produced by cell ${index + 1}`}
                className="mx-auto max-w-full px-3 py-2"
              />
            ) : (
              <p className="px-3 py-2 text-[12px] text-ink-muted">
                A figure was stored in a format Turex doesn&rsquo;t recognise.
              </p>
            )
          )}

          {cell.error && (
            <div className="flex items-start gap-2 border-t border-border bg-danger-soft/40 px-3 py-2">
              <AlertTriangle aria-hidden className="mt-0.5 size-3.5 shrink-0 text-danger" />
              <pre className="scrollbar-slim overflow-x-auto font-mono text-[12px] leading-relaxed whitespace-pre-wrap text-danger">
                {cell.error}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
