"use client";

import { ArrowLeft, BookOpen, ExternalLink, FileText, RotateCw, Star } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { PageContainer } from "@/components/layout/page-container";
import { StudyPanel } from "@/components/study/study-panel";
import { Button } from "@/components/ui/button";
import { Badge, Card, Skeleton } from "@/components/ui/primitives";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import {
  formatAuthors,
  formatFileSize,
  isProcessing,
  papers,
  type PaperDetail,
  type PaperSection,
  type ReadingStatus,
} from "@/lib/papers";

const READING_OPTIONS: { value: ReadingStatus; label: string }[] = [
  { value: "unread", label: "Unread" },
  { value: "reading", label: "Reading" },
  { value: "read", label: "Read" },
  { value: "revisit", label: "Revisit" },
];

export default function PaperPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();

  const [paper, setPaper] = useState<PaperDetail | null>(null);
  const [sections, setSections] = useState<PaperSection[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(
    async ({ silent = false }: { silent?: boolean } = {}) => {
      try {
        const detail = await papers.get(id);
        setPaper(detail);
        setError(null);
        if (detail.status === "ready") setSections(await papers.sections(id));
      } catch (caught) {
        if (caught instanceof ApiError && caught.code === "not_found") {
          setError("That paper isn't in your library.");
        } else if (!silent) {
          setError("Turex couldn't load that paper. Try again.");
        }
      }
    },
    [id],
  );

  useEffect(() => {
    void load();
  }, [load]);

  // Opening the reader is what moves an unread paper to "reading".
  useEffect(() => {
    if (paper?.status === "ready") void papers.markOpened(id).catch(() => undefined);
    // Runs once per paper, not on every field change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, paper?.status]);

  const processing = paper ? isProcessing(paper) : false;
  useEffect(() => {
    if (!processing) return;
    const timer = setInterval(() => void load({ silent: true }), 1500);
    return () => clearInterval(timer);
  }, [processing, load]);

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    try {
      await action();
      await load({ silent: true });
    } finally {
      setBusy(false);
    }
  }

  if (error) {
    return (
      <PageContainer>
        <BackLink />
        <p role="alert" className="mt-6 text-sm text-ink-muted">
          {error}
        </p>
      </PageContainer>
    );
  }

  if (!paper) {
    return (
      <PageContainer>
        <BackLink />
        <Skeleton className="mt-6 h-8 w-3/5" />
        <Skeleton className="mt-3 h-4 w-2/5" />
        <Skeleton className="mt-8 h-40 w-full rounded-lg" />
        <span className="sr-only">Loading paper</span>
      </PageContainer>
    );
  }

  return (
    <PageContainer>
      <BackLink />

      <header className="mt-5">
        <div className="flex items-start justify-between gap-4">
          <h1 className="text-2xl leading-tight font-semibold tracking-[-0.02em] text-balance text-ink">
            {paper.display_title}
          </h1>
          <Button
            variant="ghost"
            size="sm"
            disabled={busy}
            aria-pressed={paper.is_favorite}
            aria-label={paper.is_favorite ? "Remove from favourites" : "Add to favourites"}
            onClick={() => run(() => papers.update(paper.id, { is_favorite: !paper.is_favorite }))}
            className={cn("shrink-0", paper.is_favorite && "text-highlight")}
          >
            <Star fill={paper.is_favorite ? "currentColor" : "none"} aria-hidden />
          </Button>
        </div>

        {paper.authors.length > 0 && (
          <p className="mt-2 text-sm text-ink-muted">{formatAuthors(paper.authors, 12)}</p>
        )}

        <dl className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-[13px] text-ink-subtle">
          {paper.publication_year && <Meta label="Year" value={String(paper.publication_year)} />}
          {paper.page_count && <Meta label="Pages" value={String(paper.page_count)} />}
          <Meta label="Size" value={formatFileSize(paper.file_size_bytes)} />
          {paper.source !== "upload" && paper.source_url && (
            <ExternalMeta
              label="Added from"
              value={paper.source === "arxiv" ? "arXiv" : paper.source === "doi" ? "DOI" : "Link"}
              href={paper.source_url}
            />
          )}
          {paper.arxiv_id && (
            <ExternalMeta
              label="arXiv"
              value={paper.arxiv_id}
              href={`https://arxiv.org/abs/${paper.arxiv_id}`}
            />
          )}
          {paper.doi && (
            <ExternalMeta label="DOI" value={paper.doi} href={`https://doi.org/${paper.doi}`} />
          )}
        </dl>
      </header>

      {processing && <ProcessingPanel paper={paper} />}

      {paper.status === "failed" && (
        <Card className="mt-6 border-danger/30 bg-danger-soft p-4">
          <p className="text-sm text-ink">
            {paper.failure_reason ?? "Turex couldn't read this paper."}
          </p>
          <Button
            variant="secondary"
            size="sm"
            loading={busy}
            className="mt-3"
            onClick={() => run(() => papers.reprocess(paper.id))}
          >
            <RotateCw aria-hidden />
            Try reading it again
          </Button>
        </Card>
      )}

      {paper.status === "ready" && (
        <>
          <div className="mt-6 flex flex-wrap items-center gap-3">
            <Button asChild size="sm">
              <Link href={`/library/${paper.id}/read`}>
                <BookOpen aria-hidden />
                Read in Turex
              </Link>
            </Button>

            <Button asChild variant="secondary" size="sm">
              <a href={papers.fileUrl(paper.id)} target="_blank" rel="noreferrer">
                <FileText aria-hidden />
                Open the PDF
              </a>
            </Button>

            <label className="flex items-center gap-2 text-[13px] text-ink-muted">
              Reading status
              <select
                value={paper.reading_status}
                disabled={busy}
                onChange={(event) =>
                  run(() =>
                    papers.update(paper.id, {
                      reading_status: event.target.value as ReadingStatus,
                    }),
                  )
                }
                className="h-8 rounded-md border border-border bg-surface px-2 text-[13px] text-ink focus:border-accent focus:outline-none"
              >
                {READING_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>

            <Badge tone="neutral">{paper.chunk_count} indexed passages</Badge>
          </div>

          {paper.abstract && (
            <section className="mt-8" aria-labelledby="abstract-heading">
              <h2 id="abstract-heading" className="text-[13px] font-semibold text-ink-muted">
                Abstract
              </h2>
              <p className="measure mt-2 font-serif text-[15px] leading-relaxed text-ink">
                {paper.abstract}
              </p>
            </section>
          )}

          {sections.length > 0 && (
            <section className="mt-8" aria-labelledby="outline-heading">
              <h2 id="outline-heading" className="text-[13px] font-semibold text-ink-muted">
                Outline
              </h2>
              <ol className="mt-2 space-y-0.5">
                {sections.map((section) => (
                  <li
                    key={section.id}
                    style={{ paddingLeft: `${(section.level - 1) * 16}px` }}
                    className="flex items-baseline justify-between gap-4 rounded-sm py-1 text-sm"
                  >
                    <span className={cn(section.level === 1 ? "text-ink" : "text-ink-muted")}>
                      {section.title}
                    </span>
                    {section.page_start && (
                      <span className="shrink-0 font-mono text-[11px] text-ink-subtle" data-tabular>
                        p{section.page_start}
                      </span>
                    )}
                  </li>
                ))}
              </ol>
            </section>
          )}

          <StudyPanel paperId={paper.id} />
        </>
      )}

      <div className="mt-10 border-t border-border pt-4">
        <Button
          variant="ghost"
          size="sm"
          disabled={busy}
          className="text-ink-subtle hover:text-danger"
          onClick={async () => {
            await run(() => papers.remove(paper.id));
            router.push("/library");
          }}
        >
          Remove from library
        </Button>
      </div>
    </PageContainer>
  );
}

function BackLink() {
  return (
    <Link
      href="/library"
      className="inline-flex items-center gap-1.5 rounded-sm text-[13px] text-ink-muted hover:text-ink"
    >
      <ArrowLeft className="size-3.5" aria-hidden />
      Library
    </Link>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline gap-1.5">
      <dt className="sr-only">{label}</dt>
      <dd data-tabular>{value}</dd>
    </div>
  );
}

function ExternalMeta({ label, value, href }: { label: string; value: string; href: string }) {
  return (
    <div className="flex items-baseline gap-1.5">
      <dt>{label}</dt>
      <dd>
        <a
          href={href}
          target="_blank"
          rel="noreferrer noopener"
          className="inline-flex items-center gap-1 text-accent hover:underline"
        >
          {value}
          <ExternalLink className="size-3" aria-hidden />
        </a>
      </dd>
    </div>
  );
}

function ProcessingPanel({ paper }: { paper: PaperDetail }) {
  const percent = paper.ingestion?.progress ?? 0;
  return (
    <Card className="mt-6 p-4">
      <div className="flex items-center justify-between text-sm">
        <span className="text-ink">{paper.ingestion?.label ?? "Waiting to start"}</span>
        <span className="text-ink-muted" data-tabular>
          {percent}%
        </span>
      </div>
      <div
        role="progressbar"
        aria-valuenow={percent}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label="Reading progress"
        className="mt-2 h-1 overflow-hidden rounded-full bg-surface-sunken"
      >
        <div
          className="h-full rounded-full bg-accent transition-[width] duration-500 ease-[var(--ease-out-quart)]"
          style={{ width: `${Math.max(percent, 4)}%` }}
        />
      </div>
      <p className="mt-3 text-[13px] text-ink-muted">
        Turex is extracting the text, finding the section structure, and indexing each passage.
        You can leave this page — it keeps going.
      </p>
    </Card>
  );
}
