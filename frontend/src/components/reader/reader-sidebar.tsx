"use client";

import {
  BookMarked,
  Check,
  Copy,
  Highlighter,
  ListTree,
  Plus,
  Quote,
  Sigma,
  Trash2,
} from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { EmptyState, Skeleton } from "@/components/ui/primitives";
import { ApiError } from "@/lib/api";
import { papers, type Equation, type Reference } from "@/lib/papers";
import {
  annotations as annotationsApi,
  colourOf,
  HIGHLIGHT_COLOURS,
  type Annotation,
  type CitationBundle,
  type HighlightColour,
} from "@/lib/annotations";
import { cn } from "@/lib/cn";
import { describe } from "@/lib/use-async";
import type { PaperSection } from "@/lib/papers";

type Tab = "outline" | "highlights" | "equations" | "references" | "cite";

const TABS: { value: Tab; label: string; icon: typeof ListTree }[] = [
  { value: "outline", label: "Outline", icon: ListTree },
  { value: "highlights", label: "Highlights", icon: Highlighter },
  { value: "equations", label: "Maths", icon: Sigma },
  { value: "references", label: "Refs", icon: BookMarked },
  { value: "cite", label: "Cite", icon: Quote },
];

export function ReaderSidebar({
  paperId,
  sections,
  annotations,
  activeAnnotationId,
  onJumpToPage,
  onAskAboutEquation,
  onSelectAnnotation,
  onAnnotationsChanged,
}: {
  paperId: string;
  sections: PaperSection[];
  annotations: Annotation[];
  activeAnnotationId: string | null;
  onJumpToPage: (page: number) => void;
  /** Route an equation to the assistant. Optional so the panel still lists them without it. */
  onAskAboutEquation?: (equation: string) => void;
  onSelectAnnotation: (id: string | null) => void;
  onAnnotationsChanged: () => void;
}) {
  const [tab, setTab] = useState<Tab>("outline");

  return (
    <div className="flex h-full flex-col">
      <div role="tablist" aria-label="Reader panels" className="flex border-b border-border">
        {TABS.map(({ value, label, icon: Icon }) => (
          <button
            key={value}
            role="tab"
            aria-selected={tab === value}
            onClick={() => setTab(value)}
            className={cn(
              "flex flex-1 items-center justify-center gap-1.5 border-b-2 px-2 py-2.5 text-[12px] font-medium transition-colors",
              tab === value
                ? "border-accent text-ink"
                : "border-transparent text-ink-muted hover:text-ink",
            )}
          >
            <Icon className="size-3.5" aria-hidden />
            {label}
            {value === "highlights" && annotations.length > 0 && (
              <span className="rounded-xs bg-surface-sunken px-1 font-mono text-[10px]">
                {annotations.length}
              </span>
            )}
          </button>
        ))}
      </div>

      <div className="scrollbar-slim flex-1 overflow-y-auto p-3">
        {tab === "outline" && <Outline sections={sections} onJumpToPage={onJumpToPage} />}
        {tab === "highlights" && (
          <Highlights
            annotations={annotations}
            activeId={activeAnnotationId}
            onSelect={onSelectAnnotation}
            onJumpToPage={onJumpToPage}
            onChanged={onAnnotationsChanged}
          />
        )}
        {tab === "equations" && (
          <Equations paperId={paperId} onJumpToPage={onJumpToPage} onAsk={onAskAboutEquation} />
        )}
        {tab === "references" && <References paperId={paperId} />}
        {tab === "cite" && <Citations paperId={paperId} />}
      </div>
    </div>
  );
}

function Outline({
  sections,
  onJumpToPage,
}: {
  sections: PaperSection[];
  onJumpToPage: (page: number) => void;
}) {
  if (sections.length === 0) {
    return (
      <p className="px-1 py-3 text-[12px] text-ink-subtle">
        Turex didn&rsquo;t find headings in this document.
      </p>
    );
  }

  return (
    <ol className="space-y-0.5">
      {sections.map((section) => (
        <li key={section.id}>
          <button
            type="button"
            disabled={!section.page_start}
            onClick={() => section.page_start && onJumpToPage(section.page_start)}
            style={{ paddingLeft: `${6 + (section.level - 1) * 12}px` }}
            className="flex w-full items-baseline justify-between gap-2 rounded-sm py-1 pr-1.5 text-left text-[12px] text-ink-muted transition-colors hover:bg-surface-hover hover:text-ink disabled:opacity-50"
          >
            <span className={cn("min-w-0 truncate", section.level === 1 && "text-ink")}>
              {section.title}
            </span>
            {section.page_start && (
              <span className="shrink-0 font-mono text-[10px] text-ink-subtle">
                {section.page_start}
              </span>
            )}
          </button>
        </li>
      ))}
    </ol>
  );
}

