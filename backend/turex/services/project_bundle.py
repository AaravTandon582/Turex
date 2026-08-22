"""A whole project, as a folder of plain files.

The test of whether a research tool has really kept your work is what happens when you stop
using it. A project here is papers, notes, hypotheses, experiments, analyses and a lab
notebook, and inside Turex those are rows in eleven tables. Outside it they should be a folder
someone can read with `cat`, put under version control, attach to a submission, or hand to a
successor who has never heard of this application.

So the bundle is not an archive of Turex's data model. It is the shape a research project has
on disk anyway:

    README.md            what the project is, and what everything in here is
    references.bib       every paper, with the citation keys used everywhere else
    references.ris       the same, for reference managers that prefer it
    notes/*.md           one file per note, Markdown as written
    analyses/*.ipynb     one notebook per analysis, openable in Jupyter
    hypotheses.md        statements, status, and the evidence for and against
    experiments.md       design and results, side by side
    lab-notebook.md      the append-only record, with its hashes

Every file is text except the notebooks, which are JSON. Nothing needs Turex to read it, and a
diff between two exports says something useful — which is the whole argument for plain formats
and the reason this is worth building rather than a database dump.
"""

from __future__ import annotations

import io
import json
import re
import uuid
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from turex.models.analysis import Analysis, CellKind
from turex.models.lab import LabEntry
from turex.models.paper import Paper
from turex.models.workspace import Evidence, Experiment, Hypothesis, Note, Project
from turex.services.citations import bibtex_key
from turex.services.library_export import ExportFormat, export_papers

MAX_FILENAME_STEM = 60
"""Long enough to tell two notes apart, short enough that a path stays usable on every
filesystem once a folder name and an extension are added."""


@dataclass(frozen=True, slots=True)
class ProjectBundle:
    """The archive, and the name to offer it under."""

    filename: str
    content: bytes


def _slug(value: str, fallback: str) -> str:
    """A filename from a title, safe on every filesystem.

    Deliberately conservative: lower case, ASCII, hyphens. A note called `Results: 3/4 runs`
    becomes `results-3-4-runs` rather than a path with a directory separator in it — and the
    ordinal prefix added by the caller is what keeps two notes with the same title apart.
    """
    cleaned = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return cleaned[:MAX_FILENAME_STEM] or fallback


def _front_matter(fields: dict[str, Any]) -> str:
    """YAML front matter, the convention Obsidian, Quarto and Jekyll all read.

    Written by hand rather than with a YAML library, because every value here is a string, a
    number or a list of strings, and the one thing that needs care — a value containing a colon
    or a quote — is handled by quoting and escaping. A dependency for that is not worth it.
    """
    lines = ["---"]
    for key, value in fields.items():
        if value is None or value == [] or value == "":
            continue
        if isinstance(value, list):
            lines.append(f"{key}:")
            lines.extend(f'  - "{str(item).replace(chr(92), chr(92) * 2)}"' for item in value)
        elif isinstance(value, bool | int | float):
            lines.append(f"{key}: {value}")
        else:
            escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'{key}: "{escaped}"')
    lines.append("---\n")
    return "\n".join(lines)


