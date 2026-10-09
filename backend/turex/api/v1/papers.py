"""Library endpoints: adding papers, browsing them, and reading their files."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, File, Query, Response, UploadFile, status

from turex.api.deps import CurrentUser, GuardDep, PaperServiceDep
from turex.core.errors import AppError
from turex.ingestion.bibliography import parse_bibliography
from turex.models.job import STAGE_LABELS, IngestionJob
from turex.models.paper import Paper
from turex.models.user import User
from turex.schemas.paper import (
    AddByReference,
    EquationRead,
    ImportFailure,
    IngestionProgress,
    LibraryExportQuery,
    LibraryStats,
    Page,
    PaperDetail,
    PaperFilters,
    PaperSummary,
    PaperUpdate,
    ReferenceImportResult,
    ReferenceRead,
    SectionRead,
)
from turex.security import policy
from turex.services.library_export import (
    CONTENT_TYPES,
    FILE_SUFFIXES,
    export_papers,
)
from turex.services.paper_service import PaperService

PAGE_SIZE = 100
"""How many papers an export reads at a time — the largest page `PaperFilters` allows."""

EXPORT_CEILING = 10_000
"""How many papers one export may contain.

Not a page size — a bound on how much work one request can ask for. A personal library is
thousands, and anything past this is a request nobody made on purpose.
"""

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


async def build_detail(service: PaperService, paper: Paper) -> PaperDetail:
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
    await guard.by_user(user.id, policy.UPLOADS_PER_USER, scope="upload")

    data = await file.read()
    result = await service.upload(
        owner=user,
        filename=file.filename or "document.pdf",
        content_type=file.content_type,
        data=data,
    )
    if result.already_existed:
        response.status_code = status.HTTP_200_OK
    return await build_detail(service, result.paper)


@router.post("/from-reference", response_model=PaperDetail, status_code=status.HTTP_202_ACCEPTED)
async def add_paper_from_reference(
    payload: AddByReference,
    user: CurrentUser,
    service: PaperServiceDep,
    response: Response,
    guard: GuardDep,
) -> PaperDetail:
    """Add a paper from a link, a DOI, or an arXiv id.

    Answers as an upload does: **202** when the document is queued, **200** when those exact
    bytes are already in the library.

    Fetching a URL a caller supplied is a server-side request forgery risk, so the fetcher
    refuses non-public addresses and re-checks on every redirect — see `ingestion/fetching.py`.
    """
    await guard.by_user(user.id, policy.UPLOADS_PER_USER, scope="upload")
    result = await service.add_from_identifier(owner=user, reference=payload.reference)
    if result.already_existed:
        response.status_code = status.HTTP_200_OK
    return await build_detail(service, result.paper)


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


@router.get("/export")
async def export_library(
    user: CurrentUser,
    service: PaperServiceDep,
    query: Annotated[LibraryExportQuery, Query()],
) -> Response:
    """The library — or any slice of it — as a bibliography file.

    Takes the same filters as the list, so what you are looking at is what you export: a
    collection, a tag, a search, the whole thing.

    A file that other tools read, not a Turex format. BibTeX for LaTeX and every reference
    manager, RIS for Zotero and Mendeley, CSL-JSON for Pandoc and Quarto — all of them plain
    text, diffable, and readable in ten years without this application.
    """
    found = await _every_match(service, user, query)
    body = export_papers(found, query.format)

    return Response(
        content=body,
        media_type=CONTENT_TYPES[query.format],
        headers={
            # `attachment` so a browser saves it rather than rendering a wall of BibTeX.
            "Content-Disposition": (
                f'attachment; filename="turex-library.{FILE_SUFFIXES[query.format]}"'
            ),
        },
    )


async def _every_match(service: PaperService, user: User, query: LibraryExportQuery) -> list[Paper]:
    """Every paper the filters select, not just the first page.

    An export is a file, not a screen. Honouring a `limit` of 24 would quietly produce a
    bibliography with 24 entries in it, which is the kind of truncation someone discovers when
    a citation is missing from a manuscript they have already submitted.

    Paged rather than asked for in one go, because `PaperFilters` caps a page at 100 and that
    cap is there for a reason — an unbounded page size is how one request loads an entire
    table into memory. Raising it for this caller would weaken the rule for every caller; a
    loop respects it and costs one indexed query per hundred papers.
    """
    collected: list[Paper] = []
    base = query.model_dump(exclude={"format", "limit", "offset"})

    while len(collected) < EXPORT_CEILING:
        page = PaperFilters.model_validate(base | {"limit": PAGE_SIZE, "offset": len(collected)})
        found, total = await service.list_papers(owner=user, filters=page)
        collected.extend(found)
        if not found or len(collected) >= total:
            break

    return collected[:EXPORT_CEILING]


@router.post("/import-references", response_model=ReferenceImportResult)
async def import_references(
    user: CurrentUser,
    service: PaperServiceDep,
    guard: GuardDep,
    file: Annotated[UploadFile, File(description="A .bib or .ris file")],
) -> ReferenceImportResult:
    """Bring a bibliography in from Zotero, Mendeley, or a `.bib` beside a manuscript.

    Every entry carrying a DOI or an arXiv id is fetched and ingested exactly as "add by
    reference" would — same SSRF checks, same validation, same pipeline. Entries with neither
    are reported rather than stored: without an identifier there is nothing to fetch, and a
    row that can never become a readable paper is worse than an honest count of what was left
    behind.
    """
    await guard.by_user(user.id, policy.UPLOADS_PER_USER, scope="upload")

    raw = await file.read()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        # Reference managers still emit Latin-1 on Windows. Trying it costs nothing and is
        # the difference between an import working and a file that "isn't valid".
        text = raw.decode("latin-1", errors="replace")

    parsed = parse_bibliography(text, filename=file.filename or "")

    imported: list[str] = []
    failed: list[ImportFailure] = []

    for entry in parsed.entries:
        identifier = entry.identifier
        if identifier is None:
            continue
        try:
            result = await service.add_from_identifier(owner=user, reference=identifier)
            imported.append(str(result.paper.id))
        except AppError as exc:
            # One unreachable paper must not abandon the other fifty-nine. Each failure is
            # named so the reader can go and get that one by hand.
            failed.append(
                ImportFailure(reference=identifier, title=entry.title, reason=exc.message)
            )

    return ReferenceImportResult(
        found=len(parsed.entries),
        imported=len(imported),
        without_identifier=parsed.skipped,
        failed=failed,
    )


@router.get("/stats", response_model=LibraryStats)
async def library_stats(user: CurrentUser, service: PaperServiceDep) -> LibraryStats:
    return await service.stats(owner=user)


@router.get("/{paper_id}", response_model=PaperDetail)
async def get_paper(
    paper_id: uuid.UUID, user: CurrentUser, service: PaperServiceDep
) -> PaperDetail:
    paper = await service.get(owner=user, paper_id=paper_id)
    return await build_detail(service, paper)


@router.patch("/{paper_id}", response_model=PaperDetail)
async def update_paper(
    paper_id: uuid.UUID, patch: PaperUpdate, user: CurrentUser, service: PaperServiceDep
) -> PaperDetail:
    paper = await service.update(owner=user, paper_id=paper_id, patch=patch)
    return await build_detail(service, paper)


@router.post("/{paper_id}/opened", response_model=PaperDetail)
async def mark_opened(
    paper_id: uuid.UUID, user: CurrentUser, service: PaperServiceDep
) -> PaperDetail:
    """Record that the reader was opened. Moves an unread paper to 'reading'."""
    paper = await service.mark_opened(owner=user, paper_id=paper_id)
    return await build_detail(service, paper)


@router.post(
    "/{paper_id}/reprocess", response_model=PaperDetail, status_code=status.HTTP_202_ACCEPTED
)
async def reprocess_paper(
    paper_id: uuid.UUID, user: CurrentUser, service: PaperServiceDep
) -> PaperDetail:
    await service.reprocess(owner=user, paper_id=paper_id)
    paper = await service.get(owner=user, paper_id=paper_id)
    return await build_detail(service, paper)


@router.get("/{paper_id}/equations", response_model=list[EquationRead])
async def list_equations(
    paper_id: uuid.UUID, user: CurrentUser, service: PaperServiceDep
) -> list[EquationRead]:
    """The displayed equations found in this paper.

    Detection is heuristic — PDF text carries no markup for mathematics — so this list is
    approximate in a way the rest of the API is not, and the reader should be told so rather
    than shown an incomplete list presented as complete.
    """
    equations = await service.equations(owner=user, paper_id=paper_id)
    return [EquationRead.model_validate(equation, from_attributes=True) for equation in equations]


@router.get("/{paper_id}/references", response_model=list[ReferenceRead])
async def list_references(
    paper_id: uuid.UUID, user: CurrentUser, service: PaperServiceDep
) -> list[ReferenceRead]:
    """This paper's bibliography, split into entries.

    Parsed from extracted text, so approximate. Entries carrying an arXiv id or a DOI can be
    added to the library directly through `POST /papers/from-reference`.
    """
    references = await service.references(owner=user, paper_id=paper_id)
    return [ReferenceRead.model_validate(entry, from_attributes=True) for entry in references]


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
