"use client";

import { AlertCircle, ChevronLeft, ChevronRight, Library as LibraryIcon, Search, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { PageContainer } from "@/components/layout/page-container";
import { PaperCard } from "@/components/library/paper-card";
import { AddByReference } from "@/components/library/add-by-reference";
import { UploadDropzone } from "@/components/library/upload-dropzone";
import { useLibrary } from "@/components/library/use-library";
import { Button } from "@/components/ui/button";
import { Card, EmptyState, PageHeader, Skeleton } from "@/components/ui/primitives";
import { cn } from "@/lib/cn";
import type { PaperQuery, PaperSort, ReadingStatus } from "@/lib/papers";

const READING_FILTERS: { value: ReadingStatus | "all"; label: string }[] = [
  { value: "all", label: "All" },
  { value: "unread", label: "Unread" },
  { value: "reading", label: "Reading" },
  { value: "read", label: "Read" },
  { value: "revisit", label: "Revisit" },
];

const SORTS: { value: PaperSort; label: string }[] = [
  { value: "recent", label: "Recently added" },
  { value: "opened", label: "Recently opened" },
  { value: "title", label: "Title" },
  { value: "year", label: "Year" },
];

export default function LibraryPage() {
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [readingStatus, setReadingStatus] = useState<ReadingStatus | "all">("all");
  const [favouritesOnly, setFavouritesOnly] = useState(false);
  const [sort, setSort] = useState<PaperSort>("recent");
  const [offset, setOffset] = useState(0);

  // Debounce so a query runs once the user pauses, not on every keystroke.
  useEffect(() => {
    const timer = setTimeout(() => {
      setSearch(searchInput.trim());
      setOffset(0);
    }, 250);
    return () => clearTimeout(timer);
  }, [searchInput]);

  const query = useMemo<PaperQuery>(
    () => ({
      search: search || undefined,
      reading_status: readingStatus === "all" ? undefined : readingStatus,
      favorites_only: favouritesOnly || undefined,
      sort,
      offset,
    }),
    [search, readingStatus, favouritesOnly, sort, offset],
  );

  const { items, total, stats, loading, error, pageSize, reload } = useLibrary(query);

  const filtered = search !== "" || readingStatus !== "all" || favouritesOnly;
  const showingFrom = total === 0 ? 0 : offset + 1;
  const showingTo = Math.min(offset + items.length, total);

  return (
    <PageContainer>
      <PageHeader
        title="Library"
        description={
          stats
            ? `${stats.total} ${stats.total === 1 ? "paper" : "papers"}${
                stats.processing > 0 ? ` · ${stats.processing} being read` : ""
              }${stats.failed > 0 ? ` · ${stats.failed} couldn't be read` : ""}`
            : undefined
        }
      />

      <div className="mt-6">
        <UploadDropzone onUploaded={() => void reload({ silent: true })} />
        <AddByReference onAdded={() => void reload({ silent: true })} />
      </div>

      <div className="mt-7 flex flex-wrap items-center gap-3">
        <div className="relative min-w-56 flex-1">
          <Search
            className="pointer-events-none absolute top-1/2 left-3 size-3.5 -translate-y-1/2 text-ink-subtle"
            aria-hidden
          />
          <input
            type="search"
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
            placeholder="Search titles, authors, abstracts"
            aria-label="Search your library"
            className="h-9 w-full rounded-md border border-border bg-surface pr-8 pl-8.5 text-sm text-ink placeholder:text-ink-subtle focus:border-accent focus:ring-3 focus:ring-[var(--accent-ring)] focus:outline-none"
          />
          {searchInput && (
            <button
              type="button"
              onClick={() => setSearchInput("")}
              aria-label="Clear search"
              className="absolute top-1/2 right-2 -translate-y-1/2 rounded-sm p-0.5 text-ink-subtle hover:text-ink"
            >
              <X className="size-3.5" aria-hidden />
            </button>
          )}
        </div>

        <div
          role="group"
          aria-label="Filter by reading status"
          className="flex items-center gap-0.5 rounded-md border border-border bg-surface p-0.5"
        >
          {READING_FILTERS.map((option) => (
            <button
              key={option.value}
              type="button"
              aria-pressed={readingStatus === option.value}
              onClick={() => {
                setReadingStatus(option.value);
                setOffset(0);
              }}
              className={cn(
                "rounded-sm px-2.5 py-1 text-[13px] transition-colors",
                readingStatus === option.value
                  ? "bg-surface-hover font-medium text-ink"
                  : "text-ink-muted hover:text-ink",
              )}
            >
              {option.label}
            </button>
          ))}
        </div>

        <Button
          variant={favouritesOnly ? "secondary" : "ghost"}
          size="sm"
          aria-pressed={favouritesOnly}
          onClick={() => {
            setFavouritesOnly((value) => !value);
            setOffset(0);
          }}
        >
          Favourites
        </Button>

        <label className="flex items-center gap-2 text-[13px] text-ink-muted">
          <span className="sr-only sm:not-sr-only">Sort</span>
          <select
            value={sort}
            onChange={(event) => {
              setSort(event.target.value as PaperSort);
              setOffset(0);
            }}
            className="h-9 rounded-md border border-border bg-surface px-2.5 text-[13px] text-ink focus:border-accent focus:outline-none"
          >
            {SORTS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="mt-5">
        {error ? (
          <ErrorState message={error} onRetry={() => void reload()} />
        ) : loading ? (
          <LoadingGrid />
        ) : items.length === 0 ? (
          filtered ? (
            <EmptyState
              icon={<Search />}
              title="No papers match those filters"
              description="Try a different search, or clear the filters to see everything in your library."
              action={
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => {
                    setSearchInput("");
                    setReadingStatus("all");
                    setFavouritesOnly(false);
                  }}
                >
                  Clear filters
                </Button>
              }
            />
          ) : (
            <EmptyState
              icon={<LibraryIcon />}
              title="Your library is empty"
              description="Add a paper above. Atlas reads it, pulls out its structure and metadata, and indexes every passage so you can ask about it later."
            />
          )
        ) : (
          <>
            <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {items.map((paper) => (
                // `min-w-0` because a grid item defaults to `min-width: auto`, which means it
                // refuses to shrink below its content's intrinsic width — so one card with a
                // long venue line pushes the whole page sideways instead of being clipped by
                // the truncation that is already there. It surfaced when papers imported from
                // arXiv brought real journal references with them; the demo library's short
                // ones had been hiding it.
                <li key={paper.id} className="relative min-w-0">
                  <PaperCard
                    paper={paper}
                    progressLabel={paper.ingestion?.label}
                    progressPercent={paper.ingestion?.progress}
                    onChanged={() => void reload({ silent: true })}
                  />
                </li>
              ))}
            </ul>

            {total > pageSize && (
              <nav
                aria-label="Pagination"
                className="mt-6 flex items-center justify-between border-t border-border pt-4"
              >
                <p className="text-[13px] text-ink-muted" data-tabular>
                  {showingFrom}–{showingTo} of {total}
                </p>
                <div className="flex gap-2">
                  <Button
                    variant="secondary"
                    size="sm"
                    disabled={offset === 0}
                    onClick={() => setOffset(Math.max(0, offset - pageSize))}
                  >
                    <ChevronLeft aria-hidden />
                    Previous
                  </Button>
                  <Button
                    variant="secondary"
                    size="sm"
                    disabled={showingTo >= total}
                    onClick={() => setOffset(offset + pageSize)}
                  >
                    Next
                    <ChevronRight aria-hidden />
                  </Button>
                </div>
              </nav>
            )}
          </>
        )}
      </div>
    </PageContainer>
  );
}

function LoadingGrid() {
  return (
    <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3" aria-busy>
      {Array.from({ length: 6 }, (_, index) => (
        <li key={index}>
          <Card className="p-4">
            <Skeleton className="h-4 w-4/5" />
            <Skeleton className="mt-2.5 h-3 w-3/5" />
            <Skeleton className="mt-6 h-3 w-24" />
          </Card>
        </li>
      ))}
      <li className="sr-only">Loading your library</li>
    </ul>
  );
}

function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div
      role="alert"
      className="flex flex-col items-center gap-4 rounded-lg border border-danger/25 bg-danger-soft px-6 py-12 text-center"
    >
      <AlertCircle className="size-5 text-danger" aria-hidden />
      <p className="text-sm text-ink">{message}</p>
      <Button variant="secondary" size="sm" onClick={onRetry}>
        Try again
      </Button>
    </div>
  );
}
