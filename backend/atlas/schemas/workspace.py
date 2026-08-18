"""Request and response models for the research workspace."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import ConfigDict, Field, field_validator

from atlas.models.workspace import (
    EvidenceStance,
    ExperimentStatus,
    HypothesisStatus,
    ProjectStatus,
    TaskStatus,
)
from atlas.schemas.base import AtlasModel


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip() or None


# -- projects -------------------------------------------------------------------------


class ProjectRead(AtlasModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    research_question: str | None
    description: str | None
    status: ProjectStatus
    created_at: datetime
    updated_at: datetime

    paper_count: int = 0
    hypothesis_count: int = 0
    experiment_count: int = 0
    note_count: int = 0
    open_task_count: int = 0


class ProjectCreate(AtlasModel):
    name: str = Field(min_length=1, max_length=200)
    research_question: str | None = Field(default=None, max_length=2000)
    description: str | None = None

    @field_validator("name")
    @classmethod
    def _require_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Give the project a name")
        return stripped

    @field_validator("research_question", "description")
    @classmethod
    def _clean(cls, value: str | None) -> str | None:
        return _blank_to_none(value)


class ProjectUpdate(AtlasModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    research_question: str | None = Field(default=None, max_length=2000)
    description: str | None = None
    status: ProjectStatus | None = None


class ProjectPaperRead(AtlasModel):
    paper_id: uuid.UUID
    title: str
    authors: list[str]
    publication_year: int | None
    relevance_note: str | None


class AttachPaper(AtlasModel):
    paper_id: uuid.UUID
    relevance_note: str | None = Field(default=None, max_length=2000)


# -- hypotheses -----------------------------------------------------------------------


class EvidenceRead(AtlasModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    chunk_id: uuid.UUID | None
    paper_id: uuid.UUID | None
    stance: EvidenceStance
    paper_title: str
    locator: str
    quoted_text: str
    reasoning: str | None
    created_at: datetime


class HypothesisRead(AtlasModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID | None
    statement: str
    motivation: str | None
    assumptions: str | None
    status: HypothesisStatus
    position: int
    created_at: datetime

    supporting_count: int = 0
    contradicting_count: int = 0


class HypothesisDetail(HypothesisRead):
    evidence: list[EvidenceRead] = Field(default_factory=list)


class HypothesisCreate(AtlasModel):
    statement: str = Field(min_length=1, max_length=4000)
    project_id: uuid.UUID | None = None
    motivation: str | None = None
    assumptions: str | None = None
    status: HypothesisStatus = HypothesisStatus.proposed

    @field_validator("statement")
    @classmethod
    def _require_statement(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("State the hypothesis")
        return stripped


class HypothesisUpdate(AtlasModel):
    statement: str | None = Field(default=None, min_length=1, max_length=4000)
    motivation: str | None = None
    assumptions: str | None = None
    status: HypothesisStatus | None = None
    project_id: uuid.UUID | None = None
    position: int | None = None


class AttachEvidence(AtlasModel):
    chunk_id: uuid.UUID
    stance: EvidenceStance
    reasoning: str | None = Field(default=None, max_length=4000)


# -- experiments ----------------------------------------------------------------------


class ExperimentRead(AtlasModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID | None
    hypothesis_id: uuid.UUID | None
    title: str
    objective: str | None
    independent_variables: str | None
    dependent_variables: str | None
    controls: str | None
    confounders: str | None
    dataset: str | None
    methodology: str | None
    metrics: str | None
    expected_result: str | None
    actual_result: str | None
    interpretation: str | None
    status: ExperimentStatus
    run_on: date | None
    created_at: datetime


class ExperimentCreate(AtlasModel):
    title: str = Field(min_length=1, max_length=300)
    project_id: uuid.UUID | None = None
    hypothesis_id: uuid.UUID | None = None
    objective: str | None = None
    independent_variables: str | None = None
    dependent_variables: str | None = None
    controls: str | None = None
    confounders: str | None = None
    dataset: str | None = None
    methodology: str | None = None
    metrics: str | None = None
    expected_result: str | None = None

    @field_validator("title")
    @classmethod
    def _require_title(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Give the experiment a title")
        return stripped


class ExperimentUpdate(AtlasModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    hypothesis_id: uuid.UUID | None = None
    objective: str | None = None
    independent_variables: str | None = None
    dependent_variables: str | None = None
    controls: str | None = None
    confounders: str | None = None
    dataset: str | None = None
    methodology: str | None = None
    metrics: str | None = None
    expected_result: str | None = None
    actual_result: str | None = None
    interpretation: str | None = None
    status: ExperimentStatus | None = None
    run_on: date | None = None


# -- notes ----------------------------------------------------------------------------


class NoteRead(AtlasModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str | None
    content: str
    project_id: uuid.UUID | None
    paper_id: uuid.UUID | None
    hypothesis_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class NoteCreate(AtlasModel):
    title: str | None = Field(default=None, max_length=300)
    content: str = ""
    project_id: uuid.UUID | None = None
    paper_id: uuid.UUID | None = None
    hypothesis_id: uuid.UUID | None = None


class NoteUpdate(AtlasModel):
    title: str | None = Field(default=None, max_length=300)
    content: str | None = None
    project_id: uuid.UUID | None = None
    paper_id: uuid.UUID | None = None
    hypothesis_id: uuid.UUID | None = None


# -- tasks ----------------------------------------------------------------------------


class TaskRead(AtlasModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    title: str
    status: TaskStatus
    position: int


class TaskCreate(AtlasModel):
    title: str = Field(min_length=1, max_length=300)


class TaskUpdate(AtlasModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    status: TaskStatus | None = None
    position: int | None = None
