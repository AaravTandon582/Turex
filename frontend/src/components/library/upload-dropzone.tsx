"use client";

import { AlertCircle, CheckCircle2, FileUp, Loader2, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type DragEvent } from "react";

import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import { papers } from "@/lib/papers";
import { cn } from "@/lib/cn";

type UploadState = "uploading" | "queued" | "failed";

interface Upload {
  id: string;
  filename: string;
  state: UploadState;
  percent: number;
  error?: string;
}

/**
 * Drop target and file picker for adding papers.
 *
 * Uploads run concurrently and each reports its own progress: dropping eight PDFs at once is
 * a normal way to start a literature review, and a single global spinner would hide which
 * one failed.
 */
export function UploadDropzone({ onUploaded }: { onUploaded: () => void }) {
  const [dragging, setDragging] = useState(false);
  const [uploads, setUploads] = useState<Upload[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);
  // Drag events fire for every child element; counting enter/leave avoids flicker.
  const dragDepth = useRef(0);

  const update = useCallback((id: string, patch: Partial<Upload>) => {
    setUploads((current) =>
      current.map((upload) => (upload.id === id ? { ...upload, ...patch } : upload)),
    );
  }, []);

  const startUpload = useCallback(
    async (file: File) => {
      const id = `${file.name}-${file.size}-${crypto.randomUUID()}`;
      setUploads((current) => [
        ...current,
        { id, filename: file.name, state: "uploading", percent: 0 },
      ]);

      try {
        await papers.upload(file, (percent) => update(id, { percent }));
        update(id, { state: "queued", percent: 100 });
        onUploaded();
        // Clear the row once the library list has picked the paper up.
        setTimeout(() => setUploads((current) => current.filter((u) => u.id !== id)), 2500);
      } catch (caught) {
        update(id, {
          state: "failed",
          error:
            caught instanceof ApiError
              ? caught.message
              : "Atlas couldn't upload that file. Try again.",
        });
      }
    },
    [onUploaded, update],
  );

  const accept = useCallback(
    (files: FileList | null) => {
      if (!files) return;
      for (const file of Array.from(files)) void startUpload(file);
    },
    [startUpload],
  );

  // A drop anywhere on the page should not navigate away from the app.
  useEffect(() => {
    const prevent = (event: Event) => event.preventDefault();
    window.addEventListener("dragover", prevent);
    window.addEventListener("drop", prevent);
    return () => {
      window.removeEventListener("dragover", prevent);
      window.removeEventListener("drop", prevent);
    };
  }, []);

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    dragDepth.current = 0;
    setDragging(false);
    accept(event.dataTransfer.files);
  }

  return (
    <div className="space-y-2">
      <div
        onDragEnter={(event) => {
          event.preventDefault();
          dragDepth.current += 1;
          setDragging(true);
        }}
        onDragLeave={() => {
          dragDepth.current -= 1;
          if (dragDepth.current <= 0) setDragging(false);
        }}
        onDragOver={(event) => event.preventDefault()}
        onDrop={onDrop}
        className={cn(
          "rounded-lg border border-dashed px-5 py-6 text-center transition-colors duration-150",
          dragging ? "border-accent bg-accent-soft" : "border-border bg-surface-sunken",
        )}
      >
        <FileUp
          className={cn("mx-auto size-5", dragging ? "text-accent" : "text-ink-subtle")}
          aria-hidden
        />
        <p className="mt-2.5 text-sm text-ink">
          Drop PDFs here, or{" "}
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            className="font-medium text-accent underline-offset-2 hover:underline"
          >
            choose files
          </button>
        </p>
        <p className="mt-1 text-[13px] text-ink-subtle">
          Atlas reads each paper in the background — you can keep working while it does.
        </p>

        <input
          aria-label="Choose PDFs to upload"
          ref={inputRef}
          type="file"
          accept="application/pdf,.pdf"
          multiple
          className="sr-only"
          onChange={(event) => {
            accept(event.target.files);
            // Reset so re-selecting the same file still fires a change event.
            event.target.value = "";
          }}
        />
      </div>

      {uploads.length > 0 && (
        <ul className="space-y-1.5" aria-live="polite">
          {uploads.map((upload) => (
            <UploadRow
              key={upload.id}
              upload={upload}
              onDismiss={() =>
                setUploads((current) => current.filter((item) => item.id !== upload.id))
              }
            />
          ))}
        </ul>
      )}
    </div>
  );
}

function UploadRow({ upload, onDismiss }: { upload: Upload; onDismiss: () => void }) {
  return (
    <li className="flex items-center gap-3 rounded-md border border-border bg-surface px-3 py-2">
      {upload.state === "uploading" && (
        <Loader2 className="size-4 shrink-0 animate-spin text-ink-subtle" aria-hidden />
      )}
      {upload.state === "queued" && (
        <CheckCircle2 className="size-4 shrink-0 text-success" aria-hidden />
      )}
      {upload.state === "failed" && (
        <AlertCircle className="size-4 shrink-0 text-danger" aria-hidden />
      )}

      <div className="min-w-0 flex-1">
        <p className="truncate text-[13px] text-ink">{upload.filename}</p>
        {upload.state === "uploading" && (
          <div
            role="progressbar"
            aria-valuenow={upload.percent}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label={`Uploading ${upload.filename}`}
            className="mt-1.5 h-1 overflow-hidden rounded-full bg-surface-sunken"
          >
            <div
              className="h-full rounded-full bg-accent transition-[width] duration-200"
              style={{ width: `${upload.percent}%` }}
            />
          </div>
        )}
        {upload.state === "queued" && (
          <p className="text-[12px] text-ink-subtle">Added — Atlas is reading it now</p>
        )}
        {upload.state === "failed" && <p className="text-[12px] text-danger">{upload.error}</p>}
      </div>

      {upload.state === "failed" && (
        <Button variant="ghost" size="sm" onClick={onDismiss} aria-label="Dismiss">
          <X aria-hidden />
        </Button>
      )}
    </li>
  );
}
