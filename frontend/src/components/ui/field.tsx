"use client";

import { useId, type InputHTMLAttributes, type ReactNode } from "react";

import { cn } from "@/lib/cn";

interface FieldProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "id"> {
  label: string;
  /** Guidance shown before the user makes a mistake. */
  hint?: ReactNode;
  /** Replaces the hint once validation fails. */
  error?: string | null;
}

/**
 * A labelled text input.
 *
 * The label, hint, and error are wired to the input with generated ids so a screen reader
 * announces the error with the field rather than as loose text elsewhere on the page.
 */
export function Field({ label, hint, error, className, ...props }: FieldProps) {
  const id = useId();
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;
  const describedBy = error ? errorId : hint ? hintId : undefined;

  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="block text-[13px] font-medium text-ink">
        {label}
      </label>

      <input
        id={id}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy}
        className={cn(
          "block h-9.5 w-full rounded-md border bg-surface px-3 text-sm text-ink",
          "placeholder:text-ink-subtle",
          "transition-[border-color,box-shadow] duration-150 ease-[var(--ease-out-quart)]",
          "focus:border-accent focus:outline-none focus:ring-3 focus:ring-[var(--accent-ring)]",
          "disabled:cursor-not-allowed disabled:opacity-60",
          error ? "border-danger" : "border-border hover:border-border-strong",
          className,
        )}
        {...props}
      />

      {error ? (
        <p id={errorId} role="alert" className="text-[13px] text-danger">
          {error}
        </p>
      ) : hint ? (
        <p id={hintId} className="text-[13px] text-ink-subtle">
          {hint}
        </p>
      ) : null}
    </div>
  );
}
