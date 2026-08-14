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
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from alembic import command
from atlas.core.config import Environment, Settings, get_settings
from atlas.db.session import dispose_engine, init_engine, session_scope
from atlas.main import create_app
from atlas.storage.local import LocalDocumentStore
from atlas.workers.runner import IngestionWorker

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
    application = create_app(settings)
    application.dependency_overrides[get_settings] = lambda: settings
    init_engine(settings)
    yield application
    await dispose_engine()


@pytest.fixture(autouse=True)
async def clean_tables(app: object, settings: Settings) -> AsyncIterator[None]:
    """Leave the database empty after every test so tests cannot depend on each other."""
    yield
    async with session_scope() as session:
        # Papers, sections, chunks, jobs, collections, and tags all cascade from users.
        await session.execute(text("TRUNCATE users RESTART IDENTITY CASCADE"))


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
