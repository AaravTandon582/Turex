"use client";

import { Code2, FlaskConical, FolderOpen, Plus, RotateCcw, Trash2, Type } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { Cell } from "@/components/workstation/cell";
import { PageContainer } from "@/components/layout/page-container";
import { Button } from "@/components/ui/button";
import { LoadError } from "@/components/ui/async-boundary";
import { Card, EmptyState, PageHeader, Skeleton } from "@/components/ui/primitives";
import { analyses, type Analysis } from "@/lib/analyses";
import { cn } from "@/lib/cn";
import { isRuntimeReady, loadRuntime, resetNamespace, runCell } from "@/lib/python-runtime";
import { describe, useAsync } from "@/lib/use-async";

/**
 * The workstation: where a project's analysis actually runs.
 *
 * Turex could describe an experiment — variables, controls, expected result — but not do one,
 * so every number came from somewhere else and arrived as a sentence typed into a form. This
 * is the other half: Python, running here, with its output kept beside the code that produced
 * it and attached to the project it belongs to.
 *
 * The interpreter is CPython compiled to WebAssembly and it runs **in this tab**. Nothing is
 * sent to the server to be executed; the server only stores what came back. That is the
 * entire security argument, and it is why this feature can exist in a research tool at all.
 */
export default function WorkstationPage() {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<Analysis | null>(null);
  const [runningCell, setRunningCell] = useState<string | null>(null);
  const [progress, setProgress] = useState<string | null>(null);
  const [runtimeError, setRuntimeError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const executing = useRef(false);
  const pendingSaves = useRef(new Map<string, Promise<unknown>>());

  const list = useAsync(() => analyses.list(), []);

  // Warm the core interpreter while the reader writes; science packages load per cell.
  useEffect(() => {
    if (isRuntimeReady()) return;
    void loadRuntime().catch(() => {});
  }, []);

  // Open the most recent analysis on arrival, so the page has something in it.
  useEffect(() => {
    if (selectedId || !list.data || list.data.length === 0) return;
    setSelectedId(list.data[0].id);
  }, [list.data, selectedId]);

  useEffect(() => {
    if (!selectedId) return;
    let active = true;
    void analyses
      .get(selectedId)
      .then((found) => active && setDetail(found))
      .catch((caught) => active && setRuntimeError(describe(caught)));
    return () => {
      active = false;
    };
  }, [selectedId]);

  const refresh = useCallback(async () => {
    if (!selectedId) return;
    const found = await analyses.get(selectedId);
    setDetail((current) => current?.id === found.id ? found : current);
  }, [selectedId]);

  async function saveCell(analysisId: string, cellId: string, source: string) {
    const previous = pendingSaves.current.get(cellId) ?? Promise.resolve();
    const pending = previous.catch(() => {}).then(() =>
      analyses.saveCell(analysisId, cellId, { source }),
    );
    pendingSaves.current.set(cellId, pending);
    try {
      return await pending;
    } finally {
      if (pendingSaves.current.get(cellId) === pending) pendingSaves.current.delete(cellId);
    }
  }

  async function mutate(action: () => Promise<unknown>) {
    setRuntimeError(null);
    try {
      await action();
    } catch (caught) {
      setRuntimeError(describe(caught));
    }
  }

  async function create() {
    setCreating(true);
    try {
      const made = await analyses.create({ title: "Untitled analysis" });
      list.reload();
      setSelectedId(made.id);
      setDetail(made);
    } catch (caught) {
      setRuntimeError(describe(caught));
    } finally {
      setCreating(false);
    }
  }

  /**
   * Save what is on screen, run it, then record what happened.
   *
   * Saved *first* so the stored source is the one that produced the output. Skipping that
   * left the two disagreeing whenever someone typed and pressed Run inside the autosave
   * debounce, which is most of the time — the code on screen was new, the output beneath it
   * came from the old code, and nothing said so.
   *
   * The run is the truth and the write is a record of it, so a failed write is reported
   * rather than discarding a result the reader has already seen.
   */
  async function run(cellId: string, source: string) {
    if (!detail || executing.current) return;
    executing.current = true;
    setRunningCell(cellId);
    setRuntimeError(null);
    setProgress(isRuntimeReady() ? "Running…" : "Starting Python…");

    try {
      await saveCell(detail.id, cellId, source);
      const result = await runCell(source, setProgress);
      await analyses.recordRun(detail.id, cellId, {
        source,
        output: result.output,
        image: result.image,
        error: result.error,
        duration_ms: result.durationMs,
      });
      await refresh();
    } catch (caught) {
      setRuntimeError(describe(caught));
    } finally {
      executing.current = false;
      setRunningCell(null);
      setProgress(null);
    }
  }

  async function addCell(kind: "code" | "markdown") {
    if (!detail) return;
    await mutate(async () => {
      await analyses.addCell(detail.id, { kind });
      await refresh();
      list.reload();
    });
  }

  const cells = detail?.cells ?? [];

  return (
    <PageContainer>
      <PageHeader
        title="Workstation"
        description="Run analysis on your research. Python runs in this tab — numpy, pandas, matplotlib and scipy — and nothing you write here is sent anywhere to be executed."
      />

      <div className="mt-4 grid gap-4 lg:grid-cols-[220px_1fr]">
        <aside className="lg:sticky lg:top-4 lg:self-start">
          <Button size="sm" onClick={create} disabled={creating || !!runningCell} className="w-full">
            <Plus aria-hidden className="size-4" />
            New analysis
          </Button>

          {list.status === "loading" ? (
            <div className="mt-3 space-y-2">
              {Array.from({ length: 3 }, (_, index) => (
                <Skeleton key={index} className="h-10 w-full" />
              ))}
            </div>
          ) : list.status === "error" ? (
            <div className="mt-3">
              <LoadError message={list.error ?? "Couldn't load."} onRetry={list.reload} />
            </div>
          ) : (
            <ul className="mt-3 space-y-0.5">
              {(list.data ?? []).map((entry) => (
                <li key={entry.id}>
                  <button
                    type="button"
                    disabled={!!runningCell}
                    onClick={() => {
                      if (entry.id === selectedId) return;
                      setDetail(null);
                      setRuntimeError(null);
                      setSelectedId(entry.id);
                    }}
                    aria-current={entry.id === selectedId}
                    className={cn(
                      "w-full truncate rounded-md px-2.5 py-2 text-left text-[13px] transition-colors",
                      entry.id === selectedId
                        ? "bg-accent-soft text-accent"
                        : "text-ink-muted hover:bg-surface-hover hover:text-ink",
                    )}
                  >
                    {entry.title}
                    <span className="block text-[11px] text-ink-subtle">
                      {entry.cells.length} {entry.cells.length === 1 ? "cell" : "cells"}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </aside>

        <section>
          {runtimeError && (
            <p role="alert" className="mb-3 text-sm text-danger">{runtimeError}</p>
          )}
          {!detail ? (
            list.status === "loading" ? (
              <Skeleton className="h-64 w-full" />
            ) : (
              <EmptyState
                icon={<FlaskConical aria-hidden className="size-6" />}
                title="No analysis open"
                description="Create one to start computing against your research — the code runs here in your browser, not on a server."
              />
            )
          ) : (
            <>
              <Card className="flex flex-wrap items-center gap-2 p-2">
                <input
                  value={detail.title}
                  onChange={(event) => setDetail({ ...detail, title: event.target.value })}
                  onBlur={(event) => {
                    const title = event.target.value;
                    void mutate(async () => {
                      await analyses.update(detail.id, { title });
                      list.reload();
                    });
                  }}
                  aria-label="Analysis title"
                  className="min-w-0 flex-1 rounded-md border border-transparent bg-transparent px-2 py-1 text-[15px] font-medium text-ink hover:border-border focus-visible:border-border focus-visible:outline-none"
                />

                <Button size="sm" variant="ghost" onClick={() => addCell("code")}>
                  <Code2 aria-hidden className="size-4" />
                  Code
                </Button>
                <Button size="sm" variant="ghost" onClick={() => addCell("markdown")}>
                  <Type aria-hidden className="size-4" />
                  Text
                </Button>
                {detail.project_id && (
                  <Button asChild size="sm" variant="ghost">
                    <Link href={`/projects/${detail.project_id}`}>
                      <FolderOpen aria-hidden className="size-4" />
                      Project
                    </Link>
                  </Button>
                )}

                <Button
                  size="sm"
                  variant="ghost"
                  disabled={!!runningCell}
                  onClick={() => void mutate(async () => resetNamespace())}
                  title="Forget every variable, keeping Python loaded"
                >
                  <RotateCcw aria-hidden className="size-4" />
                  Reset
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={!!runningCell}
                  onClick={() => void mutate(async () => {
                    await analyses.remove(detail.id);
                    const remaining = (list.data ?? []).filter((entry) => entry.id !== detail.id);
                    list.set(remaining);
                    setDetail(null);
                    setSelectedId(remaining[0]?.id ?? null);
                  })}
                  aria-label="Delete this analysis"
                >
                  <Trash2 aria-hidden className="size-4" />
                </Button>
              </Card>

              <div className="mt-3 space-y-3">
                {cells.map((cell, index) => (
                  <Cell
                    key={cell.id}
                    cell={cell}
                    index={index}
                    running={runningCell === cell.id}
                    busy={!!runningCell}
                    progress={progress}
                    canDelete={cells.length > 1}
                    onSave={(source) => {
                      void saveCell(detail.id, cell.id, source)
                        .then(refresh)
                        .catch((caught) => setRuntimeError(describe(caught)));
                    }}
                    onRun={(source) => void run(cell.id, source)}
                    onMove={(offset) => void mutate(() => analyses.moveCell(detail.id, cell.id, offset).then(refresh))}
                    onDelete={() => void mutate(async () => {
                      await pendingSaves.current.get(cell.id);
                      await analyses.removeCell(detail.id, cell.id);
                      await refresh();
                      list.reload();
                    })}
                  />
                ))}
              </div>
            </>
          )}
        </section>
      </div>
    </PageContainer>
  );
}
