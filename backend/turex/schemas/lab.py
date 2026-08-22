"""Request and response models for the lab notebook."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import ConfigDict, Field

from turex.schemas.base import TurexModel


class LabEntryRead(TurexModel):
    """One entry as written. There is no update model, because there is no update."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sequence: int
    title: str | None = None
    body: str
    recorded_at: datetime
    project_id: uuid.UUID | None = None
    experiment_id: uuid.UUID | None = None
    paper_id: uuid.UUID | None = None

    entry_hash: str
    previous_hash: str
    """Both hashes are returned so the chain can be checked outside Turex.

    Anyone with this list and the hashing rule — which is documented in `models/lab.py` — can
    verify it themselves. Evidence nobody can check independently is not evidence.
    """


class LabEntryCreate(TurexModel):
    title: str | None = Field(default=None, max_length=300)
    body: str = Field(min_length=1, max_length=100_000)
    project_id: uuid.UUID | None = None
    experiment_id: uuid.UUID | None = None
    paper_id: uuid.UUID | None = None


class LabEntryPage(TurexModel):
    items: list[LabEntryRead]
    total: int
    limit: int
    offset: int


class ChainBreakRead(TurexModel):
    sequence: int
    entry_id: uuid.UUID
    recorded_at: datetime
    reason: str


class ChainReportRead(TurexModel):
    """The result of walking the whole chain.

    `intact` is the only field worth branching on. The rest is for a person reading the
    result — a report that says "intact except…" is not one anybody should act on.
    """

    entries: int
    intact: bool
    first_break_at: int | None = None
    breaks: list[ChainBreakRead] = Field(default_factory=list)
    checked_at: datetime
