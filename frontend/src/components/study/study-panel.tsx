"use client";

import { GraduationCap, ListChecks, PenLine, Sparkles } from "lucide-react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import { study, type Flashcard, type Prerequisite } from "@/lib/study";

/**
 * Generate study material for one paper, from the paper's own page.
 *
 * Placed here rather than on the study page because generating is something you decide while
 * looking at a paper you have just finished, not while looking at a review queue.
 */
export function StudyPanel({ paperId }: { paperId: string }) {
  const router = useRouter();
  const [cards, setCards] = useState<Flashcard[] | null>(null);
  const [busy, setBusy] = useState<"cards" | "quiz" | "short" | "prereq" | null>(null);
  const [prerequisites, setPrerequisites] = useState<Prerequisite[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // Left null on failure: the count is an assertion about the reader's cards, so it is
    // better shown as absent than as zero.
    void study
      .listCards({ paperId, limit: 200 })
      .then(setCards)
      .catch(() => undefined);
  }, [paperId]);

  async function generateCards() {
    setBusy("cards");
    setError(null);
    try {
      const created = await study.generateCards(paperId, 10);
      setCards((current) => [...created, ...(current ?? [])]);
    } catch (caught) {
      setError(describe(caught));
    } finally {
      setBusy(null);
    }
  }

  async function generateShortAnswers() {
    setBusy("short");
    setError(null);
    try {
      const quiz = await study.generateShortAnswers(paperId, 5);
      router.push(`/study/quiz/${quiz.id}`);
    } catch (caught) {
      setError(describe(caught));
      setBusy(null);
    }
  }

  async function loadPrerequisites() {
    setBusy("prereq");
    setError(null);
    try {
      setPrerequisites(await study.prerequisites(paperId));
    } catch (caught) {
      setError(describe(caught));
    } finally {
      setBusy(null);
    }
  }

  async function generateQuiz() {
    setBusy("quiz");
    setError(null);
    try {
      const quiz = await study.generateQuiz(paperId, 5);
      router.push(`/study/quiz/${quiz.id}`);
    } catch (caught) {
      setError(describe(caught));
      setBusy(null);
    }
  }

  const due = cards?.filter((card) => new Date(card.due_at) <= new Date()).length ?? 0;

  return (
    <section className="mt-8" aria-labelledby="study-heading">
      <h2 id="study-heading" className="text-[13px] font-semibold text-ink-muted">
        Study
      </h2>
      <p className="measure mt-1 text-[13px] text-ink-muted">
        Atlas writes cards and questions from this paper&rsquo;s own passages, and shows you the
        passage behind every answer.
      </p>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button size="sm" variant="secondary" loading={busy === "cards"} onClick={() => void generateCards()}>
          <GraduationCap />
          {cards && cards.length > 0 ? "Generate more cards" : "Generate flashcards"}
        </Button>
        <Button size="sm" variant="secondary" loading={busy === "quiz"} onClick={() => void generateQuiz()}>
          <ListChecks />
          Take a quiz
        </Button>
        <Button
          size="sm"
          variant="secondary"
          loading={busy === "short"}
          onClick={() => void generateShortAnswers()}
        >
          <PenLine />
          Answer from memory
        </Button>
        <Button
          size="sm"
          variant="secondary"
          loading={busy === "prereq"}
          onClick={() => void loadPrerequisites()}
        >
          <Sparkles />
          What should I know first?
        </Button>

        {cards && cards.length > 0 && (
          <Link
            href="/study"
            className="text-[13px] font-medium text-accent hover:underline"
            data-tabular
          >
            {cards.length} {cards.length === 1 ? "card" : "cards"}
            {due > 0 && `, ${due} due`}
          </Link>
        )}
      </div>

      {error && (
        <p role="alert" className="mt-2 text-[13px] text-danger">
          {error}
        </p>
      )}

      {prerequisites !== null && (
        <div className="mt-4">
          <h3 className="text-[12px] font-semibold text-ink-muted">
            Before this paper makes sense
          </h3>
          {prerequisites.length === 0 ? (
            <p className="mt-1 text-[13px] text-ink-subtle">
              Nothing in these passages assumes prior knowledge that isn&rsquo;t explained here.
            </p>
          ) : (
            <ol className="mt-2 space-y-2">
              {prerequisites.map((item) => (
                <li key={item.concept} className="measure">
                  <p className="text-[13px] font-medium text-ink">{item.concept}</p>
                  <p className="mt-0.5 text-[13px] leading-relaxed text-ink-muted">{item.why}</p>
                  {item.source_page && (
                    <p className="mt-0.5 text-[12px] text-ink-subtle">
                      assumed on page {item.source_page}
                    </p>
                  )}
                </li>
              ))}
            </ol>
          )}
        </div>
      )}
    </section>
  );
}

function describe(caught: unknown): string {
  if (caught instanceof ApiError) {
    // `not_configured` means no model provider is set up on this deployment. Saying so beats
    // "something went wrong", which sends the reader looking for a fault in their paper.
    return caught.code === "not_configured"
      ? "Study material needs an AI provider configured on the server."
      : caught.message;
  }
  return "That didn't work. Try again.";
}