function Highlights({
  annotations,
  activeId,
  onSelect,
  onJumpToPage,
  onChanged,
}: {
  annotations: Annotation[];
  activeId: string | null;
  onSelect: (id: string | null) => void;
  onJumpToPage: (page: number) => void;
  onChanged: () => void;
}) {
  if (annotations.length === 0) {
    return (
      <EmptyState
        icon={<Highlighter />}
        title="No highlights yet"
        description="Select any passage in the paper to highlight it or ask Turex about it."
        className="border-0 px-2 py-8"
      />
    );
  }

  return (
    <ul className="space-y-2">
      {annotations.map((annotation) => (
        <HighlightEntry
          key={annotation.id}
          annotation={annotation}
          active={annotation.id === activeId}
          onSelect={() => {
            onSelect(annotation.id);
            onJumpToPage(annotation.page_number);
          }}
          onChanged={onChanged}
        />
      ))}
    </ul>
  );
}

function HighlightEntry({
  annotation,
  active,
  onSelect,
  onChanged,
}: {
  annotation: Annotation;
  active: boolean;
  onSelect: () => void;
  onChanged: () => void;
}) {
  const [note, setNote] = useState(annotation.note ?? "");
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    try {
      await action();
      setError(null);
      onChanged();
    } catch (caught) {
      setError(describe(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <li
      className={cn(
        "rounded-md border border-l-2 bg-surface p-2.5 transition-colors",
        colourOf(annotation.colour).edge,
        active ? "border-border-strong" : "border-border",
      )}
    >
      <button type="button" onClick={onSelect} className="block w-full text-left">
        <span className="flex items-center gap-1.5 font-mono text-[10px] text-ink-subtle">
          p{annotation.page_number} · {colourOf(annotation.colour).label}
        </span>
        <span className="mt-1 line-clamp-4 block text-[12px] leading-relaxed text-ink">
          {annotation.selected_text}
        </span>
      </button>

      {error && <p role="alert" className="mt-2 text-xs text-danger">{error}</p>}

      {editing ? (
        <div className="mt-2 space-y-1.5">
          <textarea
            aria-label="Note on this highlight"
            value={note}
            autoFocus
            rows={3}
            onChange={(event) => setNote(event.target.value)}
            placeholder="What did you notice?"
            className="w-full resize-none rounded-sm border border-border bg-canvas p-1.5 text-[12px] text-ink placeholder:text-ink-subtle focus:border-accent focus:outline-none"
          />
          <div className="flex gap-1.5">
            <Button
              size="sm"
              loading={busy}
              onClick={() =>
                run(async () => {
                  await annotationsApi.update(annotation.id, {
                    note,
                    clear_note: note.trim() === "",
                  });
                  setEditing(false);
                })
              }
            >
              Save
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setEditing(false)}>
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        annotation.note && (
          <p className="mt-1.5 border-t border-border pt-1.5 text-[12px] leading-relaxed text-ink-muted">
            {annotation.note}
          </p>
        )
      )}

      <div className="mt-2 flex items-center gap-1">
        <div className="flex gap-0.5">
          {HIGHLIGHT_COLOURS.map((colour) => (
            <button
              key={colour.value}
              type="button"
              aria-label={`Change to ${colour.label.toLowerCase()}`}
              disabled={busy}
              onClick={() =>
                run(() =>
                  annotationsApi.update(annotation.id, {
                    colour: colour.value as HighlightColour,
                  }),
                )
              }
              className={cn(
                "size-3.5 rounded-xs border border-border transition-transform hover:scale-110",
                colour.swatch,
                annotation.colour === colour.value && "ring-1 ring-ink-subtle",
              )}
            />
          ))}
        </div>

        <button
          type="button"
          onClick={() => setEditing((value) => !value)}
          className="ml-auto rounded-sm px-1.5 text-[11px] text-ink-subtle hover:text-ink"
        >
          {annotation.note ? "Edit note" : "Add note"}
        </button>
        <button
          type="button"
          disabled={busy}
          aria-label="Delete highlight"
          onClick={() => run(() => annotationsApi.remove(annotation.id))}
          className="rounded-sm p-1 text-ink-subtle hover:text-danger"
        >
          <Trash2 className="size-3" aria-hidden />
        </button>
      </div>
    </li>
  );
}

function Citations({ paperId }: { paperId: string }) {
  const [bundle, setBundle] = useState<CitationBundle | null>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void annotationsApi
      .citations(paperId)
      .then((loaded) => { setBundle(loaded); setError(null); })
      .catch((caught) => setError(describe(caught)));
  }, [paperId]);

  if (!bundle) {
    if (error) return <p role="alert" className="text-sm text-danger">{error}</p>;
    return (
      <div className="space-y-3" aria-busy>
        <Skeleton className="h-20 w-full rounded-md" />
        <Skeleton className="h-14 w-full rounded-md" />
        <span className="sr-only">Loading citations</span>
      </div>
    );
  }

  const gaps = bundle.formats[0]?.missing_fields ?? [];

  return (
    <div className="space-y-3">
      {error && <p role="alert" className="text-sm text-danger">{error}</p>}
      {gaps.length > 0 && (
        <p className="rounded-md border border-warning/30 bg-warning-soft px-2.5 py-2 text-[12px] leading-relaxed text-ink">
          Turex doesn&rsquo;t know this paper&rsquo;s {gaps.join(", ")}. It leaves those out
          rather than guessing — fill them in on the paper page for a complete citation.
        </p>
      )}

      {bundle.formats.map((format) => (
        <div key={format.style}>
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-semibold tracking-wide text-ink-muted uppercase">
              {format.style}
            </span>
            <button
              type="button"
              onClick={async () => {
                try {
                  await navigator.clipboard.writeText(format.text);
                  setError(null);
                  setCopied(format.style);
                  setTimeout(() => setCopied(null), 1600);
                } catch {
                  setError("Couldn't copy. Select the citation text and copy it manually.");
                }
              }}
              className="flex items-center gap-1 rounded-sm px-1.5 py-0.5 text-[11px] text-ink-subtle hover:text-ink"
            >
              {copied === format.style ? (
                <>
                  <Check className="size-3" aria-hidden />
                  Copied
                </>
              ) : (
                <>
                  <Copy className="size-3" aria-hidden />
                  Copy
                </>
              )}
            </button>
          </div>
          <pre className="scrollbar-slim mt-1 overflow-x-auto rounded-md border border-border bg-surface-sunken p-2 font-mono text-[11px] leading-relaxed whitespace-pre-wrap text-ink">
            {format.text}
          </pre>
        </div>
      ))}
    </div>
  );
}

