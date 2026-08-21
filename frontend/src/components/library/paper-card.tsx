"use client";

import { AlertCircle, RotateCw, Star, Trash2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Badge, Card, type BadgeTone } from "@/components/ui/primitives";
import { cn } from "@/lib/cn";
import {
  formatAuthors,
  isProcessing,
  papers,
  type PaperSummary,
  type ReadingStatus,
} from "@/lib/papers";

const READING_STATUS: Record<ReadingStatus, { label: string; tone: BadgeTone }> = {
  unread: { label: "Unread", tone: "neutral" },
  reading: { label: "Reading", tone: "accent" },
  read: { label: "Read", tone: "success" },
  revisit: { label: "Revisit", tone: "warning" },
};

interface PaperCardProps {
  paper: PaperSummary;
  /** Progress label from the detail endpoint, when this paper is still being read. */
  progressLabel?: string;
  progressPercent?: number;
  onChanged: () => void;
}

export function PaperCard({ paper, progressLabel, progressPercent, onChanged }: PaperCardProps) {
  const [busy, setBusy] = useState(false);
  const processing = isProcessing(paper);
  const failed = paper.status === "failed";

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    try {
      await action();
      onChanged();
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card
      className={cn(
        "group flex flex-col transition-[border-color,box-shadow] duration-150",
        !processing && "hover:border-border-strong hover:shadow-[var(--shadow-md)]",
        failed && "border-danger/30",
      )}
    >
      <div className="flex-1 p-4">
        <div className="flex items-start justify-between gap-2">
          <h3 className="text-[14px] leading-snug font-medium text-balance text-ink">
            {processing ? (
              <span className="text-ink-muted">{paper.display_title}</span>
            ) : (
              <Link
                href={`/library/${paper.id}`}
                className="rounded-xs after:absolute after:inset-0 hover:text-accent"
              >
                {paper.display_title}
              </Link>
            )}
          </h3>

          <button
            type="button"
            disabled={busy}
            aria-label={paper.is_favorite ? "Remove from favourites" : "Add to favourites"}
            aria-pressed={paper.is_favorite}
            onClick={() => run(() => papers.update(paper.id, { is_favorite: !paper.is_favorite }))}
            className={cn(
              "relative z-10 -mt-0.5 -mr-1 shrink-0 rounded-sm p-1 transition-colors",
              paper.is_favorite
                ? "text-highlight"
                : "text-ink-subtle opacity-0 group-hover:opacity-100 focus-visible:opacity-100 hover:text-ink-muted",
            )}
          >
            <Star className="size-4" fill={paper.is_favorite ? "currentColor" : "none"} aria-hidden />
          </button>
        </div>

        {!processing && !failed && (
          <p className="mt-1.5 truncate text-[13px] text-ink-muted">
            {formatAuthors(paper.authors)}
          </p>
        )}

        {processing && (
          <ProcessingIndicator label={progressLabel ?? "Waiting to start"} percent={progressPercent ?? 0} />
        )}

        {failed && (
          <div className="mt-2.5 flex items-start gap-2 text-[13px] text-danger">
            <AlertCircle className="mt-px size-3.5 shrink-0" aria-hidden />
            <span>{paper.failure_reason ?? "Turex couldn't read this paper."}</span>
          </div>
        )}
      </div>

      <footer className="flex items-center gap-2 border-t border-border px-4 py-2.5">
        {!processing && !failed && (
          <>
            <Badge tone={READING_STATUS[paper.reading_status].tone}>
              {READING_STATUS[paper.reading_status].label}
            </Badge>
            <span className="text-[12px] text-ink-subtle" data-tabular>
              {paper.publication_year ?? "—"}
              {paper.page_count ? ` · ${paper.page_count}p` : ""}
            </span>
          </>
        )}

        <div className="relative z-10 ml-auto flex items-center gap-1">
          {failed && (
            <Button
              variant="ghost"
              size="sm"
              loading={busy}
              onClick={() => run(() => papers.reprocess(paper.id))}
            >
              <RotateCw aria-hidden />
              Try again
            </Button>
          )}
          <Button
            variant="ghost"
            size="sm"
            disabled={busy}
            aria-label={`Remove ${paper.display_title}`}
            onClick={() => run(() => papers.remove(paper.id))}
            className="opacity-0 group-hover:opacity-100 focus-visible:opacity-100 hover:text-danger"
          >
            <Trash2 aria-hidden />
          </Button>
        </div>
      </footer>
    </Card>
  );
}

function ProcessingIndicator({ label, percent }: { label: string; percent: number }) {
  return (
    <div className="mt-3">
      <div className="flex items-center justify-between text-[12px] text-ink-muted">
        <span>{label}</span>
        <span data-tabular>{percent}%</span>
      </div>
      <div
        role="progressbar"
        aria-valuenow={percent}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={label}
        className="mt-1.5 h-1 overflow-hidden rounded-full bg-surface-sunken"
      >
        <div
          className="h-full rounded-full bg-accent transition-[width] duration-500 ease-[var(--ease-out-quart)]"
          style={{ width: `${Math.max(percent, 4)}%` }}
        />
      </div>
    </div>
  );
}
