"""Highlights and notes on a paper."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from turex.core.errors import NotFoundError, ValidationError
from turex.core.logging import get_logger
from turex.models.annotation import Annotation, HighlightColour
from turex.models.paper import Paper
from turex.models.user import User

logger = get_logger(__name__)

MAX_SELECTION_LENGTH = 20_000
"""A highlight covering more than this is a whole-document selection, not a passage. Storing
it would bloat every list response that includes annotations."""


class AnnotationService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def _owned_paper(self, owner: User, paper_id: uuid.UUID) -> Paper:
        paper = await self._db.scalar(
            select(Paper).where(Paper.id == paper_id, Paper.owner_id == owner.id)
        )
        if paper is None:
            raise NotFoundError("We couldn't find that paper.")
        return paper

    async def list_for_paper(self, *, owner: User, paper_id: uuid.UUID) -> list[Annotation]:
        await self._owned_paper(owner, paper_id)
        rows = await self._db.scalars(
            select(Annotation)
            .where(Annotation.paper_id == paper_id, Annotation.owner_id == owner.id)
            .order_by(Annotation.page_number, Annotation.text_offset)
        )
        return list(rows)

    async def list_recent(self, *, owner: User, limit: int = 50) -> list[Annotation]:
        rows = await self._db.scalars(
            select(Annotation)
            .where(Annotation.owner_id == owner.id)
            .order_by(Annotation.created_at.desc())
            .limit(limit)
        )
        return list(rows)

    async def create(
        self,
        *,
        owner: User,
        paper_id: uuid.UUID,
        page_number: int,
        text_offset: int,
        selected_text: str,
        colour: HighlightColour,
        note: str | None,
    ) -> Annotation:
        paper = await self._owned_paper(owner, paper_id)

        cleaned = selected_text.strip()
        if not cleaned:
            raise ValidationError("Select some text to highlight.")
        if len(cleaned) > MAX_SELECTION_LENGTH:
            raise ValidationError("That selection is too large to highlight.")
        if paper.page_count and page_number > paper.page_count:
            raise ValidationError(
                f"This paper has {paper.page_count} pages.",
                detail=f"page {page_number} out of range",
            )

        annotation = Annotation(
            owner_id=owner.id,
            paper_id=paper_id,
            page_number=page_number,
            text_offset=text_offset,
            text_length=len(cleaned),
            selected_text=cleaned,
            colour=colour,
            note=note.strip() if note and note.strip() else None,
        )
        self._db.add(annotation)
        await self._db.flush()

        logger.info(
            "annotation created",
            extra={"paper_id": str(paper_id), "page": page_number, "colour": colour.value},
        )
        return annotation

    async def get(self, *, owner: User, annotation_id: uuid.UUID) -> Annotation:
        annotation = await self._db.scalar(
            select(Annotation).where(
                Annotation.id == annotation_id, Annotation.owner_id == owner.id
            )
        )
        if annotation is None:
            raise NotFoundError("We couldn't find that highlight.")
        return annotation

    async def update(
        self,
        *,
        owner: User,
        annotation_id: uuid.UUID,
        colour: HighlightColour | None = None,
        note: str | None = None,
        clear_note: bool = False,
    ) -> Annotation:
        """Change a highlight's colour or note.

        `clear_note` is separate from `note=None` because the two mean different things over
        JSON: an absent field leaves the note alone, and removing it has to be explicit.
        """
        annotation = await self.get(owner=owner, annotation_id=annotation_id)
        if colour is not None:
            annotation.colour = colour
        if clear_note:
            annotation.note = None
        elif note is not None:
            annotation.note = note.strip() or None
        await self._db.flush()
        return annotation

    async def delete(self, *, owner: User, annotation_id: uuid.UUID) -> None:
        annotation = await self.get(owner=owner, annotation_id=annotation_id)
        await self._db.delete(annotation)
