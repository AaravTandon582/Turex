"""Reading a bibliography someone else's tool wrote.

The other half of getting a library out is getting one in. Anyone adopting Turex arrives with
years of references already in Zotero, Mendeley or a `.bib` file beside a manuscript, and
"start again by hand" is not an answer — it is the reason people do not move.

Both formats are parsed for the same small set of fields, because that is what is worth acting
on: enough to find the paper again. What matters most is the **identifier**. A DOI or an arXiv
id turns an entry into a paper Turex can actually fetch and read; an entry with neither is a
title and a wish, and this says so rather than creating a row that can never become a document.

Deliberately hand-written rather than pulled in as a dependency. A BibTeX parser that handles
the whole language — `@string` macros, concatenation, nested braces, the eight ways to write an
accent — is a real piece of software, and none of that grammar reaches the four fields needed
here. What is handled is what real exports contain.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from turex.core.logging import get_logger

logger = get_logger(__name__)

MAX_ENTRIES = 5_000
"""A bound on one upload. A personal library is thousands, not millions, and the cost of an
import is one download and one ingestion per entry — so a file with more than this in it is
more likely a mistake than a request.
"""

_ARXIV_ID = r"(?:\d{4}\.\d{4,5})|(?:[a-z-]+(?:\.[A-Z]{2})?/\d{7})"
_ARXIV_IN_TEXT = re.compile(
    # Both the bare form an `eprint` field carries and the URL form a RIS `UR` line does.
    # Only the URL form was matched at first, which meant Turex could not re-import its own
    # RIS export: sixteen of nineteen entries came back with no identifier because their id
    # was inside `https://arxiv.org/abs/…` rather than after a bare `arXiv:`.
    rf"arxiv\.org/(?:abs|pdf)/({_ARXIV_ID})|arxiv[:\s]*({_ARXIV_ID})",
    re.I,
)
_DOI_IN_TEXT = re.compile(r"\b(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)")
_BRACED = re.compile(r"[{}]")

COLLECTIVE_NAMES = ("collaboration", "consortium", "group", "team", "network", "initiative")
"""Words that mark a name as an organisation rather than a person.

