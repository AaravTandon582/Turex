"use client";

import ReactMarkdown from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";

import "katex/dist/katex.min.css";

/**
 * A note, rendered.
 *
 * The notebook told people to "write however you think — Markdown, LaTeX, tables, code" and
 * then showed the raw characters back. That is the product making a claim it does not keep,
 * which matters more here than in most places: the whole argument for Atlas is that it does
 * not say things that are not so.
 *
 * `react-markdown` builds React elements rather than an HTML string, so there is no
 * `dangerouslySetInnerHTML` and no sanitiser to get wrong. Notes are the author's own text,
 * but a research note is exactly the kind of thing that gets pasted in from elsewhere.
 *
 * Styling is applied per element rather than through a typography plugin, because the note
 * body has to sit inside the app's own type scale rather than bring its own.
 */
export function NotePreview({ content }: { content: string }) {
  if (!content.trim()) {
    return (
      <p className="text-[13px] text-ink-subtle">
        Nothing written yet. Switch to Write and start typing.
      </p>
    );
  }

  return (
    <div className="measure text-[15px] leading-relaxed text-ink">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeKatex]}
        components={{
          h1: (props) => <h2 className="mt-6 mb-2 text-[20px] font-semibold text-ink" {...props} />,
          h2: (props) => <h3 className="mt-5 mb-2 text-[17px] font-semibold text-ink" {...props} />,
          h3: (props) => <h4 className="mt-4 mb-1.5 text-[15px] font-semibold text-ink" {...props} />,
          p: (props) => <p className="my-3" {...props} />,
          ul: (props) => <ul className="my-3 list-disc space-y-1 pl-5" {...props} />,
          ol: (props) => <ol className="my-3 list-decimal space-y-1 pl-5" {...props} />,
          a: (props) => (
            <a
              className="text-accent hover:underline"
              target="_blank"
              rel="noreferrer noopener"
              {...props}
            />
          ),
          blockquote: (props) => (
            <blockquote
              className="my-3 border-l-2 border-border-strong pl-3 text-ink-muted"
              {...props}
            />
          ),
          code: ({ className, children, ...props }) => {
            // No language class means an inline span rather than a fenced block.
            const fenced = /language-/.test(className ?? "");
            return fenced ? (
              <code className="font-mono text-[13px]" {...props}>
                {children}
              </code>
            ) : (
              <code
                className="rounded-xs bg-surface-sunken px-1 py-0.5 font-mono text-[13px] text-ink"
                {...props}
              >
                {children}
              </code>
            );
          },
          pre: (props) => (
            <pre
              className="scrollbar-slim my-3 overflow-x-auto rounded-md border border-border bg-surface-sunken p-3"
              {...props}
            />
          ),
          // Wide tables scroll inside themselves rather than stretching the page.
          table: (props) => (
            <div className="scrollbar-slim my-3 overflow-x-auto">
              <table className="w-full border-collapse text-[14px]" {...props} />
            </div>
          ),
          th: (props) => (
            <th
              className="border border-border bg-surface-sunken px-2 py-1 text-left font-semibold"
              {...props}
            />
          ),
          td: (props) => <td className="border border-border px-2 py-1" {...props} />,
          hr: () => <hr className="my-5 border-border" />,
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
