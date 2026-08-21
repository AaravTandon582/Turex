"""Splitting a parsed document into retrievable passages.

Three properties matter, in this order:

1. **Every chunk knows where it came from.** Page and section travel with the text, because a
   citation Turex cannot resolve to a location is not a citation.
2. **Chunks do not span sections.** A passage that straddles Methods and Results reads as
   incoherent when retrieved alone, and cannot be honestly attributed to either.
3. **Splits fall on natural boundaries.** Paragraph first, then sentence, then — only for
   pathological input like an unbroken table dump — a hard character cut.

Consecutive chunks overlap by a sentence or two so a claim spanning a boundary is still
retrievable in full from at least one of them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from turex.ingestion.pdf import ParsedDocument, ParsedSection
from turex.ingestion.text import estimate_tokens, unwrap_lines

TARGET_CHARACTERS = 1600
"""Roughly 400 tokens. Large enough to hold a complete argument, small enough that a
retrieved passage is mostly relevant rather than mostly context."""

MAX_CHARACTERS = 2400
OVERLAP_CHARACTERS = 220
MIN_CHARACTERS = 120
"""Below this a chunk is a stray heading or caption fragment — noise in the index."""

_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")

# Sections that are lists of other works rather than claims of this one. They match strongly
# on vocabulary — a bibliography contains every term the paper does — while containing nothing
# assertable, so retrieving one as evidence is always a miss. Skipping them also removes a
# large share of a paper's chunks, and with them the cost of embedding text nobody can cite.
_NON_CONTENT_SECTIONS = re.compile(
    r"^\s*(\d+(\.\d+)*\.?\s+)?(references|bibliography|works cited|acknowledge?ments?)\b",
    re.I,
)


def is_non_content_section(title: str) -> bool:
    return bool(_NON_CONTENT_SECTIONS.match(title))


# Split after sentence punctuation followed by whitespace and a capital or digit. The
# lookbehind excludes common abbreviations that would otherwise split mid-sentence.
_SENTENCE_BREAK = re.compile(
    r"(?<![A-Z])(?<!\bet al)(?<!\bFig)(?<!\bEq)(?<!\bcf)(?<!\bvs)(?<!\bi\.e)(?<!\be\.g)"
    r"(?<=[.!?])\s+(?=[A-Z0-9])"
)


@dataclass(slots=True)
class Chunk:
    ordinal: int
    content: str
    token_estimate: int
    page_start: int
    page_end: int
    section_ordinal: int | None


@dataclass(slots=True)
class _Fragment:
    """A paragraph, tagged with the page it was printed on."""

    text: str
    page: int


def _split_paragraphs(section: ParsedSection) -> list[_Fragment]:
    fragments: list[_Fragment] = []
    for page, text in section.blocks:
        for paragraph in _PARAGRAPH_BREAK.split(text):
            # Unwrap here: pages keep their line structure so headings stay detectable,
            # but a chunk should read as prose rather than as a column of fragments.
            cleaned = unwrap_lines(paragraph).strip()
            if cleaned:
                fragments.append(_Fragment(text=cleaned, page=page))
    return fragments


def _split_sentences(text: str) -> list[str]:
    return [part.strip() for part in _SENTENCE_BREAK.split(text) if part.strip()]


def _split_oversized(fragment: _Fragment) -> list[_Fragment]:
    """Break a paragraph longer than MAX_CHARACTERS at sentence boundaries."""
    if len(fragment.text) <= MAX_CHARACTERS:
        return [fragment]

    pieces: list[_Fragment] = []
    buffer = ""
    for sentence in _split_sentences(fragment.text):
        if buffer and len(buffer) + len(sentence) + 1 > TARGET_CHARACTERS:
            pieces.append(_Fragment(text=buffer, page=fragment.page))
            buffer = sentence
        elif len(sentence) > MAX_CHARACTERS:
            # A single "sentence" this long is a table, a formula dump, or a parse failure.
            # Cut it into fixed windows rather than emit something unusable.
            if buffer:
                pieces.append(_Fragment(text=buffer, page=fragment.page))
                buffer = ""
            for start in range(0, len(sentence), TARGET_CHARACTERS):
                pieces.append(
                    _Fragment(text=sentence[start : start + TARGET_CHARACTERS], page=fragment.page)
                )
        else:
            buffer = f"{buffer} {sentence}".strip()

    if buffer:
        pieces.append(_Fragment(text=buffer, page=fragment.page))
    return pieces


def _trailing_overlap(text: str) -> str:
    """The last sentence or two of a chunk, to prefix the next one."""
    sentences = _split_sentences(text)
    overlap = ""
    for sentence in reversed(sentences):
        candidate = f"{sentence} {overlap}".strip()
        if len(candidate) > OVERLAP_CHARACTERS:
            break
        overlap = candidate
    return overlap


def chunk_section(
    section: ParsedSection | None,
    fragments: list[_Fragment],
    *,
    start_ordinal: int,
) -> list[Chunk]:
    chunks: list[Chunk] = []
    ordinal = start_ordinal

    buffer: list[_Fragment] = []
    buffer_length = 0
    carried_overlap = ""

    def flush() -> None:
        nonlocal buffer, buffer_length, ordinal, carried_overlap
        if not buffer:
            return
        body = "\n\n".join(fragment.text for fragment in buffer)
        content = f"{carried_overlap}\n\n{body}".strip() if carried_overlap else body

        if len(content) >= MIN_CHARACTERS:
            chunks.append(
                Chunk(
                    ordinal=ordinal,
                    content=content,
                    token_estimate=estimate_tokens(content),
                    page_start=min(fragment.page for fragment in buffer),
                    page_end=max(fragment.page for fragment in buffer),
                    section_ordinal=section.ordinal if section else None,
                )
            )
            ordinal += 1
            carried_overlap = _trailing_overlap(body)

        buffer = []
        buffer_length = 0

    for fragment in fragments:
        for piece in _split_oversized(fragment):
            if buffer and buffer_length + len(piece.text) > TARGET_CHARACTERS:
                flush()
            buffer.append(piece)
            buffer_length += len(piece.text)

    flush()
    return chunks


def chunk_document(document: ParsedDocument) -> list[Chunk]:
    """Produce the ordered chunk list for a parsed document.

    Falls back to chunking pages directly when no sections were detected — some papers,
    posters, and preprints genuinely have no headings, and they must still be searchable.
    """
    chunks: list[Chunk] = []

    if document.sections:
        for section in document.sections:
            if is_non_content_section(section.title):
                continue
            fragments = _split_paragraphs(section)
            if fragments:
                chunks.extend(chunk_section(section, fragments, start_ordinal=len(chunks)))
        if chunks:
            return chunks

    fragments = [
        fragment
        for page in document.pages
        for paragraph in _PARAGRAPH_BREAK.split(page.text)
        if (fragment := _Fragment(text=unwrap_lines(paragraph).strip(), page=page.number)).text
    ]
    return chunk_section(None, fragments, start_ordinal=0)
