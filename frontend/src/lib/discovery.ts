import { api } from "@/lib/api";

export interface Recommendation {
  paper_id: string;
  title: string;
  authors: string[];
  publication_year: number | null;
  reason: string;
  related_to_id: string | null;
  related_to_title: string | null;
}

export type GraphNodeKind = "paper" | "concept" | "project" | "question";

export interface GraphNode {
  id: string;
  kind: GraphNodeKind;
  label: string;
  weight: number;
  entity_id: string | null;
}

export interface GraphEdge {
  source: string;
  target: string;
  kind: "mentions" | "gathered_in" | "asks";
}

export interface Graph {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export const discovery = {
  recommendations: (limit = 6) => api.get<Recommendation[]>(`/recommendations?limit=${limit}`),
  graph: () => api.get<Graph>("/graph"),
};

/** How each node kind is drawn. Colour carries meaning, so the legend is short. */
export const NODE_STYLES: Record<
  GraphNodeKind,
  { fill: string; stroke: string; text: string; label: string }
> = {
  paper: {
    fill: "var(--accent-soft)",
    stroke: "var(--accent)",
    text: "var(--ink)",
    label: "Paper",
  },
  concept: {
    fill: "var(--surface-sunken)",
    stroke: "var(--border-strong)",
    text: "var(--ink-muted)",
    label: "Concept",
  },
  project: {
    fill: "var(--success-soft)",
    stroke: "var(--success)",
    text: "var(--ink)",
    label: "Project",
  },
  question: {
    fill: "var(--warning-soft)",
    stroke: "var(--warning)",
    text: "var(--ink)",
    label: "Question",
  },
};
