"""Research workspace endpoints: projects, hypotheses, experiments, notes, and tasks."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from turex.api.deps import AnalysisServiceDep, CurrentUser, LabServiceDep, WorkspaceServiceDep
from turex.schemas.workspace import (
    AttachEvidence,
    AttachPaper,
    EvidenceRead,
    ExperimentCreate,
    ExperimentRead,
    ExperimentUpdate,
    HypothesisCreate,
    HypothesisDetail,
    HypothesisRead,
    HypothesisUpdate,
    NoteCreate,
    NoteRead,
    NoteUpdate,
    ProjectCreate,
    ProjectPaperRead,
    ProjectRead,
    ProjectUpdate,
    TaskCreate,
    TaskRead,
    TaskUpdate,
)
from turex.services.project_bundle import build_bundle
from turex.services.workspace_service import ProjectOverview

LAB_ENTRY_CEILING = 5_000
"""How many lab entries one export carries.

A bound on the request rather than a feature: a notebook longer than this is one nobody is
reading end to end, and the chain can still be verified in the application.
"""

router = APIRouter(tags=["workspace"])


def _project(overview: ProjectOverview) -> ProjectRead:
    read = ProjectRead.model_validate(overview.project)
    read.paper_count = overview.paper_count
    read.hypothesis_count = overview.hypothesis_count
    read.experiment_count = overview.experiment_count
    read.note_count = overview.note_count
    read.open_task_count = overview.open_task_count
    return read


# -- projects -------------------------------------------------------------------------


@router.get("/projects", response_model=list[ProjectRead])
async def list_projects(user: CurrentUser, service: WorkspaceServiceDep) -> list[ProjectRead]:
    return [_project(overview) for overview in await service.list_projects(owner=user)]


@router.post("/projects", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: ProjectCreate, user: CurrentUser, service: WorkspaceServiceDep
) -> ProjectRead:
    project = await service.create_project(owner=user, **payload.model_dump())
    return ProjectRead.model_validate(project)


@router.get("/projects/{project_id}", response_model=ProjectRead)
async def get_project(
    project_id: uuid.UUID, user: CurrentUser, service: WorkspaceServiceDep
) -> ProjectRead:
    return _project(await service.project_overview(owner=user, project_id=project_id))


@router.patch("/projects/{project_id}", response_model=ProjectRead)
async def update_project(
    project_id: uuid.UUID,
    payload: ProjectUpdate,
    user: CurrentUser,
    service: WorkspaceServiceDep,
) -> ProjectRead:
    project = await service.update_project(
        owner=user, project_id=project_id, changes=payload.model_dump(exclude_unset=True)
    )
    return ProjectRead.model_validate(project)


@router.get("/projects/{project_id}/export")
async def export_project(
    project_id: uuid.UUID,
    user: CurrentUser,
    service: WorkspaceServiceDep,
    analyses: AnalysisServiceDep,
    lab: LabServiceDep,
) -> Response:
    """A whole project as a folder of plain files, zipped.

    README, `references.bib`, notes as Markdown, analyses as Jupyter notebooks, hypotheses and
    experiments as Markdown, and the lab notebook with its hashes. Everything is text except
    the notebooks, which are JSON — the point being that none of it needs Turex to read, and a
    diff between two exports says something useful.

    The PDFs are not included. A paper's file belongs to its publisher rather than to the
    project, and several hundred megabytes of them would make this an export nobody runs.
    `references.bib` says exactly which papers they are.
    """
    project = await service.get_project(owner=user, project_id=project_id)

    papers = [paper for paper, _ in await service.project_papers(owner=user, project_id=project_id)]
    hypotheses = await service.list_hypotheses(owner=user, project_id=project_id)
    evidence = {
        hypothesis.id: await service.evidence_for(owner=user, hypothesis_id=hypothesis.id)
        for hypothesis in hypotheses
    }
    entries, _ = await lab.list_entries(user.id, project_id=project_id, limit=LAB_ENTRY_CEILING)

    bundle = build_bundle(
        project,
        papers=papers,
        notes=await service.list_notes(owner=user, project_id=project_id),
        hypotheses=hypotheses,
        evidence=evidence,
        experiments=await service.list_experiments(owner=user, project_id=project_id),
        analyses=await analyses.list_for(user.id, project_id=project_id),
        # Oldest first: a notebook is read forwards, and the chain only makes sense in order.
        entries=list(reversed(entries)),
    )

    return Response(
        content=bundle.content,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{bundle.filename}"'},
    )


@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: uuid.UUID, user: CurrentUser, service: WorkspaceServiceDep
) -> None:
    """Delete a project and everything inside it. The papers themselves are not deleted."""
    await service.delete_project(owner=user, project_id=project_id)


@router.get("/projects/{project_id}/papers", response_model=list[ProjectPaperRead])
async def list_project_papers(
    project_id: uuid.UUID, user: CurrentUser, service: WorkspaceServiceDep
) -> list[ProjectPaperRead]:
    rows = await service.project_papers(owner=user, project_id=project_id)
    return [
        ProjectPaperRead(
            paper_id=paper.id,
            title=paper.display_title,
            authors=[author.get("name", "") for author in (paper.authors or [])],
            publication_year=paper.publication_year,
            relevance_note=note,
        )
        for paper, note in rows
    ]


@router.put("/projects/{project_id}/papers", status_code=status.HTTP_204_NO_CONTENT)
async def attach_paper(
    project_id: uuid.UUID,
    payload: AttachPaper,
    user: CurrentUser,
    service: WorkspaceServiceDep,
) -> None:
    await service.add_paper(
        owner=user,
        project_id=project_id,
        paper_id=payload.paper_id,
        relevance_note=payload.relevance_note,
    )


@router.delete("/projects/{project_id}/papers/{paper_id}", status_code=status.HTTP_204_NO_CONTENT)
async def detach_paper(
    project_id: uuid.UUID,
    paper_id: uuid.UUID,
    user: CurrentUser,
    service: WorkspaceServiceDep,
) -> None:
    await service.remove_paper(owner=user, project_id=project_id, paper_id=paper_id)


# -- hypotheses -----------------------------------------------------------------------


@router.get("/hypotheses", response_model=list[HypothesisRead])
async def list_hypotheses(
    user: CurrentUser,
    service: WorkspaceServiceDep,
    project_id: uuid.UUID | None = None,
) -> list[HypothesisRead]:
    hypotheses = await service.list_hypotheses(owner=user, project_id=project_id)
    counts = await service.evidence_counts([h.id for h in hypotheses])

    result: list[HypothesisRead] = []
    for hypothesis in hypotheses:
        read = HypothesisRead.model_validate(hypothesis)
        read.supporting_count, read.contradicting_count = counts.get(hypothesis.id, (0, 0))
        result.append(read)
    return result


@router.post("/hypotheses", response_model=HypothesisRead, status_code=status.HTTP_201_CREATED)
async def create_hypothesis(
    payload: HypothesisCreate, user: CurrentUser, service: WorkspaceServiceDep
) -> HypothesisRead:
    hypothesis = await service.create_hypothesis(owner=user, **payload.model_dump())
    return HypothesisRead.model_validate(hypothesis)


@router.get("/hypotheses/{hypothesis_id}", response_model=HypothesisDetail)
async def get_hypothesis(
    hypothesis_id: uuid.UUID, user: CurrentUser, service: WorkspaceServiceDep
) -> HypothesisDetail:
    hypothesis = await service.get_hypothesis(owner=user, hypothesis_id=hypothesis_id)
    evidence = await service.evidence_for(owner=user, hypothesis_id=hypothesis_id)

    # Built from the base model rather than validated straight off the ORM object: a
    # response field named after a lazy relationship makes Pydantic read it, which is sync
    # IO on an async session. `lazy="raise_on_sql"` on the relationship makes that mistake
    # fail loudly, and this is the correct way round it.
    base = HypothesisRead.model_validate(hypothesis)
    supporting = sum(1 for item in evidence if item.stance == "supports")
    return HypothesisDetail(
        **base.model_dump(exclude={"supporting_count", "contradicting_count"}),
        supporting_count=supporting,
        contradicting_count=len(evidence) - supporting,
        evidence=[EvidenceRead.model_validate(item) for item in evidence],
    )


@router.patch("/hypotheses/{hypothesis_id}", response_model=HypothesisRead)
async def update_hypothesis(
    hypothesis_id: uuid.UUID,
    payload: HypothesisUpdate,
    user: CurrentUser,
    service: WorkspaceServiceDep,
) -> HypothesisRead:
    hypothesis = await service.update_hypothesis(
        owner=user,
        hypothesis_id=hypothesis_id,
        changes=payload.model_dump(exclude_unset=True),
    )
    return HypothesisRead.model_validate(hypothesis)


@router.delete("/hypotheses/{hypothesis_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_hypothesis(
    hypothesis_id: uuid.UUID, user: CurrentUser, service: WorkspaceServiceDep
) -> None:
    await service.delete_hypothesis(owner=user, hypothesis_id=hypothesis_id)


@router.post(
    "/hypotheses/{hypothesis_id}/evidence",
    response_model=EvidenceRead,
    status_code=status.HTTP_201_CREATED,
)
async def attach_evidence(
    hypothesis_id: uuid.UUID,
    payload: AttachEvidence,
    user: CurrentUser,
    service: WorkspaceServiceDep,
) -> EvidenceRead:
    """Link a passage to a hypothesis, for or against.

    Only the chunk id is accepted — the passage text and locator are read from the database
    rather than taken from the client, so evidence is always what the paper actually says.
    """
    evidence = await service.attach_evidence(
        owner=user,
        hypothesis_id=hypothesis_id,
        chunk_id=payload.chunk_id,
        stance=payload.stance,
        reasoning=payload.reasoning,
    )
    return EvidenceRead.model_validate(evidence)


@router.delete("/evidence/{evidence_id}", status_code=status.HTTP_204_NO_CONTENT)
async def detach_evidence(
    evidence_id: uuid.UUID, user: CurrentUser, service: WorkspaceServiceDep
) -> None:
    await service.detach_evidence(owner=user, evidence_id=evidence_id)


# -- experiments ----------------------------------------------------------------------


@router.get("/experiments", response_model=list[ExperimentRead])
async def list_experiments(
    user: CurrentUser,
    service: WorkspaceServiceDep,
    project_id: uuid.UUID | None = None,
) -> list[ExperimentRead]:
    experiments = await service.list_experiments(owner=user, project_id=project_id)
    return [ExperimentRead.model_validate(experiment) for experiment in experiments]


@router.post("/experiments", response_model=ExperimentRead, status_code=status.HTTP_201_CREATED)
async def create_experiment(
    payload: ExperimentCreate, user: CurrentUser, service: WorkspaceServiceDep
) -> ExperimentRead:
    experiment = await service.create_experiment(owner=user, **payload.model_dump())
    return ExperimentRead.model_validate(experiment)


@router.get("/experiments/{experiment_id}", response_model=ExperimentRead)
async def get_experiment(
    experiment_id: uuid.UUID, user: CurrentUser, service: WorkspaceServiceDep
) -> ExperimentRead:
    experiment = await service.get_experiment(owner=user, experiment_id=experiment_id)
    return ExperimentRead.model_validate(experiment)


@router.patch("/experiments/{experiment_id}", response_model=ExperimentRead)
async def update_experiment(
    experiment_id: uuid.UUID,
    payload: ExperimentUpdate,
    user: CurrentUser,
    service: WorkspaceServiceDep,
) -> ExperimentRead:
    experiment = await service.update_experiment(
        owner=user,
        experiment_id=experiment_id,
        changes=payload.model_dump(exclude_unset=True),
    )
    return ExperimentRead.model_validate(experiment)


@router.delete("/experiments/{experiment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_experiment(
    experiment_id: uuid.UUID, user: CurrentUser, service: WorkspaceServiceDep
) -> None:
    await service.delete_experiment(owner=user, experiment_id=experiment_id)


# -- notes ----------------------------------------------------------------------------


@router.get("/notes", response_model=list[NoteRead])
async def list_notes(
    user: CurrentUser,
    service: WorkspaceServiceDep,
    project_id: uuid.UUID | None = None,
    paper_id: uuid.UUID | None = None,
    search: Annotated[str | None, Query(max_length=200)] = None,
) -> list[NoteRead]:
    notes = await service.list_notes(
        owner=user, project_id=project_id, paper_id=paper_id, search=search
    )
    return [NoteRead.model_validate(note) for note in notes]


@router.post("/notes", response_model=NoteRead, status_code=status.HTTP_201_CREATED)
async def create_note(
    payload: NoteCreate, user: CurrentUser, service: WorkspaceServiceDep
) -> NoteRead:
    note = await service.create_note(owner=user, **payload.model_dump())
    return NoteRead.model_validate(note)


@router.get("/notes/{note_id}", response_model=NoteRead)
async def get_note(note_id: uuid.UUID, user: CurrentUser, service: WorkspaceServiceDep) -> NoteRead:
    return NoteRead.model_validate(await service.get_note(owner=user, note_id=note_id))


@router.patch("/notes/{note_id}", response_model=NoteRead)
async def update_note(
    note_id: uuid.UUID,
    payload: NoteUpdate,
    user: CurrentUser,
    service: WorkspaceServiceDep,
) -> NoteRead:
    note = await service.update_note(
        owner=user, note_id=note_id, changes=payload.model_dump(exclude_unset=True)
    )
    return NoteRead.model_validate(note)


@router.delete("/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_note(note_id: uuid.UUID, user: CurrentUser, service: WorkspaceServiceDep) -> None:
    await service.delete_note(owner=user, note_id=note_id)


# -- tasks ----------------------------------------------------------------------------


@router.get("/projects/{project_id}/tasks", response_model=list[TaskRead])
async def list_tasks(
    project_id: uuid.UUID, user: CurrentUser, service: WorkspaceServiceDep
) -> list[TaskRead]:
    tasks = await service.list_tasks(owner=user, project_id=project_id)
    return [TaskRead.model_validate(task) for task in tasks]


@router.post(
    "/projects/{project_id}/tasks", response_model=TaskRead, status_code=status.HTTP_201_CREATED
)
async def create_task(
    project_id: uuid.UUID,
    payload: TaskCreate,
    user: CurrentUser,
    service: WorkspaceServiceDep,
) -> TaskRead:
    task = await service.create_task(owner=user, project_id=project_id, title=payload.title)
    return TaskRead.model_validate(task)


@router.patch("/tasks/{task_id}", response_model=TaskRead)
async def update_task(
    task_id: uuid.UUID,
    payload: TaskUpdate,
    user: CurrentUser,
    service: WorkspaceServiceDep,
) -> TaskRead:
    task = await service.update_task(
        owner=user, task_id=task_id, changes=payload.model_dump(exclude_unset=True)
    )
    return TaskRead.model_validate(task)


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(task_id: uuid.UUID, user: CurrentUser, service: WorkspaceServiceDep) -> None:
    await service.delete_task(owner=user, task_id=task_id)
