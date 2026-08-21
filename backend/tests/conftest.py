"""Shared test fixtures.

Tests run against a real PostgreSQL database (`atlas_test` by default) rather than SQLite,
because Atlas depends on Postgres-specific behaviour — pgvector, `gen_random_uuid()`, JSONB.
A suite that passes on SQLite would not tell us the application works.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from alembic.config import Config
from fastapi import Depends
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from alembic import command
from atlas.ai.registry import reset_registry
from atlas.api.deps import (
    get_assistant_service,
    get_db,
    get_retrieval_service,
    reset_rate_limits,
)
from atlas.catalog.service import reset_stats_cache
from atlas.core.config import Environment, Settings, get_settings
from atlas.db.base import Base
from atlas.db.session import dispose_engine, init_engine, session_scope
from atlas.main import create_app
from atlas.retrieval.search import RetrievalService
from atlas.services.assistant_service import AssistantService
from atlas.storage.local import LocalDocumentStore
from atlas.workers.runner import IngestionWorker
from tests.support.scripted_provider import ScriptedChatProvider

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "postgresql+asyncpg://localhost/atlas_test")


@pytest.fixture(scope="session")
def storage_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("atlas-storage")


@pytest.fixture(scope="session")
def settings(storage_root: Path) -> Settings:
    return Settings(
        environment=Environment.test,
        debug=True,
        database_url=TEST_DATABASE_URL,  # type: ignore[arg-type]
        secret_key="test-secret-key-not-used-anywhere-real",
        cookie_secure=False,
        # Workers are driven explicitly in tests so ingestion is deterministic rather than
        # racing a background poller.
        worker_enabled=False,
        storage_root=storage_root,
        # The deterministic hashing embedder: retrieval runs, and ranks, with no API key and
        # no network. This is what makes the retrieval suite runnable in CI.
        embedding_provider="local",
        chat_provider="anthropic",
        anthropic_api_key=None,
    )


@pytest.fixture(scope="session", autouse=True)
def migrated_database(settings: Settings) -> Iterator[None]:
    """Bring the test database to head once per session."""
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", str(settings.database_url))
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    yield


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def app(settings: Settings) -> AsyncIterator[object]:
    reset_registry()
    application = create_app(settings)
    application.dependency_overrides[get_settings] = lambda: settings
    init_engine(settings)
    yield application
    await dispose_engine()


@pytest.fixture(autouse=True)
def clean_caches() -> None:
    """Process-wide caches outlive the database, so they are cleared with it."""
    reset_stats_cache()


@pytest.fixture(autouse=True)
def clean_rate_limits() -> None:
    """Start every test with empty counters.

    The limiter is process-global by design — that is what makes it work — so without this the
    suite exhausts the registration limit partway through and later tests fail for reasons
    that have nothing to do with what they are testing.
    """
    reset_rate_limits()


@pytest.fixture(autouse=True)
async def clean_tables(app: object, settings: Settings) -> AsyncIterator[None]:
    """Leave the database empty after every test so tests cannot depend on each other.

    Every table is named, derived from the metadata, rather than truncating `users` and
    trusting the cascade. Most tables do reach users through a foreign key — papers, chunks,
    jobs, collections, tags — but not all of them do: the catalog holds public metadata shared
    by every account and `rate_limit_counters` is keyed by a hash. Those survived a cascade
    from `users` and leaked into the next test, which showed up as a search finding a thousand
    papers a test had never inserted.

    Deriving the list means the next table someone adds is cleaned without anyone having to
    remember this file exists.
    """
    yield
    tables = ", ".join(sorted(table.name for table in Base.metadata.sorted_tables))
    async with session_scope() as session:
        await session.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture
async def client(app: object, settings: Settings) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
        follow_redirects=True,
    ) as http_client:
        yield http_client


@pytest.fixture
async def db() -> AsyncIterator[AsyncSession]:
    async with session_scope() as session:
        yield session


@pytest.fixture
def api(settings: Settings) -> str:
    return settings.api_prefix


REGISTRATION = {
    "email": "ada@example.edu",
    "full_name": "Ada Lovelace",
    "password": "analytical-engine-1843",
}


@pytest.fixture
async def registered_client(client: AsyncClient, api: str) -> AsyncClient:
    """A client with an authenticated session already established."""
    response = await client.post(f"{api}/auth/register", json=REGISTRATION)
    assert response.status_code == 201, response.text
    return client


SECOND_REGISTRATION = {
    "email": "grace@example.edu",
    "full_name": "Grace Hopper",
    "password": "compiler-invention-1952",
}


@pytest.fixture
async def other_client(app: object, settings: Settings) -> AsyncIterator[AsyncClient]:
    """A second signed-in user, for verifying that libraries are private."""
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://testserver") as http_client:
        response = await http_client.post(
            f"{settings.api_prefix}/auth/register", json=SECOND_REGISTRATION
        )
        assert response.status_code == 201, response.text
        yield http_client


@pytest.fixture
def run_worker(settings: Settings):  # type: ignore[no-untyped-def]
    """Drain the ingestion queue synchronously.

    Tests call this instead of waiting on the background pool, so a test asserts on a
    finished pipeline rather than polling and hoping.
    """

    async def drain(limit: int = 10) -> int:
        worker = IngestionWorker(settings, LocalDocumentStore(settings.storage_root))
        processed = 0
        for _ in range(limit):
            if not await worker.run_once():
                break
            processed += 1
        return processed

    return drain


@pytest.fixture
def scripted(app: object):  # type: ignore[no-untyped-def]
    """Install a scripted model behind the real assistant service.

    Reuses the real database session and the real retrieval service; only the model is
    replaced, so retrieval, persistence, and citation building are genuinely exercised.
    """
    holder: dict[str, ScriptedChatProvider] = {"provider": ScriptedChatProvider()}

    def factory(
        session: AsyncSession = Depends(get_db),
        retrieval: RetrievalService = Depends(get_retrieval_service),
    ) -> AssistantService:
        return AssistantService(session, retrieval, lambda: holder["provider"])

    app.dependency_overrides[get_assistant_service] = factory  # type: ignore[attr-defined]
    yield holder
    app.dependency_overrides.pop(get_assistant_service, None)  # type: ignore[attr-defined]
