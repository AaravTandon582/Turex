"""Library endpoints: adding papers, browsing them, and reading their files."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, File, Query, Response, UploadFile, status

from atlas.api.deps import CurrentUser, GuardDep, PaperServiceDep
from atlas.models.job import STAGE_LABELS, IngestionJob
from atlas.models.paper import Paper
from atlas.schemas.paper import (
    IngestionProgress,
    LibraryStats,
    Page,
    PaperDetail,
    PaperFilters,
    PaperSummary,
    PaperUpdate,
    SectionRead,
)
from atlas.security import policy
from atlas.services.paper_service import PaperService

router = APIRouter(prefix="/papers", tags=["papers"])


def _progress(job: IngestionJob | None) -> IngestionProgress | None:
    if job is None:
        return None
    return IngestionProgress(
        stage=job.stage,
        label=STAGE_LABELS[job.stage],
        progress=job.progress,
        attempts=job.attempts,
        error_message=job.error_message,
    )


def _summary(paper: Paper, job: IngestionJob | None = None) -> PaperSummary:
    summary = PaperSummary.model_validate(paper)
    summary.ingestion = _progress(job)
    return summary


async def _detail(service: PaperService, paper: Paper) -> PaperDetail:
    """Assemble the full paper view, including how far ingestion has got."""
    section_count, chunk_count = await service.counts_for(paper.id)
    job = await service.latest_job(paper.id)

    detail = PaperDetail.model_validate(paper)
    detail.section_count = section_count
    detail.chunk_count = chunk_count
    detail.ingestion = _progress(job)
    return detail


@router.post("", response_model=PaperDetail, status_code=status.HTTP_202_ACCEPTED)
async def upload_paper(
    user: CurrentUser,
    service: PaperServiceDep,
    response: Response,
    guard: GuardDep,
    file: Annotated[UploadFile, File(description="A PDF to add to the library")],
) -> PaperDetail:
    """Add a paper.

    Returns 202: the file is stored and queued, but reading it happens in the background.
    Poll the paper to watch `ingestion.progress` advance. An upload of a file already in the
    library returns the existing paper with 200 rather than creating a duplicate.
    """
    guard.by_user(user.id, policy.UPLOADS_PER_USER, scope="upload")

    data = await file.read()
    result = await service.upload(
        owner=user,
        filename=file.filename or "document.pdf",
        content_type=file.content_type,
        data=data,
    )
    if result.already_existed:
        response.status_code = status.HTTP_200_OK
    return await _detail(service, result.paper)


@router.get("", response_model=Page[PaperSummary])
async def list_papers(
    user: CurrentUser,
    service: PaperServiceDep,
    filters: Annotated[PaperFilters, Query()],
) -> Page[PaperSummary]:
    found, total = await service.list_papers(owner=user, filters=filters)
    jobs = await service.progress_for([paper.id for paper in found])
    return Page(
        items=[_summary(paper, jobs.get(paper.id)) for paper in found],
        total=total,
        limit=filters.limit,
        offset=filters.offset,
    )


@router.get("/stats", response_model=LibraryStats)
async def library_stats(user: CurrentUser, service: PaperServiceDep) -> LibraryStats:
    return await service.stats(owner=user)


@router.get("/{paper_id}", response_model=PaperDetail)
async def get_paper(
    paper_id: uuid.UUID, user: CurrentUser, service: PaperServiceDep
) -> PaperDetail:
    paper = await service.get(owner=user, paper_id=paper_id)
    return await _detail(service, paper)


@router.patch("/{paper_id}", response_model=PaperDetail)
async def update_paper(
    paper_id: uuid.UUID, patch: PaperUpdate, user: CurrentUser, service: PaperServiceDep
) -> PaperDetail:
    paper = await service.update(owner=user, paper_id=paper_id, patch=patch)
    return await _detail(service, paper)


@router.post("/{paper_id}/opened", response_model=PaperDetail)
async def mark_opened(
    paper_id: uuid.UUID, user: CurrentUser, service: PaperServiceDep
) -> PaperDetail:
    """Record that the reader was opened. Moves an unread paper to 'reading'."""
    paper = await service.mark_opened(owner=user, paper_id=paper_id)
    return await _detail(service, paper)


@router.post(
    "/{paper_id}/reprocess", response_model=PaperDetail, status_code=status.HTTP_202_ACCEPTED
)
async def reprocess_paper(
    paper_id: uuid.UUID, user: CurrentUser, service: PaperServiceDep
) -> PaperDetail:
    await service.reprocess(owner=user, paper_id=paper_id)
    paper = await service.get(owner=user, paper_id=paper_id)
    return await _detail(service, paper)


@router.get("/{paper_id}/sections", response_model=list[SectionRead])
async def list_sections(
    paper_id: uuid.UUID, user: CurrentUser, service: PaperServiceDep
) -> list[SectionRead]:
    sections = await service.sections(owner=user, paper_id=paper_id)
    return [SectionRead.model_validate(section) for section in sections]


@router.get("/{paper_id}/file")
async def download_paper(
    paper_id: uuid.UUID, user: CurrentUser, service: PaperServiceDep
) -> Response:
    """Serve the original PDF, for the reader and for download.

    Held in memory rather than streamed: uploads are capped at `MAX_UPLOAD_BYTES`, so the
    working set is bounded and a streaming path would add an abstraction the storage
    interface does not yet need.
    """
    paper, data = await service.file_bytes(owner=user, paper_id=paper_id)

    # `inline` so the browser renders it in the reader. Quotes and newlines are stripped
    # from the filename so it cannot break out of the header it is embedded in.
    safe_name = paper.original_filename.replace('"', "").replace("\n", "").replace("\r", "")

    return Response(
        content=data,
        media_type="application/pdf",
        headers={
            "content-disposition": f'inline; filename="{safe_name}"',
            # Private to one user, so no shared cache may hold a copy.
            "cache-control": "private, max-age=3600",
        },
    )


@router.delete("/{paper_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_paper(paper_id: uuid.UUID, user: CurrentUser, service: PaperServiceDep) -> None:
    await service.delete_paper(owner=user, paper_id=paper_id)
