"""Request and response models for the catalog."""

from __future__ import annotations

import uuid
from datetime import date

from pydantic import Field

from atlas.schemas.base import AtlasModel


class CatalogPaperRead(AtlasModel):
    """A paper Atlas knows about but has not necessarily read.

    `in_library` is what separates this from a search result on a website: it says whether
    *this* reader already has the paper, so the Discover page can offer "Open" instead of
    "Import" and never create a duplicate they then have to clean up.
    """

    id: uuid.UUID
    source: str
    external_id: str
    """This paper's id within its source — an arXiv id, or an OpenAlex work id."""
    doi: str | None = None
    title: str
    abstract: str | None = None
    authors: list[dict[str, str]] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    primary_category: str | None = None
    journal_ref: str | None = None
    comments: str | None = None
    published_on: date | None = None
    updated_on: date | None = None
    landing_url: str | None = None
    """Where a human should open it: an arXiv abstract page, or a DOI resolver."""

    pdf_url: str | None = None
    """Where the free file is, when there is one. Null means Atlas cannot fetch it, and the
    card offers to open the publisher's page instead of an import that would fail."""

    in_library: bool = False
    library_paper_id: uuid.UUID | None = None


class CatalogPage(AtlasModel):
    """A slice of search results.

    Deliberately not the library's `Page`. That one promises an exact `total`, which the
    catalog cannot give cheaply — counting every match of a common word across a large
    catalog costs more than the search itself. `total_is_exact` says whether the number is a
    count or a floor, so the UI can render "1,000+" honestly rather than a precise-looking
    number that is wrong.
    """

    items: list[CatalogPaperRead]
    total: int
    total_is_exact: bool
    limit: int
    offset: int


class CategoryCountRead(AtlasModel):
    category: str
    count: int


class CatalogStatsRead(AtlasModel):
    total: int
    by_source: dict[str, int] = Field(default_factory=dict)
    with_abstract: int
    earliest_year: int | None = None
    latest_year: int | None = None
    top_categories: list[CategoryCountRead] = Field(default_factory=list)
