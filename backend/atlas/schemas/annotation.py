"""Request and response models for highlights and citations."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import ConfigDict, Field, field_validator

from atlas.models.annotation import HighlightColour
from atlas.schemas.base import AtlasModel
from atlas.services.citations import CitationStyle


class AnnotationRead(AtlasModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    paper_id: uuid.UUID
    page_number: int
    text_offset: int
    text_length: int
    selected_text: str
    colour: HighlightColour
    note: str | None
    created_at: datetime


class AnnotationCreate(AtlasModel):
    page_number: int = Field(ge=1)
    text_offset: int = Field(ge=0)
    selected_text: str = Field(min_length=1, max_length=20_000)
    colour: HighlightColour = HighlightColour.important
    note: str | None = Field(default=None, max_length=10_000)

    @field_validator("selected_text")
    @classmethod
    def _require_content(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Select some text to highlight")
        return stripped


class AnnotationUpdate(AtlasModel):
    colour: HighlightColour | None = None
    note: str | None = Field(default=None, max_length=10_000)
    clear_note: bool = False
    """Removing a note has to be explicit: an absent `note` means "leave it alone"."""


class CitationFormat(AtlasModel):
    style: CitationStyle
    text: str
    missing_fields: list[str]
    """Metadata this style expects but the paper lacks, so the UI can prompt for it rather
    than letting an incomplete citation reach a bibliography unnoticed."""


class CitationBundle(AtlasModel):
    paper_id: uuid.UUID
    formats: list[CitationFormat]
