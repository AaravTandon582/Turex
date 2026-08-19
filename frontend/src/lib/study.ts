import { api } from "@/lib/api";

export type CardKind = "definition" | "concept" | "finding" | "method";
export type ReviewRating = "forgot" | "hard" | "good" | "easy";

export interface Flashcard {
  id: string;
  paper_id: string;
  chunk_id: string | null;
  front: string;
  back: string;
  kind: CardKind;
  source_excerpt: string;
  source_page: number | null;
  interval_days: number;
  due_at: string;
  review_count: number;
  lapse_count: number;
  last_reviewed_at: string | null;
}

export type QuestionKind = "multiple_choice" | "short_answer";

export interface Prerequisite {
  concept: string;
  why: string;
  chunk_id: string;
  source_excerpt: string;
  source_page: number | null;
}

export interface QuizQuestion {
  id: string;
  position: number;
  prompt: string;
  kind: QuestionKind;
  /** Empty for a short-answer question, which has nothing to choose between. */
  options: string[];
  /** Present only after the quiz has been submitted — the server withholds it until then. */
  correct_index?: number | null;
  /** What the paper says. Present only after submission, on short-answer questions. */
  model_answer?: string | null;
  written_answer?: string | null;
  explanation?: string;
  selected_index?: number | null;
  chunk_id?: string | null;
  source_excerpt?: string;
  source_page?: number | null;
}

export interface Quiz {
  id: string;
  paper_id: string;
  title: string;
  created_at: string;
  submitted_at: string | null;
  correct_count: number | null;
  question_count: number;
  questions: QuizQuestion[];
}

export interface PaperProgress {
  paper_id: string;
  title: string;
  card_count: number;
  due_count: number;
  mastered_count: number;
  last_reviewed_at: string | null;
  best_quiz_score: number | null;
}

export interface StudySummary {
  total_cards: number;
  due_now: number;
  mastered: number;
  reviews_last_seven_days: number;
  papers: PaperProgress[];
}

export const study = {
  generateCards: (paperId: string, count = 10) =>
    api.post<Flashcard[]>(`/papers/${paperId}/flashcards`, { count }),
  listCards: (params: { paperId?: string; dueOnly?: boolean; limit?: number } = {}) => {
    const query = new URLSearchParams();
    if (params.paperId) query.set("paper_id", params.paperId);
    if (params.dueOnly) query.set("due_only", "true");
    if (params.limit) query.set("limit", String(params.limit));
    const encoded = query.toString();
    return api.get<Flashcard[]>(`/flashcards${encoded ? `?${encoded}` : ""}`);
  },
  review: (cardId: string, rating: ReviewRating) =>
    api.post<Flashcard>(`/flashcards/${cardId}/reviews`, { rating }),
  deleteCard: (cardId: string) => api.delete<void>(`/flashcards/${cardId}`),

  generateQuiz: (paperId: string, count = 5) =>
    api.post<Quiz>(`/papers/${paperId}/quizzes`, { count }),
  listQuizzes: () => api.get<Quiz[]>("/quizzes"),
  getQuiz: (quizId: string) => api.get<Quiz>(`/quizzes/${quizId}`),
  generateShortAnswers: (paperId: string, count = 5) =>
    api.post<Quiz>(`/papers/${paperId}/short-answers`, { count }),
  prerequisites: (paperId: string) =>
    api.get<Prerequisite[]>(`/papers/${paperId}/prerequisites`),

  submitQuiz: (
    quizId: string,
    answers: Record<string, number>,
    written: Record<string, string> = {},
  ) => api.post<Quiz>(`/quizzes/${quizId}/submission`, { answers, written }),
  deleteQuiz: (quizId: string) => api.delete<void>(`/quizzes/${quizId}`),

  progress: () => api.get<StudySummary>("/study/progress"),
};

/** The four grades, in the order they are shown and numbered on the keyboard. */
export const RATINGS: readonly { value: ReviewRating; label: string; hint: string }[] = [
  { value: "forgot", label: "Forgot", hint: "See it again today" },
  { value: "hard", label: "Hard", hint: "Sooner than usual" },
  { value: "good", label: "Good", hint: "Normal interval" },
  { value: "easy", label: "Easy", hint: "Push it further out" },
] as const;

export const CARD_KIND_LABELS: Record<CardKind, string> = {
  definition: "Definition",
  concept: "Concept",
  finding: "Finding",
  method: "Method",
};

/** "in 3 days", "today", "2 days ago" — the only date phrasing this feature needs. */
export function dueLabel(dueAt: string): string {
  const days = Math.round((new Date(dueAt).getTime() - Date.now()) / 86_400_000);
  if (days <= 0) return "due now";
  if (days === 1) return "due tomorrow";
  if (days < 30) return `due in ${days} days`;
  const months = Math.round(days / 30);
  return `due in ${months} ${months === 1 ? "month" : "months"}`;
}
