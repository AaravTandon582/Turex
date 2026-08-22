"use client";

import { Loader2 } from "lucide-react";

import { cn } from "@/lib/cn";

/**
 * The three shapes waiting takes, in one place.
 *
 * They are not interchangeable, and using the wrong one is its own small lie:
 *
 * * **Skeleton** — the shape of content that is coming. Right when the layout is known and
 *   only the values are missing, because it stops the page jumping when they arrive.
 * * **Spinner** — a small, local wait attached to the thing that caused it. Right inside a
 *   button that was just pressed.
 * * **ProgressBar** — a wait long enough that a spinner starts to look stuck, and long enough
 *   that saying *what* is happening is worth the space.
 *
 * All of them are indeterminate. None claims a percentage, because none of these operations
 * can honestly report one — a fake progress bar that sits at 90% is worse than no bar.
 */

export function Spinner({
  className,
  label = "Loading",
}: {
  className?: string;
  /** Announced to screen readers. The visual spin says nothing to them. */
  label?: string;
}) {
  return (
    <span role="status" aria-live="polite" className="inline-flex items-center">
      <Loader2 aria-hidden className={cn("size-4 animate-spin text-ink-muted", className)} />
      <span className="sr-only">{label}</span>
    </span>
  );
}

/**
 * A thin indeterminate bar, for waits measured in seconds rather than milliseconds.
 *
 * `aria-busy` and the live region carry the same information as the animation, so the wait is
 * legible to a screen reader and to anyone who has turned motion off.
 */
export function ProgressBar({ label, className }: { label?: string; className?: string }) {
  return (
    <div className={cn("w-full", className)} role="status" aria-live="polite" aria-busy="true">
      <div className="h-0.5 w-full overflow-hidden rounded-full bg-surface-sunken">
        <div className="h-full w-1/3 animate-[var(--animate-indeterminate)] rounded-full bg-accent" />
      </div>
      {label ? <p className="mt-2 text-[12px] text-ink-muted">{label}</p> : null}
    </div>
  );
}

/**
 * A centred wait for a whole panel, when there is no meaningful skeleton to draw.
 *
 * Used where the content's shape is genuinely unknown until it arrives — a graph, a rendered
 * figure — rather than as a shortcut past building the skeleton.
 */
export function LoadingPanel({ label, className }: { label: string; className?: string }) {
  return (
    <div
      role="status"
      aria-live="polite"
      className={cn(
        "flex min-h-40 animate-[var(--animate-fade-in)] flex-col items-center justify-center gap-3 text-center",
        className,
      )}
    >
      <Loader2 aria-hidden className="size-5 animate-spin text-ink-subtle" />
      <p className="text-[13px] text-ink-muted">{label}</p>
    </div>
  );
}
