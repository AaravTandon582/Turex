import { api } from "@/lib/api";
import type { PaperDetail } from "@/lib/papers";

/** A paper Atlas knows about, which may or may not be in this reader's library. */
export interface CatalogPaper {
  id: string;
  /** Which index this came from: arXiv preprints, or OpenAlex's cross-field corpus. */
  source: "arxiv" | "openalex";
  /** Its id within that source — an arXiv id, or an OpenAlex work id. */
  external_id: string;
  doi: string | null;
  title: string;
  abstract: string | null;
  authors: { name: string }[];
  categories: string[];
  primary_category: string | null;
  journal_ref: string | null;
  comments: string | null;
  published_on: string | null;
  updated_on: string | null;
  landing_url: string | null;
  /**
   * Where the free file is, when there is one.
   *
   * Null means Atlas cannot fetch this paper — an OpenAlex work that is not open access. The
   * card offers to open the publisher's page rather than an import that would fail.
   */
  pdf_url: string | null;
  /** Whether this reader has already imported it, so the card offers "Open" not "Import". */
  in_library: boolean;
}

export interface CatalogPage {
  items: CatalogPaper[];
  total: number;
  /**
   * Whether `total` is a count or a floor.
   *
   * Counting every match of a common word across a large catalog costs more than the search,
   * so the count stops at a ceiling. When this is false the UI must render "1,000+", not a
   * precise-looking number that is not the truth.
   */
  total_is_exact: boolean;
  limit: number;
  offset: number;
}

export interface CatalogStats {
  total: number;
  with_abstract: number;
  earliest_year: number | null;
  latest_year: number | null;
  top_categories: { category: string; count: number }[];
}

export interface CatalogQuery {
  q?: string;
  category?: string;
  yearFrom?: number;
  yearTo?: number;
  sort?: "relevance" | "newest";
  limit?: number;
  offset?: number;
}

function parameters(query: CatalogQuery): string {
  const search = new URLSearchParams();
  if (query.q) search.set("q", query.q);
  if (query.category) search.set("category", query.category);
  if (query.yearFrom !== undefined) search.set("year_from", String(query.yearFrom));
  if (query.yearTo !== undefined) search.set("year_to", String(query.yearTo));
  if (query.sort) search.set("sort", query.sort);
  search.set("limit", String(query.limit ?? 20));
  search.set("offset", String(query.offset ?? 0));
  return search.toString();
}

export const catalog = {
  search: (query: CatalogQuery) => api.get<CatalogPage>(`/catalog/search?${parameters(query)}`),
  stats: () => api.get<CatalogStats>("/catalog/stats"),
  get: (id: string) => api.get<CatalogPaper>(`/catalog/${id}`),
  /**
   * Download the PDF and add it to the library.
   *
   * Resolves once the paper exists and ingestion is queued — not once it is readable. The
   * caller polls the paper for that, the same as it does after an upload.
   */
  import: (id: string) => api.post<PaperDetail>(`/catalog/${id}/import`),
};

/** "Vaswani, Shazeer, Parmar and 5 others" — a citation line, not a wall of names. */
export function formatAuthors(authors: { name: string }[], visible = 3): string {
  if (authors.length === 0) return "Unknown authors";
  const names = authors.map((author) => author.name);
  if (names.length <= visible) {
    if (names.length === 1) return names[0];
    return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
  }
  return `${names.slice(0, visible).join(", ")} and ${names.length - visible} others`;
}

/** `1,000+` when the count stopped at its ceiling, so the number is never overstated. */
export function formatTotal(page: Pick<CatalogPage, "total" | "total_is_exact">): string {
  return `${page.total.toLocaleString()}${page.total_is_exact ? "" : "+"}`;
}
