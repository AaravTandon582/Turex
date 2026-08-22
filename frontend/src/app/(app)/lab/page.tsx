"use client";

import { AlertTriangle, Lock, NotebookPen, ShieldCheck } from "lucide-react";
import { useCallback, useState } from "react";

import { PageContainer } from "@/components/layout/page-container";
import { Button } from "@/components/ui/button";
import { LoadError } from "@/components/ui/async-boundary";
import { Spinner } from "@/components/ui/loading";
import { Badge, Card, EmptyState, PageHeader, Skeleton } from "@/components/ui/primitives";
import { Prose } from "@/components/ui/prose";
import { lab, type ChainReport } from "@/lib/lab";
import { describe, useAsync } from "@/lib/use-async";

/**
 * The lab notebook: entries that cannot be edited or deleted.
 *
 * Everything else in Turex can be corrected, because a note whose author cannot fix a typo is
 * a note nobody writes in. This one cannot, and that is the entire point — its value in an
 * authorship or reproducibility dispute comes from what it says today being what it said when
 * it was written.
 *
 * The interface has to make that obvious *before* someone writes, not after they try to edit.
 * Hence the warning on the composer rather than a disabled button discovered later.
 */
export default function LabPage() {
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<ChainReport | null>(null);
  const [checking, setChecking] = useState(false);

  const entries = useAsync(() => lab.list(), []);

  const append = useCallback(async () => {
    if (!body.trim()) return;
    setSaving(true);
    setError(null);
    try {
      await lab.append({ title: title.trim() || undefined, body });
      setTitle("");
      setBody("");
      setReport(null);
      entries.reload();
    } catch (caught) {
      setError(describe(caught));
    } finally {
      setSaving(false);
    }
  }, [body, title, entries]);

  async function verify() {
    setChecking(true);
    setError(null);
    try {
      setReport(await lab.verify());
    } catch (caught) {
      setError(describe(caught));
    } finally {
      setChecking(false);
    }
  }

  const page = entries.data;

  return (
    <PageContainer>
      <PageHeader
        title="Lab notebook"
        description="Timestamped entries that cannot be edited or deleted. Each one carries the hash of the entry before it, so any change to the record breaks the chain and shows up."
      />

      <Card className="mt-4 p-3">
        <input
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder="What is this entry about? (optional)"
          aria-label="Entry title"
          className="w-full rounded-md border border-border bg-surface px-3 py-2 text-[14px] text-ink placeholder:text-ink-subtle focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
        />

        <textarea
          value={body}
          onChange={(event) => setBody(event.target.value)}
          rows={5}
          placeholder="What you did, what you observed, what you decided. Markdown and LaTeX are rendered."
          aria-label="Entry"
          className="scrollbar-slim mt-2 w-full resize-y rounded-md border border-border bg-surface px-3 py-2 text-[14px] leading-relaxed text-ink placeholder:text-ink-subtle focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none"
        />

        <div className="mt-2 flex flex-wrap items-center gap-2">
          {/* Said before writing, not discovered afterwards. Someone who expects to be able
              to edit will write differently from someone who knows they cannot. */}
          <p className="flex items-center gap-1.5 text-[12px] text-ink-muted">
            <Lock aria-hidden className="size-3.5" />
            Once recorded, this cannot be changed or removed.
          </p>

          <div className="ml-auto flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={verify} disabled={checking}>
              {checking ? <Spinner label="Checking the record" /> : (
                <ShieldCheck aria-hidden className="size-4" />
              )}
              Check the record
            </Button>
            <Button size="sm" onClick={append} disabled={saving || !body.trim()}>
              {saving ? <Spinner label="Recording" /> : <NotebookPen aria-hidden className="size-4" />}
              Record
            </Button>
          </div>
        </div>

        {error && (
          <p role="alert" className="mt-2 text-[13px] text-danger">
            {error}
          </p>
        )}

        {report && (
          <div className="mt-3 border-t border-border pt-3">
            {report.intact ? (
              <p className="flex items-center gap-1.5 text-[13px] text-success">
                <ShieldCheck aria-hidden className="size-4" />
                All {report.entries} {report.entries === 1 ? "entry" : "entries"} verify. Nothing
                has been altered.
              </p>
            ) : (
              <div className="text-[13px] text-danger">
                <p className="flex items-center gap-1.5 font-medium">
                  <AlertTriangle aria-hidden className="size-4" />
                  The record has been altered, starting at entry {report.first_break_at}.
                </p>
                <ul className="mt-1.5 space-y-1">
                  {report.breaks.map((issue, index) => (
                    <li key={`${issue.entry_id}-${index}`} className="text-ink-muted">
                      Entry {issue.sequence}: {issue.reason}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <p className="mt-1.5 text-[11px] text-ink-subtle">
              Checked {new Date(report.checked_at).toLocaleString()}. This shows nothing was
              rewritten — it does not prove when anything was written.
            </p>
          </div>
        )}
      </Card>

      {entries.status === "loading" ? (
        <div className="mt-4 space-y-3">
          {Array.from({ length: 3 }, (_, index) => (
            <Skeleton key={index} className="h-24 w-full" />
          ))}
        </div>
      ) : entries.status === "error" ? (
        <div className="mt-4">
          <LoadError message={entries.error ?? "Couldn't load."} onRetry={entries.reload} />
        </div>
      ) : page && page.items.length === 0 ? (
        <div className="mt-4">
          <EmptyState
            icon={<NotebookPen aria-hidden className="size-6" />}
            title="Nothing recorded yet"
            description="Write down what you did while you remember it. Entries are timestamped and cannot be changed afterwards, which is what makes them worth anything later."
          />
        </div>
      ) : page ? (
        <>
          <p className="mt-4 text-sm text-ink-muted">
            {page.total} {page.total === 1 ? "entry" : "entries"}
          </p>

          <ol className="mt-3 space-y-3">
            {page.items.map((entry) => (
              <li key={entry.id}>
                <Card className="p-4">
                  <div className="flex flex-wrap items-center gap-2 text-[12px] text-ink-subtle">
                    <Badge tone="neutral">#{entry.sequence}</Badge>
                    <time dateTime={entry.recorded_at}>
                      {new Date(entry.recorded_at).toLocaleString()}
                    </time>
                  </div>

                  {entry.title && (
                    <h3 className="mt-1.5 text-[15px] font-medium text-ink">{entry.title}</h3>
                  )}

                  <Prose density="tight" className="mt-1.5 text-[14px] leading-relaxed text-ink">
                    {entry.body}
                  </Prose>

                  {/* Shown, not hidden. The hash is the evidence, and evidence nobody can
                      copy out and check for themselves is not evidence. */}
                  <p className="mt-2 font-mono text-[10px] break-all text-ink-subtle">
                    {entry.entry_hash}
                  </p>
                </Card>
              </li>
            ))}
          </ol>
        </>
      ) : null}
    </PageContainer>
  );
}
