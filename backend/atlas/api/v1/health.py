"""Liveness and readiness endpoints."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text

from atlas.api.deps import DbDep
from atlas.core.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok"]


class ReadinessResponse(BaseModel):
    status: Literal["ready", "degraded"]
    database: Literal["ok", "unreachable"]


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """The process is up. Deliberately does no I/O so it never fails on a slow dependency."""
    return HealthResponse(status="ok")


@router.get("/ready", response_model=ReadinessResponse)
async def ready(db: DbDep) -> ReadinessResponse:
    """The process can serve traffic — i.e. its dependencies answer."""
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        logger.exception("readiness probe failed: database unreachable")
        return ReadinessResponse(status="degraded", database="unreachable")
    return ReadinessResponse(status="ready", database="ok")
