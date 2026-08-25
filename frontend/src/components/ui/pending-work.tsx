"use client";

import { useEffect, useState } from "react";

import { cn } from "@/lib/cn";

/**
 * What a long wait looks like when it is honest about being long.
 *
 * Asking a model to write a set of flashcards takes between twenty and forty seconds. A
 * disabled button with a sixteen-pixel spinner in it does not survive that: the label is
 * hidden, nothing moves except a ring most of a centimetre across, and the reasonable
 * conclusion after ten seconds is that the application has hung. It was reported as exactly
 * that.
 *
 * Three things fix it, and all three are needed:
 *
 * * **A count of seconds.** The single most convincing evidence that something is still
 *   running is a number that keeps changing. A spinner loops identically whether the work is
 *   progressing or the tab is dead.
 * * **What is happening**, in words — not "Loading" but "Reading the paper and writing
 *   questions".
 * * **How long it usually takes.** Someone told to expect half a minute waits calmly for
 *   forty seconds. Someone told nothing gives up at eight.
 *
 * The bar is indeterminate and never claims a percentage, because none of this work reports
 * progress and a bar that sits at 90% is a lie that erodes every other number in the product.
 */

interface PendingWorkProps {
  /** What is being done, as a sentence. "Writing flashcards from this paper." */
  label: string;
  /** Roughly how long it usually takes, in seconds. Omit only if genuinely unknown. */
  expectedSeconds?: number;
  className?: string;
}

export function PendingWork({ label, expectedSeconds, className }: PendingWorkProps) {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const started = Date.now();
    const timer = window.setInterval(
      () => setElapsed(Math.floor((Date.now() - started) / 1000)),
      1000,
    );
    return () => window.clearInterval(timer);
  }, []);

  /**
   * What to say once it has taken longer than expected.
   *
   * Silence past the estimate is worse than no estimate at all — it turns a wait into a
   * broken promise. Saying so keeps the number honest and keeps the reader waiting on
   * purpose rather than out of hope.
   */
  const overdue = expectedSeconds !== undefined && elapsed > expectedSeconds + 10;

  return (
    <div
      role="status"
      aria-live="polite"
      aria-busy="true"
      className={cn("rounded-md border border-border bg-surface-sunken p-3", className)}
    >
      <div className="h-0.5 w-full overflow-hidden rounded-full bg-border">
        <div className="h-full w-1/3 animate-[var(--animate-indeterminate)] rounded-full bg-accent" />
      </div>

      <div className="mt-2.5 flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
        <p className="text-[13px] text-ink">{label}</p>
        <p className="text-[12px] text-ink-subtle" data-tabular>
          {elapsed}s
          {expectedSeconds !== undefined && !overdue && ` · usually about ${expectedSeconds}s`}
        </p>
      </div>

      {overdue && (
        <p className="mt-1 text-[12px] text-ink-muted">
          Taking longer than usual. It is still running — the model is slower on some papers
          than others.
        </p>
      )}
    </div>
  );
}
