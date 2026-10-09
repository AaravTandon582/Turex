"""Analysis endpoints: the notebooks attached to a research project.

**The server never runs any of this.** Code entered here executes in the reader's own browser,
in Python compiled to WebAssembly, and only the resulting text is sent back to be stored. That
boundary is the whole security argument for the feature, and it is why `POST .../run` takes a
*result* rather than a request to execute something — there is no execution endpoint to
attack, and adding one would be adding remote code execution to a research tool.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from turex.api.deps import AnalysisServiceDep, CurrentUser
from turex.models.analysis import Analysis
from turex.schemas.analysis import (
    AnalysisCreate,
    AnalysisRead,
    AnalysisUpdate,
    CellCreate,
    CellMove,
    CellRead,
    CellRun,
    CellUpdate,
)
from turex.services.analysis_service import CellResult

router = APIRouter(prefix="/analyses", tags=["analyses"])

STARTER = """import numpy as np

# Everything runs in your browser — numpy, pandas, matplotlib and scipy are available.
# Nothing here reaches the server or the internet.
values = np.array([2, 4, 4, 4, 5, 5, 7, 9])
print("mean", values.mean(), "sd", values.std())
"""


def _read(analysis: Analysis) -> AnalysisRead:
    detail = AnalysisRead.model_validate(analysis)
    detail.cells = [
        CellRead.model_validate(cell)
        for cell in sorted(analysis.cells, key=lambda cell: cell.ordinal)
    ]
    return detail


@router.get("", response_model=list[AnalysisRead])
async def list_analyses(
    user: CurrentUser,
    service: AnalysisServiceDep,
    project_id: Annotated[uuid.UUID | None, Query()] = None,
) -> list[AnalysisRead]:
    found = await service.list_for(user.id, project_id=project_id)
    return [_read(analysis) for analysis in found]


@router.post("", response_model=AnalysisRead, status_code=status.HTTP_201_CREATED)
async def create_analysis(
    payload: AnalysisCreate, user: CurrentUser, service: AnalysisServiceDep
) -> AnalysisRead:
    """Start an analysis, with one cell already in it.

    The starter cell is a working example rather than a comment, because the first question a
    computational notebook has to answer is "does this actually run", and a cell you can press
    play on answers it in two seconds.
    """
    analysis = await service.create(
        owner_id=user.id,
        title=payload.title,
        description=payload.description,
        project_id=payload.project_id,
        experiment_id=payload.experiment_id,
        starter=STARTER,
    )
    return _read(analysis)


@router.get("/{analysis_id}", response_model=AnalysisRead)
async def read_analysis(
    analysis_id: uuid.UUID, user: CurrentUser, service: AnalysisServiceDep
) -> AnalysisRead:
    return _read(await service.get(user.id, analysis_id))


@router.patch("/{analysis_id}", response_model=AnalysisRead)
async def update_analysis(
    analysis_id: uuid.UUID,
    payload: AnalysisUpdate,
    user: CurrentUser,
    service: AnalysisServiceDep,
) -> AnalysisRead:
    analysis = await service.update(
        owner_id=user.id,
        analysis_id=analysis_id,
        title=payload.title,
        description=payload.description,
    )
    return _read(analysis)


@router.delete("/{analysis_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_analysis(
    analysis_id: uuid.UUID, user: CurrentUser, service: AnalysisServiceDep
) -> None:
    await service.delete(user.id, analysis_id)


@router.post("/{analysis_id}/cells", response_model=CellRead, status_code=status.HTTP_201_CREATED)
async def add_cell(
    analysis_id: uuid.UUID,
    payload: CellCreate,
    user: CurrentUser,
    service: AnalysisServiceDep,
) -> CellRead:
    cell = await service.add_cell(
        owner_id=user.id,
        analysis_id=analysis_id,
        kind=payload.kind,
        source=payload.source,
        after=payload.after,
    )
    return CellRead.model_validate(cell)


@router.put("/{analysis_id}/cells/{cell_id}", response_model=CellRead)
async def save_cell(
    analysis_id: uuid.UUID,
    cell_id: uuid.UUID,
    payload: CellUpdate,
    user: CurrentUser,
    service: AnalysisServiceDep,
) -> CellRead:
    """Save what was typed.

    A cell that already ran becomes **stale** here, because its stored output no longer
    corresponds to its code. Showing a number beside code that does not produce it is worse
    than showing nothing: the number looks checked.
    """
    cell = await service.save_source(
        owner_id=user.id,
        analysis_id=analysis_id,
        cell_id=cell_id,
        source=payload.source,
        kind=payload.kind,
    )
    return CellRead.model_validate(cell)


@router.post("/{analysis_id}/cells/{cell_id}/run", response_model=CellRead)
async def record_run(
    analysis_id: uuid.UUID,
    cell_id: uuid.UUID,
    payload: CellRun,
    user: CurrentUser,
    service: AnalysisServiceDep,
) -> CellRead:
    """Record what the browser got when it ran this cell.

    Nothing is executed here. The name is `run` because that is what the user did; what the
    server does is write down the answer.
    """
    cell = await service.record_run(
        owner_id=user.id,
        analysis_id=analysis_id,
        cell_id=cell_id,
        result=CellResult(
            source=payload.source,
            output=payload.output,
            image=payload.image,
            error=payload.error,
            duration_ms=payload.duration_ms,
        ),
    )
    return CellRead.model_validate(cell)


@router.post("/{analysis_id}/cells/{cell_id}/move", response_model=AnalysisRead)
async def move_cell(
    analysis_id: uuid.UUID,
    cell_id: uuid.UUID,
    payload: CellMove,
    user: CurrentUser,
    service: AnalysisServiceDep,
) -> AnalysisRead:
    analysis = await service.move_cell(
        owner_id=user.id, analysis_id=analysis_id, cell_id=cell_id, offset=payload.offset
    )
    return _read(analysis)


@router.delete("/{analysis_id}/cells/{cell_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_cell(
    analysis_id: uuid.UUID,
    cell_id: uuid.UUID,
    user: CurrentUser,
    service: AnalysisServiceDep,
) -> None:
    await service.delete_cell(owner_id=user.id, analysis_id=analysis_id, cell_id=cell_id)
