"use client";

import { python } from "@codemirror/lang-python";
import { EditorState, type Extension } from "@codemirror/state";
import { EditorView, keymap, lineNumbers, placeholder as placeholderExt } from "@codemirror/view";
import { defaultKeymap, history, historyKeymap, indentWithTab } from "@codemirror/commands";
import { bracketMatching, indentOnInput, syntaxHighlighting } from "@codemirror/language";
import { closeBrackets, closeBracketsKeymap } from "@codemirror/autocomplete";
import { HighlightStyle } from "@codemirror/language";
import { tags } from "@lezer/highlight";
import { useEffect, useRef } from "react";

import { cn } from "@/lib/cn";

/**
 * Syntax colours drawn from the app's own tokens rather than a packaged theme.
 *
 * Every editor theme worth using brings its own palette, and dropping one into Turex would put
 * a second colour scheme on the page — and one that ignores whether the reader chose light or
 * dark. These are CSS variables, so they follow the app.
 */
const highlighting = HighlightStyle.define([
  { tag: tags.keyword, color: "var(--color-accent)" },
  { tag: [tags.string, tags.special(tags.string)], color: "var(--color-success)" },
  { tag: tags.comment, color: "var(--color-ink-subtle)", fontStyle: "italic" },
  { tag: [tags.number, tags.bool, tags.null], color: "var(--color-highlight-ink, #b45309)" },
  { tag: [tags.function(tags.variableName), tags.definition(tags.variableName)], color: "var(--color-ink)" },
  { tag: tags.operator, color: "var(--color-ink-muted)" },
  { tag: tags.className, color: "var(--color-accent)" },
]);

const theme = EditorView.theme({
  "&": { fontSize: "13px", backgroundColor: "transparent" },
  ".cm-content": {
    fontFamily: "var(--font-mono, ui-monospace, monospace)",
    padding: "10px 0",
    caretColor: "var(--color-ink)",
  },
  ".cm-gutters": {
    backgroundColor: "transparent",
    border: "none",
    color: "var(--color-ink-subtle)",
    fontFamily: "var(--font-mono, ui-monospace, monospace)",
    fontSize: "11px",
  },
  ".cm-activeLine": { backgroundColor: "transparent" },
  ".cm-activeLineGutter": { backgroundColor: "transparent", color: "var(--color-ink-muted)" },
  "&.cm-focused": { outline: "none" },
  ".cm-cursor": { borderLeftColor: "var(--color-ink)" },
  ".cm-selectionBackground, ::selection": { backgroundColor: "var(--color-accent-soft)" },
  "&.cm-focused .cm-selectionBackground": { backgroundColor: "var(--color-accent-soft)" },
});

interface CodeEditorProps {
  value: string;
  onChange: (value: string) => void;
  /** Ctrl/Cmd-Enter. The one shortcut every notebook has, and the one people try first. */
  onRun?: () => void;
  language?: "python" | "markdown";
  placeholder?: string;
  className?: string;
  ariaLabel?: string;
}

export function CodeEditor({
  value,
  onChange,
  onRun,
  language = "python",
  placeholder = "",
  className,
  ariaLabel = "Code",
}: CodeEditorProps) {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);

  /**
   * The latest callbacks, read at event time.
   *
   * CodeMirror's extensions are built once when the editor mounts. Depending on the props
   * directly would mean rebuilding the whole editor on every keystroke — which loses the
   * cursor, the selection, and the undo history, i.e. everything about the editor.
   */
  const latest = useRef({ onChange, onRun });
  useEffect(() => {
    latest.current = { onChange, onRun };
  });

  useEffect(() => {
    if (!host.current) return;

    const extensions: Extension[] = [
      lineNumbers(),
      history(),
      indentOnInput(),
      bracketMatching(),
      closeBrackets(),
      syntaxHighlighting(highlighting),
      theme,
      EditorView.lineWrapping,
      placeholderExt(placeholder),
      EditorState.allowMultipleSelections.of(true),
      keymap.of([
        {
          key: "Mod-Enter",
          run: () => {
            latest.current.onRun?.();
            return true; // Handled, so the editor does not also insert a newline.
          },
        },
        ...closeBracketsKeymap,
        ...defaultKeymap,
        ...historyKeymap,
        // Tab indents rather than moving focus. A deliberate trade: it is what every code
        // editor does and what anyone writing Python expects, and the escape hatch for
        // keyboard navigation is Escape-then-Tab, which `indentWithTab` provides.
        indentWithTab,
      ]),
      EditorView.updateListener.of((update) => {
        if (update.docChanged) latest.current.onChange(update.state.doc.toString());
      }),
      EditorView.contentAttributes.of({ "aria-label": ariaLabel }),
    ];

    if (language === "python") extensions.push(python());

    const editor = new EditorView({
      state: EditorState.create({ doc: value, extensions }),
      parent: host.current,
    });
    view.current = editor;

    return () => {
      editor.destroy();
      view.current = null;
    };
    // Built once. `value` is deliberately absent: it seeds the document, and after that the
    // editor owns it. Including it would rebuild the editor on every keystroke.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [language, placeholder, ariaLabel]);

  /**
   * Accept a value changed from outside — a cell reset, or a document loaded after mount.
   *
   * Guarded on inequality so the editor's own edits do not round-trip back into it, which
   * would move the cursor to the end of the line on every character typed.
   */
  useEffect(() => {
    const editor = view.current;
    if (!editor) return;
    const current = editor.state.doc.toString();
    if (current === value) return;
    editor.dispatch({ changes: { from: 0, to: current.length, insert: value } });
  }, [value]);

  return (
    <div
      ref={host}
      className={cn("scrollbar-slim overflow-x-auto text-ink", className)}
      data-editor={language}
    />
  );
}
