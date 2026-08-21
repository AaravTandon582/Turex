"""Highlights, notes, and citation export for a paper."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from turex.api.deps import AnnotationServiceDep, CurrentUser, PaperServiceDep
from turex.schemas.annotation import (
    AnnotationCreate,
    AnnotationRead,
    AnnotationUpdate,
    CitationBundle,
    CitationFormat,
)
from turex.services.citations import format_all

router = APIRouter(tags=["annotations"])


@router.get("/papers/{paper_id}/annotations", response_model=list[AnnotationRead])
async def list_annotations(
    paper_id: uuid.UUID, user: CurrentUser, service: AnnotationServiceDep
) -> list[AnnotationRead]:
    annotations = await service.list_for_paper(owner=user, paper_id=paper_id)
    return [AnnotationRead.model_validate(annotation) for annotation in annotations]


@router.post(
    "/papers/{paper_id}/annotations",
    response_model=AnnotationRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_annotation(
    paper_id: uuid.UUID,
    payload: AnnotationCreate,
    user: CurrentUser,
    service: AnnotationServiceDep,
) -> AnnotationRead:
    annotation = await service.create(
        owner=user,
        paper_id=paper_id,
        page_number=payload.page_number,
        text_offset=payload.text_offset,
        selected_text=payload.selected_text,
        colour=payload.colour,
        note=payload.note,
    )
    return AnnotationRead.model_validate(annotation)


@router.patch("/annotations/{annotation_id}", response_model=AnnotationRead)
async def update_annotation(
    annotation_id: uuid.UUID,
    payload: AnnotationUpdate,
    user: CurrentUser,
    service: AnnotationServiceDep,
) -> AnnotationRead:
    annotation = await service.update(
        owner=user,
        annotation_id=annotation_id,
        colour=payload.colour,
        note=payload.note,
        clear_note=payload.clear_note,
    )
    return AnnotationRead.model_validate(annotation)


@router.delete("/annotations/{annotation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_annotation(
    annotation_id: uuid.UUID, user: CurrentUser, service: AnnotationServiceDep
) -> None:
    await service.delete(owner=user, annotation_id=annotation_id)


@router.get("/papers/{paper_id}/citations", response_model=CitationBundle)
async def paper_citations(
    paper_id: uuid.UUID, user: CurrentUser, service: PaperServiceDep
) -> CitationBundle:
    """Every supported citation style, built only from stored metadata.

    `missing_fields` names what the paper lacks, so an incomplete citation is visibly
    incomplete rather than quietly wrong.
    """
    paper = await service.get(owner=user, paper_id=paper_id)
    return CitationBundle(
        paper_id=paper.id,
        formats=[
            CitationFormat(
                style=formatted.style,
                text=formatted.text,
                missing_fields=formatted.missing_fields,
            )
            for formatted in format_all(paper)
        ],
    )
