"use client";

import { cn } from "@/lib/cn";
import type { ExplanationLevel } from "@/lib/assistant";

const LEVELS: readonly { value: ExplanationLevel | null; label: string; title: string }[] = [
  { value: null, label: "Default", title: "Let Turex judge from your question" },
  { value: "beginner", label: "Beginner", title: "Assume no vocabulary; define every term" },
  { value: "intermediate", label: "Intermediate", title: "Assume the field's basics" },
  { value: "advanced", label: "Advanced", title: "Assume the literature; go to the mechanism" },
] as const;

/**
 * Who the answer is written for.
 *
 * A segmented control rather than a dropdown: there are four options, all of them short, and
 * the current one should be readable without opening anything. It resets to Default after each
 * turn is composed — asking for one concept from scratch is not a request for every later
 * answer to be beginner-level.
 */
export function LevelPicker({
  value,
  onChange,
  disabled,
}: {
  value: ExplanationLevel | null;
  onChange: (level: ExplanationLevel | null) => void;
  disabled?: boolean;
}) {
  return (
    <div
      role="radiogroup"
      aria-label="Explanation level"
      className="inline-flex rounded-md border border-border bg-surface-sunken p-0.5"
    >
      {LEVELS.map((level) => {
        const active = level.value === value;
        return (
          <button
            key={level.label}
            type="button"
            role="radio"
            aria-checked={active}
            title={level.title}
            disabled={disabled}
            onClick={() => onChange(level.value)}
            className={cn(
              "rounded-sm px-2 py-1 text-[12px] transition-[background-color,color] duration-150",
              "focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none",
              active
                ? "bg-surface text-ink shadow-[var(--shadow-sm)]"
                : "text-ink-subtle hover:text-ink-muted",
              disabled && "cursor-not-allowed opacity-50",
            )}
          >
            {level.label}
          </button>
        );
      })}
    </div>
  );
}
