import { api, API_BASE_URL, ApiError } from "@/lib/api";

export type ProcessingStatus = "pending" | "processing" | "ready" | "failed";
export type ReadingStatus = "unread" | "reading" | "read" | "revisit";
export type PaperSort = "recent" | "title" | "year" | "opened";

export interface Author {
  name: string;
}

export interface IngestionProgress {
  stage: string;
  label: string;
  progress: number;
  attempts: number;
  error_message: string | null;
}

export interface PaperSummary {
  id: string;
  title: string | null;
  display_title: string;
  authors: Author[];
  publication_year: number | null;
  venue: string | null;
  doi: string | null;
  arxiv_id: string | null;
  page_count: number | null;
  status: ProcessingStatus;
  failure_reason: string | null;
  reading_status: ReadingStatus;
  is_favorite: boolean;
  original_filename: string;
  file_size_bytes: number;
  last_opened_at: string | null;
  created_at: string;
  /** Present while the paper is still being read, so a list can show real progress. */
  ingestion: IngestionProgress | null;
}

export interface PaperDetail extends PaperSummary {
  abstract: string | null;
  section_count: number;
  chunk_count: number;
}

export interface PaperSection {
  id: string;
  ordinal: number;
  title: string;
  level: number;
  page_start: number | null;
  page_end: number | null;
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface LibraryStats {
  total: number;
  processing: number;
  failed: number;
  unread: number;
  favorites: number;
}

export interface Collection {
  id: string;
  name: string;
  description: string | null;
  paper_count: number;
  created_at: string;
}

export interface PaperQuery {
  search?: string;
  reading_status?: ReadingStatus;
  status?: ProcessingStatus;
  collection_id?: string;
  favorites_only?: boolean;
  sort?: PaperSort;
  limit?: number;
  offset?: number;
}

function toQueryString(query: PaperQuery): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    // Omit empty values entirely rather than sending `?search=`, which the API would
    // treat as a filter that matches everything with an empty string.
    if (value === undefined || value === null || value === "" || value === false) continue;
    params.set(key, String(value));
  }
  const encoded = params.toString();
  return encoded ? `?${encoded}` : "";
}

/** A paper is still being read when it is pending or processing. */
export function isProcessing(paper: PaperSummary): boolean {
  return paper.status === "pending" || paper.status === "processing";
}

export const papers = {
  list: (query: PaperQuery = {}) =>
    api.get<Page<PaperSummary>>(`/papers${toQueryString(query)}`),

  get: (id: string) => api.get<PaperDetail>(`/papers/${id}`),

  stats: () => api.get<LibraryStats>("/papers/stats"),

  sections: (id: string) => api.get<PaperSection[]>(`/papers/${id}/sections`),

  update: (id: string, patch: Partial<Pick<PaperSummary, "reading_status" | "is_favorite" | "title">>) =>
    api.patch<PaperDetail>(`/papers/${id}`, patch),

  markOpened: (id: string) => api.post<PaperDetail>(`/papers/${id}/opened`),

  reprocess: (id: string) => api.post<PaperDetail>(`/papers/${id}/reprocess`),

  remove: (id: string) => api.delete<void>(`/papers/${id}`),

  fileUrl: (id: string) => `${API_BASE_URL}/papers/${id}/file`,

  /**
   * Upload a PDF.
   *
   * Uses XMLHttpRequest rather than fetch because it reports upload progress, and a 30 MB
   * PDF on a slow connection needs a progress bar rather than an indefinite spinner.
   */
  upload(file: File, onProgress?: (percent: number) => void): Promise<PaperDetail> {
    return new Promise((resolve, reject) => {
      const body = new FormData();
      body.append("file", file);

      const request = new XMLHttpRequest();
      request.open("POST", `${API_BASE_URL}/papers`);
      request.withCredentials = true;

      request.upload.addEventListener("progress", (event) => {
        if (event.lengthComputable && onProgress) {
          onProgress(Math.round((event.loaded / event.total) * 100));
        }
      });

      request.addEventListener("load", () => {
        let parsed: unknown = null;
        try {
          parsed = JSON.parse(request.responseText);
        } catch {
          // Falls through to the generic error below.
        }

        if (request.status >= 200 && request.status < 300) {
          resolve(parsed as PaperDetail);
          return;
        }

        const envelope = parsed as { error?: { code?: string; message?: string } } | null;
        reject(
          new ApiError(
            (envelope?.error?.code as ApiError["code"]) ?? "internal_error",
            envelope?.error?.message ?? "Atlas couldn't upload that file. Try again.",
            request.status,
          ),
        );
      });

      request.addEventListener("error", () =>
        reject(new ApiError("network_error", "The upload was interrupted. Try again.", 0)),
      );
      request.addEventListener("abort", () =>
        reject(new ApiError("network_error", "The upload was cancelled.", 0)),
      );

      request.send(body);
    });
  },
};

export const collections = {
  list: () => api.get<Collection[]>("/collections"),
  create: (input: { name: string; description?: string }) =>
    api.post<Collection>("/collections", input),
  remove: (id: string) => api.delete<void>(`/collections/${id}`),
  addPaper: (collectionId: string, paperId: string) =>
    api.put<void>(`/collections/${collectionId}/papers/${paperId}`),
  removePaper: (collectionId: string, paperId: string) =>
    api.delete<void>(`/collections/${collectionId}/papers/${paperId}`),
};

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatAuthors(authors: Author[], limit = 3): string {
  if (authors.length === 0) return "Unknown authors";
  const names = authors.slice(0, limit).map((author) => author.name);
  if (authors.length > limit) return `${names.join(", ")} +${authors.length - limit}`;
  return names.join(", ");
}
