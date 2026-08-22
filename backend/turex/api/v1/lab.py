"""Lab notebook endpoints.

**There is no update and no delete here.** Not one that is guarded — genuinely none, because
an endpoint that exists is an endpoint that can be reached, and the whole value of this record
is that what it says today is what it said when it was written.

The entries carry a hash chain, and `verify` walks it. See `turex/models/lab.py` for what that
proves and, just as importantly, what it does not.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from turex.api.deps import CurrentUser, LabServiceDep
from turex.schemas.lab import (
    ChainBreakRead,
    ChainReportRead,
    LabEntryCreate,
    LabEntryPage,
    LabEntryRead,
)

router = APIRouter(prefix="/lab", tags=["lab notebook"])


@router.post("/entries", response_model=LabEntryRead, status_code=status.HTTP_201_CREATED)
async def append_entry(
    payload: LabEntryCreate, user: CurrentUser, service: LabServiceDep
) -> LabEntryRead:
    """Append an entry. It cannot be edited or removed afterwards.

    The timestamp is the server's, not one the writer supplies — a date the author controls is
    the first thing that would be altered in a dispute. Work done at another time belongs in
    the body, where it reads as a claim rather than as something Turex is vouching for.
    """
    entry = await service.append(
        owner_id=user.id,
        body=payload.body,
        title=payload.title,
        project_id=payload.project_id,
        experiment_id=payload.experiment_id,
        paper_id=payload.paper_id,
    )
    return LabEntryRead.model_validate(entry)


@router.get("/entries", response_model=LabEntryPage)
async def list_entries(
    user: CurrentUser,
    service: LabServiceDep,
    project_id: Annotated[uuid.UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> LabEntryPage:
    entries, total = await service.list_entries(
        user.id, project_id=project_id, limit=limit, offset=offset
    )
    return LabEntryPage(
        items=[LabEntryRead.model_validate(entry) for entry in entries],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/verify", response_model=ChainReportRead)
async def verify_chain(user: CurrentUser, service: LabServiceDep) -> ChainReportRead:
    """Check every entry against its own hash and against the one before it.

    The whole chain, not a sample: the point is to be able to say the record is whole, and a
    spot check cannot say that.
    """
    report = await service.verify(user.id)
    return ChainReportRead(
        entries=report.entries,
        intact=report.intact,
        first_break_at=report.first_break_at,
        breaks=[
            ChainBreakRead(
                sequence=item.sequence,
                entry_id=item.entry_id,
                recorded_at=item.recorded_at,
                reason=item.reason,
            )
            for item in report.breaks
        ],
        checked_at=report.checked_at,
    )
