"""Request and response models for the research workspace."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated

from pydantic import ConfigDict, Field, field_validator

from turex.models.workspace import (
    EvidenceStance,
    ExperimentStatus,
    HypothesisStatus,
    ProjectStatus,
    TaskStatus,
)
from turex.schemas.base import NeverNull, TurexModel


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip() or None


# -- projects -------------------------------------------------------------------------


class ProjectRead(TurexModel):
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


class ProjectCreate(TurexModel):
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


class ProjectUpdate(TurexModel):
    name: Annotated[str | None, NeverNull] = Field(default=None, min_length=1, max_length=200)
    research_question: str | None = Field(default=None, max_length=2000)
    description: str | None = None
    status: Annotated[ProjectStatus | None, NeverNull] = None


class ProjectPaperRead(TurexModel):
    paper_id: uuid.UUID
    title: str
    authors: list[str]
    publication_year: int | None
    relevance_note: str | None


class AttachPaper(TurexModel):
    paper_id: uuid.UUID
    relevance_note: str | None = Field(default=None, max_length=2000)


# -- hypotheses -----------------------------------------------------------------------


class EvidenceRead(TurexModel):
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


class HypothesisRead(TurexModel):
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


class HypothesisCreate(TurexModel):
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


class HypothesisUpdate(TurexModel):
    statement: Annotated[str | None, NeverNull] = Field(default=None, min_length=1, max_length=4000)
    motivation: str | None = None
    assumptions: str | None = None
    status: Annotated[HypothesisStatus | None, NeverNull] = None
    project_id: uuid.UUID | None = None
    position: Annotated[int | None, NeverNull] = None


class AttachEvidence(TurexModel):
    chunk_id: uuid.UUID
    stance: EvidenceStance
    reasoning: str | None = Field(default=None, max_length=4000)


# -- experiments ----------------------------------------------------------------------


class ExperimentRead(TurexModel):
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


class ExperimentCreate(TurexModel):
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


class ExperimentUpdate(TurexModel):
    title: Annotated[str | None, NeverNull] = Field(default=None, min_length=1, max_length=300)
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
    status: Annotated[ExperimentStatus | None, NeverNull] = None
    run_on: date | None = None


# -- notes ----------------------------------------------------------------------------


class NoteRead(TurexModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str | None
    content: str
    project_id: uuid.UUID | None
    paper_id: uuid.UUID | None
    hypothesis_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class NoteCreate(TurexModel):
    title: str | None = Field(default=None, max_length=300)
    content: str = ""
    project_id: uuid.UUID | None = None
    paper_id: uuid.UUID | None = None
    hypothesis_id: uuid.UUID | None = None


class NoteUpdate(TurexModel):
    title: str | None = Field(default=None, max_length=300)
    content: Annotated[str | None, NeverNull] = None
    project_id: uuid.UUID | None = None
    paper_id: uuid.UUID | None = None
    hypothesis_id: uuid.UUID | None = None


# -- tasks ----------------------------------------------------------------------------


class TaskRead(TurexModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    title: str
    status: TaskStatus
    position: int


class TaskCreate(TurexModel):
    title: str = Field(min_length=1, max_length=300)


class TaskUpdate(TurexModel):
    title: Annotated[str | None, NeverNull] = Field(default=None, min_length=1, max_length=300)
    status: Annotated[TaskStatus | None, NeverNull] = None
    position: Annotated[int | None, NeverNull] = None
