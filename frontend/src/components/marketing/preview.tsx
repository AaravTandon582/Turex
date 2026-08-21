import { FileText, Quote } from "lucide-react";

import { Badge } from "@/components/ui/primitives";

/**
 * A static composition of Turex's real interface elements.
 *
 * Built from the product's own tokens and components rather than a screenshot, so it cannot
 * drift out of date and never depicts a capability that does not exist. Everything shown here
 * is behaviour Turex actually implements: retrieval with resolvable citations.
 */
export function AssistantPreview() {
  return (
    <div className="overflow-hidden rounded-xl border border-border bg-surface shadow-[var(--shadow-lg)]">
      <div className="flex items-center gap-2 border-b border-border bg-surface-sunken px-4 py-2.5">
        <div className="flex gap-1.5" aria-hidden>
          <span className="size-2.5 rounded-full bg-border-strong" />
          <span className="size-2.5 rounded-full bg-border-strong" />
          <span className="size-2.5 rounded-full bg-border-strong" />
        </div>
        <span className="ml-2 font-mono text-[11px] text-ink-subtle">
          assistant · research mode
        </span>
      </div>

      <div className="space-y-4 p-5">
        <p className="ml-auto w-fit max-w-[85%] rounded-lg rounded-br-sm bg-accent-soft px-3.5 py-2 text-[13px] text-ink">
          What do my papers say about hallucination under retrieval?
        </p>

        <div className="space-y-3">
          <p className="max-w-[92%] text-[13px] leading-relaxed text-ink">
            Two of your papers measure this directly. Both report that grounding reduces
            unsupported claims but does not eliminate them — the residual errors come from
            passages that were retrieved and then misread, not from missing evidence.
          </p>

          <div className="space-y-2">
            <Citation
              index={1}
              title="Retrieval-Augmented Generation for Knowledge-Intensive NLP"
              locator="p. 7 · §4.2 Results"
              quote="Grounded generations reduced unsupported assertions by 41% relative to the closed-book baseline."
            />
            <Citation
              index={2}
              title="Measuring Faithfulness in Grounded Summarisation"
              locator="p. 3 · §2 Method"
              quote="We annotate each sentence as supported, partially supported, or unsupported by the retrieved context."
            />
          </div>

          <p className="flex items-center gap-1.5 text-[11px] text-ink-subtle">
            <span className="inline-block size-1.5 rounded-full bg-success" aria-hidden />
            Grounded in 2 sources from your library
          </p>
        </div>
      </div>
    </div>
  );
}

function Citation({
  index,
  title,
  locator,
  quote,
}: {
  index: number;
  title: string;
  locator: string;
  quote: string;
}) {
  return (
    <div className="rounded-md border border-border bg-surface-sunken p-3">
      <div className="flex items-start gap-2">
        <span className="mt-px flex size-4 shrink-0 items-center justify-center rounded-xs bg-accent text-[10px] font-semibold text-ink-inverse">
          {index}
        </span>
        <div className="min-w-0">
          <p className="truncate text-[12px] font-medium text-ink">{title}</p>
          <p className="mt-0.5 flex items-center gap-1 font-mono text-[10px] text-ink-subtle">
            <FileText className="size-2.5" aria-hidden />
            {locator}
          </p>
        </div>
      </div>
      <blockquote className="mt-2 flex gap-1.5 border-l-2 border-highlight pl-2.5 text-[12px] leading-relaxed text-ink-muted italic">
        <Quote className="mt-0.5 size-2.5 shrink-0 text-highlight not-italic" aria-hidden />
        {quote}
      </blockquote>
    </div>
  );
}

/** A hypothesis card, showing evidence tracked on both sides of a claim. */
export function HypothesisPreview() {
  return (
    <div className="rounded-xl border border-border bg-surface p-4 shadow-[var(--shadow-md)]">
      <div className="flex items-start justify-between gap-3">
        <p className="text-[13px] leading-relaxed font-medium text-ink">
          Structured retrieval improves reasoning accuracy in small models more than scale alone.
        </p>
        <Badge tone="warning">Testing</Badge>
      </div>

      <dl className="mt-4 space-y-2.5 text-[12px]">
        <div className="flex items-baseline gap-2">
          <dt className="w-24 shrink-0 text-ink-subtle">Supports</dt>
          <dd className="text-success">3 passages</dd>
        </div>
        <div className="flex items-baseline gap-2">
          <dt className="w-24 shrink-0 text-ink-subtle">Contradicts</dt>
          <dd className="text-danger">1 passage</dd>
        </div>
        <div className="flex items-baseline gap-2">
          <dt className="w-24 shrink-0 text-ink-subtle">Assumes</dt>
          <dd className="text-ink-muted">Retrieval quality held constant</dd>
        </div>
      </dl>
    </div>
  );
}
