import { api } from "@/lib/api";

export type CellKind = "code" | "markdown";
/** `stale` means the source changed after the output was produced — see the server model. */
export type CellStatus = "idle" | "ok" | "error" | "stale";

export interface AnalysisCell {
  id: string;
  ordinal: number;
  kind: CellKind;
  source: string;
  output: string | null;
  image: string | null;
  error: string | null;
  status: CellStatus;
  duration_ms: number | null;
  executed_at: string | null;
}

export interface Analysis {
  id: string;
  title: string;
  description: string | null;
  project_id: string | null;
  experiment_id: string | null;
  last_run_at: string | null;
  created_at: string;
  cells: AnalysisCell[];
}

export const analyses = {
  list: (projectId?: string) =>
    api.get<Analysis[]>(`/analyses${projectId ? `?project_id=${projectId}` : ""}`),

  get: (id: string) => api.get<Analysis>(`/analyses/${id}`),

  create: (body: { title: string; description?: string; project_id?: string }) =>
    api.post<Analysis>("/analyses", body),

  update: (id: string, body: { title?: string; description?: string }) =>
    api.patch<Analysis>(`/analyses/${id}`, body),

  remove: (id: string) => api.delete<void>(`/analyses/${id}`),

  addCell: (id: string, body: { kind?: CellKind; source?: string; after?: string }) =>
    api.post<AnalysisCell>(`/analyses/${id}/cells`, body),

  saveCell: (id: string, cellId: string, body: { source: string; kind?: CellKind }) =>
    api.put<AnalysisCell>(`/analyses/${id}/cells/${cellId}`, body),

  /**
   * Record what this browser got when it ran the cell.
   *
   * The server does not execute anything — it writes down the answer. Named for what the
   * person did rather than what the server does, because that is what the URL means to a
   * reader of the API.
   */
  recordRun: (
    id: string,
    cellId: string,
    body: { output?: string; image?: string | null; error?: string | null; duration_ms?: number },
  ) => api.post<AnalysisCell>(`/analyses/${id}/cells/${cellId}/run`, body),

  moveCell: (id: string, cellId: string, offset: -1 | 1) =>
    api.post<Analysis>(`/analyses/${id}/cells/${cellId}/move`, { offset }),

  removeCell: (id: string, cellId: string) => api.delete<void>(`/analyses/${id}/cells/${cellId}`),
};
