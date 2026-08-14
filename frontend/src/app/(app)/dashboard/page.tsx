"use client";

import { FileText, FlaskConical, Library, Sparkles } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { useSession } from "@/components/auth/session-provider";
import { PageContainer } from "@/components/layout/page-container";
import { Button } from "@/components/ui/button";
import { Card, EmptyState, Skeleton } from "@/components/ui/primitives";
import { firstName } from "@/lib/auth";
import { discovery, type Recommendation } from "@/lib/discovery";
import { formatAuthors, papers, type LibraryStats, type PaperSummary } from "@/lib/papers";
import { workspace, type Project } from "@/lib/workspace";

interface Dashboard {
  stats: LibraryStats;
  reading: PaperSummary[];
  projects: Project[];
  recommendations: Recommendation[];
}

/**
 * The dashboard answers one question: what am I working on?
 *
 * Everything shown is real. Where there is nothing yet, the empty state names the next action
 * rather than displaying a zeroed-out statistic that implies the product is broken.
 */
export default function DashboardPage() {
  const { user } = useSession();
  const [data, setData] = useState<Dashboard | null>(null);

  useEffect(() => {
    void (async () => {
      const [stats, reading, projects, recommendations] = await Promise.all([
        papers.stats().catch(() => ({ total: 0, processing: 0, failed: 0, unread: 0, favorites: 0 })),
        papers
          .list({ reading_status: "reading", sort: "opened", limit: 4 })
          .then((page) => page.items)
          .catch(() => []),
        workspace.listProjects().catch(() => []),
        discovery.recommendations(3).catch(() => []),
      ]);
      setData({ stats, reading, projects, recommendations });
    })();
  }, []);

  const activeProjects = data?.projects.filter((project) => project.status === "active") ?? [];

  return (
    <PageContainer>
      <header>
        <h1 className="text-2xl font-semibold tracking-[-0.015em] text-ink">
          {user ? `Welcome back, ${firstName(user)}` : <Skeleton className="h-8 w-64" />}
        </h1>
        <p className="measure mt-1.5 text-sm text-ink-muted">
          {data
            ? summarise(data)
            : "Everything you are reading, questioning, and testing — in one place."}
        </p>
      </header>

      <div className="mt-8 grid gap-4 lg:grid-cols-3">
        <section className="lg:col-span-2" aria-labelledby="active-projects">
          <h2 id="active-projects" className="mb-3 text-[13px] font-semibold text-ink-muted">
            Active projects
          </h2>

          {!data ? (
            <Skeleton className="h-32 w-full rounded-lg" />
          ) : activeProjects.length === 0 ? (
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
          ) : (
            <ul className="space-y-2">
              {activeProjects.slice(0, 4).map((project) => (
                <li key={project.id}>
                  <Card className="transition-[border-color] hover:border-border-strong">
                    <Link href={`/projects/${project.id}`} className="block rounded-lg p-3.5">
                      <p className="text-[14px] font-medium text-ink">{project.name}</p>
                      {project.research_question && (
                        <p className="measure mt-1 line-clamp-1 text-[13px] text-ink-muted">
                          {project.research_question}
                        </p>
                      )}
                      <p className="mt-2 text-[12px] text-ink-subtle" data-tabular>
                        {project.paper_count} papers · {project.hypothesis_count} hypotheses
                        {project.open_task_count > 0 && (
                          <span className="text-accent">
                            {" "}
                            · {project.open_task_count} open
                          </span>
                        )}
                      </p>
                    </Link>
                  </Card>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section aria-labelledby="continue-reading">
          <h2 id="continue-reading" className="mb-3 text-[13px] font-semibold text-ink-muted">
            Continue reading
          </h2>

          {!data ? (
            <Skeleton className="h-32 w-full rounded-lg" />
          ) : data.reading.length === 0 ? (
            <EmptyState
              icon={<FileText />}
              title="Nothing in progress"
              description="Papers you have started appear here so you can pick up where you stopped."
            />
          ) : (
            <ul className="space-y-2">
              {data.reading.map((paper) => (
                <li key={paper.id}>
                  <Card className="transition-[border-color] hover:border-border-strong">
                    <Link href={`/library/${paper.id}/read`} className="block rounded-lg p-3">
                      <p className="line-clamp-2 text-[13px] font-medium text-ink">
                        {paper.display_title}
                      </p>
                      <p className="mt-1 truncate text-[12px] text-ink-subtle">
                        {formatAuthors(paper.authors, 2)}
                      </p>
                    </Link>
                  </Card>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      {data && data.recommendations.length > 0 && (
        <section className="mt-10" aria-labelledby="recommended">
          <h2 id="recommended" className="mb-1 text-[13px] font-semibold text-ink-muted">
            Worth reading next
          </h2>
          <p className="mb-3 text-[12px] text-ink-subtle">
            Each one says why it surfaced. Nothing here is a guess about your taste.
          </p>
          <ul className="grid gap-3 sm:grid-cols-3">
            {data.recommendations.map((entry) => (
              <li key={entry.paper_id}>
                <Card className="h-full transition-[border-color] hover:border-border-strong">
                  <Link href={`/library/${entry.paper_id}`} className="block h-full rounded-lg p-3.5">
                    <p className="line-clamp-2 text-[13px] font-medium text-ink">{entry.title}</p>
                    <p className="mt-2 text-[12px] leading-relaxed text-ink-muted">
                      {entry.reason}
                    </p>
                  </Link>
                </Card>
              </li>
            ))}
          </ul>
        </section>
      )}

      {data && data.stats.total === 0 && (
        <section className="mt-10" aria-labelledby="get-started">
          <h2 id="get-started" className="mb-3 text-[13px] font-semibold text-ink-muted">
            Get started
          </h2>
          <div className="grid gap-3 sm:grid-cols-3">
            <NextStep
              href="/library"
              icon={<Library />}
              title="Add your first paper"
              description="Upload a PDF. Atlas reads and indexes it."
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
      )}
    </PageContainer>
  );
}

function summarise({ stats, projects }: Dashboard): string {
  if (stats.total === 0) {
    return "Everything you are reading, questioning, and testing — in one place.";
  }

  const parts = [`${stats.total} ${stats.total === 1 ? "paper" : "papers"}`];
  const active = projects.filter((project) => project.status === "active").length;
  if (active > 0) parts.push(`${active} active ${active === 1 ? "project" : "projects"}`);
  if (stats.unread > 0) parts.push(`${stats.unread} unread`);
  if (stats.processing > 0) parts.push(`${stats.processing} still being read`);
  return parts.join(" · ");
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
