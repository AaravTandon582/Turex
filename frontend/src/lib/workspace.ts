import { api } from "@/lib/api";

export type ProjectStatus = "active" | "paused" | "complete";
export type HypothesisStatus =
  | "proposed"
  | "testing"
  | "supported"
  | "weakly_supported"
  | "contradicted"
  | "abandoned";
export type EvidenceStance = "supports" | "contradicts";
export type ExperimentStatus = "planned" | "running" | "complete" | "abandoned";
export type TaskStatus = "todo" | "doing" | "done";

export interface Project {
  id: string;
  name: string;
  research_question: string | null;
  description: string | null;
  status: ProjectStatus;
  created_at: string;
  updated_at: string;
  paper_count: number;
  hypothesis_count: number;
  experiment_count: number;
  note_count: number;
  open_task_count: number;
}

export interface ProjectPaper {
  paper_id: string;
  title: string;
  authors: string[];
  publication_year: number | null;
  relevance_note: string | null;
}

export interface Evidence {
  id: string;
  chunk_id: string | null;
  paper_id: string | null;
  stance: EvidenceStance;
  paper_title: string;
  locator: string;
  quoted_text: string;
  reasoning: string | null;
  created_at: string;
}

export interface Hypothesis {
  id: string;
  project_id: string | null;
  statement: string;
  motivation: string | null;
  assumptions: string | null;
  status: HypothesisStatus;
  position: number;
  created_at: string;
  supporting_count: number;
  contradicting_count: number;
}

export interface HypothesisDetail extends Hypothesis {
  evidence: Evidence[];
}

export interface Experiment {
  id: string;
  project_id: string | null;
  hypothesis_id: string | null;
  title: string;
  objective: string | null;
  independent_variables: string | null;
  dependent_variables: string | null;
  controls: string | null;
  confounders: string | null;
  dataset: string | null;
  methodology: string | null;
  metrics: string | null;
  expected_result: string | null;
  actual_result: string | null;
  interpretation: string | null;
  status: ExperimentStatus;
  run_on: string | null;
  created_at: string;
}

