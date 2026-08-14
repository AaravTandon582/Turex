import { api } from "@/lib/api";

export type HighlightColour = "important" | "question" | "method" | "result";

export interface Annotation {
  id: string;
  paper_id: string;
  page_number: number;
  text_offset: number;
  text_length: number;
  selected_text: string;
  colour: HighlightColour;
  note: string | null;
  created_at: string;
}

export interface CitationFormat {
  style: "bibtex" | "apa" | "mla";
  text: string;
  missing_fields: string[];
}

export interface CitationBundle {
  paper_id: string;
  formats: CitationFormat[];
}

/**
 * Highlight colours, named by what they mean rather than by hue.
 *
 * The intent survives a change of palette, and filtering by "every question I raised while
 * reading" is more useful than filtering by "everything yellow".
 */
export const HIGHLIGHT_COLOURS: {
  value: HighlightColour;
  label: string;
  /** Fill for the highlight itself. */
  swatch: string;
  /** Border used on the sidebar entry. */
  edge: string;
}[] = [
  { value: "important", label: "Important", swatch: "bg-highlight/35", edge: "border-l-highlight" },
  { value: "question", label: "Question", swatch: "bg-accent/25", edge: "border-l-accent" },
  { value: "method", label: "Method", swatch: "bg-success/25", edge: "border-l-success" },
  { value: "result", label: "Result", swatch: "bg-danger/20", edge: "border-l-danger" },
];

export function colourOf(value: HighlightColour) {
  return HIGHLIGHT_COLOURS.find((colour) => colour.value === value) ?? HIGHLIGHT_COLOURS[0];
}

export const annotations = {
  list: (paperId: string) => api.get<Annotation[]>(`/papers/${paperId}/annotations`),

  create: (
    paperId: string,
    input: {
      page_number: number;
      text_offset: number;
      selected_text: string;
      colour?: HighlightColour;
      note?: string;
    },
  ) => api.post<Annotation>(`/papers/${paperId}/annotations`, input),

  update: (
    id: string,
    patch: { colour?: HighlightColour; note?: string; clear_note?: boolean },
  ) => api.patch<Annotation>(`/annotations/${id}`, patch),

  remove: (id: string) => api.delete<void>(`/annotations/${id}`),

  citations: (paperId: string) => api.get<CitationBundle>(`/papers/${paperId}/citations`),
};
