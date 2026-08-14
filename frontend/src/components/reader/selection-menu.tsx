"use client";

import { Highlighter, MessageSquareQuote, Sigma, TriangleAlert } from "lucide-react";

import { HIGHLIGHT_COLOURS, type HighlightColour } from "@/lib/annotations";
import { cn } from "@/lib/cn";

export type SelectionAction = "explain" | "critique" | "equation";

/**
 * The menu that appears over a selection.
 *
 * Four actions, chosen because they are what a reader actually wants at the moment they stop
 * on a passage: mark it, understand it, question it, or decode the maths. Anything else
 * belongs in the assistant panel, where there is room to type.
 */
export function SelectionMenu({
  point,
  onHighlight,
  onAsk,
  onDismiss,
}: {
  point: { top: number; left: number };
  onHighlight: (colour: HighlightColour) => void;
  onAsk: (action: SelectionAction) => void;
  onDismiss: () => void;
}) {
  return (
    <div
      role="toolbar"
      aria-label="Selection actions"
      // Positioned above the selection's first line, centred on it, and nudged clear of the
      // text so it never covers what the user just selected.
      style={{ top: point.top - 8, left: point.left }}
      className="absolute z-20 -translate-x-1/2 -translate-y-full animate-[var(--animate-rise)]"
      onMouseDown={(event) => event.preventDefault()}
    >
      <div className="flex items-center gap-0.5 rounded-lg border border-border bg-surface p-1 shadow-[var(--shadow-lg)]">
        <div className="flex items-center gap-0.5 pr-1">
          <Highlighter className="mx-1 size-3.5 text-ink-subtle" aria-hidden />
          {HIGHLIGHT_COLOURS.map((colour) => (
            <button
              key={colour.value}
              type="button"
              title={`Highlight as ${colour.label.toLowerCase()}`}
              aria-label={`Highlight as ${colour.label.toLowerCase()}`}
              onClick={() => onHighlight(colour.value)}
              className={cn(
                "size-5 rounded-sm border border-border transition-transform hover:scale-110",
                colour.swatch,
              )}
            />
          ))}
        </div>

        <span className="h-5 w-px bg-border" aria-hidden />

        <MenuAction icon={<MessageSquareQuote />} label="Explain" onClick={() => onAsk("explain")} />
        <MenuAction icon={<TriangleAlert />} label="Critique" onClick={() => onAsk("critique")} />
        <MenuAction icon={<Sigma />} label="Equation" onClick={() => onAsk("equation")} />

        <span className="h-5 w-px bg-border" aria-hidden />
        <button
          type="button"
          onClick={onDismiss}
          aria-label="Dismiss"
          className="rounded-sm px-1.5 py-1 text-[12px] text-ink-subtle hover:text-ink"
        >
          Esc
        </button>
      </div>
    </div>
  );
}

function MenuAction({
  icon,
  label,
  onClick,
}: {
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex items-center gap-1.5 rounded-sm px-2 py-1 text-[12px] font-medium text-ink-muted transition-colors hover:bg-surface-hover hover:text-ink [&_svg]:size-3.5"
    >
      {icon}
      {label}
    </button>
  );
}
