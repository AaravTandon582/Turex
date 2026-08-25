"use client";

import { AlertTriangle, Check, Download, Upload } from "lucide-react";
import { useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/loading";
import { PendingWork } from "@/components/ui/pending-work";
import { Card } from "@/components/ui/primitives";
import {
  papers,
  type ExportFormat,
  type PaperQuery,
  type ReferenceImportResult,
} from "@/lib/papers";
import { describe } from "@/lib/use-async";

const FORMATS: { value: ExportFormat; label: string; note: string }[] = [
  { value: "bibtex", label: "BibTeX", note: "LaTeX, Overleaf, and every reference manager" },
  { value: "ris", label: "RIS", note: "Zotero, Mendeley, EndNote" },
  { value: "csl", label: "CSL-JSON", note: "Pandoc and Quarto, read directly" },
];

/**
 * Getting the library in and out in formats other tools already read.
 *
 * A library collected over years should move to whatever comes next without anyone writing a
 * scraper, and the way to guarantee that is to emit what those tools already speak. All three
 * are plain text: diffable, committable, and readable in ten years without this application.
 *
 * The export honours whatever filters are on screen, so what you are looking at is what you
 * get — a collection, a tag, a search, or everything.
 */
export function Bibliography({ query, total }: { query: PaperQuery; total: number }) {
  const [importing, setImporting] = useState(false);
  const [result, setResult] = useState<ReferenceImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);

  async function handleFile(file: File) {
    setImporting(true);
    setError(null);
    setResult(null);
    try {
      setResult(await papers.importReferences(file));
    } catch (caught) {
      setError(describe(caught));
    } finally {
      setImporting(false);
      // Cleared so choosing the same file again re-fires `change`, which it otherwise
      // would not — a retry after a failure would silently do nothing.
      if (input.current) input.current.value = "";
    }
  }

  return (
    <Card className="p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[13px] font-medium text-ink">Bibliography</span>
        <span className="text-[12px] text-ink-subtle">
          {total.toLocaleString()} {total === 1 ? "paper" : "papers"} in this view
        </span>

        <div className="ml-auto flex flex-wrap items-center gap-1">
          {FORMATS.map((format) => (
            <Button key={format.value} asChild variant="ghost" size="sm" title={format.note}>
              {/* A plain link, so the browser downloads it with the filename the server
                  chose and nothing is held in memory. */}
              <a href={papers.exportUrl(format.value, query)} download>
                <Download aria-hidden className="size-4" />
                {format.label}
              </a>
            </Button>
          ))}

          <Button
            variant="ghost"
            size="sm"
            onClick={() => input.current?.click()}
            disabled={importing}
            title="Import a .bib or .ris file from Zotero, Mendeley, or a manuscript"
          >
            {importing ? <Spinner label="Importing references" /> : (
              <Upload aria-hidden className="size-4" />
            )}
            Import
          </Button>

          <input
            ref={input}
            type="file"
            accept=".bib,.ris,.bibtex,text/plain,application/x-bibtex"
            aria-label="Import a bibliography file"
            className="sr-only"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) void handleFile(file);
            }}
          />
        </div>
      </div>

      {importing && (
        <PendingWork
          className="mt-3"
          label="Fetching each reference that carries a DOI or an arXiv id, and reading it."
        />
      )}

      {error && (
        <p role="alert" className="mt-2 text-[13px] text-danger">
          {error}
        </p>
      )}

      {result && (
        <div className="mt-3 border-t border-border pt-3">
          {/* Four numbers that add up, so nothing disappears without explanation. */}
          <p className="flex items-center gap-1.5 text-[13px] text-ink">
            <Check aria-hidden className="size-4 text-success" />
            {result.imported} of {result.found} added.
          </p>

          {result.without_identifier > 0 && (
            <p className="mt-1 text-[12px] text-ink-muted">
              {result.without_identifier} had no DOI or arXiv id, so there was nothing to fetch.
            </p>
          )}

          {result.failed.length > 0 && (
            <details className="mt-2">
              <summary className="cursor-pointer text-[12px] text-ink-muted hover:text-ink">
                <AlertTriangle aria-hidden className="mr-1 inline size-3.5 text-warning" />
                {result.failed.length} could not be fetched
              </summary>
              {/* Named individually, because "3 failed" leaves nobody able to go and get
                  those three by hand. */}
              <ul className="mt-1.5 space-y-1">
                {result.failed.slice(0, 20).map((failure) => (
                  <li key={failure.reference} className="text-[12px] text-ink-muted">
                    <span className="font-mono">{failure.reference}</span> — {failure.reason}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}
    </Card>
  );
}
