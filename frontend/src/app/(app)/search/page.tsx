"use client";

import { Search, Sparkles } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { PageContainer } from "@/components/layout/page-container";
import { LoadError } from "@/components/ui/async-boundary";
import { Badge, Card, EmptyState, PageHeader, Skeleton } from "@/components/ui/primitives";
import { assistant, type SearchResult } from "@/lib/assistant";
import { cn } from "@/lib/cn";
import { describe } from "@/lib/use-async";

const EXAMPLES = [
  "methods for reducing hallucination",
  "papers challenging this conclusion",
  "how attention scales with sequence length",
];

/**
 * Semantic search across the library.
 *
 * Distinct from the library's title filter: this searches inside papers, by meaning as well
 * as by keyword, and returns the passage — because when you are hunting for a half-remembered
 * claim, the paragraph is the answer, not the paper.
 */
export default function SearchPage() {
  const [input, setInput] = useState("");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  // Bumped by the retry button. Part of the effect's dependencies, so retrying an identical
  // query actually re-runs it rather than being skipped as unchanged.
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const timer = setTimeout(() => setQuery(input.trim()), 300);
    return () => clearTimeout(timer);
  }, [input]);

  useEffect(() => {
    if (!query) {
      setResults(null);
      setFailure(null);
      return;
    }
    let cancelled = false;
    setSearching(true);
    setFailure(null);
    void assistant
      .search(query, { limit: 20 })
      .then((response) => !cancelled && setResults(response.results))
      // A failed search must not render as "no results" — that would send the reader looking
      // for a paper they already have.
      .catch((caught) => {
        if (cancelled) return;
        setResults(null);
        setFailure(describe(caught));
      })
      .finally(() => !cancelled && setSearching(false));
    return () => {
      cancelled = true;
    };
  }, [query, attempt]);

  return (
    <PageContainer>
      <PageHeader
        title="Search"
        description="Search inside your papers by meaning, not just by keyword. Results are passages, with the page they came from."
      />

      <div className="relative mt-6">
        <Search
          className="pointer-events-none absolute top-1/2 left-3.5 size-4 -translate-y-1/2 text-ink-subtle"
          aria-hidden
        />
        <input
          type="search"
          autoFocus
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder="What are you looking for?"
          aria-label="Search your papers"
          className="h-11 w-full rounded-md border border-border bg-surface pr-3 pl-10 text-[15px] text-ink placeholder:text-ink-subtle focus:border-accent focus:ring-3 focus:ring-[var(--accent-ring)] focus:outline-none"
        />
      </div>

      {!query && (
        <div className="mt-3 flex flex-wrap gap-2">
          {EXAMPLES.map((example) => (
            <button
              key={example}
              type="button"
              onClick={() => setInput(example)}
              className="rounded-full border border-border bg-surface px-3 py-1 text-[12px] text-ink-muted transition-colors hover:border-border-strong hover:text-ink"
            >
              {example}
            </button>
          ))}
        </div>
      )}

      <div className="mt-6">
        {failure ? (
          <LoadError message={failure} onRetry={() => setAttempt((count) => count + 1)} />
        ) : searching && results === null ? (
          <div className="space-y-3" aria-busy>
            {Array.from({ length: 3 }, (_, index) => (
              <Card key={index} className="p-4">
                <Skeleton className="h-3 w-1/3" />
                <Skeleton className="mt-2.5 h-4 w-full" />
                <Skeleton className="mt-1.5 h-4 w-4/5" />
              </Card>
            ))}
            <span className="sr-only">Searching</span>
          </div>
        ) : results === null ? (
          <EmptyState
            icon={<Sparkles />}
            title="Search your library"
            description="Turex matches on meaning and on exact terms at once, so a paraphrase and a gene name both find what you meant."
          />
        ) : results.length === 0 ? (
          <EmptyState
            icon={<Search />}
            title="Nothing found"
            description="No passage in your library matches that. Try different words, or add the paper you are thinking of."
          />
        ) : (
          <>
            <p className="text-[13px] text-ink-muted" data-tabular>
              {results.length} {results.length === 1 ? "passage" : "passages"}
            </p>
            <ul className="mt-3 space-y-3">
              {results.map((result) => (
                <li key={result.chunk_id}>
                  <ResultCard result={result} />
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </PageContainer>
  );
}

function ResultCard({ result }: { result: SearchResult }) {
  return (
    <Card className="p-4 transition-[border-color] duration-150 hover:border-border-strong">
      <div className="flex items-start justify-between gap-3">
        <Link
          href={`/library/${result.paper_id}`}
          className="min-w-0 truncate text-[13px] font-medium text-ink hover:text-accent"
        >
          {result.paper_title}
        </Link>
        <Badge tone={result.found_by === "both" ? "accent" : "neutral"}>
          {result.found_by === "both"
            ? "meaning + keyword"
            : result.found_by === "meaning"
              ? "meaning"
              : "keyword"}
        </Badge>
      </div>

      <p className="mt-1 font-mono text-[11px] text-ink-subtle">{result.locator}</p>

      <p className={cn("measure mt-2.5 text-[14px] leading-relaxed text-ink-muted")}>
        {result.content.length > 500 ? `${result.content.slice(0, 500)}…` : result.content}
      </p>
    </Card>
  );
}
