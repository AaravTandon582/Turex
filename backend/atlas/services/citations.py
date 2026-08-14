"""Formatting a paper as a citation.

Built strictly from stored metadata. Nothing here guesses, completes, or infers a missing
field — a citation with an invented year or a hallucinated venue is worse than an incomplete
one, because it looks finished and gets pasted into a bibliography unchecked.

Missing fields are reported to the caller so the interface can say which ones need filling in,
and are rendered as the placeholder each style uses for unknown data (`n.d.` for a missing
date) rather than silently omitted.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum

from atlas.models.paper import Paper


class CitationStyle(StrEnum):
    bibtex = "bibtex"
    apa = "apa"
    mla = "mla"


@dataclass(frozen=True, slots=True)
class FormattedCitation:
    style: CitationStyle
    text: str
    missing_fields: list[str]
    """Fields the style expects that this paper does not have. Surfaced so the user can
    correct the metadata rather than discovering the gap in their bibliography."""


def _author_names(paper: Paper) -> list[str]:
    return [
        name for author in (paper.authors or []) if (name := str(author.get("name", "")).strip())
    ]


def _split_name(name: str) -> tuple[str, str]:
    """Return (family, given). Assumes "Given Family", which is how extraction stores names.

    Names are genuinely harder than this — particles, multiple family names, cultures that
    order differently. Atlas does not attempt to solve that; it keeps the printed order and
    lets the user correct anything the naive split gets wrong.
    """
    parts = name.split()
    if len(parts) == 1:
        return parts[0], ""
    return parts[-1], " ".join(parts[:-1])


def _initials(given: str) -> str:
    return " ".join(f"{part[0]}." for part in given.split() if part)


def _missing(paper: Paper) -> list[str]:
    gaps: list[str] = []
    if not paper.title:
        gaps.append("title")
    if not _author_names(paper):
        gaps.append("authors")
    if not paper.publication_year:
        gaps.append("year")
    if not paper.venue:
        gaps.append("venue")
    return gaps


# -- BibTeX ---------------------------------------------------------------------------

_BIBTEX_UNSAFE = re.compile(r"[{}\\]")


def _bibtex_key(paper: Paper) -> str:
    """`vaswani2017attention` — the conventional author-year-word form."""
    authors = _author_names(paper)
    family = _split_name(authors[0])[0].lower() if authors else "unknown"
    family = _ascii_slug(family) or "unknown"
    year = str(paper.publication_year) if paper.publication_year else "nd"

    first_word = ""
    if paper.title:
        skip = {"a", "an", "the", "on", "of", "in", "for", "and", "is", "to"}
        for word in re.findall(r"[A-Za-z]+", paper.title.lower()):
            if word not in skip and len(word) > 2:
                first_word = _ascii_slug(word)
                break

    return f"{family}{year}{first_word}"


def _ascii_slug(value: str) -> str:
    """Fold accents and drop anything a BibTeX key may not contain."""
    folded = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", folded.lower())


def _bibtex_escape(value: str) -> str:
    return _BIBTEX_UNSAFE.sub("", value)


def to_bibtex(paper: Paper) -> FormattedCitation:
    authors = _author_names(paper)
    # BibTeX joins authors with " and ", and expects "Family, Given" for reliable parsing.
    author_field = " and ".join(
        f"{family}, {given}".rstrip(", ") for family, given in map(_split_name, authors)
    )

    entry_type = "article" if paper.venue or paper.doi else "misc"

    # Each entry is the fully-rendered `{...}` value, so the join stays a plain format and
    # cannot get the bracing wrong for one field.
    fields: list[tuple[str, str]] = []

    if paper.title:
        # Double braces: the inner pair protects the capitalisation of proper nouns and
        # acronyms, which most BibTeX styles would otherwise lowercase.
        fields.append(("title", f"{{{{{_bibtex_escape(paper.title)}}}}}"))
    if author_field:
        fields.append(("author", f"{{{_bibtex_escape(author_field)}}}"))
    if paper.publication_year:
        fields.append(("year", f"{{{paper.publication_year}}}"))
    if paper.venue:
        fields.append(("journal", f"{{{_bibtex_escape(paper.venue)}}}"))
    if paper.doi:
        fields.append(("doi", f"{{{paper.doi}}}"))
    if paper.arxiv_id:
        fields.append(("eprint", f"{{{paper.arxiv_id}}}"))
        fields.append(("archivePrefix", "{arXiv}"))

    body = ",\n".join(f"  {name} = {value}" for name, value in fields)
    text = f"@{entry_type}{{{_bibtex_key(paper)},\n{body}\n}}"
    return FormattedCitation(style=CitationStyle.bibtex, text=text, missing_fields=_missing(paper))


# -- APA ------------------------------------------------------------------------------


def to_apa(paper: Paper) -> FormattedCitation:
    authors = _author_names(paper)
    formatted = [
        f"{family}, {_initials(given)}".rstrip(", ") for family, given in map(_split_name, authors)
    ]

    if not formatted:
        author_part = ""
    elif len(formatted) == 1:
        author_part = formatted[0]
    elif len(formatted) <= 20:
        author_part = f"{', '.join(formatted[:-1])}, & {formatted[-1]}"
    else:
        # APA 7: first 19, an ellipsis, then the final author.
        author_part = f"{', '.join(formatted[:19])}, ... {formatted[-1]}"

    # APA 7 closes the date element with a period: "Vaswani, A. (2017). Title."
    year = f"({paper.publication_year})." if paper.publication_year else "(n.d.)."
    title = paper.title or paper.original_filename

    parts = [part for part in (author_part, year, f"{title}.") if part]
    if paper.venue:
        parts.append(f"{paper.venue}.")
    if paper.doi:
        parts.append(f"https://doi.org/{paper.doi}")
    elif paper.arxiv_id:
        parts.append(f"arXiv:{paper.arxiv_id}")

    return FormattedCitation(
        style=CitationStyle.apa, text=" ".join(parts), missing_fields=_missing(paper)
    )


# -- MLA ------------------------------------------------------------------------------


def to_mla(paper: Paper) -> FormattedCitation:
    authors = _author_names(paper)

    if not authors:
        author_part = ""
    else:
        family, given = _split_name(authors[0])
        first = f"{family}, {given}".rstrip(", ")
        # MLA 9: two authors are both named; three or more use "et al."
        if len(authors) == 1:
            author_part = f"{first}."
        elif len(authors) == 2:
            author_part = f"{first}, and {authors[1]}."
        else:
            author_part = f"{first}, et al."

    title = paper.title or paper.original_filename
    parts = [part for part in (author_part, f'"{title}."') if part]
    if paper.venue:
        parts.append(f"{paper.venue},")
    if paper.publication_year:
        parts.append(f"{paper.publication_year}.")
    if paper.doi:
        parts.append(f"https://doi.org/{paper.doi}.")
    elif paper.arxiv_id:
        parts.append(f"arXiv:{paper.arxiv_id}.")

    return FormattedCitation(
        style=CitationStyle.mla, text=" ".join(parts), missing_fields=_missing(paper)
    )


_FORMATTERS = {
    CitationStyle.bibtex: to_bibtex,
    CitationStyle.apa: to_apa,
    CitationStyle.mla: to_mla,
}


def format_citation(paper: Paper, style: CitationStyle) -> FormattedCitation:
    return _FORMATTERS[style](paper)


def format_all(paper: Paper) -> list[FormattedCitation]:
    """Every style at once — the reader shows them together so the user picks and copies."""
    return [formatter(paper) for formatter in _FORMATTERS.values()]
