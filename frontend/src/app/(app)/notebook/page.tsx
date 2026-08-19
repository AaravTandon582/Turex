"use client";

import { BookText, ChevronLeft, Plus, Search, Trash2, X } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { NotePreview } from "@/components/notebook/note-preview";
import { EmptyState, Skeleton } from "@/components/ui/primitives";
import { cn } from "@/lib/cn";
import { describe } from "@/lib/use-async";
import { workspace, type Note, type Project } from "@/lib/workspace";

const SAVE_DELAY_MS = 700;

export default function NotebookPage() {
  return (
    <Suspense fallback={<NotebookSkeleton />}>
      <Notebook />
    </Suspense>
  );
}

/**
 * The research notebook.
 *
 * Two panes: the list of notes, and the one being written. Notes save themselves — a notebook
 * that needs an explicit save is a notebook that loses a thought when a tab closes.
 */
function Notebook() {
  const params = useSearchParams();

  const [notes, setNotes] = useState<Note[] | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [activeId, setActiveId] = useState<string | null>(params.get("note"));
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [notesError, setNotesError] = useState<string | null>(null);

  useEffect(() => {
    const timer = setTimeout(() => setSearch(searchInput.trim()), 250);
    return () => clearTimeout(timer);
  }, [searchInput]);

  const reload = useCallback(async () => {
    try {
      const loaded = await workspace.listNotes({ search: search || undefined });
      setNotes(loaded);
      setNotesError(null);
      return loaded;
    } catch (caught) {
      // Not an empty list: "no notes yet" and "we could not reach the server" must not look
      // the same to someone who has written notes.
      setNotes(null);
      setNotesError(describe(caught));
      return [];
    }
  }, [search]);

  useEffect(() => {
    void reload();
  }, [reload]);

  useEffect(() => {
    void workspace
      .listProjects()
      .then(setProjects)
      // Only fills the "link to a project" menu. A failure leaves it empty, which reads as
      // "no projects to pick", and the note still saves without one.
      .catch(() => undefined);
  }, []);

  const active = notes?.find((note) => note.id === activeId) ?? null;

  async function createNote() {
    const created = await workspace.createNote({ content: "" });
    setNotes((current) => [created, ...(current ?? [])]);
    setActiveId(created.id);
  }

  return (
    <div className="flex h-[calc(100dvh-3.5rem)] md:h-dvh">
      <aside
        className={cn(
          "flex-col border-r border-border bg-surface-sunken md:flex md:w-72 md:shrink-0",
          // One pane at a time on a phone: a 288px list beside an editor leaves neither usable.
          active ? "hidden w-full" : "flex w-full",
        )}
      >
        <div className="space-y-2 p-3">
          <Button size="sm" className="w-full" onClick={createNote}>
            <Plus aria-hidden />
            New note
          </Button>

          <div className="relative">
            <Search
              className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-ink-subtle"
              aria-hidden
            />
            <input
              type="search"
              value={searchInput}
              onChange={(event) => setSearchInput(event.target.value)}
              placeholder="Search notes"
              aria-label="Search notes"
              className="h-8 w-full rounded-md border border-border bg-surface pr-2 pl-8 text-[13px] text-ink placeholder:text-ink-subtle focus:border-accent focus:outline-none"
            />
          </div>
        </div>

        <nav aria-label="Notes" className="scrollbar-slim flex-1 overflow-y-auto px-2 pb-3">
          {notesError ? (
            <div className="p-2">
              <p role="alert" className="text-[12px] leading-relaxed text-danger">
                {notesError}
              </p>
              <Button size="sm" variant="secondary" className="mt-2" onClick={() => void reload()}>
                Try again
              </Button>
            </div>
          ) : notes === null ? (
            <div className="space-y-1.5 p-1">
              {Array.from({ length: 4 }, (_, index) => (
                <Skeleton key={index} className="h-12 w-full rounded-md" />
              ))}
            </div>
          ) : notes.length === 0 ? (
            <p className="px-2 py-3 text-[12px] text-ink-subtle">
              {search ? "No notes match that." : "No notes yet."}
            </p>
          ) : (
            <ul className="space-y-0.5">
              {notes.map((note) => (
                <li key={note.id}>
                  <button
                    type="button"
                    onClick={() => setActiveId(note.id)}
                    aria-current={note.id === activeId ? "true" : undefined}
                    className={cn(
                      "w-full rounded-md px-2.5 py-2 text-left transition-colors",
                      note.id === activeId
                        ? "bg-surface-hover"
                        : "hover:bg-surface-hover",
                    )}
                  >
                    <span className="block truncate text-[13px] font-medium text-ink">
                      {note.title || "Untitled note"}
                    </span>
                    <span className="mt-0.5 line-clamp-1 block text-[12px] text-ink-subtle">
                      {note.content.replace(/\s+/g, " ").trim() || "Empty"}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </nav>
      </aside>

      <main className={cn("min-w-0 flex-1", active ? "block" : "hidden md:block")}>
        {active ? (
          <NoteEditor
            key={active.id}
            note={active}
            projects={projects}
            onBack={() => setActiveId(null)}
            onSaved={(updated) =>
              setNotes((current) =>
                (current ?? []).map((note) => (note.id === updated.id ? updated : note)),
              )
            }
            onDeleted={async () => {
              await workspace.deleteNote(active.id);
              setActiveId(null);
              await reload();
            }}
          />
        ) : (
          <div className="flex h-full items-center justify-center p-8">
            <EmptyState
              icon={<BookText />}
              title="Your research notebook"
              description="Write in Markdown. Link a note to the paper or project it belongs to, or leave it loose — a thought arrives before it is clear where it goes."
              action={
                <Button size="sm" onClick={createNote}>
                  Write a note
                </Button>
              }
              className="border-0"
            />
          </div>
        )}
      </main>
    </div>
  );
}

function NoteEditor({
  note,
  projects,
  onSaved,
  onDeleted,
  onBack,
}: {
  note: Note;
  projects: Project[];
  onSaved: (note: Note) => void;
  onDeleted: () => void;
  onBack: () => void;
}) {
  const [title, setTitle] = useState(note.title ?? "");
  const [content, setContent] = useState(note.content);
  const [status, setStatus] = useState<"idle" | "saving" | "saved">("idle");
  // Write and read are separate views rather than a split pane: a note is narrow, and half a
  // screen each makes both halves worse on the laptop this is actually used on.
  const [view, setView] = useState<"write" | "read">("write");

  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Debounced autosave. Typing should never be interrupted by a network round trip, and a
  // notebook that requires pressing Save is one that loses a thought when a tab closes.
  //
  // The effect re-runs on every keystroke and its cleanup cancels the pending timer, so only
  // the final scheduled save survives — and its closure already holds the newest text.
  useEffect(() => {
    if (title === (note.title ?? "") && content === note.content) return;

    setStatus("saving");
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(async () => {
      const saved = await workspace
        .updateNote(note.id, { title: title.trim() || null, content })
        .catch(() => null);
      if (saved) {
        onSaved(saved);
        setStatus("saved");
        setTimeout(() => setStatus("idle"), 1500);
      } else {
        setStatus("idle");
      }
    }, SAVE_DELAY_MS);

    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [title, content]);

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-3 border-b border-border px-5 py-2.5">
        <button
          type="button"
          onClick={onBack}
          aria-label="Back to notes"
          className="-ml-2 flex size-8 shrink-0 items-center justify-center rounded-md text-ink-muted transition-colors hover:bg-surface-hover hover:text-ink md:hidden"
        >
          <ChevronLeft className="size-4" aria-hidden />
        </button>

        <span
          className="min-w-16 text-[12px] text-ink-subtle"
          aria-live="polite"
          role="status"
        >
          {status === "saving" ? "Saving…" : status === "saved" ? "Saved" : ""}
        </span>

        <label className="ml-auto flex items-center gap-1.5 text-[12px] text-ink-muted">
          Project
          <select
            value={note.project_id ?? ""}
            onChange={async (event) => {
              const saved = await workspace.updateNote(note.id, {
                project_id: event.target.value || null,
              });
              onSaved(saved);
            }}
            className="h-7 max-w-44 rounded-md border border-border bg-surface px-1.5 text-[12px] text-ink focus:border-accent focus:outline-none"
          >
            <option value="">None</option>
            {projects.map((project) => (
              <option key={project.id} value={project.id}>
                {project.name}
              </option>
            ))}
          </select>
        </label>

        <div
          role="tablist"
          aria-label="Note view"
          className="flex rounded-md border border-border bg-surface-sunken p-0.5"
        >
          {(["write", "read"] as const).map((mode) => (
            <button
              key={mode}
              type="button"
              role="tab"
              aria-selected={view === mode}
              onClick={() => setView(mode)}
              className={cn(
                "rounded-sm px-2 py-1 text-[12px] capitalize transition-colors",
                view === mode
                  ? "bg-surface text-ink shadow-[var(--shadow-sm)]"
                  : "text-ink-subtle hover:text-ink-muted",
              )}
            >
              {mode}
            </button>
          ))}
        </div>

        <button
          type="button"
          aria-label="Delete note"
          onClick={onDeleted}
          className="rounded-sm p-1 text-ink-subtle hover:text-danger"
        >
          <Trash2 className="size-3.5" aria-hidden />
        </button>
      </header>

      <div className="scrollbar-slim flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-3xl px-6 py-8">
          <input
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="Untitled note"
            aria-label="Note title"
            className="w-full bg-transparent text-2xl font-semibold tracking-[-0.02em] text-ink placeholder:text-ink-subtle focus:outline-none"
          />

          {view === "write" ? (
            <textarea
              value={content}
              onChange={(event) => setContent(event.target.value)}
              placeholder="Markdown, LaTeX, tables, code — write however you think."
              aria-label="Note content"
              className="mt-5 min-h-[60vh] w-full resize-none bg-transparent font-serif text-[16px] leading-[1.75] text-ink placeholder:font-sans placeholder:text-[15px] placeholder:text-ink-subtle focus:outline-none"
            />
          ) : (
            <div className="mt-5 min-h-[60vh]">
              <NotePreview content={content} />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function NotebookSkeleton() {
  return (
    <div className="flex h-dvh" aria-busy>
      <div className="w-72 shrink-0 border-r border-border bg-surface-sunken p-3">
        <Skeleton className="h-8 w-full rounded-md" />
        <div className="mt-4 space-y-1.5">
          {Array.from({ length: 5 }, (_, index) => (
            <Skeleton key={index} className="h-12 w-full rounded-md" />
          ))}
        </div>
      </div>
      <div className="flex-1 p-8">
        <Skeleton className="h-8 w-2/5" />
        <Skeleton className="mt-6 h-64 w-full" />
      </div>
      <span className="sr-only">Loading your notebook</span>
    </div>
  );
}
