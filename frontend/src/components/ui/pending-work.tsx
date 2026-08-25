"use client";

import { cn } from "@/lib/cn";

/**
 * What a long wait looks like.
 *
 * Asking a model to write a set of flashcards takes twenty to forty seconds. A disabled button
 * with a sixteen-pixel spinner inside it does not survive that — the label is hidden, almost
 * nothing moves, and the reasonable conclusion is that the application has hung. It was
 * reported as exactly that.
 *
 * So: a wheel large enough to read as a loading indicator from across the screen, and a line
 * saying what is being done. Nothing claims a percentage, because none of this work reports
 * progress and a bar stuck at 90% is a lie that erodes every other number in the product.
 */

export function PendingWork({ label, className }: { label: string; className?: string }) {
  return (
    <div
      role="status"
      aria-live="polite"
      aria-busy="true"
      className={cn(
        "flex items-center gap-3 rounded-md border border-border bg-surface-sunken p-3",
        className,
      )}
    >
      <Wheel />
      <p className="text-[13px] text-ink">{label}</p>
    </div>
  );
}

/**
 * The wheel itself.
 *
 * A ring with one quarter picked out in the accent colour, so the rotation is unmistakable.
 * A uniform ring spins invisibly — there is nothing to track around it — which is why a border
 * with a single transparent side is the shape every loader converges on.
 *
 * `aria-hidden` because the surrounding live region already announces the wait in words. A
 * screen reader gains nothing from being told there is a picture of a circle.
 */
function Wheel({ className }: { className?: string }) {
  return (
    <span
      aria-hidden
      className={cn(
        "size-5 shrink-0 animate-spin rounded-full border-2 border-border-strong border-t-accent",
        className,
      )}
    />
  );
}

export { Wheel };
