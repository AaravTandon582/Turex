import { cn } from "@/lib/cn";

/**
 * The Atlas mark: three linked nodes.
 *
 * A constellation rather than a book or a brain — the product's premise is that research
 * value comes from the connections between sources, not the sources alone.
 */
export function AtlasMark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      role="img"
      aria-label="Atlas"
      className={cn("text-accent", className)}
    >
      <path
        d="M12 4.5 5.5 18.5M12 4.5 18.5 18.5M5.5 18.5h13"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        opacity="0.4"
      />
      <circle cx="12" cy="4.5" r="2.75" fill="currentColor" />
      <circle cx="5.5" cy="18.5" r="2.25" fill="currentColor" opacity="0.75" />
      <circle cx="18.5" cy="18.5" r="2.25" fill="currentColor" opacity="0.55" />
    </svg>
  );
}
