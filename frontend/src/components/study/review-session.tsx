"use client";

import { Check, ChevronRight, ExternalLink } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Badge, Card } from "@/components/ui/primitives";
import { CARD_KIND_LABELS, RATINGS, dueLabel, study } from "@/lib/study";
import type { Flashcard, ReviewRating } from "@/lib/study";

/**
 * One card at a time: prompt, then answer, then a grade.
 *
 * The answer stays hidden until the reader asks for it. That is the whole mechanism — a card
 * whose answer is already on screen tests nothing — so revealing is a deliberate action with
 * its own key, and the grades only appear once it has happened.
 *
 * Everything is reachable from the keyboard, because a review session is thirty decisions in
 * a row and reaching for a mouse for each one is what makes people stop doing it.
 */
export function ReviewSession({
  cards,
  onFinished,
}: {
  cards: Flashcard[];
  onFinished: () => void;
}) {
  const [queue, setQueue] = useState<Flashcard[]>(cards);
  const [revealed, setRevealed] = useState(false);
  const [graded, setGraded] = useState(0);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // The session always shows the front of the queue; grading removes that card. Tracking a
  // cursor over a list that is being mutated underneath it is how off-by-one bugs get in.
  const card = queue[0];

  const grade = useCallback(
    async (rating: ReviewRating) => {
      if (!card || saving) return;
      setSaving(true);
      setError(null);
      try {
        const updated = await study.review(card.id, rating);
        setGraded((count) => count + 1);

        // A forgotten card goes to the back of this session rather than out of it. The
        // server has already scheduled it for today; re-showing it now is what makes that
        // schedule mean something before the session ends.
        setQueue((current) => {
          const remaining = current.slice(1);
          return rating === "forgot" ? [...remaining, updated] : remaining;
        });
        setRevealed(false);
      } catch {
        setError("That review didn't save. Check your connection and try again.");
      } finally {
        setSaving(false);
      }
    },
    [card, saving],
  );

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      const target = event.target as HTMLElement | null;
      if (target && ["INPUT", "TEXTAREA"].includes(target.tagName)) return;

      if (!revealed && (event.key === " " || event.key === "Enter")) {
        event.preventDefault();
        setRevealed(true);
        return;
      }
      if (revealed) {
        const position = Number(event.key);
        if (position >= 1 && position <= RATINGS.length) {
          event.preventDefault();
          void grade(RATINGS[position - 1].value);
        }
      }
    }

    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [revealed, grade]);

  if (!card) {
    return (
      <Card className="p-8 text-center">
        <span className="mx-auto flex size-10 items-center justify-center rounded-full bg-success-soft text-success">
          <Check className="size-5" />
        </span>
        <h2 className="mt-3 text-[15px] font-medium text-ink">Session finished</h2>
        <p className="measure mx-auto mt-1 text-[13px] text-ink-muted">
          {graded} {graded === 1 ? "card" : "cards"} reviewed. Nothing else is due right now.
        </p>
        <Button className="mt-4" size="sm" variant="secondary" onClick={onFinished}>
          Back to progress
        </Button>
      </Card>
    );
  }

  return (
    <div>
      <div className="flex items-center justify-between text-[12px] text-ink-subtle">
        <span data-tabular>
          {graded + 1} of {graded + queue.length}
        </span>
        <span>{dueLabel(card.due_at)}</span>
      </div>

      <div
        className="mt-2 h-0.5 w-full overflow-hidden rounded-full bg-surface-sunken"
        role="progressbar"
        aria-valuenow={graded}
        aria-valuemin={0}
        aria-valuemax={graded + queue.length}
        aria-label="Review progress"
      >
        <div
          className="h-full bg-accent transition-[width] duration-200 ease-out"
          style={{ width: `${(graded / (graded + queue.length)) * 100}%` }}
        />
      </div>

      <Card className="mt-4 p-6">
        <Badge tone="neutral">{CARD_KIND_LABELS[card.kind]}</Badge>
        <p className="measure mt-3 text-[17px] leading-snug font-medium text-ink">{card.front}</p>

        {!revealed ? (
          <Button className="mt-6" onClick={() => setRevealed(true)}>
            Show answer
            <kbd className="ml-1 rounded-xs border border-ink-inverse/30 px-1 text-[10px] opacity-70">
              space
            </kbd>
          </Button>
        ) : (
          <div className="mt-5 border-t border-border pt-5">
            <p className="measure text-[15px] leading-relaxed text-ink">{card.back}</p>

            <details className="mt-4">
              <summary className="inline-flex cursor-pointer items-center gap-1 text-[12px] text-ink-muted hover:text-ink">
                <ChevronRight className="size-3 transition-transform [details[open]_&]:rotate-90" />
                The passage this came from
                {card.source_page && ` · page ${card.source_page}`}
              </summary>
              <blockquote className="measure mt-2 border-l-2 border-border-strong pl-3 text-[13px] leading-relaxed text-ink-muted">
                {card.source_excerpt}
              </blockquote>
              <Link
                href={`/library/${card.paper_id}/read`}
                className="mt-2 inline-flex items-center gap-1 text-[12px] font-medium text-accent hover:underline"
              >
                Open the paper <ExternalLink className="size-3" />
              </Link>
            </details>
          </div>
        )}
      </Card>

      {revealed && (
        <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
          {RATINGS.map((rating, position) => (
            <button
              key={rating.value}
              type="button"
              disabled={saving}
              onClick={() => void grade(rating.value)}
              className="group rounded-md border border-border bg-surface px-3 py-2.5 text-left transition-[border-color,background-color] duration-150 hover:border-border-strong hover:bg-surface-hover disabled:opacity-50"
            >
              <span className="flex items-center justify-between">
                <span className="text-[13px] font-medium text-ink">{rating.label}</span>
                <kbd className="rounded-xs border border-border px-1 text-[10px] text-ink-subtle">
                  {position + 1}
                </kbd>
              </span>
              <span className="mt-0.5 block text-[11px] text-ink-subtle">{rating.hint}</span>
            </button>
          ))}
        </div>
      )}

      {error && (
        <p role="alert" className="mt-3 text-[13px] text-danger">
          {error}
        </p>
      )}
    </div>
  );
}