def _notebook(analysis: Analysis) -> str:
    """An analysis as a Jupyter notebook.

    nbformat 4, which is what every tool that reads notebooks expects — Jupyter, VS Code,
    Colab, nbconvert, GitHub's own renderer. The outputs are carried across as `stream` text
    and `display_data` images, so opening the file shows what the analysis produced without
    re-running it, which for a result someone is checking is the point.
    """
    cells: list[dict[str, Any]] = []

    for cell in sorted(analysis.cells, key=lambda item: item.ordinal):
        source = cell.source.splitlines(keepends=True)

        # nbformat 4.5 requires an id per cell, and warns that it will become a hard error.
        # The cell's own identifier is used rather than a generated one, so re-exporting the
        # same analysis produces the same file and a diff shows only what actually changed.
        cell_id = str(cell.id)[:64]

        if cell.kind is CellKind.markdown:
            cells.append(
                {"id": cell_id, "cell_type": "markdown", "metadata": {}, "source": source}
            )
            continue

        outputs: list[dict[str, Any]] = []
        if cell.output:
            outputs.append(
                {
                    "output_type": "stream",
                    "name": "stdout",
                    "text": cell.output.splitlines(keepends=True),
                }
            )
        if cell.image and cell.image.startswith("data:image/png;base64,"):
            outputs.append(
                {
                    "output_type": "display_data",
                    "data": {"image/png": cell.image.split(",", 1)[1]},
                    "metadata": {},
                }
            )
        if cell.error:
            # `error` rather than a stream, so a reader's tools show it as a failure. A
            # traceback presented as ordinary output reads as a result.
            outputs.append(
                {
                    "output_type": "error",
                    "ename": "Error",
                    "evalue": cell.error.splitlines()[0] if cell.error else "",
                    "traceback": cell.error.splitlines(),
                }
            )

        cells.append(
            {
                "id": cell_id,
                "cell_type": "code",
                "execution_count": None,
                # Recorded so a stale result is visible in the file, not only in Turex.
                "metadata": {"turex": {"status": cell.status.value}},
                "outputs": outputs,
                "source": source,
            }
        )

    notebook = {
        "cells": cells,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    return json.dumps(notebook, indent=1, ensure_ascii=False) + "\n"


def _readme(
    project: Project,
    *,
    papers: list[Paper],
    notes: list[Note],
    hypotheses: list[Hypothesis],
    experiments: list[Experiment],
    analyses: list[Analysis],
    entries: list[LabEntry],
    exported_at: datetime,
) -> str:
    """The file someone opens first.

    It says what is in the folder and what each part means, because an archive whose contents
    need explaining is one that gets deleted by whoever inherits it.
    """
    lines = [
        f"# {project.name}",
        "",
    ]
    if project.research_question:
        lines += [f"**Research question:** {project.research_question}", ""]
    if project.description:
        lines += [project.description, ""]

    def count(number: int, singular: str, plural: str | None = None) -> str:
        """`1 note`, `2 notes`. A table that says "1 experiments" reads as unfinished."""
        return f"{number} {singular if number == 1 else (plural or singular + 's')}"

    lines += [
        "## What is in here",
        "",
        "| Path | Contents |",
        "|---|---|",
        f"| `references.bib`, `references.ris` | {count(len(papers), 'paper')}, with the "
        "citation keys used throughout |",
        f"| `notes/` | {count(len(notes), 'note')}, as Markdown |",
        f"| `analyses/` | {count(len(analyses), 'Jupyter notebook')}, with saved output |",
        f"| `hypotheses.md` | {count(len(hypotheses), 'hypothesis', 'hypotheses')} and their "
        "evidence |",
        f"| `experiments.md` | {count(len(experiments), 'experiment')}, design beside results |",
        f"| `lab-notebook.md` | {count(len(entries), 'append-only entry', 'append-only entries')}"
        ", with their hashes |",
        "",
        "Everything is plain text except the notebooks, which are JSON. Nothing here needs "
        "Turex to read it.",
        "",
        "## Citing these papers",
        "",
        "```bash",
        "pandoc paper.md --citeproc --bibliography=references.bib -o paper.pdf",
        "```",
        "",
        "The keys in `references.bib` are stable — derived from author, year and title word — "
        "so a `\\cite{}` written against this file keeps working after a re-export.",
        "",
        "## The lab notebook",
        "",
        "`lab-notebook.md` records each entry with the hash of the one before it. Altering any "
        "entry changes its hash and breaks every entry after it, so a chain that still links "
        "up is a record nothing has been quietly rewritten in.",
        "",
        "It does **not** prove *when* an entry was written — those timestamps came from the "
        "server that recorded them, with no outside witness.",
        "",
        "---",
        "",
        f"Exported from Turex on {exported_at.strftime('%Y-%m-%d %H:%M UTC')}.",
        "",
    ]
    return "\n".join(lines)


def _hypotheses_markdown(
    hypotheses: list[Hypothesis], evidence: dict[uuid.UUID, list[Evidence]]
) -> str:
    lines = ["# Hypotheses", ""]
    if not hypotheses:
        lines.append("_None recorded._")

    for hypothesis in hypotheses:
        lines += [f"## {hypothesis.statement}", "", f"**Status:** {hypothesis.status.value}", ""]
        if hypothesis.motivation:
            lines += ["**Motivation**", "", hypothesis.motivation, ""]
        if hypothesis.assumptions:
            lines += ["**Assumptions**", "", hypothesis.assumptions, ""]
        for stance in ("supports", "contradicts"):
            items = [e for e in evidence.get(hypothesis.id, []) if e.stance.value == stance]
            if not items:
                continue
            lines += [f"**Evidence that {stance}**", ""]
            for item in items:
                # Verbatim: it is the thing the claim rests on, and a paraphrase would break
                # the link between the claim and its source. The locator says where to check.
                quote = " ".join((item.quoted_text or "").split())
                lines.append(f"- > {quote}" if quote else "- (no passage recorded)")
                lines.append(f"  — *{item.paper_title}*, {item.locator}")
                if item.reasoning:
                    lines.append(f"  - {item.reasoning}")
            lines.append("")

    return "\n".join(lines) + "\n"


def _experiments_markdown(experiments: list[Experiment]) -> str:
    lines = ["# Experiments", ""]
    if not experiments:
        lines.append("_None recorded._")

    for experiment in experiments:
        lines += [f"## {experiment.title}", "", f"**Status:** {experiment.status.value}", ""]
        for label, value in (
            ("Objective", experiment.objective),
            ("Independent variables", experiment.independent_variables),
            ("Dependent variables", experiment.dependent_variables),
            ("Controls", experiment.controls),
            ("Confounders", experiment.confounders),
            ("Dataset", experiment.dataset),
            ("Methodology", experiment.methodology),
            ("Metrics", experiment.metrics),
        ):
            if value:
                lines += [f"**{label}**", "", value, ""]

        # Expected before actual, and never merged. Keeping both is the difference between an
        # experiment and a story told afterwards.
        if experiment.expected_result:
            lines += ["**Expected result**", "", experiment.expected_result, ""]
        if experiment.actual_result:
            lines += ["**Actual result**", "", experiment.actual_result, ""]
        if experiment.interpretation:
            lines += ["**Interpretation**", "", experiment.interpretation, ""]

    return "\n".join(lines) + "\n"


def _lab_markdown(entries: list[LabEntry]) -> str:
    lines = [
        "# Lab notebook",
        "",
        "Append-only. Each entry carries the hash of the one before it, so altering any entry "
        "breaks every entry after it.",
        "",
    ]
    if not entries:
        lines.append("_No entries._")

    for entry in entries:
        stamp = entry.recorded_at.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")
        lines += [f"## {entry.sequence}. {entry.title or stamp}", ""]
        if entry.title:
            lines += [f"_{stamp}_", ""]
        lines += [
            entry.body,
            "",
            f"`hash {entry.entry_hash}`  ",
            f"`prev {entry.previous_hash}`",
            "",
        ]

    return "\n".join(lines) + "\n"


def build_bundle(
    project: Project,
    *,
    papers: list[Paper],
    notes: list[Note],
    hypotheses: list[Hypothesis],
    evidence: dict[uuid.UUID, list[Evidence]],
    experiments: list[Experiment],
    analyses: list[Analysis],
    entries: list[LabEntry],
) -> ProjectBundle:
    """Assemble the archive in memory.

    In memory because a project's text is small — the papers themselves are not included, since
    a PDF is the publisher's file rather than the project's record, and shipping several
    hundred megabytes of them would make the export something people avoid running.
    """
    exported_at = datetime.now(UTC)
    root = _slug(project.name, "project")

    buffer = io.BytesIO()
    # Deflate: this is almost entirely text, which compresses to a fraction of its size.
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:

        def write(path: str, content: str) -> None:
            archive.writestr(f"{root}/{path}", content)

        write(
            "README.md",
            _readme(
                project,
                papers=papers,
                notes=notes,
                hypotheses=hypotheses,
                experiments=experiments,
                analyses=analyses,
                entries=entries,
                exported_at=exported_at,
            ),
        )

        write("references.bib", export_papers(papers, ExportFormat.bibtex))
        write("references.ris", export_papers(papers, ExportFormat.ris))
        write("references.json", export_papers(papers, ExportFormat.csl))

        for index, note in enumerate(notes, start=1):
            # Numbered so two notes with the same title cannot collide, and so the folder
            # lists in the order they were written.
            name = f"{index:03d}-{_slug(note.title or '', 'note')}.md"
            front = _front_matter(
                {
                    "title": note.title or "Untitled note",
                    "created": note.created_at.astimezone(UTC).isoformat(timespec="seconds"),
                    "updated": note.updated_at.astimezone(UTC).isoformat(timespec="seconds"),
                }
            )
            write(f"notes/{name}", f"{front}\n{note.content or ''}\n")

        for index, analysis in enumerate(analyses, start=1):
            name = f"{index:03d}-{_slug(analysis.title, 'analysis')}.ipynb"
            write(f"analyses/{name}", _notebook(analysis))

        write("hypotheses.md", _hypotheses_markdown(hypotheses, evidence))
        write("experiments.md", _experiments_markdown(experiments))
        write("lab-notebook.md", _lab_markdown(entries))

        # A citation key index, so a reader can go from a `\cite{}` back to a title without
        # opening the `.bib` and reading BibTeX.
        write(
            "papers.md",
            "# Papers\n\n"
            + "\n".join(
                f"- `{bibtex_key(paper)}` — {paper.title or paper.original_filename}"
                + (f" ({paper.publication_year})" if paper.publication_year else "")
                for paper in papers
            )
            + "\n",
        )

    return ProjectBundle(
        filename=f"{root}-{exported_at.strftime('%Y%m%d')}.zip",
        content=buffer.getvalue(),
    )
