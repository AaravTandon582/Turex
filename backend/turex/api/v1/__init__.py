"""Version 1 of the Turex API."""

from fastapi import APIRouter

from turex.api.v1 import (
    analysis,
    annotations,
    assistant,
    auth,
    catalog,
    collections,
    discovery,
    health,
    lab,
    papers,
    study,
    workspace,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(papers.router)
api_router.include_router(catalog.router)
api_router.include_router(analysis.router)
api_router.include_router(lab.router)
api_router.include_router(collections.router)
api_router.include_router(assistant.router)
api_router.include_router(annotations.router)
api_router.include_router(workspace.router)
api_router.include_router(discovery.router)
api_router.include_router(study.router)

__all__ = ["api_router"]
