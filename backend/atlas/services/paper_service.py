"""Library business logic: adding papers, finding them, and keeping them private.

Every method takes the acting user and scopes its queries to them. Ownership is enforced in
the query rather than checked afterwards, so a missing filter is a failed lookup rather than
a data leak — and a paper belonging to someone else is indistinguishable from one that does
not exist.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import Select, Text, and_, cast, delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from atlas.core.config import Settings
from atlas.core.errors import (
    ConflictError,
    NotFoundError,
    PayloadTooLargeError,
    UnsupportedMediaTypeError,
    ValidationError,
)
from atlas.core.logging import get_logger
from atlas.ingestion.pipeline import count_chunks
from atlas.models.job import IngestionJob, JobStatus
from atlas.models.library import Collection, CollectionPaper, PaperTag, Tag
from atlas.models.paper import (
    Paper,
    PaperChunk,
    PaperSection,
    PaperSource,
    ProcessingStatus,
    ReadingStatus,
)
from atlas.models.user import User
from atlas.schemas.paper import LibraryStats, PaperFilters, PaperUpdate
from atlas.storage.base import DocumentStore
from atlas.workers.queue import JobQueue

logger = get_logger(__name__)

PDF_MAGIC = b"%PDF-"
ACCEPTED_CONTENT_TYPES = frozenset({"application/pdf", "application/x-pdf"})


@dataclass(frozen=True, slots=True)
class UploadResult:
    paper: Paper
    job: IngestionJob | None
    """None when the upload matched a paper the user already has."""

    already_existed: bool


class PaperService:
    def __init__(self, db: AsyncSession, store: DocumentStore, settings: Settings) -> None:
        self._db = db
        self._store = store
        self._settings = settings

    # -- adding ------------------------------------------------------------------

    async def upload(
        self, *, owner: User, filename: str, content_type: str | None, data: bytes
    ) -> UploadResult:
        """Store an uploaded PDF and queue it for ingestion.

        The file is validated by its *contents*, not by the declared content type or the
        extension — both are attacker-controlled and neither says anything about the bytes.
        """
        self._validate_upload(filename=filename, content_type=content_type, data=data)

        stored = await self._store.put(namespace=owner.id.hex, filename=filename, data=data)

        existing = await self._db.scalar(
            select(Paper).where(
                Paper.owner_id == owner.id, Paper.content_hash == stored.content_hash
            )
        )
        if existing is not None:
            # The same bytes are already in this library. Returning the existing paper is
            # what the user wants; a duplicate row is not.
            logger.info(
                "upload matched an existing paper",
                extra={"paper_id": str(existing.id), "user_id": str(owner.id)},
            )
            return UploadResult(paper=existing, job=None, already_existed=True)

        paper = Paper(
            owner_id=owner.id,
            source=PaperSource.upload,
            original_filename=safe_filename(filename),
            storage_key=stored.key,
            content_hash=stored.content_hash,
            file_size_bytes=stored.size_bytes,
            status=ProcessingStatus.pending,
        )
        self._db.add(paper)

        try:
            await self._db.flush()
        except IntegrityError as exc:
            # Two concurrent uploads of the same file; the other one won.
            await self._db.rollback()
            raise ConflictError(
                "That paper is already in your library.", detail="duplicate content_hash"
            ) from exc

        # Enqueued in the same transaction as the paper, so an upload cannot half-succeed.
        job = await JobQueue(self._db).enqueue(
            paper.id, max_attempts=self._settings.job_max_attempts
        )

        logger.info(
            "paper uploaded",
            extra={
                "paper_id": str(paper.id),
                "user_id": str(owner.id),
                "size_bytes": stored.size_bytes,
            },
        )
        return UploadResult(paper=paper, job=job, already_existed=False)

    def _validate_upload(self, *, filename: str, content_type: str | None, data: bytes) -> None:
        if not data:
            raise ValidationError("That file is empty.")

        if len(data) > self._settings.max_upload_bytes:
            limit_mb = self._settings.max_upload_bytes // (1024 * 1024)
            raise PayloadTooLargeError(
                f"That file is larger than {limit_mb} MB. Try a smaller PDF."
            )

        # The declared type is a hint; the magic number is the fact. A file claiming to be a
        # PDF but starting with something else is either broken or hostile, and either way
        # must not reach the parser.
        if not data.startswith(PDF_MAGIC):
            raise UnsupportedMediaTypeError(
                "Atlas can only read PDFs at the moment.",
                detail=f"magic bytes were {data[:8]!r}, declared type {content_type!r}",
            )

        if content_type and content_type.split(";")[0].strip() not in ACCEPTED_CONTENT_TYPES:
            logger.info(
                "accepted a PDF with an unexpected content type",
                extra={"content_type": content_type, "filename": filename},
            )

    # -- reading -----------------------------------------------------------------

    async def get(self, *, owner: User, paper_id: uuid.UUID) -> Paper:
        paper = await self._db.scalar(
            select(Paper).where(Paper.id == paper_id, Paper.owner_id == owner.id)
        )
        if paper is None:
            # Deliberately identical to a genuinely missing paper: a 403 here would confirm
            # that the id exists in someone else's library.
            raise NotFoundError("We couldn't find that paper.")
        return paper

    async def list_papers(self, *, owner: User, filters: PaperFilters) -> tuple[list[Paper], int]:
        base = self._apply_filters(select(Paper).where(Paper.owner_id == owner.id), filters)

        total = await self._db.scalar(
            select(func.count()).select_from(base.order_by(None).subquery())
        )

        rows = await self._db.scalars(
            self._apply_sort(base, filters).limit(filters.limit).offset(filters.offset)
        )
        return list(rows), total or 0

    def _apply_filters(
        self, statement: Select[tuple[Paper]], filters: PaperFilters
    ) -> Select[tuple[Paper]]:
        if filters.search:
            # Substring matching over the fields a person scans when hunting for a paper
            # they already know they have. Semantic search over contents is a separate
            # feature with a separate endpoint.
            pattern = f"%{filters.search}%"
            statement = statement.where(
                or_(
                    Paper.title.ilike(pattern),
                    Paper.original_filename.ilike(pattern),
                    Paper.abstract.ilike(pattern),
                    # Author names live in JSONB; cast so a substring search reaches them.
                    cast(Paper.authors, Text).ilike(pattern),
                )
            )

        if filters.reading_status:
            statement = statement.where(Paper.reading_status == filters.reading_status)
        if filters.status:
            statement = statement.where(Paper.status == filters.status)
        if filters.favorites_only:
            statement = statement.where(Paper.is_favorite.is_(True))

        if filters.collection_id:
            statement = statement.where(
                Paper.id.in_(
                    select(CollectionPaper.paper_id).where(
                        CollectionPaper.collection_id == filters.collection_id
                    )
                )
            )

        if filters.tag:
            statement = statement.where(
                Paper.id.in_(
                    select(PaperTag.paper_id)
                    .join(Tag, Tag.id == PaperTag.tag_id)
                    .where(and_(Tag.name == filters.tag, Tag.owner_id == Paper.owner_id))
                )
            )

        return statement

    @staticmethod
    def _apply_sort(statement: Select[tuple[Paper]], filters: PaperFilters) -> Select[tuple[Paper]]:
        match filters.sort:
            case "title":
                # Papers still being read have no title yet; sort those to the end rather
                # than letting NULLs lead the list.
                return statement.order_by(Paper.title.asc().nullslast(), Paper.created_at.desc())
            case "year":
                return statement.order_by(
                    Paper.publication_year.desc().nullslast(), Paper.created_at.desc()
                )
            case "opened":
                return statement.order_by(
                    Paper.last_opened_at.desc().nullslast(), Paper.created_at.desc()
                )
            case _:
                return statement.order_by(Paper.created_at.desc())

    async def stats(self, *, owner: User) -> LibraryStats:
        """Every library counter in a single round trip."""
        row = (
            await self._db.execute(
                select(
                    func.count().label("total"),
                    func.count()
                    .filter(
                        Paper.status.in_([ProcessingStatus.pending, ProcessingStatus.processing])
                    )
                    .label("processing"),
                    func.count().filter(Paper.status == ProcessingStatus.failed).label("failed"),
                    func.count()
                    .filter(Paper.reading_status == ReadingStatus.unread)
                    .label("unread"),
                    func.count().filter(Paper.is_favorite.is_(True)).label("favorites"),
                ).where(Paper.owner_id == owner.id)
            )
        ).one()

        return LibraryStats(
            total=row.total,
            processing=row.processing,
            failed=row.failed,
            unread=row.unread,
            favorites=row.favorites,
        )

    async def progress_for(self, paper_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, IngestionJob]:
        """Latest job per paper, for a page of results.

        One query for the whole page rather than one per row: a library of forty papers
        should not cost forty round trips to render its progress bars.
        """
        if not paper_ids:
            return {}

        rows = await self._db.scalars(
            select(IngestionJob)
            .where(IngestionJob.paper_id.in_(paper_ids))
            .order_by(IngestionJob.paper_id, IngestionJob.created_at.desc())
        )

        latest: dict[uuid.UUID, IngestionJob] = {}
        for job in rows:
            # Ordered newest-first within each paper, so the first one wins.
            latest.setdefault(job.paper_id, job)
        return latest

    async def latest_job(self, paper_id: uuid.UUID) -> IngestionJob | None:
        return await self._db.scalar(
            select(IngestionJob)
            .where(IngestionJob.paper_id == paper_id)
            .order_by(IngestionJob.created_at.desc())
            .limit(1)
        )

    async def sections(self, *, owner: User, paper_id: uuid.UUID) -> list[PaperSection]:
        await self.get(owner=owner, paper_id=paper_id)
        rows = await self._db.scalars(
            select(PaperSection)
            .where(PaperSection.paper_id == paper_id)
            .order_by(PaperSection.ordinal)
        )
        return list(rows)

    async def counts_for(self, paper_id: uuid.UUID) -> tuple[int, int]:
        sections = await self._db.scalar(
            select(func.count()).select_from(PaperSection).where(PaperSection.paper_id == paper_id)
        )
        return sections or 0, await count_chunks(self._db, paper_id)

    async def file_bytes(self, *, owner: User, paper_id: uuid.UUID) -> tuple[Paper, bytes]:
        paper = await self.get(owner=owner, paper_id=paper_id)
        return paper, await self._store.get(paper.storage_key)

    # -- updating ----------------------------------------------------------------

    async def update(self, *, owner: User, paper_id: uuid.UUID, patch: PaperUpdate) -> Paper:
        paper = await self.get(owner=owner, paper_id=paper_id)
        changes = patch.model_dump(exclude_unset=True)

        if "authors" in changes and changes["authors"] is not None:
            changes["authors"] = [{"name": author["name"]} for author in changes["authors"]]

        for field, value in changes.items():
            setattr(paper, field, value)

        await self._db.flush()
        return paper

    async def mark_opened(self, *, owner: User, paper_id: uuid.UUID) -> Paper:
        """Record that the reader was opened, promoting an unread paper to 'reading'."""
        paper = await self.get(owner=owner, paper_id=paper_id)
        paper.last_opened_at = datetime.now(UTC)
        if paper.reading_status is ReadingStatus.unread:
            paper.reading_status = ReadingStatus.reading
        await self._db.flush()
        return paper

    # -- removing ----------------------------------------------------------------

    async def delete_paper(self, *, owner: User, paper_id: uuid.UUID) -> None:
        """Delete a paper and its derived data.

        The stored file is removed only if no other paper references it — content-addressed
        storage means two papers can legitimately share one blob.
        """
        paper = await self.get(owner=owner, paper_id=paper_id)
        storage_key = paper.storage_key

        # Sections, chunks, jobs, and memberships all cascade from the paper row.
        await self._db.delete(paper)
        await self._db.flush()

        still_referenced = await self._db.scalar(
            select(func.count()).select_from(Paper).where(Paper.storage_key == storage_key)
        )
        if not still_referenced:
            await self._store.delete(storage_key)

        logger.info("paper deleted", extra={"paper_id": str(paper_id), "user_id": str(owner.id)})

    async def reprocess(self, *, owner: User, paper_id: uuid.UUID) -> IngestionJob:
        """Queue a paper for ingestion again, after a failure or a parser improvement."""
        paper = await self.get(owner=owner, paper_id=paper_id)

        active = await self._db.scalar(
            select(IngestionJob).where(
                IngestionJob.paper_id == paper.id,
                IngestionJob.status.in_([JobStatus.queued, JobStatus.running]),
            )
        )
        if active is not None:
            raise ConflictError("Atlas is already processing that paper.")

        paper.status = ProcessingStatus.pending
        paper.failure_reason = None
        return await JobQueue(self._db).enqueue(
            paper.id, max_attempts=self._settings.job_max_attempts
        )


class CollectionService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def list_collections(self, *, owner: User) -> list[tuple[Collection, int]]:
        rows = await self._db.execute(
            select(Collection, func.count(CollectionPaper.paper_id))
            .outerjoin(CollectionPaper, CollectionPaper.collection_id == Collection.id)
            .where(Collection.owner_id == owner.id)
            .group_by(Collection.id)
            .order_by(Collection.name)
        )
        return [(collection, count) for collection, count in rows]

    async def create(self, *, owner: User, name: str, description: str | None) -> Collection:
        collection = Collection(owner_id=owner.id, name=name, description=description)
        self._db.add(collection)
        try:
            await self._db.flush()
        except IntegrityError as exc:
            await self._db.rollback()
            raise ConflictError("You already have a collection with that name.") from exc
        return collection

    async def get(self, *, owner: User, collection_id: uuid.UUID) -> Collection:
        collection = await self._db.scalar(
            select(Collection).where(
                Collection.id == collection_id, Collection.owner_id == owner.id
            )
        )
        if collection is None:
            raise NotFoundError("We couldn't find that collection.")
        return collection

    async def delete(self, *, owner: User, collection_id: uuid.UUID) -> None:
        collection = await self.get(owner=owner, collection_id=collection_id)
        await self._db.delete(collection)

    async def add_paper(
        self, *, owner: User, collection_id: uuid.UUID, paper_id: uuid.UUID
    ) -> None:
        await self.get(owner=owner, collection_id=collection_id)
        # Confirms the paper is the caller's before linking it.
        paper = await self._db.scalar(
            select(Paper).where(Paper.id == paper_id, Paper.owner_id == owner.id)
        )
        if paper is None:
            raise NotFoundError("We couldn't find that paper.")

        already = await self._db.get(CollectionPaper, (collection_id, paper_id))
        if already is None:
            self._db.add(CollectionPaper(collection_id=collection_id, paper_id=paper_id))
            await self._db.flush()

    async def remove_paper(
        self, *, owner: User, collection_id: uuid.UUID, paper_id: uuid.UUID
    ) -> None:
        await self.get(owner=owner, collection_id=collection_id)
        await self._db.execute(
            delete(CollectionPaper).where(
                CollectionPaper.collection_id == collection_id,
                CollectionPaper.paper_id == paper_id,
            )
        )


async def chunks_for_paper(db: AsyncSession, paper_id: uuid.UUID) -> list[PaperChunk]:
    rows = await db.scalars(
        select(PaperChunk).where(PaperChunk.paper_id == paper_id).order_by(PaperChunk.ordinal)
    )
    return list(rows)


def safe_filename(filename: str) -> str:
    """Reduce an uploaded name to something safe to store and display.

    The storage key is content-addressed, so a traversing name was never able to reach the
    filesystem, and the download header already strips what would break it. This is the third
    layer: the name is shown in the library, exported into citations, and read by a person, and
    none of those want `../../etc/passwd.pdf` in them.

    Directory components are dropped rather than escaped — a filename has no directories — and
    control characters go with them.
    """
    base = filename.replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = "".join(character for character in base if character.isprintable()).strip()
    cleaned = cleaned.lstrip(".") or "document.pdf"
    return cleaned[:500]
