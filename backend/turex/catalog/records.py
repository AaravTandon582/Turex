"""Parsing arXiv's OAI-PMH metadata format into records Turex can store.

Kept apart from the HTTP client so the parser can be tested against saved XML without a
network, which matters more here than usual: the failures worth catching are malformed records
in the middle of a good response, and those are impossible to provoke on demand from a live
endpoint.

The `arXiv` metadata format is used rather than the mandatory `oai_dc`. Dublin Core flattens
every author into a single `dc:creator` string and drops the categories, the DOI, and the
journal reference. Those are exactly the fields worth filtering on.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from xml.etree import ElementTree

from turex.core.logging import get_logger

logger = get_logger(__name__)

OAI_NS = "{http://www.openarchives.org/OAI/2.0/}"
ARXIV_NS = "{http://arxiv.org/OAI/arXiv/}"

_VERSION_SUFFIX = re.compile(r"v\d+$")
_WHITESPACE = re.compile(r"\s+")
_DOCTYPE = re.compile(rb"<!DOCTYPE", re.IGNORECASE)


class HarvestError(RuntimeError):
    """The endpoint answered, but not with something that can be harvested."""


@dataclass(frozen=True, slots=True)
class CatalogRecord:
    """One paper, as the source describes it."""

    arxiv_id: str
    title: str
    abstract: str | None = None
    authors: list[dict[str, Any]] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    doi: str | None = None
    journal_ref: str | None = None
    comments: str | None = None
    published_on: date | None = None
    updated_on: date | None = None

    @property
    def primary_category(self) -> str | None:
        return self.categories[0] if self.categories else None


@dataclass(frozen=True, slots=True)
class RecordPage:
    """One response: the records it held and the token for the next one, if any."""

    records: list[CatalogRecord]
    resumption_token: str | None
    complete_size: int | None
    """How many records the whole harvest will yield, when the endpoint chooses to say.

    It is optional in the OAI-PMH spec and arXiv only sends it on some responses, so it drives
    a progress estimate and nothing else. Nothing may depend on it being present.
    """

    skipped: int = 0
    """Records that could not be parsed. Reported rather than silently dropped."""


def _text(node: ElementTree.Element | None) -> str | None:
    """Collapse an element's text to a single clean line, or None if it is empty.

    arXiv wraps abstracts to a fixed width inside the XML, so the raw text arrives full of
    newlines and leading spaces. Stored as-is it renders as ragged nonsense in the UI and
    tokenises with spurious breaks, so it is normalised once here rather than at every use.
    """
    if node is None or node.text is None:
        return None
    collapsed = _WHITESPACE.sub(" ", node.text).strip()
    return collapsed or None


def _parse_date(raw: str | None) -> date | None:
    """arXiv sends ISO dates. A malformed one loses the date, not the record."""
    if not raw:
        return None
    try:
        return date.fromisoformat(raw.strip()[:10])
    except ValueError:
        return None


def normalise_arxiv_id(raw: str) -> str:
    """`oai:arXiv.org:2103.14030v2` and `2103.14030` both become `2103.14030`.

    The version suffix is stripped because the catalog holds one row per paper, not per
    version, and because `arxiv.org/pdf/2103.14030` always resolves to the newest version —
    which is what someone importing a paper wants.
    """
    identifier = raw.strip()
    _, _, identifier = identifier.rpartition(":")
    return _VERSION_SUFFIX.sub("", identifier)


def _parse_authors(metadata: ElementTree.Element) -> list[dict[str, Any]]:
    """`{"name": "Ashish Vaswani"}` per author, in the paper's own order.

    arXiv splits names into `keyname` and `forenames`, and either may be absent — single-word
    names and collaboration names ("ATLAS Collaboration", which is a real and unrelated
    coincidence) have only a keyname. Joining what is present avoids the leading space that
    naive concatenation produces.
    """
    authors: list[dict[str, Any]] = []
    for author in metadata.iterfind(f"{ARXIV_NS}authors/{ARXIV_NS}author"):
        parts = [
            part
            for part in (
                _text(author.find(f"{ARXIV_NS}forenames")),
                _text(author.find(f"{ARXIV_NS}keyname")),
            )
            if part
        ]
        if not parts:
            continue
        entry: dict[str, Any] = {"name": " ".join(parts)}
        if affiliation := _text(author.find(f"{ARXIV_NS}affiliation")):
            entry["affiliation"] = affiliation
        authors.append(entry)
    return authors


def parse_record(record: ElementTree.Element) -> CatalogRecord | None:
    """One `<record>`, or None if it holds nothing worth storing.

    Two cases return None rather than raising. A **deleted** record is a tombstone with a
    header and no metadata — arXiv sends these for withdrawn papers, and they are a normal
    part of the feed, not an error. A record with no id or no title cannot be stored at all,
    since one is the natural key and the other is not nullable.
    """
    header = record.find(f"{OAI_NS}header")
    if header is not None and header.get("status") == "deleted":
        return None

    metadata = record.find(f"{OAI_NS}metadata/{ARXIV_NS}arXiv")
    if metadata is None:
        return None

    identifier = _text(metadata.find(f"{ARXIV_NS}id"))
    title = _text(metadata.find(f"{ARXIV_NS}title"))
    if not identifier or not title:
        return None

    categories = (_text(metadata.find(f"{ARXIV_NS}categories")) or "").split()

    return CatalogRecord(
        arxiv_id=normalise_arxiv_id(identifier)[:64],
        title=title,
        abstract=_text(metadata.find(f"{ARXIV_NS}abstract")),
        authors=_parse_authors(metadata),
        categories=categories,
        doi=(_text(metadata.find(f"{ARXIV_NS}doi")) or None),
        journal_ref=_text(metadata.find(f"{ARXIV_NS}journal-ref")),
        comments=_text(metadata.find(f"{ARXIV_NS}comments")),
        published_on=_parse_date(_text(metadata.find(f"{ARXIV_NS}created"))),
        updated_on=_parse_date(_text(metadata.find(f"{ARXIV_NS}updated"))),
    )


def parse_page(xml: bytes | str) -> RecordPage:
    """A whole OAI-PMH response.

    An `<error>` element raises: `noRecordsMatch` means the query selected nothing and
    `badResumptionToken` means a resumed harvest can no longer continue, and both need to stop
    the run rather than look like an empty page. A record that fails to parse is counted and
    skipped — one malformed entry must not discard the thousand good ones beside it.
    """
    raw = xml.encode("utf-8") if isinstance(xml, str) else xml

    # Refuse a document type declaration outright.
    #
    # `xml.etree` does not resolve external entities, so this is not an XXE risk, but every
    # entity-expansion attack — billion laughs, quadratic blowup — needs a DTD to define the
    # entities it expands, and a response that has already been read into memory can still
    # exhaust it during parsing. OAI-PMH responses never carry a DTD, so rejecting one costs
    # nothing and removes the whole class. Cheaper and clearer than a third dependency.
    if _DOCTYPE.search(raw[:4096]):
        raise HarvestError("the response declared a document type, which OAI-PMH never does")

    try:
        root = ElementTree.fromstring(raw.decode("utf-8"))
    except ElementTree.ParseError as exc:
        raise HarvestError(f"the response was not valid XML: {exc}") from exc

    if (error := root.find(f"{OAI_NS}error")) is not None:
        raise HarvestError(f"{error.get('code', 'error')}: {(error.text or '').strip()}")

    records: list[CatalogRecord] = []
    skipped = 0
    for node in root.iterfind(f"{OAI_NS}ListRecords/{OAI_NS}record"):
        try:
            parsed = parse_record(node)
        except (ValueError, TypeError) as exc:
            skipped += 1
            logger.warning("skipped an unparseable catalog record", extra={"error": str(exc)})
            continue
        if parsed is None:
            skipped += 1
            continue
        records.append(parsed)

    token_node = root.find(f"{OAI_NS}ListRecords/{OAI_NS}resumptionToken")
    token = _text(token_node)

    complete_size: int | None = None
    if token_node is not None and (raw_size := token_node.get("completeListSize")):
        try:
            complete_size = int(raw_size)
        except ValueError:
            complete_size = None

    return RecordPage(
        records=records, resumption_token=token, complete_size=complete_size, skipped=skipped
    )
