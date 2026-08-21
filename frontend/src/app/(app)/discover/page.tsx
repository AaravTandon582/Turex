"use client";

import { ChevronLeft, ChevronRight, Compass, Search, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { CatalogCard } from "@/components/catalog/catalog-card";
import { PageContainer } from "@/components/layout/page-container";
import { Button } from "@/components/ui/button";
import { LoadError } from "@/components/ui/async-boundary";
import { Card, EmptyState, PageHeader, Skeleton } from "@/components/ui/primitives";
import { catalog, describeSources, formatTotal, type CatalogQuery } from "@/lib/catalog";
import { cn } from "@/lib/cn";
import { useAsync } from "@/lib/use-async";

const PAGE_SIZE = 20;

const SORTS: { value: "relevance" | "newest"; label: string }[] = [
  { value: "relevance", label: "Best match" },
  { value: "newest", label: "Newest" },
];

/**
 * Search the catalog — every paper Atlas knows about, whether or not it has read one.
 *
 * This is the shallow half of the library: metadata and abstracts for as many papers as have
 * been harvested, which is far more than could ever be stored in full. Nothing here is
 * readable until it is imported, and the cards say so rather than implying otherwise.
 */
export default function DiscoverPage() {
  const [searchInput, setSearchInput] = useState("");
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<string | null>(null);
  const [sort, setSort] = useState<"relevance" | "newest">("relevance");
  const [offset, setOffset] = useState(0);

  /**
   * Library ids for papers imported during this visit.
   *
   * The search response's `in_library` is a snapshot from when the request was made, so a
   * paper imported a moment ago still reads as absent until the next search. Holding the new
   * ids here lets the card offer "Read" immediately, and survives paging back and forth.
   */
  const [justImported, setJustImported] = useState<Record<string, string>>({});

  // Debounced so a query runs when the reader pauses, not on every keystroke — at this scale
  // each keystroke would be a full-text search over the whole catalog.
  useEffect(() => {
    const timer = setTimeout(() => {
      setQuery(searchInput.trim());
      setOffset(0);
    }, 300);
    return () => clearTimeout(timer);
  }, [searchInput]);

  const stats = useAsync(() => catalog.stats(), []);

  const request = useMemo<CatalogQuery>(
    () => ({
      q: query || undefined,
      category: category ?? undefined,
      sort,
      limit: PAGE_SIZE,
      offset,
    }),
    [query, category, sort, offset],
  );

  const results = useAsync(
    () => catalog.search(request),
    [query, category ?? "", sort, offset],
  );

  const handleImported = useCallback((externalId: string, paperId: string) => {
    setJustImported((current) => ({ ...current, [externalId]: paperId }));
  }, []);

  const page = results.data;
  const showing = page ? page.items.length : 0;
  const hasMore = page ? page.offset + showing < page.total : false;

  return (
    <PageContainer>
      <PageHeader
        title="Discover"
        description={
          stats.data
            ? `Search ${stats.data.total.toLocaleString()} papers from ${describeSources(
                stats.data,
              )}${
                stats.data.earliest_year && stats.data.latest_year
                  ? `, ${stats.data.earliest_year}–${stats.data.latest_year}`
                  : ""
              }. Add any of them to your library to read and ask about.`
            : "Search the papers Atlas knows about, and add any of them to your library."
        }
      />

      <Card className="mt-4 p-3">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
          <div className="relative flex-1">
            <Search
              aria-hidden
              className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-ink-muted"
            />
            <input
              type="search"
              value={searchInput}
              onChange={(event) => setSearchInput(event.target.value)}
              placeholder="Search titles and abstracts…"
              aria-label="Search the catalog"
              // WebKit draws its own clear button inside a search input, which sat right
              // beside ours and gave the box two X's. Hiding it keeps the one that matches
              // the rest of the app, and `type="search"` is still worth having for the
              // on-screen keyboard and the semantics it carries.
              className="h-10 w-full rounded-md border border-border bg-surface pr-9 pl-9 text-sm text-ink placeholder:text-ink-muted focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none [&::-webkit-search-cancel-button]:appearance-none"
            />
            {searchInput ? (
              <button
                type="button"
                onClick={() => setSearchInput("")}
                aria-label="Clear the search"
                className="absolute top-1/2 right-2 -translate-y-1/2 rounded p-1 text-ink-muted hover:text-ink"
              >
                <X aria-hidden className="size-4" />
              </button>
            ) : null}
          </div>

          <div className="flex items-center gap-1">
            <span id="sort-label" className="sr-only">
              Sort results
            </span>
            {SORTS.map((option) => (
              <Button
                key={option.value}
                variant={sort === option.value ? "secondary" : "ghost"}
                size="sm"
                aria-pressed={sort === option.value}
                onClick={() => {
                  setSort(option.value);
                  setOffset(0);
                }}
              >
                {option.label}
              </Button>
            ))}
          </div>
        </div>

        {stats.data && stats.data.top_categories.length > 0 ? (
          <div className="mt-3 flex flex-wrap items-center gap-1.5 border-t border-border pt-3">
            <span className="mr-1 text-xs text-ink-muted">Fields:</span>
            <Button
              variant={category === null ? "secondary" : "ghost"}
              size="sm"
              aria-pressed={category === null}
              onClick={() => {
                setCategory(null);
                setOffset(0);
              }}
            >
              All
            </Button>
            {stats.data.top_categories.slice(0, 8).map((entry) => (
              <Button
                key={entry.category}
                variant={category === entry.category ? "secondary" : "ghost"}
                size="sm"
                aria-pressed={category === entry.category}
                onClick={() => {
                  setCategory(category === entry.category ? null : entry.category);
                  setOffset(0);
                }}
              >
                {entry.category}
                <span className="ml-1 text-ink-muted">{entry.count.toLocaleString()}</span>
              </Button>
            ))}
          </div>
        ) : null}
      </Card>

      {results.status === "loading" ? (
        <div className="mt-4 space-y-3" aria-busy="true" aria-label="Searching">
          {Array.from({ length: 4 }, (_, index) => (
            <Skeleton key={index} className="h-44 w-full" />
          ))}
        </div>
      ) : results.status === "error" ? (
        <div className="mt-4">
          <LoadError message={results.error ?? "That search failed."} onRetry={results.reload} />
        </div>
      ) : page && page.items.length === 0 ? (
        <div className="mt-4">
          <EmptyState
            icon={<Compass aria-hidden className="size-6" />}
            title={query ? "Nothing matched that" : "The catalog is empty"}
            description={
              query
                ? "Try fewer words, or a different field."
                : "Run the harvester to fill it: python -m scripts.harvest_arxiv --set cs"
            }
          />
        </div>
      ) : page ? (
        <>
          <p className="mt-4 text-sm text-ink-muted" aria-live="polite">
            {formatTotal(page)} {page.total === 1 ? "paper" : "papers"}
            {query ? <> matching &ldquo;{query}&rdquo;</> : null}
            {category ? <> in {category}</> : null}
          </p>

          <div className="mt-3 space-y-3">
            {page.items.map((paper) => (
              <CatalogCard
                key={paper.id}
                paper={paper}
                onImported={handleImported}
                libraryPaperId={justImported[paper.external_id]}
              />
            ))}
          </div>

          {(offset > 0 || hasMore) && (
            <div className="mt-4 flex items-center justify-between">
              <Button
                variant="ghost"
                size="sm"
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
              >
                <ChevronLeft aria-hidden className="size-4" />
                Previous
              </Button>
              <span className={cn("text-sm text-ink-muted")}>
                {offset + 1}–{offset + showing}
              </span>
              <Button
                variant="ghost"
                size="sm"
                disabled={!hasMore}
                onClick={() => setOffset(offset + PAGE_SIZE)}
              >
                Next
                <ChevronRight aria-hidden className="size-4" />
              </Button>
            </div>
          )}
        </>
      ) : null}
    </PageContainer>
  );
}