export interface Note {
  id: string;
  title: string | null;
  content: string;
  project_id: string | null;
  paper_id: string | null;
  hypothesis_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface Task {
  id: string;
  project_id: string;
  title: string;
  status: TaskStatus;
  position: number;
}

/**
 * Hypothesis states and how they read.
 *
 * `weakly_supported` is deliberately distinct from `supported`: collapsing them is how a
 * tentative result quietly becomes a confident one.
 */
export const HYPOTHESIS_STATUSES: {
  value: HypothesisStatus;
  label: string;
  tone: "neutral" | "accent" | "success" | "warning" | "danger";
}[] = [
  { value: "proposed", label: "Proposed", tone: "neutral" },
  { value: "testing", label: "Testing", tone: "accent" },
  { value: "supported", label: "Supported", tone: "success" },
  { value: "weakly_supported", label: "Weakly supported", tone: "warning" },
  { value: "contradicted", label: "Contradicted", tone: "danger" },
  { value: "abandoned", label: "Abandoned", tone: "neutral" },
];

export const EXPERIMENT_STATUSES: { value: ExperimentStatus; label: string }[] = [
  { value: "planned", label: "Planned" },
  { value: "running", label: "Running" },
  { value: "complete", label: "Complete" },
  { value: "abandoned", label: "Abandoned" },
];

export function hypothesisStatus(value: HypothesisStatus) {
  return HYPOTHESIS_STATUSES.find((status) => status.value === value) ?? HYPOTHESIS_STATUSES[0];
}

export const workspace = {
  // -- projects --------------------------------------------------------------
  listProjects: () => api.get<Project[]>("/projects"),
  createProject: (input: { name: string; research_question?: string; description?: string }) =>
    api.post<Project>("/projects", input),
  getProject: (id: string) => api.get<Project>(`/projects/${id}`),
  updateProject: (id: string, patch: Partial<Pick<Project, "name" | "research_question" | "description" | "status">>) =>
    api.patch<Project>(`/projects/${id}`, patch),
  deleteProject: (id: string) => api.delete<void>(`/projects/${id}`),

  projectPapers: (id: string) => api.get<ProjectPaper[]>(`/projects/${id}/papers`),
  attachPaper: (id: string, paperId: string, relevanceNote?: string) =>
    api.put<void>(`/projects/${id}/papers`, {
      paper_id: paperId,
      relevance_note: relevanceNote,
    }),
  detachPaper: (id: string, paperId: string) =>
    api.delete<void>(`/projects/${id}/papers/${paperId}`),

  // -- hypotheses ------------------------------------------------------------
  listHypotheses: (projectId?: string) =>
    api.get<Hypothesis[]>(`/hypotheses${projectId ? `?project_id=${projectId}` : ""}`),
  createHypothesis: (input: {
    statement: string;
    project_id?: string;
    motivation?: string;
    assumptions?: string;
  }) => api.post<Hypothesis>("/hypotheses", input),
  getHypothesis: (id: string) => api.get<HypothesisDetail>(`/hypotheses/${id}`),
  updateHypothesis: (
    id: string,
    patch: Partial<Pick<Hypothesis, "statement" | "motivation" | "assumptions" | "status">>,
  ) => api.patch<Hypothesis>(`/hypotheses/${id}`, patch),
  deleteHypothesis: (id: string) => api.delete<void>(`/hypotheses/${id}`),

  attachEvidence: (
    hypothesisId: string,
    input: { chunk_id: string; stance: EvidenceStance; reasoning?: string },
  ) => api.post<Evidence>(`/hypotheses/${hypothesisId}/evidence`, input),
  detachEvidence: (id: string) => api.delete<void>(`/evidence/${id}`),

  // -- experiments -----------------------------------------------------------
  listExperiments: (projectId?: string) =>
    api.get<Experiment[]>(`/experiments${projectId ? `?project_id=${projectId}` : ""}`),
  createExperiment: (input: Record<string, unknown>) =>
    api.post<Experiment>("/experiments", input),
  getExperiment: (id: string) => api.get<Experiment>(`/experiments/${id}`),
  updateExperiment: (id: string, patch: Record<string, unknown>) =>
    api.patch<Experiment>(`/experiments/${id}`, patch),
  deleteExperiment: (id: string) => api.delete<void>(`/experiments/${id}`),

  // -- notes -----------------------------------------------------------------
  listNotes: (params: { projectId?: string; paperId?: string; search?: string } = {}) => {
    const query = new URLSearchParams();
    if (params.projectId) query.set("project_id", params.projectId);
    if (params.paperId) query.set("paper_id", params.paperId);
    if (params.search) query.set("search", params.search);
    const encoded = query.toString();
    return api.get<Note[]>(`/notes${encoded ? `?${encoded}` : ""}`);
  },
  createNote: (input: Partial<Pick<Note, "title" | "content" | "project_id" | "paper_id">>) =>
    api.post<Note>("/notes", input),
  updateNote: (id: string, patch: Partial<Pick<Note, "title" | "content" | "project_id">>) =>
    api.patch<Note>(`/notes/${id}`, patch),
  deleteNote: (id: string) => api.delete<void>(`/notes/${id}`),

  // -- tasks -----------------------------------------------------------------
  listTasks: (projectId: string) => api.get<Task[]>(`/projects/${projectId}/tasks`),
  createTask: (projectId: string, title: string) =>
    api.post<Task>(`/projects/${projectId}/tasks`, { title }),
  updateTask: (id: string, patch: Partial<Pick<Task, "title" | "status">>) =>
    api.patch<Task>(`/tasks/${id}`, patch),
  deleteTask: (id: string) => api.delete<void>(`/tasks/${id}`),
};
