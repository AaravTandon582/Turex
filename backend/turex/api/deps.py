"""Shared FastAPI dependencies."""

from __future__ import annotations

import uuid
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from turex.ai.registry import ProviderRegistry, get_registry
from turex.catalog.service import CatalogService
from turex.core.config import Settings, get_settings
from turex.core.errors import UnauthenticatedError
from turex.core.logging import bind_request_context
from turex.core.security import ACCESS_COOKIE_NAME, decode_access_token
from turex.db.session import get_db, get_session_factory
from turex.models.user import User, UserSession
from turex.retrieval.search import RetrievalService
from turex.security.database_limiter import DatabaseRateLimiter
from turex.security.guard import Guard
from turex.security.rate_limit import (
    Decision,
    InMemoryRateLimiter,
    Limit,
    RateLimiter,
)
from turex.services.analysis_service import AnalysisService
from turex.services.annotation_service import AnnotationService
from turex.services.assistant_service import AssistantService
from turex.services.auth_service import AuthService, ClientInfo
from turex.services.lab_service import LabService
from turex.services.paper_service import CollectionService, PaperService
from turex.services.study_service import StudyService
from turex.services.workspace_service import WorkspaceService
from turex.storage.base import DocumentStore
from turex.storage.local import LocalDocumentStore

SettingsDep = Annotated[Settings, Depends(get_settings)]
DbDep = Annotated[AsyncSession, Depends(get_db)]


def get_client_info(request: Request) -> ClientInfo:
    return ClientInfo(
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
    )


ClientInfoDep = Annotated[ClientInfo, Depends(get_client_info)]


def get_auth_service(db: DbDep, settings: SettingsDep) -> AuthService:
    return AuthService(db, settings)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


# One limiter for the process. Its counters are the state that makes limiting work, so it must
# not be rebuilt per request — a fresh limiter every time would enforce nothing at all.
_limiter = InMemoryRateLimiter()


def reset_rate_limits() -> None:
    """Clear every counter.

    Exists for the test suite, which would otherwise share one limiter across hundreds of
    tests and start rejecting registrations partway through a run — a failure that looks like
    a bug in whatever test happened to be unlucky.
    """
    global _limiter
    _limiter = InMemoryRateLimiter()


def get_guard(settings: SettingsDep) -> Guard:
    if not settings.rate_limiting_enabled:
        return Guard(_NoopLimiter())
    if settings.rate_limiting_shared:
        return Guard(DatabaseRateLimiter(get_session_factory()))
    return Guard(_limiter)


GuardDep = Annotated[Guard, Depends(get_guard)]


class _NoopLimiter(RateLimiter):
    """Allows everything. Only reachable when rate limiting is deliberately disabled, which
    `check_production_readiness` refuses to let happen in production."""

    async def check(self, key: str, limit: Limit) -> Decision:
        return Decision(allowed=True, remaining=limit.requests, retry_after_seconds=0)


@lru_cache(maxsize=1)
def _document_store(root: Path) -> DocumentStore:
    """One store per process. Cached because construction creates the root directory."""
    return LocalDocumentStore(root)


def get_document_store(settings: SettingsDep) -> DocumentStore:
    return _document_store(settings.storage_root)


DocumentStoreDep = Annotated[DocumentStore, Depends(get_document_store)]


def get_paper_service(db: DbDep, store: DocumentStoreDep, settings: SettingsDep) -> PaperService:
    return PaperService(db, store, settings)


PaperServiceDep = Annotated[PaperService, Depends(get_paper_service)]


def get_analysis_service(db: DbDep) -> AnalysisService:
    return AnalysisService(db)


AnalysisServiceDep = Annotated[AnalysisService, Depends(get_analysis_service)]


def get_lab_service(db: DbDep) -> LabService:
    return LabService(db)


LabServiceDep = Annotated[LabService, Depends(get_lab_service)]


def get_catalog_service(db: DbDep) -> CatalogService:
    return CatalogService(db)


CatalogServiceDep = Annotated[CatalogService, Depends(get_catalog_service)]


def get_collection_service(db: DbDep) -> CollectionService:
    return CollectionService(db)


CollectionServiceDep = Annotated[CollectionService, Depends(get_collection_service)]


def get_annotation_service(db: DbDep) -> AnnotationService:
    return AnnotationService(db)


AnnotationServiceDep = Annotated[AnnotationService, Depends(get_annotation_service)]


def get_workspace_service(db: DbDep) -> WorkspaceService:
    return WorkspaceService(db)


WorkspaceServiceDep = Annotated[WorkspaceService, Depends(get_workspace_service)]


def get_provider_registry(settings: SettingsDep) -> ProviderRegistry:
    return get_registry(settings)


ProviderRegistryDep = Annotated[ProviderRegistry, Depends(get_provider_registry)]


def get_retrieval_service(db: DbDep, registry: ProviderRegistryDep) -> RetrievalService:
    return RetrievalService(db, registry.embedder())


RetrievalServiceDep = Annotated[RetrievalService, Depends(get_retrieval_service)]


def get_assistant_service(
    db: DbDep, retrieval: RetrievalServiceDep, registry: ProviderRegistryDep
) -> AssistantService:
    # The provider is passed as a factory. `registry.chat()` raises NotConfiguredError when no
    # key is set; deferring the call means only the endpoints that need a model fail, so a
    # user can still read their past conversations on an instance with no key.
    return AssistantService(db, retrieval, registry.chat)


AssistantServiceDep = Annotated[AssistantService, Depends(get_assistant_service)]


def get_study_service(db: DbDep, registry: ProviderRegistryDep) -> StudyService:
    return StudyService(db, registry.chat)


StudyServiceDep = Annotated[StudyService, Depends(get_study_service)]


async def get_current_user(request: Request, db: DbDep, settings: SettingsDep) -> User:
    """Resolve the signed-in user, or reject the request.

    The session row is checked alongside the token so that signing out takes effect
    immediately rather than when the access token happens to expire.
    """
    token = request.cookies.get(ACCESS_COOKIE_NAME)
    if not token:
        raise UnauthenticatedError(detail="no access cookie present")

    claims = decode_access_token(token, secret_key=settings.secret_key)
    if claims is None:
        raise UnauthenticatedError(detail="access token invalid or expired")

    try:
        user_id = uuid.UUID(claims.user_id)
        session_id = uuid.UUID(claims.session_id)
    except ValueError as exc:
        raise UnauthenticatedError(detail="access token carried malformed identifiers") from exc

    row = (
        await db.execute(
            select(User, UserSession)
            .join(UserSession, UserSession.user_id == User.id)
            .where(User.id == user_id, UserSession.id == session_id)
        )
    ).first()

    if row is None:
        raise UnauthenticatedError(detail="session no longer exists")

    user, session = row
    if not session.is_active:
        raise UnauthenticatedError(detail="session revoked or expired")
    if not user.is_active:
        raise UnauthenticatedError(detail="user account is disabled")

    bind_request_context(user_id=str(user.id))
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
