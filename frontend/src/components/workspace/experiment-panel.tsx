"use client";

import { ChevronDown, FlaskConical, Plus, Trash2 } from "lucide-react";
import { useEffect, useId, useState } from "react";

import { Button } from "@/components/ui/button";
import { LoadError } from "@/components/ui/async-boundary";
import { Badge, Card, EmptyState } from "@/components/ui/primitives";
import { cn } from "@/lib/cn";
import { describe } from "@/lib/use-async";
import {
  EXPERIMENT_STATUSES,
  workspace,
  type Experiment,
  type ExperimentStatus,
  type Hypothesis,
} from "@/lib/workspace";

/** The design fields, in the order a person actually thinks through an experiment. */
const DESIGN_FIELDS: { key: keyof Experiment; label: string; placeholder: string }[] = [
  { key: "objective", label: "Objective", placeholder: "What are you trying to find out?" },
  {
    key: "independent_variables",
    label: "Independent variables",
    placeholder: "What you change",
  },
  { key: "dependent_variables", label: "Dependent variables", placeholder: "What you measure" },
  { key: "controls", label: "Controls", placeholder: "What you hold constant" },
  {
    key: "confounders",
    label: "Confounders",
    placeholder: "What else could explain the result",
  },
  { key: "dataset", label: "Dataset", placeholder: "What you run it on" },
  { key: "methodology", label: "Methodology", placeholder: "How you run it" },
  { key: "metrics", label: "Metrics", placeholder: "How you decide it worked" },
];

