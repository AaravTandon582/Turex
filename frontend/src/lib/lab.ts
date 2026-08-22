import { api, API_BASE_URL } from "@/lib/api";

/** One appended entry. There is no update type, because there is no update. */
export interface LabEntry {
  id: string;
  sequence: number;
  title: string | null;
  body: string;
  recorded_at: string;
  project_id: string | null;
  experiment_id: string | null;
  paper_id: string | null;
  /**
   * Both hashes, so the chain can be checked outside Turex.
   *
   * Evidence nobody can verify independently is not evidence — the hashing rule is documented
   * in the backend's `models/lab.py`, and these two fields are everything needed to apply it.
   */
  entry_hash: string;
  previous_hash: string;
}

export interface LabEntryPage {
  items: LabEntry[];
  total: number;
  limit: number;
  offset: number;
}

export interface ChainBreak {
  sequence: number;
  entry_id: string;
  recorded_at: string;
  reason: string;
}

export interface ChainReport {
  entries: number;
  /** The only field worth branching on. The rest is detail for a person reading it. */
  intact: boolean;
  first_break_at: number | null;
  breaks: ChainBreak[];
  checked_at: string;
}

export const lab = {
  list: (projectId?: string, limit = 50) =>
    api.get<LabEntryPage>(
      `/lab/entries?limit=${limit}${projectId ? `&project_id=${projectId}` : ""}`,
    ),

  append: (body: { title?: string; body: string; project_id?: string; paper_id?: string }) =>
    api.post<LabEntry>("/lab/entries", body),

  verify: () => api.get<ChainReport>("/lab/verify"),
};

/**
 * Where a project's bundle is downloaded from.
 *
 * A plain URL rather than a fetch: the response is a zip with a `Content-Disposition`, and
 * letting the browser handle it keeps the filename the server chose and holds nothing in
 * memory.
 */
export function projectBundleUrl(projectId: string): string {
  return `${API_BASE_URL}/projects/${projectId}/export`;
}
