"use client";

import { FlaskConical, Plus } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { PageContainer } from "@/components/layout/page-container";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { FormError } from "@/components/ui/form-error";
import { Card, EmptyState, PageHeader, Skeleton } from "@/components/ui/primitives";
import { ApiError } from "@/lib/api";
import { workspace, type Project } from "@/lib/workspace";

export default function ProjectsPage() {
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [creating, setCreating] = useState(false);

  async function reload() {
    setProjects(await workspace.listProjects().catch(() => []));
  }

  useEffect(() => {
    void reload();
  }, []);

  return (
    <PageContainer>
      <PageHeader
        title="Projects"
        description="A research question, and everything you have gathered to answer it."
        actions={
          !creating && projects && projects.length > 0 ? (
            <Button size="sm" onClick={() => setCreating(true)}>
              <Plus aria-hidden />
              New project
            </Button>
          ) : undefined
        }
      />

      {creating && (
        <NewProjectForm
          onCancel={() => setCreating(false)}
          onCreated={async () => {
            setCreating(false);
            await reload();
          }}
        />
      )}

      <div className="mt-6">
        {!projects ? (
          <div className="grid gap-3 sm:grid-cols-2" aria-busy>
            {Array.from({ length: 2 }, (_, index) => (
              <Card key={index} className="p-4">
                <Skeleton className="h-4 w-2/5" />
                <Skeleton className="mt-3 h-3 w-4/5" />
                <Skeleton className="mt-6 h-3 w-32" />
              </Card>
            ))}
            <span className="sr-only">Loading projects</span>
          </div>
        ) : projects.length === 0 && !creating ? (
          <EmptyState
            icon={<FlaskConical />}
            title="No projects yet"
            description="A project starts with a question. Atlas keeps the papers, notes, hypotheses, and experiments that bear on it together, so you can see what you actually know."
            action={
              <Button size="sm" onClick={() => setCreating(true)}>
                Start a project
              </Button>
            }
          />
        ) : (
          <ul className="grid gap-3 sm:grid-cols-2">
            {projects.map((project) => (
              <li key={project.id}>
                <ProjectCard project={project} />
              </li>
            ))}
          </ul>
        )}
      </div>
    </PageContainer>
  );
}

function ProjectCard({ project }: { project: Project }) {
  const counts = [
    { label: "papers", value: project.paper_count },
    { label: "hypotheses", value: project.hypothesis_count },
    { label: "experiments", value: project.experiment_count },
    { label: "notes", value: project.note_count },
  ].filter((entry) => entry.value > 0);

  return (
    <Card className="relative h-full transition-[border-color,box-shadow] duration-150 hover:border-border-strong hover:shadow-[var(--shadow-md)]">
      <Link href={`/projects/${project.id}`} className="block h-full rounded-lg p-4">
        <h2 className="text-[15px] leading-snug font-medium text-balance text-ink">
          {project.name}
        </h2>

        {project.research_question ? (
          <p className="measure mt-2 text-[13px] leading-relaxed text-ink-muted">
            {project.research_question}
          </p>
        ) : (
          <p className="mt-2 text-[13px] text-ink-subtle italic">
            No research question yet — the most useful thing to write next.
          </p>
        )}

        <div className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-ink-subtle">
          {counts.length === 0 ? (
            <span>Nothing gathered yet</span>
          ) : (
            counts.map((entry) => (
              <span key={entry.label} data-tabular>
                {entry.value} {entry.label}
              </span>
            ))
          )}
          {project.open_task_count > 0 && (
            <span className="text-accent" data-tabular>
              {project.open_task_count} open
            </span>
          )}
        </div>
      </Link>
    </Card>
  );
}

function NewProjectForm({
  onCancel,
  onCreated,
}: {
  onCancel: () => void;
  onCreated: () => void;
}) {
  const [name, setName] = useState("");
  const [question, setQuestion] = useState("");
  const [error, setError] = useState<ApiError | null>(null);
  const [submitting, setSubmitting] = useState(false);

  return (
    <Card className="mt-6 animate-[var(--animate-rise)] p-4">
      <form
        className="space-y-4"
        onSubmit={async (event) => {
          event.preventDefault();
          setSubmitting(true);
          setError(null);
          try {
            await workspace.createProject({
              name,
              research_question: question.trim() || undefined,
            });
            onCreated();
          } catch (caught) {
            setError(
              caught instanceof ApiError
                ? caught
                : new ApiError("internal_error", "Atlas couldn't create that project.", 500),
            );
            setSubmitting(false);
          }
        }}
      >
        <FormError error={error} ignoreFields={["name"]} />

        <Field
          label="Project name"
          required
          autoFocus
          value={name}
          onChange={(event) => setName(event.target.value)}
          error={error?.fieldError("name")}
        />

        <div className="space-y-1.5">
          <label
            htmlFor="research-question"
            className="block text-[13px] font-medium text-ink"
          >
            Research question
          </label>
          <textarea
            id="research-question"
            rows={2}
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder="Can structured retrieval improve reasoning accuracy in small models?"
            className="block w-full resize-none rounded-md border border-border bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-subtle focus:border-accent focus:ring-3 focus:ring-[var(--accent-ring)] focus:outline-none"
          />
          <p className="text-[13px] text-ink-subtle">
            Optional now, but a project without a question tends to drift. You can change it
            later.
          </p>
        </div>

        <div className="flex gap-2">
          <Button type="submit" size="sm" loading={submitting} disabled={!name.trim()}>
            Create project
          </Button>
          <Button type="button" variant="ghost" size="sm" onClick={onCancel}>
            Cancel
          </Button>
        </div>
      </form>
    </Card>
  );
}
