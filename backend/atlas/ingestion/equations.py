"""Finding the equations in a paper's extracted text.

PDF text extraction does not mark equations. What arrives is a line of characters that happens
to contain more mathematics than prose, often followed by a number in parentheses. So this is
recognition by evidence rather than by markup, and it is deliberately conservative: a missed
equation costs the reader a list entry, while a false positive puts a line of ordinary prose in
a panel labelled "Equations", which makes the whole feature look broken.

The signals, roughly in order of how much they are worth:

- **Relational operators.** Almost every displayed equation asserts something: `=`, `≤`, `∝`.
- **Mathematical symbols** — Greek letters, operators, arrows, set notation.
- **A low proportion of ordinary words.** A sentence about an equation is mostly words; the
  equation itself is mostly not.
- **An equation number**, `(3)` at the end of the line, which is nearly conclusive on its own.

None is sufficient alone. "Table 3 shows that accuracy = 91%" has an equals sign and a number
and is prose.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from atlas.ingestion.chunking import is_non_content_section
from atlas.ingestion.pdf import ParsedDocument

MIN_LENGTH = 6
MAX_LENGTH = 600
"""Longer than this and it is a paragraph that happens to contain symbols."""

# Characters that essentially only appear in mathematics.
_MATH_SYMBOLS = set(
    "=≈≠≤≥<>±∓×÷·∘⊕⊗√∑∏∫∂∇∞→←↔⇒⇔∈∉⊂⊆∪∩∀∃¬∧∨⊥∥⌊⌋⌈⌉αβγδεζηθικλμνξπρστυφχψωΓΔΘΛΞΠΣΦΨΩˆ˜¯′″"
)
_SUPERSCRIPTS = set("⁰¹²³⁴⁵⁶⁷⁸⁹ⁿ⁺⁻")
_SUBSCRIPTS = set("₀₁₂₃₄₅₆₇₈₉ₙₖᵢⱼ")

_EQUATION_NUMBER = re.compile(r"\(\s*\d+(?:\.\d+)?\s*\)\s*$")
_WORD = re.compile(r"\b[A-Za-z]{4,}\b")
_ANY_WORD = re.compile(r"\b[A-Za-z]{3,}\b")

MAX_PROSE_WORDS = 4
"""Above this the line is a sentence that mentions mathematics, not mathematics.

Measured against real papers: displayed equations carried nought to four such words, while the
prose that kept slipping through — "We used the Adam optimizer with β1 = 0.9", "i.e., 3072 for
the H = 768" — carried five or more."""

# `warmup_steps = 4000.` is a fact about a hyperparameter, not an equation anyone returns to.
_SCALAR_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_ ]{0,24}\s*=\s*[\d.,e+-]+\.?$")

# A citation carrying numbers in brackets reads as symbolic and is not.
_CITATION = re.compile(r"\bet al\.|\b\d{4}[a-z]?\)", re.IGNORECASE)

# A URL is dense in symbols and equals signs and is never an equation. These come from the
# bibliography, which is also why detection skips non-content sections entirely.
_URL_LIKE = re.compile(
    r"https?://|www\.|\.(?:org|com|net|edu)\b|forum\?id=|doi\.org", re.IGNORECASE
)

# A line beginning with an English function word is the tail of a sentence that wrapped, not a
# displayed equation: "of 1/√dk", "is (L=64, H=512, A=2) with 235M parameters".
_LEADING_PROSE = re.compile(
    r"^(?:the|a|an|and|or|of|is|are|was|were|be|been|to|for|with|by|as|at|in|on|from|that|"
    r"this|these|those|we|it|its|where|which|when|then|thus|so|if|but)\b",
    re.IGNORECASE,
)

# Lines that look mathematical but are furniture rather than equations.
_NOT_AN_EQUATION = re.compile(
    r"^\s*(?:table|figure|fig\.|eq\.|equation|algorithm|section|appendix|theorem|lemma)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class DetectedEquation:
    content: str
    page_number: int
    label: str | None
    """The equation number, when the paper gave it one — what a reader cites."""


def _symbol_ratio(text: str) -> float:
    stripped = [character for character in text if not character.isspace()]
    if not stripped:
        return 0.0
    mathematical = sum(
        1
        for character in stripped
        if character in _MATH_SYMBOLS or character in _SUPERSCRIPTS or character in _SUBSCRIPTS
    )
    return mathematical / len(stripped)


def _word_ratio(text: str) -> float:
    """How much of this is ordinary prose, by character count."""
    stripped = "".join(character for character in text if not character.isspace())
    if not stripped:
        return 1.0
    return sum(len(word) for word in _WORD.findall(text)) / len(stripped)


def looks_like_an_equation(line: str) -> bool:
    """Whether a single line is mathematics rather than prose."""
    text = line.strip()
    if not (MIN_LENGTH <= len(text) <= MAX_LENGTH):
        return False
    if _NOT_AN_EQUATION.match(text):
        return False
    if len(_ANY_WORD.findall(text)) > MAX_PROSE_WORDS:
        return False
    if _SCALAR_ASSIGNMENT.match(text) or _CITATION.search(text) or _URL_LIKE.search(text):
        return False
    if _LEADING_PROSE.match(text):
        return False

    numbered = bool(_EQUATION_NUMBER.search(text))
    symbols = _symbol_ratio(text)
    words = _word_ratio(text)
    has_relation = any(operator in text for operator in "=≈≠≤≥∝")

    # A numbered line still has to look mathematical; "(3)" alone proves nothing.
    if numbered and (has_relation or symbols > 0.04) and words < 0.72:
        return True

    # Unnumbered: demand a relation and either real symbol density or very little prose.
    if has_relation and words < 0.45 and (symbols > 0.05 or words < 0.28):
        return True

    # Dense symbols with almost no words — a bare expression on its own line.
    return symbols > 0.16 and words < 0.32


def detect_equations(document: ParsedDocument, *, limit: int = 60) -> list[DetectedEquation]:
    """Pull the equations out of a paper.

    Only content sections are scanned. A bibliography is full of URLs and identifiers that are
    dense in symbols and equals signs, and every one of them would be a false positive — the
    same reason chunking skips those sections.

    Capped because a maths-heavy paper can carry hundreds, and a list that long is a wall
    rather than a reference.
    """
    pages: list[tuple[int, str]] = []
    for section in document.sections:
        if is_non_content_section(section.title):
            continue
        pages.extend(section.blocks)

    if not pages:
        # No sections were detected, so fall back to the raw pages rather than finding nothing.
        pages = [(page.number, page.text) for page in document.pages]

    found: list[DetectedEquation] = []
    seen: set[str] = set()

    for page_number, text in pages:
        for raw in text.splitlines():
            line = " ".join(raw.split())
            if not looks_like_an_equation(line):
                continue

            key = line.casefold()
            if key in seen:
                # Running heads and repeated definitions; the first occurrence is the one to
                # point at.
                continue
            seen.add(key)

            match = _EQUATION_NUMBER.search(line)
            label = match.group(0).strip().strip("()").strip() if match else None
            content = _EQUATION_NUMBER.sub("", line).strip() if match else line

            found.append(DetectedEquation(content=content, page_number=page_number, label=label))
            if len(found) >= limit:
                return found

    return found
