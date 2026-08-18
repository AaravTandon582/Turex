"use client";

import { AlertCircle, RotateCw } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/primitives";
import { cn } from "@/lib/cn";
import type { AsyncResult } from "@/lib/use-async";

/**
 * Renders the loading and failed states of a request, and gets out of the way otherwise.
 *
 * The failure state is a real state with a real message and a retry, not a silent fallback to
 * an empty list. Distinguishing "nothing here yet" from "we could not find out" is the whole
 * point — see `lib/use-async.ts`.
 */
export function AsyncBoundary<T>({
  state,
  skeleton,
  children,
  className,
}: {
  state: AsyncResult<T>;
  /** Sized like the content it stands in for, so the layout does not jump when it resolves. */
  skeleton?: ReactNode;
  children: (data: T) => ReactNode;
  className?: string;
}) {
  if (state.status === "error") {
    return <LoadError message={state.error} onRetry={state.reload} className={className} />;
  }

  if (state.status === "loading" && state.data === null) {
    return <>{skeleton ?? <Skeleton className={cn("h-32 w-full rounded-lg", className)} />}</>;
  }

  // A reload keeps the previous data on screen rather than flashing back to skeletons —
  // replacing content the reader is looking at with placeholders reads as a bug.
  return <>{state.data !== null && children(state.data)}</>;
}

export function LoadError({
  message,
  onRetry,
  className,
}: {
  message: string | null;
  onRetry?: () => void;
  className?: string;
}) {
  return (
    <div
      role="alert"
      className={cn(
        "flex flex-col items-center justify-center rounded-lg border border-dashed border-danger/40 bg-danger-soft/30 px-6 py-12 text-center",
        className,
      )}
    >
      <AlertCircle aria-hidden className="size-5 text-danger" />
      <p className="measure mt-3 text-sm text-ink">
        {message ?? "Atlas couldn't load that."}
      </p>
      {onRetry && (
        <Button size="sm" variant="secondary" className="mt-4" onClick={onRetry}>
          <RotateCw aria-hidden />
          Try again
        </Button>
      )}
    </div>
  );
}
