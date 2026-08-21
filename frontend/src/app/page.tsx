import { ArrowRight, Highlighter, Network, ShieldCheck } from "lucide-react";
import Link from "next/link";

import { TurexMark } from "@/components/brand/turex-mark";
import { AssistantPreview, HypothesisPreview } from "@/components/marketing/preview";
import { ThemeToggle } from "@/components/theme/theme-toggle";
import { Button } from "@/components/ui/button";

/**
 * The landing page has one job: make the premise legible in under a minute.
 *
 * No hero gradient, no stock imagery. The product's actual interface carries the argument,
 * and the copy stays specific about what Turex does — and what it refuses to do.
 */

const LOOP = [
  "Read",
  "Understand",
  "Connect",
  "Question",
  "Hypothesise",
  "Test",
  "Learn",
] as const;

export default function LandingPage() {
  return (
    <div className="min-h-dvh bg-canvas">
      <SiteHeader />

      <main id="main">
        <Hero />
        <ResearchLoop />
        <Capabilities />
        <Honesty />
        <ClosingCta />
      </main>

      <SiteFooter />
    </div>
  );
}

function SiteHeader() {
  return (
    <header className="sticky top-0 z-30 border-b border-border bg-canvas/85 backdrop-blur-sm">
      <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-5 sm:px-8">
        <Link
          href="/"
          className="inline-flex items-center gap-2.5 rounded-md text-[15px] font-semibold tracking-[-0.01em] text-ink"
        >
          <TurexMark className="size-6" />
          Turex
        </Link>
        <div className="flex items-center gap-2">
          <ThemeToggle className="hidden sm:inline-flex" />
          <Button asChild variant="ghost" size="sm">
            <Link href="/login">Sign in</Link>
          </Button>
          <Button asChild size="sm">
            <Link href="/register">Get started</Link>
          </Button>
        </div>
      </div>
    </header>
  );
}

function Hero() {
  return (
    <section className="mx-auto max-w-6xl px-5 pt-16 pb-6 sm:px-8 sm:pt-24">
      <div className="grid items-center gap-12 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.05fr)] lg:gap-16">
        <div className="animate-[var(--animate-rise)]">
          <p className="font-mono text-[11px] tracking-[0.14em] text-ink-subtle uppercase">
            An intelligent research workspace
          </p>
          <h1 className="mt-4 text-4xl leading-[1.05] font-semibold tracking-[-0.03em] text-balance text-ink sm:text-5xl">
            Research, connected.
          </h1>
          <p className="measure mt-5 text-base leading-relaxed text-ink-muted sm:text-lg">
            Understand papers. Connect ideas. Test hypotheses. Discover what to investigate
            next.
          </p>

          <div className="mt-8 flex flex-wrap items-center gap-3">
            <Button asChild size="lg">
              <Link href="/register">
                Start reading
                <ArrowRight aria-hidden />
              </Link>
            </Button>
            <Button asChild variant="secondary" size="lg">
              <Link href="/login">Sign in</Link>
            </Button>
          </div>

          <p className="mt-5 text-[13px] text-ink-subtle">
            Built for students and independent researchers who do not have a lab behind them.
          </p>
        </div>

        <div className="animate-[var(--animate-rise)] [animation-delay:80ms]">
          <AssistantPreview />
        </div>
      </div>
    </section>
  );
}

