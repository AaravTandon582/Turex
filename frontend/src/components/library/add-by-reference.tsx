"use client";

import { Link2 } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import { papers } from "@/lib/papers";

/**
 * Add a paper without having the file.
 *
 * One field rather than a chooser for "link / DOI / arXiv", because the person pasting already
 * knows what they have and making them classify it is asking the reader to do the computer's
 * job. The server recognises all three.
 */
export function AddByReference({ onAdded }: { onAdded: () => void }) {
  const [reference, setReference] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const trimmed = reference.trim();
    if (!trimmed || busy) return;

    setBusy(true);
    setError(null);
    try {
      await papers.addByReference(trimmed);
      setReference("");
      onAdded();
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught.message
          : "Atlas couldn't add that. Check the link and try again.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="mt-3">
      <div className="flex gap-2">
        <div className="relative flex-1">
          <Link2
            aria-hidden
            className="pointer-events-none absolute top-1/2 left-3 size-3.5 -translate-y-1/2 text-ink-subtle"
          />
          <input
            value={reference}
            onChange={(event) => setReference(event.target.value)}
            placeholder="Paste an arXiv link, a DOI, or a PDF address"
            aria-label="Paper link, DOI, or arXiv id"
            className="h-9 w-full rounded-md border border-border bg-surface pr-3 pl-9 text-[13px] text-ink placeholder:text-ink-subtle focus:border-accent focus:ring-3 focus:ring-[var(--accent-ring)] focus:outline-none"
          />
        </div>
        <Button type="submit" size="sm" variant="secondary" loading={busy} disabled={!reference.trim()}>
          Add
        </Button>
      </div>

      {error && (
        <p role="alert" className="mt-2 text-[12px] text-danger">
          {error}
        </p>
      )}
      <p className="mt-1.5 text-[12px] text-ink-subtle">
        arXiv works directly. A DOI only works when the publisher serves the PDF rather than a
        landing page — for anything paywalled, download it and upload the file.
      </p>
    </form>
  );
}
