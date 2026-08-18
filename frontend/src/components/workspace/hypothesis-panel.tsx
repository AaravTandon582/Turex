"use client";

import { ChevronDown, Lightbulb, Minus, Plus, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { LoadError } from "@/components/ui/async-boundary";
import { Badge, Card, EmptyState } from "@/components/ui/primitives";
import { cn } from "@/lib/cn";
import { describe } from "@/lib/use-async";
import {
  hypothesisStatus,
  HYPOTHESIS_STATUSES,
  workspace,
  type Hypothesis,
  type HypothesisDetail,
  type HypothesisStatus,
} from "@/lib/workspace";

export function HypothesisPanel({ projectId }: { projectId: string }) {
  const [hypotheses, setHypotheses] = useState<Hypothesis[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);

  async function reload() {
    try {
      setHypotheses(await workspace.listHypotheses(projectId));
      setLoadError(null);
    } catch (caught) {
      setLoadError(describe(caught));
    }
  }

  useEffect(() => {
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="measure text-[13px] text-ink-muted">
          A hypothesis is a claim that could turn out to be false. Atlas tracks the evidence on
          both sides.
        </p>
        {!adding && (
          <Button size="sm" variant="secondary" onClick={() => setAdding(true)}>
            <Plus aria-hidden />
            Add
          </Button>
        )}
      </div>

      {adding && (
        <NewHypothesis
          projectId={projectId}
          onCancel={() => setAdding(false)}
          onCreated={async () => {
            setAdding(false);
            await reload();
          }}
        />
      )}

      {loadError && (
        <LoadError message={loadError} onRetry={() => void reload()} className="mt-3" />
      )}

      {!loadError && hypotheses && hypotheses.length === 0 && !adding && (
        <EmptyState
          icon={<Lightbulb />}
          title="No hypotheses yet"
          description="Write down what you think might be true. Even a rough one is easier to test than a vague intention."
          action={
            <Button size="sm" onClick={() => setAdding(true)}>
              Write one
            </Button>
          }
        />
      )}

      <ul className="space-y-2">
        {(hypotheses ?? []).map((hypothesis) => (
          <li key={hypothesis.id}>
            <HypothesisCard hypothesis={hypothesis} onChanged={reload} />
          </li>
        ))}
      </ul>
    </div>
  );
}

function HypothesisCard({
  hypothesis,
  onChanged,
}: {
  hypothesis: Hypothesis;
  onChanged: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [detail, setDetail] = useState<HypothesisDetail | null>(null);
  const status = hypothesisStatus(hypothesis.status);

  useEffect(() => {
    if (!expanded) return;
    void workspace
      .getHypothesis(hypothesis.id)
      .then(setDetail)
      .catch(() => setDetail(null));
  }, [expanded, hypothesis.id]);

  return (
    <Card className="p-4">
      <div className="flex items-start justify-between gap-3">
        <p className="measure text-[14px] leading-relaxed text-ink">{hypothesis.statement}</p>
        <Badge tone={status.tone}>{status.label}</Badge>
      </div>

      <dl className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px]">
        <div className="flex items-center gap-1.5">
          <dt className="text-ink-subtle">Supports</dt>
          <dd className={cn(hypothesis.supporting_count > 0 ? "text-success" : "text-ink-subtle")}>
            {hypothesis.supporting_count}
          </dd>
        </div>
        <div className="flex items-center gap-1.5">
          <dt className="text-ink-subtle">Contradicts</dt>
          <dd
            className={cn(hypothesis.contradicting_count > 0 ? "text-danger" : "text-ink-subtle")}
          >
            {hypothesis.contradicting_count}
          </dd>
        </div>
      </dl>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-1.5 text-[12px] text-ink-muted">
          Status
          <select
            value={hypothesis.status}
            onChange={async (event) => {
              await workspace.updateHypothesis(hypothesis.id, {
                status: event.target.value as HypothesisStatus,
              });
              onChanged();
            }}
            className="h-7 rounded-md border border-border bg-surface px-1.5 text-[12px] text-ink focus:border-accent focus:outline-none"
          >
            {HYPOTHESIS_STATUSES.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        <button
          type="button"
          onClick={() => setExpanded((value) => !value)}
          aria-expanded={expanded}
          className="flex items-center gap-1 rounded-sm px-1.5 py-1 text-[12px] text-ink-muted hover:text-ink"
        >
          <ChevronDown
            className={cn("size-3 transition-transform", expanded && "rotate-180")}
            aria-hidden
          />
          Evidence and detail
        </button>

        <button
          type="button"
          aria-label="Delete hypothesis"
          onClick={async () => {
            await workspace.deleteHypothesis(hypothesis.id);
            onChanged();
          }}
          className="ml-auto rounded-sm p-1 text-ink-subtle hover:text-danger"
        >
          <Trash2 className="size-3.5" aria-hidden />
        </button>
      </div>

      {expanded && (
        <div className="mt-3 space-y-3 border-t border-border pt-3">
          {hypothesis.motivation && (
            <Detail label="Motivation" value={hypothesis.motivation} />
          )}
          {hypothesis.assumptions && (
            <Detail label="Assumptions" value={hypothesis.assumptions} />
          )}

          {detail === null ? (
            <p className="text-[12px] text-ink-subtle">Loading evidence…</p>
          ) : detail.evidence.length === 0 ? (
            <p className="measure text-[12px] text-ink-subtle">
              No evidence attached yet. Search your library, then link the passages that bear on
              this — for or against.
            </p>
          ) : (
            <ul className="space-y-2">
              {detail.evidence.map((item) => (
                <li
                  key={item.id}
                  className={cn(
                    "rounded-md border border-l-2 bg-surface-sunken p-2.5",
                    item.stance === "supports"
                      ? "border-l-success border-border"
                      : "border-l-danger border-border",
                  )}
                >
                  <div className="flex items-center gap-1.5 text-[11px]">
                    {item.stance === "supports" ? (
                      <Plus className="size-3 text-success" aria-hidden />
                    ) : (
                      <Minus className="size-3 text-danger" aria-hidden />
                    )}
                    <span className="truncate text-ink">{item.paper_title}</span>
                    <span className="shrink-0 font-mono text-ink-subtle">{item.locator}</span>
                    <button
                      type="button"
                      aria-label="Remove evidence"
                      onClick={async () => {
                        await workspace.detachEvidence(item.id);
                        setDetail(await workspace.getHypothesis(hypothesis.id));
                        onChanged();
                      }}
                      className="ml-auto shrink-0 rounded-sm p-0.5 text-ink-subtle hover:text-danger"
                    >
                      <Trash2 className="size-3" aria-hidden />
                    </button>
                  </div>
                  <p className="mt-1.5 line-clamp-3 text-[12px] leading-relaxed text-ink-muted">
                    {item.quoted_text}
                  </p>
                  {item.reasoning && (
                    <p className="mt-1.5 border-t border-border pt-1.5 text-[12px] text-ink">
                      {item.reasoning}
                    </p>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </Card>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[11px] font-semibold tracking-wide text-ink-muted uppercase">{label}</p>
      <p className="measure mt-0.5 text-[13px] leading-relaxed text-ink">{value}</p>
    </div>
  );
}

function NewHypothesis({
  projectId,
  onCancel,
  onCreated,
}: {
  projectId: string;
  onCancel: () => void;
  onCreated: () => void;
}) {
  const [statement, setStatement] = useState("");
  const [assumptions, setAssumptions] = useState("");
  const [submitting, setSubmitting] = useState(false);

  return (
    <Card className="animate-[var(--animate-rise)] p-4">
      <form
        className="space-y-3"
        onSubmit={async (event) => {
          event.preventDefault();
          setSubmitting(true);
          try {
            await workspace.createHypothesis({
              statement,
              project_id: projectId,
              assumptions: assumptions.trim() || undefined,
            });
            onCreated();
          } finally {
            setSubmitting(false);
          }
        }}
      >
        <div className="space-y-1.5">
          <label htmlFor="statement" className="block text-[13px] font-medium text-ink">
            Hypothesis
          </label>
          <textarea
            id="statement"
            rows={2}
            autoFocus
            required
            value={statement}
            onChange={(event) => setStatement(event.target.value)}
            placeholder="Structured retrieval improves reasoning accuracy more than scale alone."
            className="block w-full resize-none rounded-md border border-border bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-subtle focus:border-accent focus:outline-none"
          />
        </div>

        <div className="space-y-1.5">
          <label htmlFor="assumptions" className="block text-[13px] font-medium text-ink">
            Assumptions
          </label>
          <textarea
            id="assumptions"
            rows={2}
            value={assumptions}
            onChange={(event) => setAssumptions(event.target.value)}
            placeholder="What has to be true for this to be testable at all?"
            className="block w-full resize-none rounded-md border border-border bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-subtle focus:border-accent focus:outline-none"
          />
          <p className="text-[12px] text-ink-subtle">
            Writing these down is what makes a failed test interpretable rather than just
            disappointing.
          </p>
        </div>

        <div className="flex gap-2">
          <Button type="submit" size="sm" loading={submitting} disabled={!statement.trim()}>
            Add hypothesis
          </Button>
          <Button type="button" variant="ghost" size="sm" onClick={onCancel}>
            Cancel
          </Button>
        </div>
      </form>
    </Card>
  );
}