There is no general way to tell "ATLAS Collaboration" from "Ashish Vaswani" — both are two
words — so this is a narrow list of the terms that actually appear in author fields. Getting
it wrong the other way puts "Collaboration, ATLAS" in a bibliography, which is visibly wrong
in a way an editor will notice and an author will be embarrassed by.
"""


def is_collective(name: str) -> bool:
    lowered = name.lower()
    return any(word in lowered for word in COLLECTIVE_NAMES)


@dataclass(frozen=True, slots=True)
class BibliographyEntry:
    """One reference, reduced to what Turex can act on."""

    title: str | None = None
    authors: list[str] | None = None
    year: int | None = None
    venue: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None

    @property
    def identifier(self) -> str | None:
        """What to hand the importer, or None if this entry cannot be fetched.

        arXiv first: it resolves to a free PDF every time, where a DOI resolves to a publisher's
        landing page that may be paywalled. Preferring the one that works is not a guess — it
        is the difference between an import that succeeds and one that reports a web page.
        """
        if self.arxiv_id:
            return self.arxiv_id
        if self.doi:
            return self.doi
        return None


@dataclass(frozen=True, slots=True)
class ParsedBibliography:
    entries: list[BibliographyEntry]
    skipped: int
    """Entries that parsed but carry no identifier. Counted and reported rather than dropped
    silently, because "42 of 60 imported" needs the other 18 explained."""


def _clean(value: str) -> str:
    """Strip BibTeX's braces and collapse whitespace.

    Braces in a value are protection against a style lowercasing a word — `{BERT}` — and carry
    no meaning once the value is a plain string, which is what everything downstream wants.
    """
    return " ".join(_BRACED.sub("", value).split()).strip(" ,")


def _year(value: str) -> int | None:
    match = re.search(r"\b(1[5-9]\d{2}|20\d{2}|21\d{2})\b", value)
    return int(match.group(1)) if match else None


def _identifiers(blob: str) -> tuple[str | None, str | None]:
    """Find a DOI and an arXiv id anywhere in an entry's text.

    Searched across the whole entry rather than in a named field, because exporters scatter
    them: an arXiv id turns up in `eprint`, in `journal`, in `note`, in `url`, and in none of
    them consistently. The patterns are specific enough that a false positive would have to be
    a genuine identifier appearing in prose.
    """
    arxiv = _ARXIV_IN_TEXT.search(blob)
    doi = _DOI_IN_TEXT.search(blob)
    # Whichever alternative matched — the URL form or the bare one — carries the id.
    identifier = (arxiv.group(1) or arxiv.group(2)) if arxiv else None
    return (
        doi.group(1).rstrip(".,;)}") if doi else None,
        identifier,
    )


# -- BibTeX ---------------------------------------------------------------------------------


def _split_bibtex_entries(text: str) -> list[str]:
    """Cut the file into entries by tracking brace depth.

    A regular expression cannot do this correctly: entry bodies contain braces, and a lazy
    match stops at the first `}` inside a title while a greedy one swallows the rest of the
    file. Counting depth is the only way to find where an entry actually ends.
    """
    entries: list[str] = []
    index = 0

    while (start := text.find("@", index)) != -1:
        opening = text.find("{", start)
        if opening == -1:
            break

        depth = 0
        cursor = opening
        while cursor < len(text):
            if text[cursor] == "{":
                depth += 1
            elif text[cursor] == "}":
                depth -= 1
                if depth == 0:
                    break
            cursor += 1

        if depth != 0:  # Unbalanced: the file is truncated, so stop rather than guess.
            break

        entries.append(text[start : cursor + 1])
        index = cursor + 1

    return entries


_FIELD_NAME = re.compile(r"(\w+)\s*=\s*")


def _read_fields(entry: str) -> dict[str, str]:
    """Field values, read by tracking brace depth rather than by regular expression.

    A lazy brace match stops at the first closing brace, which is inside the value whenever a
    title protects a word: `{{BERT}: Pre-training}` was read as `BERT` and the rest of the
    title silently discarded. A greedy match has the opposite failure. Depth counting is the
    only thing that finds where a value actually ends — the same reason entries are split this
    way.
    """
    fields: dict[str, str] = {}
    # Past the entry type and citation key, which are not fields.
    cursor = entry.find(",", entry.find("{")) + 1
    if cursor == 0:
        return fields

    while (match := _FIELD_NAME.search(entry, cursor)) is not None:
        name = match.group(1).lower()
        start = match.end()
        if start >= len(entry):
            break

        if entry[start] == "{":
            depth, index = 0, start
            while index < len(entry):
                if entry[index] == "{":
                    depth += 1
                elif entry[index] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                index += 1
            value, cursor = entry[start + 1 : index], index + 1
        elif entry[start] == '"':
            index = entry.find('"', start + 1)
            index = len(entry) if index == -1 else index
            value, cursor = entry[start + 1 : index], index + 1
        else:
            index = start
            while index < len(entry) and entry[index] not in ",\n}":
                index += 1
            value, cursor = entry[start:index], index + 1

        fields[name] = _clean(value)

    return fields


def parse_bibtex(text: str) -> ParsedBibliography:
    entries: list[BibliographyEntry] = []
    skipped = 0

    for raw in _split_bibtex_entries(text)[:MAX_ENTRIES]:
        # `@comment`, `@string` and `@preamble` are not references.
        if re.match(r"@\s*(comment|string|preamble)\b", raw, re.I):
            continue

        fields = _read_fields(raw)
        doi, arxiv = _identifiers(raw)

        entry = BibliographyEntry(
            title=fields.get("title") or None,
            authors=[part.strip() for part in fields["author"].split(" and ")]
            if fields.get("author")
            else None,
            year=_year(fields.get("year", "")) or _year(fields.get("date", "")),
            venue=fields.get("journal") or fields.get("booktitle") or None,
            doi=doi or (fields.get("doi") or None),
            arxiv_id=arxiv or (fields.get("eprint") or None),
        )
        if entry.identifier is None:
            skipped += 1
        entries.append(entry)

    return ParsedBibliography(entries=entries, skipped=skipped)


# -- RIS ------------------------------------------------------------------------------------


_RIS_LINE = re.compile(r"^([A-Z][A-Z0-9])\s{2}-\s?(.*)$")


def parse_ris(text: str) -> ParsedBibliography:
    """RIS is line-oriented: `TAG  - value`, records ending at `ER`.

    A continuation line — one with no tag — belongs to the field above it, which is how
    exporters wrap long abstracts. Treating it as a new field loses the rest of the sentence.
    """
    entries: list[BibliographyEntry] = []
    skipped = 0
    current: dict[str, list[str]] = {}
    raw_lines: list[str] = []
    last_tag: str | None = None

    def first(*tags: str) -> str | None:
        """The first value under whichever of these tags the exporter chose to use."""
        for tag in tags:
            values = current.get(tag)
            if values:
                return values[0]
        return None

    def finish() -> None:
        nonlocal skipped, current, raw_lines, last_tag
        if current:
            doi, arxiv = _identifiers("\n".join(raw_lines))
            entry = BibliographyEntry(
                title=first("TI", "T1"),
                authors=current.get("AU") or current.get("A1") or None,
                year=_year(" ".join(current.get("PY", []) + current.get("Y1", []))),
                venue=first("JO", "JF", "T2"),
                doi=doi or first("DO"),
                arxiv_id=arxiv,
            )
            if entry.identifier is None:
                skipped += 1
            entries.append(entry)
        current, raw_lines, last_tag = {}, [], None

    for line in text.splitlines():
        raw_lines.append(line)
        match = _RIS_LINE.match(line.rstrip())

        if match is None:
            if last_tag and line.strip() and current.get(last_tag):
                current[last_tag][-1] += f" {line.strip()}"
            continue

        tag, value = match.group(1), match.group(2).strip()
        if tag == "ER":
            finish()
            if len(entries) >= MAX_ENTRIES:
                break
            continue

        if value:
            current.setdefault(tag, []).append(value)
            last_tag = tag

    finish()  # A file whose last record has no `ER` still yields it.
    return ParsedBibliography(entries=entries, skipped=skipped)


def parse_bibliography(text: str, *, filename: str = "") -> ParsedBibliography:
    """Parse either format, deciding from the content rather than the extension.

    A file's name is whatever someone typed. `@article{` at the start of a line is BibTeX and
    `TY  - ` is RIS, and neither can be mistaken for the other — so the contents decide, with
    the extension used only to break a tie on a file that looks like neither.
    """
    sample = text[:8000]

    if re.search(r"^\s*@\w+\s*\{", sample, re.M):
        return parse_bibtex(text)
    if re.search(r"^TY\s{2}-", sample, re.M):
        return parse_ris(text)

    if filename.lower().endswith(".ris"):
        return parse_ris(text)
    return parse_bibtex(text)
