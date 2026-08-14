"use client";

import { FileText, FlaskConical, Library, Sparkles } from "lucide-react";
import Link from "next/link";

import { useSession } from "@/components/auth/session-provider";
import { PageContainer } from "@/components/layout/page-container";
import { Button } from "@/components/ui/button";
import { Card, EmptyState, Skeleton } from "@/components/ui/primitives";
import { firstName } from "@/lib/auth";

/**
 * The dashboard answers one question: what am I working on?
 *
 * Until a user has papers or projects, that question has an honest answer — nothing yet — so
 * the screen is built around getting them to their first paper rather than showing zeroed-out
 * statistics that imply the product is broken.
 */
export default function DashboardPage() {
  const { user } = useSession();

  return (
    <PageContainer>
      <header>
        <h1 className="text-2xl font-semibold tracking-[-0.015em] text-ink">
          {user ? `Welcome back, ${firstName(user)}` : <Skeleton className="h-8 w-64" />}
        </h1>
        <p className="measure mt-1.5 text-sm text-ink-muted">
          Everything you are reading, questioning, and testing — in one place.
        </p>
      </header>

      <div className="mt-8 grid gap-4 lg:grid-cols-3">
        <section className="lg:col-span-2" aria-labelledby="active-projects">
          <h2 id="active-projects" className="mb-3 text-[13px] font-semibold text-ink-muted">
            Active projects
          </h2>
          <EmptyState
            icon={<FlaskConical />}
            title="No projects yet"
            description="A project holds a research question together with the papers, notes, hypotheses, and experiments that answer it."
            action={
              <Button asChild size="sm">
                <Link href="/projects">Start a project</Link>
              </Button>
            }
          />
        </section>

        <section aria-labelledby="continue-reading">
          <h2 id="continue-reading" className="mb-3 text-[13px] font-semibold text-ink-muted">
            Continue reading
          </h2>
          <EmptyState
            icon={<FileText />}
            title="Nothing in progress"
            description="Papers you have started appear here so you can pick up where you stopped."
          />
        </section>
      </div>

      <section className="mt-10" aria-labelledby="get-started">
        <h2 id="get-started" className="mb-3 text-[13px] font-semibold text-ink-muted">
          Get started
        </h2>
        <div className="grid gap-3 sm:grid-cols-3">
          <NextStep
            href="/library"
            icon={<Library />}
            title="Add your first paper"
            description="Upload a PDF or paste an arXiv link. Atlas reads and indexes it."
          />
          <NextStep
            href="/assistant"
            icon={<Sparkles />}
            title="Ask about your library"
            description="Every answer cites the passage it came from, or says it doesn't know."
          />
          <NextStep
            href="/projects"
            icon={<FlaskConical />}
            title="Frame a question"
            description="Turn a curiosity into a hypothesis you can actually test."
          />
        </div>
      </section>
    </PageContainer>
  );
}

function NextStep({
  href,
  icon,
  title,
  description,
}: {
  href: string;
  icon: React.ReactNode;
  title: string;
  description: string;
}) {
  return (
    <Card className="transition-[border-color,box-shadow] duration-150 hover:border-border-strong hover:shadow-[var(--shadow-md)]">
      <Link href={href} className="block h-full rounded-lg p-4">
        <span className="flex size-8 items-center justify-center rounded-md bg-accent-soft text-accent [&_svg]:size-4">
          {icon}
        </span>
        <h3 className="mt-3 text-sm font-medium text-ink">{title}</h3>
        <p className="mt-1 text-[13px] leading-relaxed text-ink-muted">{description}</p>
      </Link>
    </Card>
  );
}
