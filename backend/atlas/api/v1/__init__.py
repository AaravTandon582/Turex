"""Version 1 of the Atlas API."""

from fastapi import APIRouter

from atlas.api.v1 import annotations, assistant, auth, collections, health, papers

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(papers.router)
api_router.include_router(collections.router)
api_router.include_router(assistant.router)
api_router.include_router(annotations.router)

__all__ = ["api_router"]
