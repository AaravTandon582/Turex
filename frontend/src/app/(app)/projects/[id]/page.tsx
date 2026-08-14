"use client";

import { ArrowLeft, BookText, Check, FileText, ListTodo, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { PageContainer } from "@/components/layout/page-container";
import { ExperimentPanel } from "@/components/workspace/experiment-panel";
import { HypothesisPanel } from "@/components/workspace/hypothesis-panel";
import { Button } from "@/components/ui/button";
import { Card, EmptyState, Skeleton } from "@/components/ui/primitives";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { papers as papersApi, type PaperSummary } from "@/lib/papers";
import {
  workspace,
  type Hypothesis,
  type Note,
  type Project,
  type ProjectPaper,
  type Task,
} from "@/lib/workspace";

type Tab = "hypotheses" | "experiments" | "papers" | "notes" | "tasks";

const TABS: { value: Tab; label: string }[] = [
  { value: "hypotheses", label: "Hypotheses" },
  { value: "experiments", label: "Experiments" },
  { value: "papers", label: "Papers" },
  { value: "notes", label: "Notes" },
  { value: "tasks", label: "Tasks" },
];

export default function ProjectPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();

  const [project, setProject] = useState<Project | null>(null);
  const [hypotheses, setHypotheses] = useState<Hypothesis[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("hypotheses");

  const reload = useCallback(async () => {
    try {
      const [loaded, loadedHypotheses] = await Promise.all([
        workspace.getProject(id),
        workspace.listHypotheses(id),
      ]);
      setProject(loaded);
      setHypotheses(loadedHypotheses);
    } catch (caught) {
      setError(
        caught instanceof ApiError && caught.code === "not_found"
          ? "That project doesn't exist."
          : "Atlas couldn't load that project.",
      );
    }
  }, [id]);

  useEffect(() => {
    void reload();
  }, [reload]);

  if (error) {
    return (
      <PageContainer>
        <BackLink />
        <p role="alert" className="mt-6 text-sm text-ink-muted">
          {error}
        </p>
      </PageContainer>
    );
  }

  if (!project) {
    return (
      <PageContainer>
        <BackLink />
        <Skeleton className="mt-6 h-8 w-2/5" />
        <Skeleton className="mt-3 h-4 w-3/5" />
        <Skeleton className="mt-8 h-40 w-full rounded-lg" />
        <span className="sr-only">Loading project</span>
      </PageContainer>
    );
  }

  return (
    <PageContainer>
      <BackLink />

      <header className="mt-5">
        <h1 className="text-2xl font-semibold tracking-[-0.02em] text-balance text-ink">
          {project.name}
        </h1>
        <ResearchQuestion project={project} onSaved={reload} />
      </header>

      <div role="tablist" aria-label="Project sections" className="mt-7 flex gap-1 border-b border-border">
        {TABS.map((entry) => (
          <button
            key={entry.value}
            role="tab"
            aria-selected={tab === entry.value}
            onClick={() => setTab(entry.value)}
            className={cn(
              "-mb-px border-b-2 px-3 py-2 text-[13px] font-medium transition-colors",
              tab === entry.value
                ? "border-accent text-ink"
                : "border-transparent text-ink-muted hover:text-ink",
            )}
          >
            {entry.label}
          </button>
        ))}
      </div>

      <div className="mt-5">
        {tab === "hypotheses" && <HypothesisPanel projectId={id} />}
        {tab === "experiments" && <ExperimentPanel projectId={id} hypotheses={hypotheses} />}
        {tab === "papers" && <PapersPanel projectId={id} onChanged={reload} />}
        {tab === "notes" && <NotesPanel projectId={id} />}
        {tab === "tasks" && <TasksPanel projectId={id} onChanged={reload} />}
      </div>

      <div className="mt-10 border-t border-border pt-4">
        <Button
          variant="ghost"
          size="sm"
          className="text-ink-subtle hover:text-danger"
          onClick={async () => {
            await workspace.deleteProject(id);
            router.push("/projects");
          }}
        >
          Delete project
        </Button>
        <p className="mt-1 text-[12px] text-ink-subtle">
          Hypotheses, experiments, and tasks go with it. Your papers and notes are kept.
        </p>
      </div>
    </PageContainer>
  );
}

/** The research question, editable in place — it changes as the work does. */
function ResearchQuestion({ project, onSaved }: { project: Project; onSaved: () => void }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(project.research_question ?? "");

  if (!editing) {
    return (
      <button
        type="button"
        onClick={() => setEditing(true)}
        className="measure mt-2 block rounded-sm text-left"
      >
        {project.research_question ? (
          <span className="text-[15px] leading-relaxed text-ink-muted">
            {project.research_question}
          </span>
        ) : (
          <span className="text-[15px] text-ink-subtle italic">
            Add a research question — projects without one tend to drift.
          </span>
        )}
      </button>
    );
  }

  return (
    <div className="measure mt-2 space-y-2">
      <textarea
        rows={2}
        autoFocus
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        className="block w-full resize-none rounded-md border border-border bg-surface px-3 py-2 text-[15px] text-ink focus:border-accent focus:outline-none"
      />
      <div className="flex gap-2">
        <Button
          size="sm"
          onClick={async () => {
            await workspace.updateProject(project.id, {
              research_question: draft.trim() || null,
            });
            setEditing(false);
            onSaved();
          }}
        >
          Save
        </Button>
        <Button variant="ghost" size="sm" onClick={() => setEditing(false)}>
          Cancel
        </Button>
      </div>
    </div>
  );
}

function PapersPanel({ projectId, onChanged }: { projectId: string; onChanged: () => void }) {
  const [attached, setAttached] = useState<ProjectPaper[]>([]);
  const [library, setLibrary] = useState<PaperSummary[]>([]);
  const [picking, setPicking] = useState(false);

  const reload = useCallback(async () => {
    setAttached(await workspace.projectPapers(projectId).catch(() => []));
  }, [projectId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  useEffect(() => {
    if (!picking) return;
    void papersApi
      .list({ status: "ready", limit: 50 })
      .then((page) => setLibrary(page.items))
      .catch(() => setLibrary([]));
  }, [picking]);

  const attachedIds = new Set(attached.map((paper) => paper.paper_id));

  return (
    <div className="space-y-3">
      <div className="flex justify-end">
        <Button size="sm" variant="secondary" onClick={() => setPicking((value) => !value)}>
          <Plus aria-hidden />
          Add from library
        </Button>
      </div>

      {picking && (
        <Card className="max-h-64 overflow-y-auto p-2">
          {library.length === 0 ? (
            <p className="p-3 text-[13px] text-ink-subtle">
              No processed papers in your library yet.
            </p>
          ) : (
            <ul className="space-y-0.5">
              {library.map((paper) => (
                <li key={paper.id}>
                  <button
                    type="button"
                    disabled={attachedIds.has(paper.id)}
                    onClick={async () => {
                      await workspace.attachPaper(projectId, paper.id);
                      await reload();
                      onChanged();
                    }}
                    className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left text-[13px] text-ink transition-colors hover:bg-surface-hover disabled:opacity-50"
                  >
                    <span className="min-w-0 flex-1 truncate">{paper.display_title}</span>
                    {attachedIds.has(paper.id) && (
                      <Check className="size-3.5 shrink-0 text-success" aria-hidden />
                    )}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}

      {attached.length === 0 ? (
        <EmptyState
          icon={<FileText />}
          title="No papers gathered"
          description="Add the papers this question depends on. They stay in your library — a project is a view onto it, not a folder."
        />
      ) : (
        <ul className="space-y-2">
          {attached.map((paper) => (
            <li key={paper.paper_id}>
              <Card className="flex items-start justify-between gap-3 p-3">
                <div className="min-w-0">
                  <Link
                    href={`/library/${paper.paper_id}`}
                    className="block truncate text-[13px] font-medium text-ink hover:text-accent"
                  >
                    {paper.title}
                  </Link>
                  <p className="mt-0.5 truncate text-[12px] text-ink-subtle">
                    {paper.authors.slice(0, 3).join(", ") || "Unknown authors"}
                    {paper.publication_year ? ` · ${paper.publication_year}` : ""}
                  </p>
                </div>
                <button
                  type="button"
                  aria-label={`Remove ${paper.title} from this project`}
                  onClick={async () => {
                    await workspace.detachPaper(projectId, paper.paper_id);
                    await reload();
                    onChanged();
                  }}
                  className="shrink-0 rounded-sm p-1 text-ink-subtle hover:text-danger"
                >
                  <Trash2 className="size-3.5" aria-hidden />
                </button>
              </Card>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function NotesPanel({ projectId }: { projectId: string }) {
  const [notes, setNotes] = useState<Note[]>([]);

  const reload = useCallback(async () => {
    setNotes(await workspace.listNotes({ projectId }).catch(() => []));
  }, [projectId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  return (
    <div className="space-y-3">
      <div className="flex justify-end">
        <Button
          size="sm"
          variant="secondary"
          onClick={async () => {
            await workspace.createNote({ project_id: projectId, content: "" });
            await reload();
          }}
        >
          <Plus aria-hidden />
          New note
        </Button>
      </div>

      {notes.length === 0 ? (
        <EmptyState
          icon={<BookText />}
          title="No notes in this project"
          description="Your own thinking, kept next to the sources it came from."
        />
      ) : (
        <ul className="space-y-2">
          {notes.map((note) => (
            <li key={note.id}>
              <Card className="p-3">
                <Link
                  href={`/notebook?note=${note.id}`}
                  className="block text-[13px] font-medium text-ink hover:text-accent"
                >
                  {note.title || "Untitled note"}
                </Link>
                <p className="mt-1 line-clamp-2 text-[12px] leading-relaxed text-ink-muted">
                  {note.content || "Empty"}
                </p>
              </Card>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function TasksPanel({ projectId, onChanged }: { projectId: string; onChanged: () => void }) {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [title, setTitle] = useState("");

  const reload = useCallback(async () => {
    setTasks(await workspace.listTasks(projectId).catch(() => []));
  }, [projectId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  return (
    <div className="space-y-3">
      <form
        className="flex gap-2"
        onSubmit={async (event) => {
          event.preventDefault();
          if (!title.trim()) return;
          await workspace.createTask(projectId, title);
          setTitle("");
          await reload();
          onChanged();
        }}
      >
        <input
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder="What needs doing next?"
          aria-label="New task"
          className="h-9 flex-1 rounded-md border border-border bg-surface px-3 text-sm text-ink placeholder:text-ink-subtle focus:border-accent focus:outline-none"
        />
        <Button type="submit" size="sm" disabled={!title.trim()}>
          Add
        </Button>
      </form>

      {tasks.length === 0 ? (
        <EmptyState
          icon={<ListTodo />}
          title="Nothing queued"
          description="The next concrete action, so picking this project back up doesn't start with remembering where you were."
        />
      ) : (
        <ul className="space-y-1">
          {tasks.map((task) => (
            <li key={task.id}>
              <Card className="flex items-center gap-3 px-3 py-2">
                <button
                  type="button"
                  role="checkbox"
                  aria-checked={task.status === "done"}
                  aria-label={task.title}
                  onClick={async () => {
                    await workspace.updateTask(task.id, {
                      status: task.status === "done" ? "todo" : "done",
                    });
                    await reload();
                    onChanged();
                  }}
                  className={cn(
                    "flex size-4 shrink-0 items-center justify-center rounded-xs border transition-colors",
                    task.status === "done"
                      ? "border-success bg-success text-white"
                      : "border-border-strong hover:border-accent",
                  )}
                >
                  {task.status === "done" && <Check className="size-3" aria-hidden />}
                </button>

                <span
                  className={cn(
                    "min-w-0 flex-1 text-[13px]",
                    task.status === "done" ? "text-ink-subtle line-through" : "text-ink",
                  )}
                >
                  {task.title}
                </span>

                <button
                  type="button"
                  aria-label={`Delete ${task.title}`}
                  onClick={async () => {
                    await workspace.deleteTask(task.id);
                    await reload();
                    onChanged();
                  }}
                  className="shrink-0 rounded-sm p-1 text-ink-subtle hover:text-danger"
                >
                  <Trash2 className="size-3.5" aria-hidden />
                </button>
              </Card>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function BackLink() {
  return (
    <Link
      href="/projects"
      className="inline-flex items-center gap-1.5 rounded-sm text-[13px] text-ink-muted hover:text-ink"
    >
      <ArrowLeft className="size-3.5" aria-hidden />
      Projects
    </Link>
  );
}
