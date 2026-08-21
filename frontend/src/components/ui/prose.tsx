"use client";

import type { ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";

import { cn } from "@/lib/cn";

import "katex/dist/katex.min.css";

/**
 * Text with Markdown and maths rendered, wherever Atlas shows prose.
 *
 * Every surface in Atlas carries text written by someone other than the UI — a research note,
 * a model's answer, a quiz question, an arXiv abstract — and all of it contains LaTeX. Papers
 * are where maths lives, so `$O(n\log n)$` and `\alpha` turn up in abstracts, in questions
 * about equations, and in any explanation of a result. Only the notebook rendered it. Everywhere
 * else showed the raw characters, which is both ugly and, for an equation, genuinely
 * unreadable: `$\frac{\partial L}{\partial \theta}$` communicates nothing as text.
 *
 * `react-markdown` builds React elements rather than an HTML string, so there is no
 * `dangerouslySetInnerHTML` and no sanitiser to get wrong. That matters more than it looks:
 * two of these surfaces render text a *language model* produced from a *fetched document*, and
 * neither is trusted input.
 *
 * Styling is applied per element rather than through a typography plugin, because this text
 * has to sit inside the app's own type scale rather than bring its own.
 */

type ProseDensity = "comfortable" | "tight" | "inline";

interface ProseProps {
  children: string;
  /**
   * `tight` drops the vertical margins between blocks.
   *
   * For the places prose is a fragment rather than a document — a search result's abstract, a
   * flashcard's front. A paragraph's `my-3` also defeats `line-clamp`, which measures the
   * element's own box, so a clamped abstract needs this to clamp at all.
   *
   * `inline` goes further and unwraps paragraphs entirely, rendering into a `<span>`. It is for
   * text that has to flow inside something else — the assistant's answer, where clickable
   * citation markers are interleaved with the prose and a block element between them would
   * break the line. Block structure there comes from the container's `whitespace-pre-wrap`,
   * which keeps the model's own line breaks; what this adds is the inline half of Markdown —
   * maths, code, emphasis — which is the half that was unreadable as raw characters.
   */
  density?: ProseDensity;
  className?: string;
}

function components(density: ProseDensity) {
  const paragraph = density === "tight" ? "my-0 [&+p]:mt-2" : "my-3";

  if (density === "inline") {
    return {
      // Unwrapped: a `<p>` between two citation markers would put them on separate lines.
      p: ({ children }: { children?: ReactNode }) => <>{children}</>,
      code: ({ children, ...props }: { children?: ReactNode }) => (
        <code className="rounded-xs bg-surface-sunken px-1 py-0.5 font-mono text-[13px]" {...props}>
          {children}
        </code>
      ),
      a: (props: object) => (
        <a
          className="text-accent hover:underline"
          target="_blank"
          rel="noreferrer noopener"
          {...props}
        />
      ),
    };
  }

  return {
    // Headings shift down one level. This text is nested inside a page that already has an
    // `h1`, and an `h1` in an answer would break the document outline for a screen reader.
    h1: (props: object) => (
      <h2 className="mt-4 mb-2 text-[17px] font-semibold text-ink" {...props} />
    ),
    h2: (props: object) => (
      <h3 className="mt-4 mb-2 text-[16px] font-semibold text-ink" {...props} />
    ),
    h3: (props: object) => (
      <h4 className="mt-3 mb-1.5 text-[15px] font-semibold text-ink" {...props} />
    ),
    p: (props: object) => <p className={paragraph} {...props} />,
    ul: (props: object) => (
      <ul
        className={cn("list-disc space-y-1 pl-5", density === "tight" ? "my-1" : "my-3")}
        {...props}
      />
    ),
    ol: (props: object) => (
      <ol
        className={cn("list-decimal space-y-1 pl-5", density === "tight" ? "my-1" : "my-3")}
        {...props}
      />
    ),
    a: (props: object) => (
      <a
        className="text-accent hover:underline"
        target="_blank"
        rel="noreferrer noopener"
        {...props}
      />
    ),
    blockquote: (props: object) => (
      <blockquote className="my-3 border-l-2 border-border-strong pl-3 text-ink-muted" {...props} />
    ),
    code: ({ className, children, ...props }: { className?: string; children?: ReactNode }) => {
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
    pre: (props: object) => (
      <pre
        className="scrollbar-slim my-3 overflow-x-auto rounded-md border border-border bg-surface-sunken p-3"
        {...props}
      />
    ),
    // Wide tables scroll inside themselves rather than stretching the page.
    table: (props: object) => (
      <div className="scrollbar-slim my-3 overflow-x-auto">
        <table className="w-full border-collapse text-[14px]" {...props} />
      </div>
    ),
    th: (props: object) => (
      <th
        className="border border-border bg-surface-sunken px-2 py-1 text-left font-semibold"
        {...props}
      />
    ),
    td: (props: object) => <td className="border border-border px-2 py-1" {...props} />,
    hr: () => <hr className="my-5 border-border" />,
  };
}

export function Prose({ children, density = "comfortable", className }: ProseProps) {
  const markdown = (
    <ReactMarkdown
      remarkPlugins={[remarkGfm, remarkMath]}
      rehypePlugins={[rehypeKatex]}
      components={components(density)}
    >
      {children}
    </ReactMarkdown>
  );

  if (density === "inline") return <span className={className}>{markdown}</span>;

  // `break-words` because a long unbroken token — a URL, a chemical name, an over-long
  // identifier — is otherwise unbreakable and pushes its container wider than the page.
  return <div className={cn("break-words", className)}>{markdown}</div>;
}