function ResearchLoop() {
  return (
    <section aria-labelledby="loop-heading" className="mx-auto max-w-6xl px-5 py-16 sm:px-8">
      <h2 id="loop-heading" className="sr-only">
        The research loop
      </h2>
      <div className="rounded-xl border border-border bg-surface-sunken px-5 py-6 sm:px-8">
        <p className="text-[13px] text-ink-muted">
          Most tools stop at the first step. Turex is built around the whole loop.
        </p>
        <ol className="mt-4 flex flex-wrap items-center gap-x-1.5 gap-y-2">
          {LOOP.map((stage, index) => (
            <li key={stage} className="flex items-center gap-1.5">
              <span className="rounded-sm bg-surface px-2.5 py-1 text-[13px] font-medium text-ink shadow-[var(--shadow-sm)]">
                {stage}
              </span>
              {index < LOOP.length - 1 && (
                <ArrowRight className="size-3 text-ink-subtle" aria-hidden />
              )}
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

const CAPABILITIES = [
  {
    icon: Highlighter,
    title: "Read with something that read it too",
    body: "Select a paragraph and ask what it means. Select an equation and get every variable named. Select a methods section and hear what is weak about it. Your highlights and notes stay attached to the page they came from.",
  },
  {
    icon: Network,
    title: "See what your library already knows",
    body: "Semantic search finds passages by meaning, not keyword. Turex surfaces the paper that contradicts the one you just read, and the concept two of your sources share without citing each other.",
  },
  {
    icon: ShieldCheck,
    title: "Turn reading into a question you can test",
    body: "Write a hypothesis, track the evidence for and against it, and design an experiment with its variables, controls, and confounders written down. Suggestions are labelled as suggestions.",
  },
] as const;

function Capabilities() {
  return (
    <section aria-labelledby="capabilities-heading" className="mx-auto max-w-6xl px-5 py-8 sm:px-8">
      <h2
        id="capabilities-heading"
        className="text-2xl font-semibold tracking-[-0.02em] text-ink sm:text-3xl"
      >
        From reading science to doing science
      </h2>

      <div className="mt-10 grid gap-10 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)] lg:items-start lg:gap-16">
        <dl className="space-y-8">
          {CAPABILITIES.map(({ icon: Icon, title, body }) => (
            <div key={title} className="flex gap-4">
              <span className="flex size-9 shrink-0 items-center justify-center rounded-md border border-border bg-surface text-accent">
                <Icon className="size-4" aria-hidden />
              </span>
              <div>
                <dt className="text-[15px] font-semibold text-ink">{title}</dt>
                <dd className="measure mt-1.5 text-sm leading-relaxed text-ink-muted">{body}</dd>
              </div>
            </div>
          ))}
        </dl>

        <div className="lg:sticky lg:top-24">
          <HypothesisPreview />
          <p className="mt-3 text-center text-[12px] text-ink-subtle">
            A hypothesis, with evidence tracked on both sides.
          </p>
        </div>
      </div>
    </section>
  );
}

function Honesty() {
  return (
    <section aria-labelledby="honesty-heading" className="mx-auto max-w-6xl px-5 py-16 sm:px-8">
      <div className="rounded-xl border border-border bg-surface p-6 sm:p-9">
        <h2
          id="honesty-heading"
          className="text-xl font-semibold tracking-[-0.015em] text-ink sm:text-2xl"
        >
          A research tool has to be honest to be useful
        </h2>
        <p className="measure mt-3 text-sm leading-relaxed text-ink-muted">
          A fabricated citation is worse than no answer, so Turex is built not to produce one.
          Answers are assembled from passages actually retrieved from your documents, and every
          claim links back to the page it came from. Turex separates what a source states from
          what it infers, marks its own ideas as ideas, and says plainly when your library does
          not contain the answer.
        </p>
        <ul className="mt-6 grid gap-3 sm:grid-cols-3">
          {[
            "Citations resolve to a real page and paragraph",
            "Evidence and interpretation are labelled separately",
            "Your documents stay private to your account",
          ].map((claim) => (
            <li
              key={claim}
              className="rounded-md border border-border bg-surface-sunken px-3.5 py-3 text-[13px] leading-relaxed text-ink-muted"
            >
              {claim}
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

function ClosingCta() {
  return (
    <section className="mx-auto max-w-6xl px-5 pb-20 sm:px-8">
      <div className="flex flex-col items-center gap-5 border-t border-border pt-14 text-center">
        <h2 className="text-2xl font-semibold tracking-[-0.02em] text-balance text-ink sm:text-3xl">
          Bring the paper you have been meaning to understand.
        </h2>
        <Button asChild size="lg">
          <Link href="/register">
            Create your workspace
            <ArrowRight aria-hidden />
          </Link>
        </Button>
      </div>
    </section>
  );
}

function SiteFooter() {
  return (
    <footer className="border-t border-border">
      <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-4 px-5 py-8 sm:flex-row sm:px-8">
        <div className="flex items-center gap-2 text-[13px] text-ink-subtle">
          <TurexMark className="size-4" />
          Turex — an intelligent research workspace
        </div>
        <ThemeToggle />
      </div>
    </footer>
  );
}
