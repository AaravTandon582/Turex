"use client";

import { Check, X } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { PageContainer } from "@/components/layout/page-container";
import { Button } from "@/components/ui/button";
import { Card, Skeleton } from "@/components/ui/primitives";
import { study, type Quiz, type QuizQuestion } from "@/lib/study";

/**
 * Take a quiz, then see what each answer rested on.
 *
 * The correct answers are not in this page until the quiz has been submitted — the server
 * withholds them, so there is nothing to read out of the network tab mid-quiz.
 */
export default function QuizPage() {
  const { id } = useParams<{ id: string }>();
  const [quiz, setQuiz] = useState<Quiz | null>(null);
  const [answers, setAnswers] = useState<Record<string, number>>({});
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void study
      .getQuiz(id)
      .then((loaded) => {
        setQuiz(loaded);
        setAnswers(
          Object.fromEntries(
            loaded.questions
              .filter((question) => question.selected_index != null)
              .map((question) => [question.id, question.selected_index as number]),
          ),
        );
      })
      .catch(() => setError("That quiz could not be loaded."));
  }, [id]);

  async function submit() {
    if (!quiz) return;
    setSubmitting(true);
    setError(null);
    try {
      setQuiz(await study.submitQuiz(quiz.id, answers));
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch {
      setError("Your answers didn't save. Check your connection and try again.");
    } finally {
      setSubmitting(false);
    }
  }

  if (error && !quiz) {
    return (
      <PageContainer width="reading">
        <p role="alert" className="text-[14px] text-danger">
          {error}
        </p>
      </PageContainer>
    );
  }

  if (!quiz) {
    return (
      <PageContainer width="reading">
        <Skeleton className="h-8 w-2/3 rounded-md" />
        <Skeleton className="mt-6 h-64 w-full rounded-lg" />
      </PageContainer>
    );
  }

  const submitted = quiz.submitted_at !== null;
  const answered = Object.keys(answers).length;

  return (
    <PageContainer width="reading">
      <header>
        <p className="text-[12px] text-ink-subtle">Quiz</p>
        <h1 className="mt-0.5 text-xl font-semibold tracking-[-0.01em] text-ink">{quiz.title}</h1>
        {submitted ? (
          <p className="mt-2 text-[14px] text-ink-muted" data-tabular>
            You scored <strong className="text-ink">{quiz.correct_count}</strong> out of{" "}
            {quiz.question_count}.
          </p>
        ) : (
          <p className="mt-2 text-[13px] text-ink-muted" data-tabular>
            {answered} of {quiz.question_count} answered
          </p>
        )}
      </header>

      <ol className="mt-6 space-y-4">
        {quiz.questions.map((question, position) => (
          <li key={question.id}>
            <QuestionCard
              question={question}
              position={position}
              selected={answers[question.id]}
              submitted={submitted}
              onSelect={(index) => setAnswers((current) => ({ ...current, [question.id]: index }))}
            />
          </li>
        ))}
      </ol>

      {error && (
        <p role="alert" className="mt-4 text-[13px] text-danger">
          {error}
        </p>
      )}

      <div className="mt-6 flex items-center gap-3">
        {submitted ? (
          <Button asChild variant="secondary">
            <Link href="/study">Back to study</Link>
          </Button>
        ) : (
          <>
            <Button onClick={() => void submit()} loading={submitting} disabled={answered === 0}>
              Submit answers
            </Button>
            {answered < quiz.question_count && (
              <p className="text-[12px] text-ink-subtle">
                Unanswered questions are marked as such, not as wrong.
              </p>
            )}
          </>
        )}
      </div>
    </PageContainer>
  );
}

function QuestionCard({
  question,
  position,
  selected,
  submitted,
  onSelect,
}: {
  question: QuizQuestion;
  position: number;
  selected: number | undefined;
  submitted: boolean;
  onSelect: (index: number) => void;
}) {
  const correct = question.correct_index;

  return (
    <Card className="p-4">
      <fieldset>
        <legend className="measure text-[15px] leading-snug font-medium text-ink">
          <span className="mr-1.5 text-ink-subtle" data-tabular>
            {position + 1}.
          </span>
          {question.prompt}
        </legend>

        <div className="mt-3 space-y-1.5">
          {question.options.map((option, index) => {
            const isSelected = selected === index;
            const isCorrect = submitted && correct === index;
            const isWrongChoice = submitted && isSelected && correct !== index;

            return (
              <label
                key={index}
                className={[
                  "flex cursor-pointer items-start gap-2.5 rounded-md border px-3 py-2 transition-[border-color,background-color] duration-150",
                  isCorrect
                    ? "border-success bg-success-soft"
                    : isWrongChoice
                      ? "border-danger bg-danger-soft"
                      : isSelected
                        ? "border-accent bg-accent-soft"
                        : "border-border hover:border-border-strong hover:bg-surface-hover",
                  submitted && "cursor-default",
                ]
                  .filter(Boolean)
                  .join(" ")}
              >
                <input
                  type="radio"
                  name={question.id}
                  checked={isSelected}
                  disabled={submitted}
                  onChange={() => onSelect(index)}
                  className="mt-1 size-3.5 shrink-0 accent-[var(--accent)]"
                />
                <span className="text-[14px] leading-relaxed text-ink">{option}</span>
                {isCorrect && <Check className="mt-0.5 ml-auto size-4 shrink-0 text-success" />}
                {isWrongChoice && <X className="mt-0.5 ml-auto size-4 shrink-0 text-danger" />}
              </label>
            );
          })}
        </div>
      </fieldset>

      {submitted && question.explanation && (
        <div className="mt-4 border-t border-border pt-3">
          <p className="measure text-[13px] leading-relaxed text-ink-muted">
            {question.explanation}
          </p>
          {question.source_excerpt && (
            <details className="mt-2">
              <summary className="cursor-pointer text-[12px] text-ink-subtle hover:text-ink-muted">
                The passage this came from
                {question.source_page ? ` · page ${question.source_page}` : ""}
              </summary>
              <blockquote className="measure mt-2 border-l-2 border-border-strong pl-3 text-[13px] leading-relaxed text-ink-muted">
                {question.source_excerpt}
              </blockquote>
            </details>
          )}
        </div>
      )}
    </Card>
  );
}
