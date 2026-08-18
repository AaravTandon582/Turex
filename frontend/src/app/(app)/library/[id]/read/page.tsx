"use client";

import { ArrowLeft, Minus, PanelRightClose, PanelRightOpen, Plus } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { Document, pdfjs } from "react-pdf";

import { AskPanel, type AskRequest } from "@/components/reader/ask-panel";
import { PdfPage, type PageSelection } from "@/components/reader/pdf-page";
import { ReaderSidebar } from "@/components/reader/reader-sidebar";
import { SelectionMenu, type SelectionAction } from "@/components/reader/selection-menu";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/primitives";
import { ApiError } from "@/lib/api";
import {
  annotations as annotationsApi,
  type Annotation,
  type HighlightColour,
} from "@/lib/annotations";
import type { AssistantMode } from "@/lib/assistant";
import { papers, type PaperDetail, type PaperSection } from "@/lib/papers";

import "react-pdf/dist/Page/TextLayer.css";

// The worker is resolved from the installed package rather than copied into /public, so it
// can never drift out of step with the pdfjs version react-pdf was built against.
pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  "pdfjs-dist/build/pdf.worker.min.mjs",
  import.meta.url,
).toString();

const ZOOM_STEPS = [0.75, 0.9, 1, 1.15, 1.35, 1.6];
const BASE_WIDTH = 720;

/** What each selection action asks, and in which mode. */
const ACTIONS: Record<SelectionAction, { mode: AssistantMode; prompt: (text: string) => string }> =
  {
    explain: {
      mode: "explain",
      prompt: (text) =>
        `Explain this passage from the paper I'm reading, in plain language:\n\n"${text}"`,
    },
    critique: {
      mode: "critique",
      prompt: (text) =>
        `Critique this passage. What does it assume, and what could undermine it?\n\n"${text}"`,
    },
    equation: {
      mode: "explain",
      prompt: (text) =>
        `Break down this equation. Say what it computes, what every symbol means, the ` +
        `intuition behind it, and how this paper uses it:\n\n"${text}"`,
    },
  };