export function ExperimentPanel({
  projectId,
  hypotheses,
}: {
  projectId: string;
  hypotheses: Hypothesis[];
}) {
  const [experiments, setExperiments] = useState<Experiment[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [title, setTitle] = useState("");

  async function reload() {
    try {
      setExperiments(await workspace.listExperiments(projectId));
      setLoadError(null);
    } catch (caught) {
      setLoadError(describe(caught));
    }
  }

  useEffect(() => {
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  return (
    <div className="space-y-3">
      <form
        className="flex gap-2"
        onSubmit={async (event) => {
          event.preventDefault();
          if (!title.trim()) return;
          try {
            await workspace.createExperiment({ title, project_id: projectId });
            setTitle("");
            await reload();
          } catch (caught) {
            setLoadError(describe(caught));
          }
        }}
      >
        <input
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder="Name an experiment — e.g. “Ablate the retriever”"
          aria-label="New experiment title"
          className="h-9 flex-1 rounded-md border border-border bg-surface px-3 text-sm text-ink placeholder:text-ink-subtle focus:border-accent focus:outline-none"
        />
        <Button type="submit" size="sm" disabled={!title.trim()}>
          <Plus aria-hidden />
          Add
        </Button>
      </form>

      {loadError && (
        <LoadError message={loadError} onRetry={() => void reload()} className="mt-3" />
      )}

      {!loadError && experiments && experiments.length === 0 && (
        <EmptyState
          icon={<FlaskConical />}
          title="No experiments planned"
          description="Plan the test before running it. Recording what you expect, before you know, is what separates an experiment from a story told afterwards."
        />
      )}

      <ul className="space-y-2">
        {(experiments ?? []).map((experiment) => (
          <li key={experiment.id}>
            <ExperimentCard
              experiment={experiment}
              hypotheses={hypotheses}
              onChanged={reload}
            />
          </li>
        ))}
      </ul>
    </div>
  );
}

function ExperimentCard({
  experiment,
  hypotheses,
  onChanged,
}: {
  experiment: Experiment;
  hypotheses: Hypothesis[];
  onChanged: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const linked = hypotheses.find((hypothesis) => hypothesis.id === experiment.hypothesis_id);

  async function save(field: string, value: string) {
    try {
      await workspace.updateExperiment(experiment.id, { [field]: value || null });
      setError(null);
      onChanged();
    } catch (caught) {
      setError(describe(caught));
    }
  }

  return (
    <Card className="p-4">
      {error && <p role="alert" className="mb-2 text-sm text-danger">{error}</p>}
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-[14px] font-medium text-ink">{experiment.title}</h3>
          {linked && (
            <p className="mt-1 line-clamp-1 text-[12px] text-ink-muted">
              Tests: {linked.statement}
            </p>
          )}
        </div>
        <Badge tone={experiment.status === "complete" ? "success" : "neutral"}>
          {experiment.status}
        </Badge>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-1.5 text-[12px] text-ink-muted">
          Status
          <select
            value={experiment.status}
            onChange={(event) => save("status", event.target.value as ExperimentStatus)}
            className="h-7 rounded-md border border-border bg-surface px-1.5 text-[12px] text-ink focus:border-accent focus:outline-none"
          >
            {EXPERIMENT_STATUSES.map((option) => (
              <option key={option.value} value={option.value} title={option.hint}>
                {option.label} — {option.hint}
              </option>
            ))}
          </select>
        </label>

        {hypotheses.length > 0 && (
          <label className="flex items-center gap-1.5 text-[12px] text-ink-muted">
            Tests
            <select
              value={experiment.hypothesis_id ?? ""}
              onChange={(event) => save("hypothesis_id", event.target.value)}
              className="h-7 max-w-56 rounded-md border border-border bg-surface px-1.5 text-[12px] text-ink focus:border-accent focus:outline-none"
            >
              <option value="">No hypothesis</option>
              {hypotheses.map((hypothesis) => (
                <option key={hypothesis.id} value={hypothesis.id}>
                  {hypothesis.statement.slice(0, 60)}
                </option>
              ))}
            </select>
          </label>
        )}

        <button
          type="button"
          onClick={() => setExpanded((value) => !value)}
          aria-expanded={expanded}
          className="flex items-center gap-1 rounded-sm px-1.5 py-1 text-[12px] text-ink-muted hover:text-ink"
        >
          <ChevronDown
            className={cn("size-3 transition-transform", expanded && "rotate-180")}
            aria-hidden
          />
          Design
        </button>

        <button
          type="button"
          aria-label="Delete experiment"
          onClick={async () => {
            try {
              await workspace.deleteExperiment(experiment.id);
              onChanged();
            } catch (caught) {
              setError(describe(caught));
            }
          }}
          className="ml-auto rounded-sm p-1 text-ink-subtle hover:text-danger"
        >
          <Trash2 className="size-3.5" aria-hidden />
        </button>
      </div>

      {expanded && (
        <div className="mt-3 space-y-3 border-t border-border pt-3">
          {DESIGN_FIELDS.map((field) => (
            <EditableField
              key={field.key}
              label={field.label}
              placeholder={field.placeholder}
              value={(experiment[field.key] as string | null) ?? ""}
              onSave={(value) => save(field.key as string, value)}
            />
          ))}

          <div className="rounded-md border border-border bg-surface-sunken p-3">
            <p className="text-[11px] font-semibold tracking-wide text-ink-muted uppercase">
              Prediction and outcome
            </p>
            <p className="mt-1 text-[12px] text-ink-subtle">
              Write the expected result before running. Turex keeps both, so a surprise stays
              visible as a surprise.
            </p>
            <div className="mt-2.5 space-y-3">
              <EditableField
                label="Expected result"
                placeholder="What you predict, and why"
                value={experiment.expected_result ?? ""}
                onSave={(value) => save("expected_result", value)}
              />
              <EditableField
                label="Actual result"
                placeholder="What happened"
                value={experiment.actual_result ?? ""}
                onSave={(value) => save("actual_result", value)}
              />
              <EditableField
                label="Interpretation"
                placeholder="What it means — and what it doesn't"
                value={experiment.interpretation ?? ""}
                onSave={(value) => save("interpretation", value)}
              />
            </div>
          </div>
        </div>
      )}
    </Card>
  );
}

/**
 * A field that saves when it loses focus.
 *
 * No Save button per field: an experiment has fifteen of them, and a form that has to be
 * submitted is a form that gets abandoned halfway through.
 */
function EditableField({
  label,
  placeholder,
  value,
  onSave,
}: {
  label: string;
  placeholder: string;
  value: string;
  onSave: (value: string) => void;
}) {
  const [draft, setDraft] = useState(value);
  // Generated rather than derived from the label: two fields can share a label text, and
  // duplicate ids would point both labels at the same control.
  const fieldId = useId();

  useEffect(() => setDraft(value), [value]);

  return (
    <div className="space-y-1">
      <label
        htmlFor={fieldId}
        className="block text-[11px] font-semibold tracking-wide text-ink-muted uppercase"
      >
        {label}
      </label>
      <textarea
        id={fieldId}
        rows={draft.length > 90 ? 3 : 1}
        value={draft}
        placeholder={placeholder}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={() => draft !== value && onSave(draft)}
        className="block w-full resize-none rounded-sm border border-border bg-surface px-2 py-1.5 text-[13px] leading-relaxed text-ink placeholder:text-ink-subtle focus:border-accent focus:outline-none"
      />
    </div>
  );
}
