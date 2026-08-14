"use client";

import { Check, ChevronDown } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/cn";
import type { AssistantMode, ModeInfo } from "@/lib/assistant";

/**
 * Selects what kind of help the user wants.
 *
 * Modes are surfaced prominently rather than hidden in a menu: the spec's point is that the
 * current mode should be obvious, and "critique" versus "explain" changes the answer enough
 * that the reader needs to know which one they asked for.
 */
export function ModePicker({
  modes,
  value,
  onChange,
  disabled,
}: {
  modes: ModeInfo[];
  value: AssistantMode;
  onChange: (mode: AssistantMode) => void;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const current = modes.find((mode) => mode.value === value);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="flex h-8 items-center gap-1.5 rounded-md border border-border bg-surface px-2.5 text-[13px] font-medium text-ink transition-colors hover:bg-surface-hover disabled:opacity-50"
      >
        {current?.label ?? "Mode"}
        <ChevronDown className="size-3 text-ink-subtle" aria-hidden />
      </button>

      {open && (
        <ul
          role="listbox"
          aria-label="Assistant mode"
          className="absolute bottom-[calc(100%+6px)] left-0 z-30 w-72 animate-[var(--animate-rise)] rounded-lg border border-border bg-surface p-1 shadow-[var(--shadow-lg)]"
        >
          {modes.map((mode) => (
            <li key={mode.value}>
              <button
                type="button"
                role="option"
                aria-selected={mode.value === value}
                onClick={() => {
                  onChange(mode.value);
                  setOpen(false);
                }}
                className={cn(
                  "flex w-full items-start gap-2 rounded-sm px-2 py-1.5 text-left transition-colors",
                  mode.value === value ? "bg-surface-hover" : "hover:bg-surface-hover",
                )}
              >
                <Check
                  className={cn(
                    "mt-0.5 size-3.5 shrink-0",
                    mode.value === value ? "text-accent" : "invisible",
                  )}
                  aria-hidden
                />
                <span>
                  <span className="block text-[13px] font-medium text-ink">{mode.label}</span>
                  <span className="block text-[12px] leading-snug text-ink-muted">
                    {mode.description}
                  </span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