export default function ReaderPage() {
  const { id } = useParams<{ id: string }>();

  const [paper, setPaper] = useState<PaperDetail | null>(null);
  const [sections, setSections] = useState<PaperSection[]>([]);
  const [annotations, setAnnotations] = useState<Annotation[]>([]);
  const [pageCount, setPageCount] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const [zoomIndex, setZoomIndex] = useState(2);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [selection, setSelection] = useState<PageSelection | null>(null);
  const [activeAnnotationId, setActiveAnnotationId] = useState<string | null>(null);
  const [askRequest, setAskRequest] = useState<AskRequest | null>(null);

  const scrollRef = useRef<HTMLDivElement>(null);
  const width = Math.round(BASE_WIDTH * ZOOM_STEPS[zoomIndex]);

  const reloadAnnotations = useCallback(() => {
    void annotationsApi
      .list(id)
      .then(setAnnotations)
      .catch(() => undefined);
  }, [id]);

  useEffect(() => {
    void (async () => {
      try {
        const detail = await papers.get(id);
        setPaper(detail);
        if (detail.status === "ready") {
          const [loadedSections] = await Promise.all([
            papers.sections(id),
            papers.markOpened(id).catch(() => undefined),
          ]);
          setSections(loadedSections);
        }
        reloadAnnotations();
      } catch (caught) {
        setError(
          caught instanceof ApiError && caught.code === "not_found"
            ? "That paper isn't in your library."
            : "Atlas couldn't open that paper.",
        );
      }
    })();
  }, [id, reloadAnnotations]);

  // Escape clears whatever is open, innermost first.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (askRequest) setAskRequest(null);
      else if (selection) setSelection(null);
      else setActiveAnnotationId(null);
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [askRequest, selection]);

  function jumpToPage(page: number) {
    scrollRef.current
      ?.querySelector(`[data-page="${page}"]`)
      ?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  async function highlight(colour: HighlightColour) {
    if (!selection) return;
    const pending = selection;
    setSelection(null);
    window.getSelection()?.removeAllRanges();

    try {
      const created = await annotationsApi.create(id, {
        page_number: pending.pageNumber,
        text_offset: pending.offset,
        selected_text: pending.text,
        colour,
      });
      setAnnotations((current) => [...current, created]);
    } catch {
      // A failed highlight is recoverable by trying again; reload so the UI matches the server.
      reloadAnnotations();
    }
  }

  function askAbout(action: SelectionAction) {
    if (!selection) return;
    const { prompt, mode } = ACTIONS[action];
    setAskRequest({ question: prompt(selection.text), mode, quotedText: selection.text });
    setSelection(null);
    window.getSelection()?.removeAllRanges();
  }

  if (error) {
    return (
      <div className="p-8">
        <BackLink paperId={id} />
        <p role="alert" className="mt-6 text-sm text-ink-muted">
          {error}
        </p>
      </div>
    );
  }

  if (!paper) {
    return (
      <div className="p-8">
        <Skeleton className="h-6 w-40" />
        <Skeleton className="mx-auto mt-8 h-[900px] w-[720px]" />
        <span className="sr-only">Opening the paper</span>
      </div>
    );
  }

  if (paper.status !== "ready") {
    return (
      <div className="p-8">
        <BackLink paperId={id} />
        <p className="mt-6 text-sm text-ink-muted">
          Atlas is still reading this paper. It will be available here once processing
          finishes.
        </p>
        <Button asChild variant="secondary" size="sm" className="mt-4">
          <Link href={`/library/${id}`}>See progress</Link>
        </Button>
      </div>
    );
  }

  return (
    <div className="flex h-[calc(100dvh-3.5rem)] flex-col md:h-dvh">
      <header className="flex h-12 shrink-0 items-center gap-3 border-b border-border px-3">
        <BackLink paperId={id} />
        <h1 className="min-w-0 flex-1 truncate text-[13px] font-medium text-ink">
          {paper.display_title}
        </h1>

        <div className="flex items-center gap-0.5 rounded-md border border-border p-0.5">
          <button
            type="button"
            aria-label="Zoom out"
            disabled={zoomIndex === 0}
            onClick={() => setZoomIndex((index) => Math.max(0, index - 1))}
            className="flex size-6 items-center justify-center rounded-sm text-ink-muted hover:bg-surface-hover disabled:opacity-40"
          >
            <Minus className="size-3.5" aria-hidden />
          </button>
          <span className="w-10 text-center font-mono text-[11px] text-ink-subtle" data-tabular>
            {Math.round(ZOOM_STEPS[zoomIndex] * 100)}%
          </span>
          <button
            type="button"
            aria-label="Zoom in"
            disabled={zoomIndex === ZOOM_STEPS.length - 1}
            onClick={() => setZoomIndex((index) => Math.min(ZOOM_STEPS.length - 1, index + 1))}
            className="flex size-6 items-center justify-center rounded-sm text-ink-muted hover:bg-surface-hover disabled:opacity-40"
          >
            <Plus className="size-3.5" aria-hidden />
          </button>
        </div>

        <button
          type="button"
          onClick={() => setSidebarOpen((open) => !open)}
          aria-label={sidebarOpen ? "Hide panel" : "Show panel"}
          aria-pressed={sidebarOpen}
          className="flex size-8 items-center justify-center rounded-md text-ink-muted hover:bg-surface-hover hover:text-ink"
        >
          {sidebarOpen ? (
            <PanelRightClose className="size-4" aria-hidden />
          ) : (
            <PanelRightOpen className="size-4" aria-hidden />
          )}
        </button>
      </header>

      <div className="relative flex min-h-0 flex-1">
        <div ref={scrollRef} className="scrollbar-slim flex-1 overflow-y-auto bg-surface-sunken">
          <div className="relative mx-auto w-fit py-8">
            <Document
              file={papers.fileUrl(id)}
              // The PDF is served from the API origin behind a session cookie.
              options={{ withCredentials: true }}
              onLoadSuccess={({ numPages }) => setPageCount(numPages)}
              onLoadError={() => setError("Atlas couldn't render this PDF.")}
              loading={<Skeleton className="h-[900px] w-[720px]" />}
              error={
                <p className="p-8 text-sm text-ink-muted">Atlas couldn&rsquo;t render this PDF.</p>
              }
            >
              <div className="space-y-8">
                {Array.from({ length: pageCount }, (_, index) => (
                  <PdfPage
                    key={index}
                    pageNumber={index + 1}
                    width={width}
                    annotations={annotations}
                    activeAnnotationId={activeAnnotationId}
                    onSelect={setSelection}
                    onHighlightClick={setActiveAnnotationId}
                    overlay={
                      selection?.pageNumber === index + 1 ? (
                        <SelectionMenu
                          point={selection.point}
                          onHighlight={highlight}
                          onAsk={askAbout}
                          onDismiss={() => setSelection(null)}
                        />
                      ) : undefined
                    }
                  />
                ))}
              </div>
            </Document>

          </div>
        </div>

        {sidebarOpen && (
          <aside
            className={
              // Full width over the page on a phone, a fixed rail beside it from md up. A
              // 320px panel alongside a PDF on a 375px screen leaves the paper unreadable,
              // which defeats the point of a reader.
              "absolute inset-y-0 right-0 z-20 flex w-full flex-col border-l border-border bg-canvas shadow-[var(--shadow-lg)] " +
              "md:static md:z-auto md:w-80 md:shrink-0 md:shadow-none"
            }
          >
            <div className="min-h-0 flex-1">
              <ReaderSidebar
                paperId={id}
                sections={sections}
                annotations={annotations}
                activeAnnotationId={activeAnnotationId}
                onJumpToPage={jumpToPage}
                onSelectAnnotation={setActiveAnnotationId}
                onAnnotationsChanged={reloadAnnotations}
              />
            </div>
            {askRequest && (
              <AskPanel paperId={id} request={askRequest} onClose={() => setAskRequest(null)} />
            )}
          </aside>
        )}
      </div>
    </div>
  );
}

function BackLink({ paperId }: { paperId: string }) {
  return (
    <Link
      href={`/library/${paperId}`}
      className="inline-flex shrink-0 items-center gap-1.5 rounded-sm text-[13px] text-ink-muted hover:text-ink"
    >
      <ArrowLeft className="size-3.5" aria-hidden />
      <span className="hidden sm:inline">Back</span>
    </Link>
  );
}
