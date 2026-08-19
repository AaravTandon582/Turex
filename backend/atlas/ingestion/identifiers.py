"""Recognising what someone pasted, and turning it into something fetchable.

People add a paper by pasting whatever they have: an arXiv URL, a bare arXiv id, a DOI, a
`doi.org` link, or a direct PDF link. Asking them to say which is which is a form asking the
user to do the computer's job, so this works it out.

Only arXiv resolves to a PDF without a publisher lookup. A DOI is resolved through `doi.org`,
which redirects to the publisher — and most publishers serve a landing page rather than a PDF,
so that path succeeds only when the publisher happens to serve the file directly. Saying that
plainly in the failure message is better than implying Atlas can reach any paywalled paper.
"""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass
from urllib.parse import urlparse


class IdentifierKind(enum.StrEnum):
    arxiv = "arxiv"
    doi = "doi"
    url = "url"


@dataclass(frozen=True, slots=True)
class ResolvedIdentifier:
    kind: IdentifierKind
    value: str
    """The normalised identifier — a bare arXiv id, a bare DOI, or the URL itself."""

    pdf_url: str
    """Where to fetch the document from."""


# 2402.01234, with an optional version suffix. Also the pre-2007 form, cs/0112017.
_ARXIV_MODERN = re.compile(r"\b(\d{4}\.\d{4,5})(v\d+)?\b")
_ARXIV_LEGACY = re.compile(r"\b([a-z-]+(?:\.[A-Z]{2})?/\d{7})(v\d+)?\b")

# A DOI is "10." then a registrant, a slash, and a suffix that permits almost anything. The
# trailing character class excludes punctuation that is nearly always sentence-final rather
# than part of the identifier.
_DOI = re.compile(r"\b(10\.\d{4,9}/[^\s\"'<>]*[^\s\"'<>.,;:)\]])", re.IGNORECASE)


def parse_identifier(raw: str) -> ResolvedIdentifier:
    """Work out what this is. Raises `ValueError` if it is not anything recognisable."""
    text = raw.strip()
    if not text:
        raise ValueError("nothing to resolve")

    # An explicit arXiv link, in any of its shapes.
    if "arxiv.org" in text.lower():
        for pattern in (_ARXIV_MODERN, _ARXIV_LEGACY):
            match = pattern.search(text)
            if match:
                return _arxiv(match.group(1))

    # doi.org links carry the DOI in the path.
    parsed = urlparse(text if "//" in text else f"https://{text}")
    if parsed.hostname and parsed.hostname.lower().endswith("doi.org"):
        match = _DOI.search(parsed.path.lstrip("/"))
        if match:
            return _doi(match.group(1))

    if text.lower().startswith(("http://", "https://")):
        return ResolvedIdentifier(kind=IdentifierKind.url, value=text, pdf_url=text)

    # A bare identifier, pasted on its own.
    if text.lower().startswith("arxiv:"):
        return _arxiv(text.split(":", 1)[1])
    if text.lower().startswith("doi:"):
        return _doi(text.split(":", 1)[1])

    match = _DOI.search(text)
    if match and text.startswith("10."):
        return _doi(match.group(1))

    for pattern in (_ARXIV_MODERN, _ARXIV_LEGACY):
        match = pattern.fullmatch(text) or pattern.match(text)
        if match and match.start() == 0:
            return _arxiv(match.group(1))

    raise ValueError(f"not a recognisable link, DOI, or arXiv id: {text[:80]!r}")


def _arxiv(identifier: str) -> ResolvedIdentifier:
    # Version stripped deliberately: arXiv serves the latest version at the unversioned URL,
    # and two people pasting v1 and v3 of the same paper mean the same paper.
    bare = re.sub(r"v\d+$", "", identifier.strip())
    return ResolvedIdentifier(
        kind=IdentifierKind.arxiv, value=bare, pdf_url=f"https://arxiv.org/pdf/{bare}"
    )


def _doi(identifier: str) -> ResolvedIdentifier:
    bare = identifier.strip().rstrip(".")
    return ResolvedIdentifier(
        kind=IdentifierKind.doi, value=bare, pdf_url=f"https://doi.org/{bare}"
    )
