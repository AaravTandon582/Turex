"use client";

import { Prose } from "@/components/ui/prose";

/**
 * A note, rendered.
 *
 * The notebook told people to "write however you think — Markdown, LaTeX, tables, code" and
 * then showed the raw characters back. That is the product making a claim it does not keep,
 * which matters more here than in most places: the whole argument for Turex is that it does
 * not say things that are not so.
 *
 * The rendering itself now lives in `Prose`, because every other surface had the same problem
 * and the notebook was simply the first place it was noticed.
 */
export function NotePreview({ content }: { content: string }) {
  if (!content.trim()) {
    return (
      <p className="text-[13px] text-ink-subtle">
        Nothing written yet. Switch to Write and start typing.
      </p>
    );
  }

  return <Prose className="measure text-[15px] leading-relaxed text-ink">{content}</Prose>;
}
