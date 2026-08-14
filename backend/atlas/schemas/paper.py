"""Request and response models for the library."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

from atlas.models.job import IngestionStage
from atlas.models.paper import ProcessingStatus, ReadingStatus

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """A slice of a larger list.

    `total` is included so the UI can show "48 papers" and render pagination without a
    second request.
    """

    items: list[T]
    total: int
    limit: int
    offset: int

    @property
    def has_more(self) -> bool:
        return self.offset + len(self.items) < self.total


class Author(BaseModel):
    name: str


class IngestionProgress(BaseModel):
    """What Atlas is currently doing to a paper, for the processing indicator."""

    stage: IngestionStage
    label: str
    progress: int
    attempts: int
    error_message: str | None = None


class PaperSummary(BaseModel):
    """The library-listing shape. Deliberately excludes the abstract, which is large and
    unread in a grid of forty papers."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str | None
    display_title: str
    authors: list[Author]
    publication_year: int | None
    venue: str | None
    doi: str | None
    arxiv_id: str | None
    page_count: int | None
    status: ProcessingStatus
    failure_reason: str | None
    reading_status: ReadingStatus
    is_favorite: bool
    original_filename: str
    file_size_bytes: int
    last_opened_at: datetime | None
    created_at: datetime

    ingestion: IngestionProgress | None = None
    """Present while a paper is being read, so the library can show real progress without
    a follow-up request per row."""


class PaperDetail(PaperSummary):
    abstract: str | None
    section_count: int = 0
    chunk_count: int = 0


class SectionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ordinal: int
    title: str
    level: int
    page_start: int | None
    page_end: int | None


class PaperUpdate(BaseModel):
    """Corrections a user may make.

    Metadata extraction is heuristic and occasionally wrong, so every extracted field is
    editable. Re-ingestion respects these corrections rather than overwriting them.
    """

    title: str | None = Field(default=None, max_length=1000)
    authors: list[Author] | None = None
    abstract: str | None = None
    publication_year: int | None = Field(default=None, ge=1500, le=2200)
    venue: str | None = Field(default=None, max_length=500)
    doi: str | None = Field(default=None, max_length=255)
    reading_status: ReadingStatus | None = None
    is_favorite: bool | None = None

    @field_validator("title", "venue", "abstract")
    @classmethod
    def _blank_to_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


PaperSort = Literal["recent", "title", "year", "opened"]


class PaperFilters(BaseModel):
    """Library query parameters, validated as a unit."""

    search: str | None = Field(default=None, max_length=200)
    reading_status: ReadingStatus | None = None
    status: ProcessingStatus | None = None
    collection_id: uuid.UUID | None = None
    tag: str | None = Field(default=None, max_length=64)
    favorites_only: bool = False
    sort: PaperSort = "recent"
    limit: Annotated[int, Field(ge=1, le=100)] = 24
    offset: Annotated[int, Field(ge=0)] = 0

    @field_validator("search", "tag")
    @classmethod
    def _blank_to_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class CollectionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    paper_count: int = 0
    created_at: datetime


class CollectionWrite(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Name cannot be blank")
        return stripped


class TagRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    paper_count: int = 0


class LibraryStats(BaseModel):
    """Counts the library header shows, in one query rather than several."""

    total: int
    processing: int
    failed: int
    unread: int
    favorites: int
