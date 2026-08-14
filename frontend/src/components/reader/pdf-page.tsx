"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Page } from "react-pdf";

import { cn } from "@/lib/cn";
import { colourOf, type Annotation } from "@/lib/annotations";
import {
  anchorFromSelection,
  rectsForAnchor,
  selectionAnchorPoint,
  type HighlightRect,
  type TextAnchor,
} from "@/lib/text-layer";

export interface PageSelection extends TextAnchor {
  pageNumber: number;
  /** Position of the floating menu, relative to the page. */
  point: { top: number; left: number };
}

interface PdfPageProps {
  pageNumber: number;
  width: number;
  annotations: Annotation[];
  activeAnnotationId: string | null;
  onSelect: (selection: PageSelection | null) => void;
  onHighlightClick: (annotationId: string) => void;
  /** The selection menu, when the active selection is on this page. Rendered here because
      the coordinates come from this page's text layer. */
  overlay?: ReactNode;
}

/**
 * One rendered page, with its highlights drawn over the text layer.
 *
 * Highlight rectangles are recomputed whenever the page re-renders or resizes rather than
 * stored: they are a function of the current layout, and caching them across a zoom change
 * would leave highlights floating away from their text.
 */
export function PdfPage({
  pageNumber,
  width,
  annotations,
  activeAnnotationId,
  onSelect,
  onHighlightClick,
  overlay,
}: PdfPageProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [rendered, setRendered] = useState(false);
  const [rects, setRects] = useState<Map<string, HighlightRect[]>>(new Map());

  const pageAnnotations = annotations.filter(
    (annotation) => annotation.page_number === pageNumber,
  );

  const measure = useCallback(() => {
    const layer = containerRef.current?.querySelector<HTMLElement>(
      ".react-pdf__Page__textContent",
    );
    if (!layer) return;

    const next = new Map<string, HighlightRect[]>();
    for (const annotation of pageAnnotations) {
      const found = rectsForAnchor(layer, {
        offset: annotation.text_offset,
        length: annotation.text_length,
      });
      if (found.length > 0) next.set(annotation.id, found);
    }
    setRects(next);
    // `pageAnnotations` is derived each render; depending on it directly would loop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [annotations, pageNumber]);

  useEffect(() => {
    if (rendered) measure();
  }, [rendered, measure, width]);

  // Re-measure when the page box changes size — a window resize or a zoom step.
  useEffect(() => {
    const element = containerRef.current;
    if (!element || !rendered) return;
    const observer = new ResizeObserver(() => measure());
    observer.observe(element);
    return () => observer.disconnect();
  }, [rendered, measure]);

  function handleMouseUp() {
    const layer = containerRef.current?.querySelector<HTMLElement>(
      ".react-pdf__Page__textContent",
    );
    const selection = window.getSelection();
    if (!layer || !selection) {
      onSelect(null);
      return;
    }

    const anchor = anchorFromSelection(layer, selection);
    const point = selectionAnchorPoint(layer, selection);
    onSelect(anchor && point ? { ...anchor, pageNumber, point } : null);
  }

  return (
    <div
      ref={containerRef}
      data-page={pageNumber}
      onMouseUp={handleMouseUp}
      className="relative mx-auto w-fit shadow-[var(--shadow-md)]"
    >
      <Page
        pageNumber={pageNumber}
        width={width}
        renderTextLayer
        renderAnnotationLayer={false}
        onRenderSuccess={() => setRendered(true)}
        loading={
          <div
            className="animate-[var(--animate-shimmer)] bg-surface-sunken"
            style={{ width, height: width * 1.294 }}
          />
        }
      />

      {/* Drawn under the text layer so selection still works through them. */}
      <div className="pointer-events-none absolute inset-0" aria-hidden>
        {pageAnnotations.map((annotation) =>
          (rects.get(annotation.id) ?? []).map((rect, index) => (
            <button
              key={`${annotation.id}-${index}`}
              type="button"
              tabIndex={-1}
              onClick={() => onHighlightClick(annotation.id)}
              className={cn(
                "pointer-events-auto absolute rounded-[2px] transition-colors",
                colourOf(annotation.colour).swatch,
                activeAnnotationId === annotation.id && "ring-2 ring-accent",
              )}
              style={{
                top: rect.top,
                left: rect.left,
                width: rect.width,
                height: rect.height,
              }}
            />
          )),
        )}
      </div>

      {overlay}

      <span className="pointer-events-none absolute -bottom-5 left-0 font-mono text-[10px] text-ink-subtle">
        {pageNumber}
      </span>
    </div>
  );
}
