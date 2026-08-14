"use client";

import { GraduationCap, ListChecks } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { ReviewSession } from "@/components/study/review-session";
import { PageContainer } from "@/components/layout/page-container";
import { Button } from "@/components/ui/button";
import { Card, EmptyState, PageHeader, Skeleton } from "@/components/ui/primitives";
import { study, type Flashcard, type Quiz, type StudySummary } from "@/lib/study";

export default function StudyPage() {
  const [summary, setSummary] = useState<StudySummary | null>(null);
  const [quizzes, setQuizzes] = useState<Quiz[]>([]);
  const [session, setSession] = useState<Flashcard[] | null>(null);
  const [starting, setStarting] = useState(false);

  const load = useCallback(async () => {
    const [progress, recent] = await Promise.all([
      study.progress().catch(() => null),
      study.listQuizzes().catch(() => []),
    ]);
    if (progress) setSummary(progress);
    setQuizzes(recent);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function startSession() {
    setStarting(true);
    try {
      const due = await study.listCards({ dueOnly: true, limit: 40 });
      setSession(due);
    } finally {
      setStarting(false);
    }
  }

  if (session) {
    return (
      <PageContainer width="reading">
        <ReviewSession
          cards={session}
          onFinished={() => {
            setSession(null);
            void load();
          }}
        />
      </PageContainer>
    );
  }

  return (
    <PageContainer>
      <PageHeader
        title="Study"
        description="Cards and questions written from passages of your own papers. Every answer shows the passage it came from, so you can check it rather than trust it."
      />

      {!summary ? (
        <Skeleton className="mt-6 h-40 w-full rounded-lg" />
      ) : summary.total_cards === 0 ? (
        <EmptyState
          className="mt-6"
          icon={<GraduationCap />}
          title="No cards yet"
          description="Open a paper you have read and generate a set. Atlas writes cards from the paper's own passages — nothing is invented."
          action={
            <Button asChild size="sm">
              <Link href="/library">Go to your library</Link>
            </Button>
          }
        />
      ) : (
        <>
          <div className="mt-6 grid gap-3 sm:grid-cols-4">
            <Stat label="Due now" value={summary.due_now} emphasis={summary.due_now > 0} />
            <Stat label="Total cards" value={summary.total_cards} />
            <Stat label="Mastered" value={summary.mastered} />
            <Stat label="Reviews this week" value={summary.reviews_last_seven_days} />
          </div>

          <div className="mt-5">
            <Button onClick={() => void startSession()} loading={starting} disabled={summary.due_now === 0}>
              {summary.due_now > 0
                ? `Review ${summary.due_now} ${summary.due_now === 1 ? "card" : "cards"}`
                : "Nothing due right now"}
            </Button>
            {summary.due_now === 0 && (
              <p className="mt-2 text-[12px] text-ink-subtle">
                Cards come back on a schedule that stretches as you keep getting them right.
              </p>
            )}
          </div>

          <section className="mt-10" aria-labelledby="by-paper">
            <h2 id="by-paper" className="mb-3 text-[13px] font-semibold text-ink-muted">
              By paper
            </h2>
            <ul className="space-y-2">
              {summary.papers.map((paper) => (
                <li key={paper.paper_id}>
                  <Card className="transition-[border-color] hover:border-border-strong">
                    <Link href={`/library/${paper.paper_id}`} className="block rounded-lg p-3.5">
                      <p className="line-clamp-1 text-[14px] font-medium text-ink">{paper.title}</p>
                      <p className="mt-1 text-[12px] text-ink-subtle" data-tabular>
                        {paper.card_count} cards · {paper.mastered_count} mastered
                        {paper.due_count > 0 && (
                          <span className="text-accent"> · {paper.due_count} due</span>
                        )}
                        {paper.best_quiz_score !== null && (
                          <> · best quiz {Math.round(paper.best_quiz_score * 100)}%</>
                        )}
                      </p>
                    </Link>
                  </Card>
                </li>
              ))}
            </ul>
          </section>
        </>
      )}

      {quizzes.length > 0 && (
        <section className="mt-10" aria-labelledby="quizzes">
          <h2 id="quizzes" className="mb-3 text-[13px] font-semibold text-ink-muted">
            Quizzes
          </h2>
          <ul className="space-y-2">
            {quizzes.map((quiz) => (
              <li key={quiz.id}>
                <Card className="transition-[border-color] hover:border-border-strong">
                  <Link
                    href={`/study/quiz/${quiz.id}`}
                    className="flex items-center gap-3 rounded-lg p-3.5"
                  >
                    <ListChecks className="size-4 shrink-0 text-ink-subtle" />
                    <span className="min-w-0 flex-1">
                      <span className="block line-clamp-1 text-[14px] font-medium text-ink">
                        {quiz.title}
                      </span>
                      <span className="mt-0.5 block text-[12px] text-ink-subtle" data-tabular>
                        {quiz.question_count} questions ·{" "}
                        {quiz.submitted_at
                          ? `scored ${quiz.correct_count}/${quiz.question_count}`
                          : "not taken yet"}
                      </span>
                    </span>
                  </Link>
                </Card>
              </li>
            ))}
          </ul>
        </section>
      )}
    </PageContainer>
  );
}

function Stat({
  label,
  value,
  emphasis = false,
}: {
  label: string;
  value: number;
  emphasis?: boolean;
}) {
  return (
    <Card className="p-3.5">
      <p className="text-[12px] text-ink-subtle">{label}</p>
      <p
        className={`mt-1 text-2xl font-semibold ${emphasis ? "text-accent" : "text-ink"}`}
        data-tabular
      >
        {value}
      </p>
    </Card>
  );
}
