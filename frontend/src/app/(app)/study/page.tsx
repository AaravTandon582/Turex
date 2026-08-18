"use client";

import { GraduationCap, ListChecks } from "lucide-react";
import Link from "next/link";
import { useCallback, useState } from "react";

import { ReviewSession } from "@/components/study/review-session";
import { PageContainer } from "@/components/layout/page-container";
import { Button } from "@/components/ui/button";
import { AsyncBoundary } from "@/components/ui/async-boundary";
import { Card, EmptyState, PageHeader, Skeleton } from "@/components/ui/primitives";
import { study, type Flashcard } from "@/lib/study";
import { useAsync } from "@/lib/use-async";

export default function StudyPage() {
  const summary = useAsync(() => study.progress(), []);
  const quizzes = useAsync(() => study.listQuizzes(), []);
  const [session, setSession] = useState<Flashcard[] | null>(null);
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);

  const reload = useCallback(() => {
    summary.reload();
    quizzes.reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function startSession() {
    setStarting(true);
    setStartError(null);
    try {
      setSession(await study.listCards({ dueOnly: true, limit: 40 }));
    } catch {
      setStartError("Atlas couldn't load your due cards. Check your connection and try again.");
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
            reload();
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

      <AsyncBoundary state={summary} skeleton={<Skeleton className="mt-6 h-40 w-full rounded-lg" />}>
        {(progress) =>
          progress.total_cards === 0 ? (
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
              <div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
                <Stat label="Due now" value={progress.due_now} emphasis={progress.due_now > 0} />
                <Stat label="Total cards" value={progress.total_cards} />
                <Stat label="Mastered" value={progress.mastered} />
                <Stat label="Reviews this week" value={progress.reviews_last_seven_days} />
              </div>

              <div className="mt-5">
                <Button
                  onClick={() => void startSession()}
                  loading={starting}
                  disabled={progress.due_now === 0}
                >
                  {progress.due_now > 0
                    ? `Review ${progress.due_now} ${progress.due_now === 1 ? "card" : "cards"}`
                    : "Nothing due right now"}
                </Button>
                {progress.due_now === 0 && (
                  <p className="mt-2 text-[12px] text-ink-subtle">
                    Cards come back on a schedule that stretches as you keep getting them right.
                  </p>
                )}
                {startError && (
                  <p role="alert" className="mt-2 text-[13px] text-danger">
                    {startError}
                  </p>
                )}
              </div>

              <section className="mt-10" aria-labelledby="by-paper">
                <h2 id="by-paper" className="mb-3 text-[13px] font-semibold text-ink-muted">
                  By paper
                </h2>
                <ul className="space-y-2">
                  {progress.papers.map((paper) => (
                    <li key={paper.paper_id}>
                      <Card className="transition-[border-color] hover:border-border-strong">
                        <Link href={`/library/${paper.paper_id}`} className="block rounded-lg p-3.5">
                          <p className="line-clamp-1 text-[14px] font-medium text-ink">
                            {paper.title}
                          </p>
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
          )
        }
      </AsyncBoundary>

      {quizzes.data && quizzes.data.length > 0 && (
        <section className="mt-10" aria-labelledby="quizzes">
          <h2 id="quizzes" className="mb-3 text-[13px] font-semibold text-ink-muted">
            Quizzes
          </h2>
          <ul className="space-y-2">
            {quizzes.data.map((quiz) => (
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
