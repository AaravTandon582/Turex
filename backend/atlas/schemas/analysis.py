"""Request and response models for analyses."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import ConfigDict, Field

from atlas.models.analysis import CellKind, CellStatus
from atlas.schemas.base import AtlasModel


class CellRead(AtlasModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ordinal: int
    kind: CellKind
    source: str
    output: str | None = None
    image: str | None = None
    error: str | None = None
    status: CellStatus
    duration_ms: int | None = None
    executed_at: datetime | None = None


class AnalysisRead(AtlasModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    description: str | None = None
    project_id: uuid.UUID | None = None
    experiment_id: uuid.UUID | None = None
    last_run_at: datetime | None = None
    created_at: datetime
    cells: list[CellRead] = Field(default_factory=list)


class AnalysisCreate(AtlasModel):
    title: str = Field(min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=4000)
    project_id: uuid.UUID | None = None
    experiment_id: uuid.UUID | None = None


class AnalysisUpdate(AtlasModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=4000)


class CellCreate(AtlasModel):
    kind: CellKind = CellKind.code
    source: str = Field(default="", max_length=100_000)
    after: uuid.UUID | None = Field(
        default=None, description="Insert below this cell rather than at the end"
    )


class CellUpdate(AtlasModel):
    """What the editor saves as someone types."""

    source: str = Field(max_length=100_000)
    kind: CellKind | None = None


class CellRun(AtlasModel):
    """What a cell produced, reported by the browser that ran it.

    The server stores these as text. It does not execute anything, and nothing here is ever
    rendered as HTML — `output` is a code block and `image` is checked to be a PNG data URI
    before it reaches an `img` tag.
    """

    output: str | None = Field(default=None, max_length=200_000)
    image: str | None = Field(default=None, max_length=4_000_000)
    error: str | None = Field(default=None, max_length=200_000)
    duration_ms: int | None = Field(default=None, ge=0, le=86_400_000)


class CellMove(AtlasModel):
    offset: int = Field(description="-1 to move up, 1 to move down", ge=-1, le=1)