/**
 * The equations found in this paper.
 *
 * Detection is heuristic — PDF text carries no markup for mathematics — so the list says so
 * rather than presenting itself as complete. A reader who sees four equations in a panel that
 * implies exhaustiveness will trust it and be wrong; one who is told it is approximate can use
 * it for what it is, which is a way back to the page.
 */
function Equations({
  paperId,
  onJumpToPage,
  onAsk,
}: {
  paperId: string;
  onJumpToPage: (page: number) => void;
  onAsk?: (equation: string) => void;
}) {
  const [equations, setEquations] = useState<Equation[] | null>(null);

  useEffect(() => {
    void papers
      .equations(paperId)
      .then(setEquations)
      .catch(() => setEquations([]));
  }, [paperId]);

  if (equations === null) {
    return (
      <div className="space-y-2 p-3">
        {Array.from({ length: 3 }, (_, index) => (
          <Skeleton key={index} className="h-10 w-full rounded-sm" />
        ))}
      </div>
    );
  }

  if (equations.length === 0) {
    return (
      <EmptyState
        className="m-3 border-0"
        icon={<Sigma />}
        title="No equations found"
        description="Turex looks for displayed mathematics in the extracted text. A paper with none, or one whose equations are images rather than text, shows nothing here."
      />
    );
  }

  return (
    <div className="p-2">
      <ul className="space-y-1">
        {equations.map((equation) => (
          <li key={equation.id}>
            <div className="rounded-sm border border-border bg-surface p-2">
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-[11px] text-ink-subtle" data-tabular>
                  {equation.label ? `(${equation.label})` : "unnumbered"} · p{equation.page_number}
                </span>
                <div className="flex gap-1">
                  <button
                    type="button"
                    onClick={() => onJumpToPage(equation.page_number)}
                    className="text-[11px] font-medium text-accent hover:underline"
                  >
                    Go to page
                  </button>
                  {onAsk && (
                    <button
                      type="button"
                      onClick={() => onAsk(equation.content)}
                      className="text-[11px] font-medium text-accent hover:underline"
                    >
                      Explain
                    </button>
                  )}
                </div>
              </div>
              <p className="scrollbar-slim mt-1 overflow-x-auto font-mono text-[12px] whitespace-pre text-ink">
                {equation.content}
              </p>
            </div>
          </li>
        ))}
      </ul>
      <p className="px-1 py-2 text-[11px] leading-relaxed text-ink-subtle">
        Found by pattern, not by markup — PDFs do not label their mathematics. Some equations
        may be missing, and an equation rendered as an image will not appear at all.
      </p>
    </div>
  );
}

