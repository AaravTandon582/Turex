"use client";

import { BookOpen, Check, Download, ExternalLink, Loader2 } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { Prose } from "@/components/ui/prose";
import { Button } from "@/components/ui/button";
import { Badge, Card } from "@/components/ui/primitives";
import { catalog, formatAuthors, type CatalogPaper } from "@/lib/catalog";
import { isProcessing, papers, type PaperDetail } from "@/lib/papers";
import { describe } from "@/lib/use-async";

const POLL_MS = 2_000;

interface CatalogCardProps {
  paper: CatalogPaper;
  /** Told the library id once the paper is readable, so paging back keeps the Read link. */
  onImported: (arxivId: string, paperId: string) => void;
  /** Set when this paper was imported earlier in the visit. */
  libraryPaperId?: string;
}

/**
 * One search result.
 *
 * The card's job is to answer "is this worth reading" without leaving the page, which is why
 * the abstract is shown at length rather than trimmed to a line. Importing costs a download
 * and a minute of ingestion, so the decision is better made here than after.
 */
export function CatalogCard({ paper, onImported, libraryPaperId }: CatalogCardProps) {
  const [error, setError] = useState<string | null>(null);
  const [imported, setImported] = useState<PaperDetail | null>(null);
  const [starting, setStarting] = useState(false);

  /**
   * Poll the imported paper until it is readable.
   *
   * The import returns as soon as the file is stored and ingestion is *queued*, which is
   * seconds before the paper can actually be opened — the reader needs sections and chunks,
   * and shows "Atlas is still reading this paper" until it has them. Offering a Read link at
   * 202 therefore sent people to a page that told them to come back later, which is a worse
   * experience than the honest wait, and the reason this polls rather than linking straight
   * away. It is the same thing the library list does for an upload, for the same reason.
   */
  const pending = imported !== null && isProcessing(imported);
  const paperId = imported?.id ?? null;

  // The latest callback, so the polling effect does not restart when the parent re-renders.
  const notify = useRef(onImported);
  useEffect(() => {
    notify.current = onImported;
  });

  useEffect(() => {
    if (!pending || !paperId) return;

    let active = true;
    const timer = setInterval(async () => {
      try {
        const current = await papers.get(paperId);
        if (!active) return;
        setImported(current);
        if (!isProcessing(current)) notify.current(paper.arxiv_id, current.id);
      } catch (caught) {
        if (!active) return;
        // Stop polling and say so. A silent retry loop against a server that is down looks
        // identical to a paper that takes a very long time to process.
        setError(describe(caught));
        setImported(null);
      }
    }, POLL_MS);

    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [pending, paperId, paper.arxiv_id]);

  async function handleImport() {
    setStarting(true);
    setError(null);
    try {
      const added = await catalog.import(paper.id);
      setImported(added);
      // Already ingested — the same file was in the library under another name.
      if (!isProcessing(added)) onImported(paper.arxiv_id, added.id);
    } catch (caught) {
      // Shown on the card rather than swallowed. An import that quietly does nothing is the
      // failure mode that makes a person click the button four more times.
      setError(describe(caught));
    } finally {
      setStarting(false);
    }
  }

  const readableId = libraryPaperId ?? (imported && !isProcessing(imported) ? imported.id : null);
  const failed = imported?.status === "failed";
  const year = paper.published_on ? paper.published_on.slice(0, 4) : null;

  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-center gap-2 text-xs text-ink-muted">
        {paper.primary_category ? <Badge tone="accent">{paper.primary_category}</Badge> : null}
        {paper.categories
          .filter((category) => category !== paper.primary_category)
          .slice(0, 3)
          .map((category) => (
            <Badge key={category}>{category}</Badge>
          ))}
        {year ? <span>{year}</span> : null}
        <span className="font-mono">{paper.arxiv_id}</span>
      </div>

      <h3 className="mt-2 text-base leading-snug font-medium text-ink">
        <Prose density="inline">{paper.title}</Prose>
      </h3>

      <p className="mt-1 text-sm text-ink-muted">{formatAuthors(paper.authors)}</p>

      {paper.abstract ? (
        // `tight` so the clamp works: a paragraph's own vertical margin sits outside the box
        // `line-clamp` measures, and the abstract then refuses to clamp at all.
        <Prose density="tight" className="mt-2 line-clamp-4 text-sm leading-relaxed text-ink-muted">
          {paper.abstract}
        </Prose>
      ) : null}

      {paper.journal_ref ? (
        <p className="mt-2 text-xs text-ink-muted italic">{paper.journal_ref}</p>
      ) : null}

      <div className="mt-3 flex flex-wrap items-center gap-2">
        {readableId ? (
          <Button asChild variant="secondary" size="sm">
            <Link href={`/library/${readableId}/read`}>
              <BookOpen aria-hidden className="size-4" />
              Read
            </Link>
          </Button>
        ) : pending ? (
          <Button variant="secondary" size="sm" disabled>
            <Loader2 aria-hidden className="size-4 animate-spin" />
            {imported?.ingestion?.label ?? "Reading the paper"}…
          </Button>
        ) : paper.in_library ? (
          <Button variant="secondary" size="sm" asChild>
            <Link href="/library">
              <Check aria-hidden className="size-4" />
              In your library
            </Link>
          </Button>
        ) : (
          <Button size="sm" onClick={handleImport} disabled={starting}>
            {starting ? (
              <Loader2 aria-hidden className="size-4 animate-spin" />
            ) : (
              <Download aria-hidden className="size-4" />
            )}
            {starting ? "Adding…" : "Add to library"}
          </Button>
        )}

        <Button asChild variant="ghost" size="sm">
          <a href={paper.abs_url} target="_blank" rel="noreferrer noopener">
            <ExternalLink aria-hidden className="size-4" />
            arXiv
          </a>
        </Button>
      </div>

      {failed ? (
        <p role="alert" className="mt-2 text-sm text-danger">
          {imported?.failure_reason ?? "Atlas couldn't read that paper."}
        </p>
      ) : null}

      {error ? (
        <p role="alert" className="mt-2 text-sm text-danger">
          {error}
        </p>
      ) : null}
    </Card>
  );
}
