"""Turex API application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from turex.api.exception_handlers import register_exception_handlers
from turex.api.middleware import RequestContextMiddleware
from turex.api.v1 import api_router
from turex.core.config import Settings, get_settings
from turex.core.logging import configure_logging, get_logger
from turex.db.session import dispose_engine, init_engine
from turex.storage.local import LocalDocumentStore
from turex.workers.runner import WorkerPool

logger = get_logger(__name__)

DESCRIPTION = """
Turex is an intelligent research workspace: read papers, understand them, connect ideas,
form hypotheses, and design experiments in one place.
""".strip()


def _lifespan(settings: Settings):  # type: ignore[no-untyped-def]
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        init_engine(settings)
        # Ingestion runs as background tasks in this process; see docs/decisions.md D2.
        workers = WorkerPool(settings, LocalDocumentStore(settings.storage_root))
        await workers.start()
        logger.info("turex api started", extra={"environment": settings.environment.value})
        try:
            yield
        finally:
            await workers.stop()
            await dispose_engine()
            logger.info("turex api stopped")

    return lifespan


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    configure_logging(
        json_output=settings.is_production,
        level=logging.DEBUG if settings.debug else logging.INFO,
    )

    if settings.is_production:
        for problem in settings.check_production_readiness():
            logger.critical("insecure production configuration: %s", problem)

    app = FastAPI(
        title="Turex",
        description=DESCRIPTION,
        version="0.1.0",
        lifespan=_lifespan(settings),
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",
    )

    # Read by `security.guard.client_address`, which needs it on every request and must not
    # reach for global settings to get it.
    app.state.trust_proxy_headers = settings.trust_proxy_headers

    app.add_middleware(RequestContextMiddleware, send_hsts=settings.cookie_secure)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,  # Session cookies must accompany cross-origin requests.
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        # `range` is included because pdf.js issues ranged requests when fetching a
        # document cross-origin; without it the preflight fails and the reader shows
        # nothing.
        allow_headers=["content-type", "x-request-id", "range"],
        expose_headers=["x-request-id", "content-length", "accept-ranges", "content-range"],
    )

    register_exception_handlers(app, settings)
    app.include_router(api_router, prefix=settings.api_prefix)
    return app


# Run with:  uvicorn turex.main:create_app --factory
# The factory form keeps import of this module side-effect free, so tests can build an app
# with their own settings instead of inheriting a module-level one.