/**
 * The paper's bibliography, split into entries.
 *
 * An entry carrying an arXiv id or a DOI can be added to the library in one action, which is
 * the point: a bibliography is a reading list that nobody has time to retype. The others are
 * still listed, because knowing what `[12]` refers to without scrolling to the back is most of
 * the value.
 */
function References({ paperId }: { paperId: string }) {
  const [references, setReferences] = useState<Reference[] | null>(null);
  const [adding, setAdding] = useState<string | null>(null);
  const [added, setAdded] = useState<Set<string>>(new Set());
  const [failed, setFailed] = useState<Record<string, string>>({});
  const [filter, setFilter] = useState("");

  useEffect(() => {
    void papers
      .references(paperId)
      .then(setReferences)
      .catch(() => setReferences([]));
  }, [paperId]);

  async function add(reference: Reference) {
    const identifier = reference.arxiv_id ?? reference.doi;
    if (!identifier) return;

    setAdding(reference.id);
    setFailed((current) => {
      const next = { ...current };
      delete next[reference.id];
      return next;
    });
    try {
      await papers.addByReference(identifier);
      setAdded((current) => new Set(current).add(reference.id));
    } catch (caught) {
      setFailed((current) => ({
        ...current,
        [reference.id]:
          caught instanceof ApiError ? caught.message : "Turex couldn't fetch that one.",
      }));
    } finally {
      setAdding(null);
    }
  }

  if (references === null) {
    return (
      <div className="space-y-2 p-3">
        {Array.from({ length: 4 }, (_, index) => (
          <Skeleton key={index} className="h-9 w-full rounded-sm" />
        ))}
      </div>
    );
  }

  if (references.length === 0) {
    return (
      <EmptyState
        className="m-3 border-0"
        icon={<BookMarked />}
        title="No references found"
        description="Turex splits a bibliography out of the extracted text. A paper without one, or one whose references did not parse, shows nothing here."
      />
    );
  }

  const needle = filter.trim().toLowerCase();
  const shown = needle
    ? references.filter(
        (reference) =>
          reference.text.toLowerCase().includes(needle) || reference.marker === needle,
      )
    : references;

  return (
    <div className="p-2">
      <input
        type="search"
        value={filter}
        onChange={(event) => setFilter(event.target.value)}
        placeholder="Find a reference, or type its number"
        aria-label="Filter references"
        className="mb-2 h-8 w-full rounded-md border border-border bg-surface px-2.5 text-[12px] text-ink placeholder:text-ink-subtle focus:border-accent focus:outline-none"
      />

      <ul className="space-y-1">
        {shown.map((reference) => {
          const identifier = reference.arxiv_id ?? reference.doi;
          return (
            <li key={reference.id} className="rounded-sm border border-border bg-surface p-2">
              <div className="flex items-start gap-2">
                <span className="mt-0.5 shrink-0 font-mono text-[11px] text-ink-subtle">
                  {reference.marker ? `[${reference.marker}]` : "—"}
                </span>
                <p className="min-w-0 flex-1 text-[12px] leading-relaxed text-ink-muted">
                  {reference.text}
                </p>
              </div>

              {identifier && (
                <div className="mt-1.5 flex items-center gap-2 pl-6">
                  {added.has(reference.id) ? (
                    <span className="inline-flex items-center gap-1 text-[11px] text-success">
                      <Check className="size-3" aria-hidden />
                      Added to your library
                    </span>
                  ) : (
                    <button
                      type="button"
                      disabled={adding === reference.id}
                      onClick={() => void add(reference)}
                      className="inline-flex items-center gap-1 text-[11px] font-medium text-accent hover:underline disabled:opacity-50"
                    >
                      <Plus className="size-3" aria-hidden />
                      {adding === reference.id ? "Fetching…" : "Add to library"}
                    </button>
                  )}
                  <span className="truncate font-mono text-[10px] text-ink-subtle">
                    {identifier}
                  </span>
                </div>
              )}

              {failed[reference.id] && (
                <p role="alert" className="mt-1 pl-6 text-[11px] text-danger">
                  {failed[reference.id]}
                </p>
              )}
            </li>
          );
        })}
      </ul>

      <p className="px-1 py-2 text-[11px] leading-relaxed text-ink-subtle">
        Split from the extracted text, so some entries may be merged or clipped. Only references
        carrying an arXiv id or a DOI can be fetched.
      </p>
    </div>
  );
}
