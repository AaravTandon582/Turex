"""Getting a library out of Turex, in formats other tools already read.

A research tool that can only be read from inside itself is a liability. Papers collected over
years should move to whatever comes next — a reference manager, a LaTeX document, a colleague's
machine — without anyone having to write a scraper, and the way to guarantee that is to emit
the formats those tools already speak.

Three, because they are read by different things:

* **BibTeX** — LaTeX, and every reference manager. The citation keys are stable and derived
  from author, year and title word, so a `\\cite{vaswani2017attention}` written today still
  resolves after a re-export. That stability is the whole reason a manuscript can survive its
  bibliography being regenerated.
* **RIS** — the interchange format Zotero, Mendeley, EndNote and most publishers agree on. Less
  expressive than BibTeX and far more widely accepted.
* **CSL-JSON** — what Zotero stores natively and what Pandoc and Quarto consume directly, so a
  Markdown manuscript can cite straight out of this file with no conversion step.

Nothing here invents a field. A paper with no year exports with no year, because a bibliography
entry with a guessed date is worse than an incomplete one — it looks finished, and it gets
pasted into a manuscript unchecked.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from enum import StrEnum
from typing import Any

from turex.ingestion.bibliography import is_collective
from turex.models.paper import Paper
from turex.services.citations import bibtex_key, to_bibtex


class ExportFormat(StrEnum):
    bibtex = "bibtex"
    ris = "ris"
    csl = "csl"


CONTENT_TYPES: dict[ExportFormat, str] = {
    # `application/x-bibtex` is what Zotero and Overleaf recognise on a download.
    ExportFormat.bibtex: "application/x-bibtex; charset=utf-8",
    ExportFormat.ris: "application/x-research-info-systems; charset=utf-8",
    ExportFormat.csl: "application/json; charset=utf-8",
}

FILE_SUFFIXES: dict[ExportFormat, str] = {
    ExportFormat.bibtex: "bib",
    ExportFormat.ris: "ris",
    ExportFormat.csl: "json",
}


def _authors(paper: Paper) -> list[str]:
    return [
        name for author in (paper.authors or []) if (name := str(author.get("name", "")).strip())
    ]


def _split_name(name: str) -> tuple[str, str]:
    """`Ashish Vaswani` → `("Vaswani", "Ashish")`.

    Everything before the last space is treated as given names. It is wrong for a compound
    surname written without a comma, and there is no way to be right about that from a display
    string — which is why the given form is preserved exactly in the CSL `literal` fallback
    where the split looks unsafe.
    """
    cleaned = " ".join(name.split())
    if "," in cleaned:
        family, _, given = cleaned.partition(",")
        return family.strip(), given.strip()
    # An organisation has no surname. Splitting "ATLAS Collaboration" into
    # "Collaboration, ATLAS" is visibly wrong in a bibliography.
    if is_collective(cleaned):
        return cleaned, ""
    parts = cleaned.rsplit(" ", 1)
    return (parts[1], parts[0]) if len(parts) == 2 else (cleaned, "")


# -- RIS ------------------------------------------------------------------------------------


def _ris_lines(paper: Paper) -> list[str]:
    """One record. RIS is `TAG  - value`, exactly two spaces, terminated by `ER  -`.

    The spacing is not cosmetic: importers parse by column position, and a single space is
    silently dropped by several of them.
    """
    # `JOUR` for anything with a venue, `GEN` otherwise. RIS has no preprint type that
    # importers agree on, and claiming `JOUR` for an arXiv preprint would assert a journal
    # publication that has not happened.
    kind = "JOUR" if paper.venue else "GEN"

    lines = [f"TY  - {kind}"]
    for name in _authors(paper):
        family, given = _split_name(name)
        lines.append(f"AU  - {family}, {given}" if given else f"AU  - {family}")

    if paper.title:
        lines.append(f"TI  - {paper.title}")
    if paper.publication_year:
        lines.append(f"PY  - {paper.publication_year}")
    if paper.venue:
        lines.append(f"JO  - {paper.venue}")
    if paper.doi:
        lines.append(f"DO  - {paper.doi}")
    if paper.abstract:
        # Newlines would terminate the field, so the abstract is flattened to one line.
        lines.append(f"AB  - {' '.join(paper.abstract.split())}")
    if paper.arxiv_id:
        lines.append(f"UR  - https://arxiv.org/abs/{paper.arxiv_id}")
    elif paper.source_url:
        lines.append(f"UR  - {paper.source_url}")

    lines.append("ER  - ")
    return lines


# -- CSL-JSON -------------------------------------------------------------------------------


def _csl_entry(paper: Paper) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "id": bibtex_key(paper),
        # `article-journal` when there is a venue, `manuscript` otherwise — the CSL type for
        # unpublished work, which is what a preprint is.
        "type": "article-journal" if paper.venue else "manuscript",
    }

    if paper.title:
        entry["title"] = paper.title

    authors: list[dict[str, str]] = []
    for name in _authors(paper):
        family, given = _split_name(name)
        # A name that does not split into two parts is kept whole. CSL's `literal` exists for
        # exactly this — collaborations, mononyms — and is preferable to inventing a surname.
        authors.append({"family": family, "given": given} if given else {"literal": name})
    if authors:
        entry["author"] = authors

    if paper.publication_year:
        entry["issued"] = {"date-parts": [[paper.publication_year]]}
    if paper.venue:
        entry["container-title"] = paper.venue
    if paper.doi:
        entry["DOI"] = paper.doi
    if paper.abstract:
        entry["abstract"] = paper.abstract
    if paper.arxiv_id:
        entry["note"] = f"arXiv:{paper.arxiv_id}"
        entry["URL"] = f"https://arxiv.org/abs/{paper.arxiv_id}"
    elif paper.source_url:
        entry["URL"] = paper.source_url

    return entry


# -- Public ---------------------------------------------------------------------------------


def export_papers(papers: Sequence[Paper], fmt: ExportFormat) -> str:
    """A whole selection of papers, as one file's worth of text."""
    if fmt is ExportFormat.bibtex:
        entries = [to_bibtex(paper).text for paper in papers]
        return "\n\n".join(entries) + ("\n" if entries else "")

    if fmt is ExportFormat.ris:
        records = ["\n".join(_ris_lines(paper)) for paper in papers]
        return "\n\n".join(records) + ("\n" if records else "")

    # `ensure_ascii=False` because these files are read by humans as often as by tools, and a
    # bibliography full of `é` is unreadable in both directions.
    return json.dumps([_csl_entry(paper) for paper in papers], indent=2, ensure_ascii=False) + "\n"
