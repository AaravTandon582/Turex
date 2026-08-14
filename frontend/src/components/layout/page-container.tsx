import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

/**
 * Standard page gutter and measure for every screen in the authenticated app.
 *
 * Centralised so density stays identical across the product — the fastest way for an
 * interface to feel unconsidered is for each page to invent its own padding.
 */
export function PageContainer({
  children,
  className,
  width = "wide",
}: {
  children: ReactNode;
  className?: string;
  /** `reading` narrows the column for prose-heavy screens like the notebook. */
  width?: "wide" | "reading" | "full";
}) {
  return (
    <div
      className={cn(
        "mx-auto w-full px-5 py-6 sm:px-8 md:px-10 md:py-9",
        width === "wide" && "max-w-6xl",
        width === "reading" && "max-w-3xl",
        className,
      )}
    >
      {children}
    </div>
  );
}
