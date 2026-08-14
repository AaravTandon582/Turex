/**
 * Anchoring highlights to text in a rendered PDF page.
 *
 * pdf.js paints a page to canvas and overlays an invisible text layer of positioned spans.
 * Selection happens in that layer, so a highlight has to be expressed in terms of it — but
 * *stored* in terms that survive a re-render at a different zoom, in a different browser, on
 * a different device.
 *
 * The stored anchor is a character offset into the page's concatenated text plus a length.
 * These helpers convert between that and a live DOM Range:
 *
 *   selection  →  { offset, length, text }   when the user highlights
 *   { offset, length }  →  rectangles        when the page renders
 *
 * Offsets are computed by walking text nodes in document order, which is the same order
 * pdf.js emits them, so the mapping is stable for a given document.
 */

export interface TextAnchor {
  offset: number;
  length: number;
  text: string;
}

/** Every text node inside the layer, in document order. */
function textNodesOf(container: HTMLElement): Text[] {
  const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
  const nodes: Text[] = [];
  let node = walker.nextNode();
  while (node) {
    nodes.push(node as Text);
    node = walker.nextNode();
  }
  return nodes;
}

/** The page's text as one string — the coordinate space offsets are measured in. */
export function pageText(container: HTMLElement): string {
  return textNodesOf(container)
    .map((node) => node.data)
    .join("");
}

/**
 * Convert the current selection into a storable anchor.
 *
 * Returns null when the selection is empty, collapsed, or lies outside this page — the last
 * case matters because a drag can run across a page boundary, and half a selection anchored
 * to the wrong page would render in the wrong place.
 */
export function anchorFromSelection(
  container: HTMLElement,
  selection: Selection,
): TextAnchor | null {
  if (selection.isCollapsed || selection.rangeCount === 0) return null;

  const range = selection.getRangeAt(0);
  if (!container.contains(range.startContainer) || !container.contains(range.endContainer)) {
    return null;
  }

  const text = selection.toString().trim();
  if (!text) return null;

  let offset = 0;
  for (const node of textNodesOf(container)) {
    if (node === range.startContainer) {
      offset += range.startOffset;
      return { offset, length: text.length, text };
    }
    offset += node.data.length;
  }

  return null;
}

/** Rebuild a DOM Range from a stored anchor, or null if the text has shifted away. */
export function rangeFromAnchor(
  container: HTMLElement,
  anchor: Pick<TextAnchor, "offset" | "length">,
): Range | null {
  const nodes = textNodesOf(container);
  const range = document.createRange();

  let cursor = 0;
  let started = false;
  const end = anchor.offset + anchor.length;

  for (const node of nodes) {
    const nodeEnd = cursor + node.data.length;

    if (!started && anchor.offset < nodeEnd) {
      range.setStart(node, Math.max(0, anchor.offset - cursor));
      started = true;
    }
    if (started && end <= nodeEnd) {
      range.setEnd(node, Math.max(0, end - cursor));
      return range;
    }
    cursor = nodeEnd;
  }

  if (started && nodes.length > 0) {
    // The anchor runs past the end of the page: clamp rather than lose the highlight.
    const last = nodes[nodes.length - 1];
    range.setEnd(last, last.data.length);
    return range;
  }

  return null;
}

export interface HighlightRect {
  top: number;
  left: number;
  width: number;
  height: number;
}

/**
 * Rectangles covering an anchor, relative to the page container.
 *
 * A selection spanning lines or columns produces several rectangles; each is drawn
 * separately so the highlight follows the text rather than boxing everything between the
 * first and last character.
 */
export function rectsForAnchor(
  container: HTMLElement,
  anchor: Pick<TextAnchor, "offset" | "length">,
): HighlightRect[] {
  const range = rangeFromAnchor(container, anchor);
  if (!range) return [];

  const origin = container.getBoundingClientRect();

  return Array.from(range.getClientRects())
    // Zero-area rects appear at line breaks and would render as invisible slivers.
    .filter((rect) => rect.width > 0.5 && rect.height > 0.5)
    .map((rect) => ({
      top: rect.top - origin.top,
      left: rect.left - origin.left,
      width: rect.width,
      height: rect.height,
    }));
}

/** Where to place a floating menu for the current selection, relative to the container. */
export function selectionAnchorPoint(
  container: HTMLElement,
  selection: Selection,
): { top: number; left: number } | null {
  if (selection.rangeCount === 0) return null;
  const rects = selection.getRangeAt(0).getClientRects();
  if (rects.length === 0) return null;

  const origin = container.getBoundingClientRect();
  const first = rects[0];
  return { top: first.top - origin.top, left: first.left - origin.left + first.width / 2 };
}
