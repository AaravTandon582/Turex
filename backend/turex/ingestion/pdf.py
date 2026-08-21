"""Reading a PDF into the structure Turex stores.

Produces three things: cleaned text per page, a section outline, and bibliographic metadata.

Structure detection is heuristic, and deliberately conservative. A wrong section boundary
degrades a citation locator; a missed one only means a chunk is attributed to the enclosing
section. When a heading is ambiguous, it is not a heading.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from turex.core.errors import ProcessingFailedError
from turex.core.logging import get_logger
from turex.ingestion.text import clean_page, normalise_characters, strip_page_furniture

logger = get_logger(__name__)

MAX_PAGES = 2000
"""A guard against decompression-bomb PDFs, not a product limit — real papers are far under."""


@dataclass(slots=True)
class ParsedPage:
    number: int
    """1-based, matching what the reader displays and what a citation says."""
    text: str


@dataclass(slots=True)
class ParsedSection:
    ordinal: int
    title: str
    level: int
    page_start: int
    page_end: int
    blocks: list[tuple[int, str]]
    """(page number, text) pairs, kept separate rather than concatenated.

    Chunking needs to know which page each passage came from, and that information is
    unrecoverable once the pages are joined into one string."""

    @property
    def text(self) -> str:
        return "\n".join(text for _, text in self.blocks).strip()


@dataclass(slots=True)
class DocumentMetadata:
    title: str | None = None
    authors: list[str] = field(default_factory=list)
    abstract: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    publication_year: int | None = None


@dataclass(slots=True)
class ParsedDocument:
    page_count: int
    pages: list[ParsedPage]
    sections: list[ParsedSection]
    metadata: DocumentMetadata

    @property
    def full_text(self) -> str:
        return "\n\n".join(page.text for page in self.pages)


# --------------------------------------------------------------------------------------
# Section detection
# --------------------------------------------------------------------------------------

# "3 Results", "3.2. Ablation study" — numbered headings, the strongest signal available.
_NUMBERED_HEADING = re.compile(r"^(?P<number>\d{1,2}(?:\.\d{1,2}){0,3})\.?\s+(?P<title>\S.{0,90})$")

# Headings that appear unnumbered in most templates.
_CANONICAL_HEADINGS = frozenset(
    {
        "abstract",
        "introduction",
        "background",
        "related work",
        "prior work",
        "method",
        "methods",
        "methodology",
        "materials and methods",
        "approach",
        "model",
        "experiments",
        "experimental setup",
        "evaluation",
        "results",
        "results and discussion",
        "analysis",
        "ablation study",
        "discussion",
        "limitations",
        "future work",
        "conclusion",
        "conclusions",
        "acknowledgements",
        "acknowledgments",
        "references",
        "bibliography",
        "appendix",
        "supplementary material",
    }
)

_TRAILING_PUNCTUATION = re.compile(r"[.:;,]+$")


def _heading_at(line: str) -> tuple[str, int] | None:
    """Classify a line as a heading, returning its title and depth.

    Rejects anything sentence-shaped. The reliable discriminator is length plus the absence of
    terminal punctuation — headings are short noun phrases that do not end in a full stop.
    """
    stripped = line.strip()
    if not (2 <= len(stripped) <= 100):
        return None
    if stripped.endswith((".", "?", "!")) and not _NUMBERED_HEADING.match(stripped):
        return None

    normalised = _TRAILING_PUNCTUATION.sub("", stripped).strip().lower()

    if normalised in _CANONICAL_HEADINGS:
        return _TRAILING_PUNCTUATION.sub("", stripped).strip(), 1

    match = _NUMBERED_HEADING.match(stripped)
    if match:
        title = _TRAILING_PUNCTUATION.sub("", match.group("title")).strip()
        # "1 introduction" is a heading; "2 of the 5 datasets" is a sentence fragment.
        if title and title[0].isupper() and len(title.split()) <= 12:
            depth = match.group("number").count(".") + 1
            return f"{match.group('number')} {title}", depth

    # All-caps short lines: common in older two-column templates. Requires real words —
    # without that, a fragment of a rendered equation such as ")V (1)" reads as all-caps and
    # becomes a spurious section boundary.
    if stripped.isupper() and 3 <= len(stripped) <= 60 and _has_word_content(stripped):
        return stripped.title(), 1

    return None


_WORD_RUN = re.compile(r"[A-Za-z]{3,}")


def _has_word_content(line: str) -> bool:
    """True when the line contains actual words rather than symbols and stray letters."""
    words = _WORD_RUN.findall(line)
    if not words:
        return False
    letters = sum(1 for character in line if character.isalpha())
    return letters >= len(line) * 0.6


def detect_sections(pages: list[ParsedPage]) -> list[ParsedSection]:
    """Split the document at detected headings.

    Text before the first heading — title block, authors, abstract — becomes a leading
    "Front matter" section so no content is orphaned.
    """
    boundaries: list[tuple[int, int, str, int]] = []  # (page, line index, title, level)
    for page in pages:
        for index, line in enumerate(page.text.splitlines()):
            heading = _heading_at(line)
            if heading:
                boundaries.append((page.number, index, heading[0], heading[1]))

    if not boundaries:
        return []

    sections: list[ParsedSection] = []
    text_by_page = {page.number: page.text.splitlines() for page in pages}
    page_numbers = [page.number for page in pages]

    def slice_blocks(start: tuple[int, int], end: tuple[int, int] | None) -> list[tuple[int, str]]:
        """Collect the lines between two (page, line) positions, grouped by page."""
        collected: list[tuple[int, str]] = []
        for number in page_numbers:
            if number < start[0]:
                continue
            if end is not None and number > end[0]:
                break
            lines = text_by_page[number]
            begin = start[1] if number == start[0] else 0
            finish = end[1] if end is not None and number == end[0] else len(lines)
            body = "\n".join(lines[begin:finish]).strip()
            if body:
                collected.append((number, body))
        return collected

    ordinal = 0
    first = boundaries[0]
    front_matter = slice_blocks((page_numbers[0], 0), (first[0], first[1]))
    if front_matter:
        sections.append(
            ParsedSection(
                ordinal=ordinal,
                title="Front matter",
                level=1,
                page_start=page_numbers[0],
                page_end=first[0],
                blocks=front_matter,
            )
        )
        ordinal += 1

    for index, (page_number, line_index, title, level) in enumerate(boundaries):
        following = boundaries[index + 1] if index + 1 < len(boundaries) else None
        body = slice_blocks(
            (page_number, line_index),
            (following[0], following[1]) if following else None,
        )
        if not body:
            continue
        sections.append(
            ParsedSection(
                ordinal=ordinal,
                title=title,
                level=level,
                page_start=page_number,
                page_end=following[0] if following else page_numbers[-1],
                blocks=body,
            )
        )
        ordinal += 1

    return sections


# --------------------------------------------------------------------------------------
# Metadata extraction
# --------------------------------------------------------------------------------------

_DOI = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+\b")
_ARXIV = re.compile(r"arXiv[:\s]\s*(\d{4}\.\d{4,5})(v\d+)?", re.I)
_YEAR = re.compile(r"\b(19[5-9]\d|20[0-4]\d)\b")
# The abstract runs from the "Abstract" heading to whatever heading follows it.
_ABSTRACT = re.compile(
    r"\babstract\b[\s:—-]*(?P<body>.+?)"
    r"(?=\n\s*(?:\d+\.?\s+)?(?:introduction|keywords|index terms)\b|\Z)",
    re.I | re.S,
)
_AUTHOR_SEPARATORS = re.compile(r",| and |&|;")
_EMAIL = re.compile(r"\S+@\S+")
_SUPERSCRIPT_MARKERS = re.compile(r"[\d*†‡§¶∗⋆★☆◦•⁎]+")

_PLACEHOLDER_TITLES = frozenset({"untitled", "document", "paper", "manuscript", "pdf", "draft"})
_PRODUCER_ARTEFACT_PREFIXES = ("microsoft word", "untitled", "doc1", "layout ")

# Licence notices, preprint stamps, and venue banners printed above the real title.
_BOILERPLATE_LINE = re.compile(
    r"(copyright|\u00a9|all rights reserved|hereby grants?|grants? permission|"
    r"permission is (hereby )?granted|licen[cs]e|"
    r"preprint|under review|submitted to|to appear in|accepted (at|to)|"
    r"proceedings of|\d+(st|nd|rd|th) (international )?(conference|workshop)|arxiv:)",
    re.I,
)

# Words that mark a line as an organisation rather than a person. "Google Brain" and
# "Google Research" are otherwise indistinguishable from a two-word personal name.
_ORGANISATION_WORDS = frozenset(
    {
        "university",
        "universite",
        "universidad",
        "universitat",
        "college",
        "school",
        "institute",
        "institut",
        "academy",
        "department",
        "faculty",
        "laboratory",
        "laboratories",
        "labs",
        "lab",
        "research",
        "brain",
        "center",
        "centre",
        "group",
        "division",
        "corporation",
        "technologies",
        "systems",
        "foundation",
        "hospital",
        "consortium",
        "council",
        "agency",
        "ltd",
        "inc",
        "llc",
        "gmbh",
        # Industrial labs, which are otherwise shaped exactly like two-word personal names.
        "google",
        "microsoft",
        "meta",
        "openai",
        "deepmind",
        "anthropic",
        "amazon",
        "apple",
        "ibm",
        "nvidia",
        "adobe",
        "salesforce",
        "huawei",
        "baidu",
        "tencent",
    }
)

# A title that ends on one of these is grammatically incomplete and continues on the next
# line. This is the most reliable signal for where a wrapped title actually ends — far more
# so than line length, which truncates long titles and merges short ones with the byline.
_DANGLING_WORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "of",
        "for",
        "and",
        "or",
        "in",
        "on",
        "to",
        "with",
        "from",
        "via",
        "by",
        "at",
        "as",
        "into",
        "through",
        "under",
        "over",
        "between",
        "across",
        "using",
        "towards",
        "toward",
        "without",
        "against",
        "beyond",
        "is",
        "are",
    }
)

# Lowercase particles that belong to the surname that follows them.
_NAME_PARTICLES = frozenset(
    {"van", "von", "de", "der", "den", "del", "della", "di", "da", "du", "la", "le", "bin", "al"}
)
_INITIAL = re.compile(r"^[A-Z]\.?$")

_ABSTRACT_OR_SECTION = re.compile(
    r"^\s*(abstract|keywords|index terms|1\.?\s+introduction)\b", re.I
)


def _looks_like_a_real_title(value: str) -> bool:
    """Reject the junk that PDF producers leave in the /Title field.

    Word and LaTeX toolchains routinely write the source filename, a template name, or a
    UUID, and displaying that as a paper's title is worse than displaying nothing.

    Placeholders are matched as whole titles or known prefixes rather than as substrings:
    a real title may legitimately contain the word "paper".
    """
    candidate = value.strip()
    if not (10 <= len(candidate) <= 300):
        return False
    lowered = candidate.lower()
    if lowered in _PLACEHOLDER_TITLES:
        return False
    if lowered.startswith(_PRODUCER_ARTEFACT_PREFIXES):
        return False
    if lowered.endswith((".pdf", ".doc", ".docx", ".tex", ".dvi")):
        return False
    return len(candidate.split()) >= 2


def _is_organisation(line: str) -> bool:
    words = {word.strip(".,()").lower() for word in line.split()}
    return bool(words & _ORGANISATION_WORDS)


def _looks_like_a_person(line: str) -> bool:
    """Two to four capitalised words, no organisation words, no email."""
    cleaned = _SUPERSCRIPT_MARKERS.sub("", line).strip(" ,.")
    if not cleaned or _EMAIL.search(cleaned) or _is_organisation(cleaned):
        return False
    words = cleaned.split()
    if not words or len(cleaned) > 60:
        return False
    if not all(word[0].isupper() or word.lower() in _NAME_PARTICLES for word in words):
        return False
    substantive = [
        word for word in words if not _INITIAL.match(word) and word.lower() not in _NAME_PARTICLES
    ]
    return 2 <= len(substantive) <= 3


_MAX_BOILERPLATE_RUN = 6


def _split_name_run(line: str) -> list[str]:
    """Split space-separated names into individual people.

    A new name begins once the current one holds two substantive tokens; initials and
    particles ("N.", "van") attach to the name in progress rather than starting a new one.
    Bails out entirely unless every token looks like part of a name, so a title fragment is
    never mistaken for a byline.
    """
    tokens = line.split()
    if not (4 <= len(tokens) <= 24) or _is_organisation(line):
        return []

    for token in tokens:
        if not (token[0].isupper() or token.lower() in _NAME_PARTICLES):
            return []

    groups: list[list[str]] = []
    current: list[str] = []
    substantive = 0

    for token in tokens:
        is_modifier = bool(_INITIAL.match(token)) or token.lower() in _NAME_PARTICLES
        if not is_modifier and substantive >= 2:
            groups.append(current)
            current, substantive = [], 0
        current.append(token)
        if not is_modifier:
            substantive += 1

    if current:
        groups.append(current)

    names = [" ".join(group) for group in groups if len(group) >= 2]
    return names if len(names) >= 2 else []


def _front_matter(text: str) -> list[str]:
    """Page-one lines with licence and preprint banners removed.

    Banners are skipped as *blocks*, not as individual lines. A licence notice wraps across
    several lines and only the first carries a recognisable keyword, so dropping just that
    line leaves its continuation behind — which then reads as the paper's title.
    """
    lines: list[str] = []
    skipping = 0

    for raw in text.splitlines()[:40]:
        stripped = raw.strip()
        if not stripped:
            continue

        if skipping:
            skipping -= 1
            # The banner ends at the line that completes its sentence.
            if stripped.endswith((".", "!", "?")):
                skipping = 0
            continue

        if _BOILERPLATE_LINE.search(stripped):
            skipping = 0 if stripped.endswith((".", "!", "?")) else _MAX_BOILERPLATE_RUN
            continue

        lines.append(stripped)

    return lines


def _title_from_first_page(text: str) -> str | None:
    """Take the title from the top of page one.

    Accumulates lines while the title is still plausibly incomplete, stopping at the first
    line that reads as a person's name — which is where the author block begins. This handles
    titles that wrap across two lines without swallowing the first author.
    """
    lines = _front_matter(text)
    if not lines:
        return None

    collected: list[str] = []
    for line in lines[:6]:
        if _EMAIL.search(line) or _ABSTRACT_OR_SECTION.match(line):
            break
        if collected and not (_continues_a_title(" ".join(collected)) or line[:1].islower()):
            break
        collected.append(line)
        if len(" ".join(collected)) > 250:
            break

    title = " ".join(collected).strip()
    return title if _looks_like_a_real_title(title) else None


def _continues_a_title(accumulated: str) -> bool:
    """Does the title so far obviously run on to the next line?

    True when it ends mid-phrase — a dangling preposition, a hyphen, or a colon — or when it
    is too short to be a title at all. Otherwise the next line begins the byline.
    """
    stripped = accumulated.rstrip()
    if stripped.endswith(("-", ":", ",")):
        return True
    if len(stripped) < 20:
        return True
    last = stripped.split()[-1].strip(",.").lower() if stripped.split() else ""
    return last in _DANGLING_WORDS


def _authors_from_first_page(text: str, title: str | None) -> list[str]:
    """Read the author block: the names between the title and the abstract.

    Deliberately conservative. A wrong author list is worse than an empty one, because a
    citation generated from it would be wrong — so anything that does not read as a person's
    name is dropped.
    """
    lines = _front_matter(text)

    start = 0
    if title:
        # Skip past however many lines the title occupied.
        remaining = title
        while start < len(lines) and remaining:
            head = lines[start]
            if remaining.startswith(head[: min(len(head), 20)]):
                remaining = remaining[len(head) :].strip()
                start += 1
            else:
                break

    authors: list[str] = []
    for line in lines[start : start + 25]:
        if _ABSTRACT_OR_SECTION.match(line):
            break
        # An inline list ("A. Smith, B. Jones and C. Lee") splits into several names; a
        # stacked layout yields one name per line. Both go through the same filter.
        for part in _AUTHOR_SEPARATORS.split(line):
            candidate = _SUPERSCRIPT_MARKERS.sub("", part).strip(" ,.")
            if not candidate:
                continue
            if _looks_like_a_person(candidate):
                authors.append(candidate)
            else:
                # Many templates print the byline with no separators at all:
                # "Kaiming He Xiangyu Zhang Shaoqing Ren Jian Sun".
                authors.extend(_split_name_run(candidate))

    # Deduplicate while preserving the printed order, which is meaningful.
    return list(dict.fromkeys(authors))[:20]


def extract_metadata(reader: PdfReader, pages: list[ParsedPage]) -> DocumentMetadata:
    metadata = DocumentMetadata()
    first_page = pages[0].text if pages else ""
    # Identifiers can appear anywhere, but searching the whole document is wasteful and picks
    # up references. The opening pages carry the paper's own identifiers.
    front = "\n".join(page.text for page in pages[:3])

    embedded = reader.metadata
    if embedded:
        raw_title = embedded.get("/Title")
        if isinstance(raw_title, str) and _looks_like_a_real_title(raw_title):
            metadata.title = normalise_characters(raw_title).strip()

        raw_author = embedded.get("/Author")
        if isinstance(raw_author, str) and raw_author.strip():
            metadata.authors = [
                name.strip()
                for name in _AUTHOR_SEPARATORS.split(normalise_characters(raw_author))
                if 2 < len(name.strip()) < 80
            ][:20]

        metadata.publication_year = _year_from_pdf_date(embedded.get("/CreationDate"))

    if not metadata.title:
        metadata.title = _title_from_first_page(first_page)
    if not metadata.authors:
        metadata.authors = _authors_from_first_page(first_page, metadata.title)

    doi = _DOI.search(front)
    if doi:
        metadata.doi = doi.group(0).rstrip(".,;)")

    arxiv = _ARXIV.search(front)
    if arxiv:
        metadata.arxiv_id = arxiv.group(1)

    abstract = _ABSTRACT.search(first_page)
    if abstract:
        body = " ".join(abstract.group("body").split())
        if 80 <= len(body) <= 4000:
            metadata.abstract = body

    # An arXiv identifier encodes YYMM of first submission, which is the paper's date. It
    # outranks the PDF's creation date, because a preprint regenerated years later carries
    # the regeneration date in its metadata — that is how "Attention Is All You Need" ends up
    # claiming to be from 2024.
    if metadata.arxiv_id:
        year_from_identifier = _year_from_arxiv_id(metadata.arxiv_id)
        if year_from_identifier is not None:
            metadata.publication_year = year_from_identifier

    if metadata.publication_year is None:
        years = [int(year) for year in _YEAR.findall(front[:3000])]
        if years:
            # The most recent plausible year on the front pages is the publication year;
            # earlier ones are citations.
            metadata.publication_year = max(years)

    return metadata


def _year_from_arxiv_id(identifier: str) -> int | None:
    """`1706.03762` → 2017. The scheme has used YYMM prefixes since April 2007."""
    prefix = identifier.split(".")[0]
    if len(prefix) != 4 or not prefix.isdigit():
        return None
    year = 2000 + int(prefix[:2])
    return year if 2007 <= year <= datetime.now().year + 1 else None


def _year_from_pdf_date(value: object) -> int | None:
    """Parse the PDF date format, `D:YYYYMMDDHHmmSS`, tolerating its many variations."""
    if not isinstance(value, str):
        return None
    match = re.search(r"(19|20)\d{2}", value)
    if not match:
        return None
    year = int(match.group(0))
    return year if 1950 <= year <= datetime.now().year + 1 else None


# --------------------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------------------


def parse_pdf(path: str) -> ParsedDocument:
    """Read a PDF from disk into pages, sections, and metadata.

    Raises `ProcessingFailedError` with a message safe to show the user. Whatever the
    underlying library complains about goes to the logs.
    """
    try:
        reader = PdfReader(path)
    except (PdfReadError, OSError, ValueError) as exc:
        raise ProcessingFailedError(
            "Turex couldn't open that PDF. It may be corrupted.",
            detail=f"PdfReader failed: {exc}",
        ) from exc

    if reader.is_encrypted:
        # An empty user password is common for print-restricted files and decrypts cleanly.
        try:
            if reader.decrypt("") == 0:
                raise ProcessingFailedError(
                    "That PDF is password protected. Remove the password and upload it again.",
                    detail="PDF requires a password",
                )
        except (NotImplementedError, PdfReadError) as exc:
            raise ProcessingFailedError(
                "That PDF uses an encryption Turex can't read.",
                detail=f"decrypt failed: {exc}",
            ) from exc

    total_pages = len(reader.pages)
    if total_pages == 0:
        raise ProcessingFailedError("That PDF has no pages.", detail="zero-page PDF")
    if total_pages > MAX_PAGES:
        raise ProcessingFailedError(
            f"That PDF has {total_pages} pages, which is more than Turex can process.",
            detail=f"page count {total_pages} exceeds MAX_PAGES",
        )

    raw_pages: list[str] = []
    for index, page in enumerate(reader.pages):
        try:
            raw_pages.append(page.extract_text() or "")
        except Exception as exc:
            # One unreadable page should not fail an otherwise good document.
            logger.warning("skipped unreadable page", extra={"page": index + 1, "reason": str(exc)})
            raw_pages.append("")

    stripped = strip_page_furniture(raw_pages)
    pages = [
        ParsedPage(number=index + 1, text=clean_page(text)) for index, text in enumerate(stripped)
    ]

    if not any(page.text.strip() for page in pages):
        raise ProcessingFailedError(
            "Turex couldn't find any text in that PDF. Scanned documents need OCR first.",
            detail="no extractable text; likely a scanned image PDF",
        )

    populated = [page for page in pages if page.text.strip()]
    return ParsedDocument(
        page_count=total_pages,
        pages=populated,
        sections=detect_sections(populated),
        metadata=extract_metadata(reader, populated),
    )
