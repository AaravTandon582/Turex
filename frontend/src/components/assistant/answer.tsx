"use client";

import { FileText, Quote } from "lucide-react";
import Link from "next/link";
import { useState, type ReactNode } from "react";

import { cn } from "@/lib/cn";
import type { Citation, StreamedSource } from "@/lib/assistant";

/** Both shapes a source can arrive in — persisted, or live on the stream. */
export type AnySource = Citation | StreamedSource;

const CITATION_MARKER = /\[(\d{1,2})\]/g;

/**
 * Renders an answer with its citation markers turned into resolvable references.
 *
 * A `[2]` in the text becomes a control that reveals the exact passage the answer drew on.
 * That is the whole point: the reader can check any claim in one click, so trust is earned
 * per sentence rather than assumed.
 *
 * A marker with no matching source is rendered as plain text, never as a citation. That case
 * should not occur — citations are built server-side from what was retrieved — but if a model
 * writes `[9]` when five sources exist, showing it as a live reference would be a lie.
 */
export function Answer({ text, sources }: { text: string; sources: AnySource[] }) {
  const [openMarker, setOpenMarker] = useState<number | null>(null);
  const byMarker = new Map(sources.map((source) => [source.marker, source]));

  return (
    <div className="space-y-3">
      <div className="measure text-[15px] leading-relaxed whitespace-pre-wrap text-ink">
        {renderWithCitations(text, byMarker, openMarker, setOpenMarker)}
      </div>

      {openMarker !== null && byMarker.has(openMarker) && (
        <SourceCard source={byMarker.get(openMarker)!} onClose={() => setOpenMarker(null)} />
      )}
    </div>
  );
}

function renderWithCitations(
  text: string,
  byMarker: Map<number, AnySource>,
  openMarker: number | null,
  setOpenMarker: (marker: number | null) => void,
): ReactNode[] {
  const nodes: ReactNode[] = [];
  let cursor = 0;
  let key = 0;

  for (const match of text.matchAll(CITATION_MARKER)) {
    const marker = Number(match[1]);
    const start = match.index ?? 0;

    if (start > cursor) nodes.push(text.slice(cursor, start));

    if (byMarker.has(marker)) {
      const source = byMarker.get(marker)!;
      nodes.push(
        <button
          key={`cite-${key++}`}
          type="button"
          onClick={() => setOpenMarker(openMarker === marker ? null : marker)}
          aria-expanded={openMarker === marker}
          title={`${source.paper_title} · ${source.locator}`}
          className={cn(
            "mx-0.5 inline-flex h-4 min-w-4 items-center justify-center rounded-xs px-1",
            "align-baseline font-mono text-[10px] font-semibold transition-colors",
            openMarker === marker
              ? "bg-accent text-ink-inverse"
              : "bg-accent-soft text-accent hover:bg-accent hover:text-ink-inverse",
          )}
        >
          {marker}
        </button>,
      );
    } else {
      // No source behind it: plain text, not a citation.
      nodes.push(match[0]);
    }

    cursor = start + match[0].length;
  }

  if (cursor < text.length) nodes.push(text.slice(cursor));
  return nodes;
}

function SourceCard({ source, onClose }: { source: AnySource; onClose: () => void }) {
  return (
    <aside className="animate-[var(--animate-rise)] rounded-md border border-border bg-surface-sunken p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-[13px] font-medium text-ink">{source.paper_title}</p>
          <p className="mt-0.5 flex items-center gap-1 font-mono text-[11px] text-ink-subtle">
            <FileText className="size-2.5" aria-hidden />
            {source.locator}
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="shrink-0 rounded-sm px-1.5 text-[11px] text-ink-subtle hover:text-ink"
        >
          Close
        </button>
      </div>

      <blockquote className="mt-2.5 flex gap-2 border-l-2 border-highlight pl-2.5 text-[13px] leading-relaxed text-ink-muted">
        <Quote className="mt-1 size-2.5 shrink-0 text-highlight" aria-hidden />
        <span>{source.quoted_text}</span>
      </blockquote>

      {source.paper_id && (
        <Link
          href={`/library/${source.paper_id}`}
          className="mt-2.5 inline-block text-[12px] font-medium text-accent hover:underline"
        >
          Open the paper
        </Link>
      )}
    </aside>
  );
}

/**
 * The passages retrieved for an answer, listed under it.
 *
 * Shown even for sources the answer did not end up citing — seeing what Atlas read but chose
 * not to use tells the reader something real about how the answer was formed.
 */
export function SourceList({ sources }: { sources: AnySource[] }) {
  const [expanded, setExpanded] = useState(false);
  if (sources.length === 0) return null;

  const cited = sources.filter((source) => "used_in_answer" in source && source.used_in_answer);
  const summary = cited.length > 0 ? `${cited.length} of ${sources.length}` : `${sources.length}`;

  return (
    <div className="mt-3 border-t border-border pt-2.5">
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        aria-expanded={expanded}
        className="flex items-center gap-1.5 text-[12px] text-ink-subtle hover:text-ink-muted"
      >
        <span className="inline-block size-1.5 rounded-full bg-success" aria-hidden />
        Grounded in {summary} retrieved {sources.length === 1 ? "passage" : "passages"}
        <span aria-hidden>{expanded ? "−" : "+"}</span>
      </button>

      {expanded && (
        <ol className="mt-2 space-y-1.5">
          {sources.map((source) => (
            <li
              key={source.marker}
              className="flex gap-2 text-[12px] leading-relaxed text-ink-muted"
            >
              <span className="mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-xs bg-surface-sunken font-mono text-[10px] text-ink-subtle">
                {source.marker}
              </span>
              <span className="min-w-0">
                <span className="text-ink">{source.paper_title}</span>
                <span className="text-ink-subtle"> · {source.locator}</span>
                {"used_in_answer" in source && !source.used_in_answer && (
                  <span className="text-ink-subtle"> · retrieved, not cited</span>
                )}
              </span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
