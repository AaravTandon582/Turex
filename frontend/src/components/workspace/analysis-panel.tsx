"use client";

import { Clock, Plus, Terminal } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { LoadError } from "@/components/ui/async-boundary";
import { Badge, Card, EmptyState, Skeleton } from "@/components/ui/primitives";
import { analyses, type Analysis } from "@/lib/analyses";
import { describe } from "@/lib/use-async";

/**
 * The analyses belonging to a project.
 *
 * The workstation existed but stood apart from the projects it was meant to serve, which made
 * it a scratchpad rather than part of the research record. An experiment's `actual_result` is
 * a sentence someone typed; an analysis is the code that produced it, kept where the claim it
 * supports can be traced back to it.
 *
 * The work itself happens in the workstation — this lists, creates, and links, and does not
 * duplicate the editor.
 */
export function AnalysisPanel({ projectId }: { projectId: string }) {
  const [items, setItems] = useState<Analysis[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    try {
      setItems(await analyses.list(projectId));
    } catch (caught) {
      setError(describe(caught));
    }
  }, [projectId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function create() {
    setCreating(true);
    try {
      await analyses.create({ title: "Untitled analysis", project_id: projectId });
      await load();
    } catch (caught) {
      setError(describe(caught));
    } finally {
      setCreating(false);
    }
  }

  if (error) return <LoadError message={error} onRetry={() => void load()} />;
  if (items === null) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 2 }, (_, index) => (
          <Skeleton key={index} className="h-16 w-full" />
        ))}
      </div>
    );
  }

  return (
    <div>
      <Button size="sm" onClick={create} disabled={creating}>
        <Plus aria-hidden className="size-4" />
        New analysis
      </Button>

      {items.length === 0 ? (
        <div className="mt-3">
          <EmptyState
            icon={<Terminal aria-hidden className="size-6" />}
            title="No analysis yet"
            description="Run Python against this project's data — in your browser, with the output kept beside the code that produced it."
          />
        </div>
      ) : (
        <ul className="mt-3 space-y-2">
          {items.map((analysis) => {
            const stale = analysis.cells.filter((cell) => cell.status === "stale").length;
            const failed = analysis.cells.filter((cell) => cell.status === "error").length;

            return (
              <li key={analysis.id}>
                <Card className="p-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <Link
                      href="/workstation"
                      className="text-[14px] font-medium text-ink hover:text-accent"
                    >
                      {analysis.title}
                    </Link>

                    {/* The two states worth surfacing away from the editor: a result that no
                        longer matches its code, and one that failed outright. */}
                    {stale > 0 && (
                      <Badge tone="warning">
                        {stale} stale {stale === 1 ? "cell" : "cells"}
                      </Badge>
                    )}
                    {failed > 0 && (
                      <Badge tone="danger">
                        {failed} {failed === 1 ? "error" : "errors"}
                      </Badge>
                    )}
                  </div>

                  <p className="mt-1 flex flex-wrap items-center gap-2 text-[12px] text-ink-subtle">
                    <span>
                      {analysis.cells.length} {analysis.cells.length === 1 ? "cell" : "cells"}
                    </span>
                    {analysis.last_run_at && (
                      <span className="flex items-center gap-1">
                        <Clock aria-hidden className="size-3" />
                        last run {new Date(analysis.last_run_at).toLocaleDateString()}
                      </span>
                    )}
                  </p>
                </Card>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
