"""Regression coverage for invalid links, unavailable providers, and worker failures."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from tests.test_reader import upload
from tests.test_workspace import make_hypothesis, make_project
from turex.ai.registry import ProviderRegistry
from turex.api.deps import SettingsDep, get_provider_registry
from turex.core.config import Settings
from turex.core.errors import ProcessingFailedError
from turex.ingestion.pipeline import IngestionPipeline
from turex.main import create_app
from turex.models.job import IngestionJob
from turex.models.paper import Paper


@pytest.mark.parametrize("missing", [False, True])
@pytest.mark.parametrize(
    ("resource", "field"),
    [
        ("hypotheses", "project_id"),
        ("experiments", "hypothesis_id"),
        ("notes", "project_id"),
        ("notes", "hypothesis_id"),
        ("notes", "paper_id"),
    ],
)
async def test_updates_refuse_foreign_or_missing_links(
    registered_client: AsyncClient,
    other_client: AsyncClient,
    api: str,
    resource: str,
    field: str,
    missing: bool,
) -> None:
    if missing:
        target = str(uuid.uuid4())
    elif field == "project_id":
        target = await make_project(other_client, api)
    elif field == "hypothesis_id":
        target = await make_hypothesis(other_client, api)
    else:
        target = await upload(other_client, api)

    payload = {"statement": "A claim"} if resource == "hypotheses" else {"title": "A record"}
    made = await registered_client.post(f"{api}/{resource}", json=payload)
    assert made.status_code == 201, made.text
    url = f"{api}/{resource}/{made.json()['id']}"
    response = await registered_client.patch(url, json={field: target})
    assert response.status_code == 404, response.text
    assert (await registered_client.get(url)).json()[field] is None


@pytest.mark.parametrize("field", ["paper_id", "hypothesis_id"])
@pytest.mark.parametrize("missing", [False, True])
async def test_notes_validate_links_on_creation(
    registered_client: AsyncClient,
    other_client: AsyncClient,
    api: str,
    field: str,
    missing: bool,
) -> None:
    if missing:
        target = str(uuid.uuid4())
    elif field == "paper_id":
        target = await upload(other_client, api)
    else:
        target = await make_hypothesis(other_client, api)
    response = await registered_client.post(f"{api}/notes", json={field: target})
    assert response.status_code == 404, response.text


@pytest.mark.parametrize("resource", ["hypotheses", "tasks"])
async def test_null_positions_are_validation_errors(
    registered_client: AsyncClient, api: str, resource: str
) -> None:
    if resource == "hypotheses":
        record_id = await make_hypothesis(registered_client, api)
    else:
        project_id = await make_project(registered_client, api)
        made = await registered_client.post(
            f"{api}/projects/{project_id}/tasks", json={"title": "Read"}
        )
        record_id = made.json()["id"]
    response = await registered_client.patch(
        f"{api}/{resource}/{record_id}", json={"position": None}
    )
    assert response.status_code == 422, response.text


async def test_conversations_work_without_embedding_credentials(
    registered_client: AsyncClient, api: str, app: FastAPI, settings: Settings
) -> None:
    registry = ProviderRegistry(
        settings.model_copy(update={"embedding_provider": "openai", "openai_api_key": None})
    )
    app.dependency_overrides[get_provider_registry] = lambda: registry
    made = await registered_client.post(f"{api}/assistant/conversations", json={})
    assert made.status_code == 201, made.text
    conversation_id = made.json()["id"]
    assert (await registered_client.get(f"{api}/assistant/conversations")).status_code == 200
    assert (
        await registered_client.get(f"{api}/assistant/conversations/{conversation_id}/messages")
    ).status_code == 200
    assert (
        await registered_client.delete(f"{api}/assistant/conversations/{conversation_id}")
    ).status_code == 204


async def test_worker_records_failure_after_a_transaction_has_started(
    registered_client: AsyncClient,
    api: str,
    run_worker: Callable[[], Awaitable[int]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paper_id = await upload(registered_client, api)

    async def fail(self: IngestionPipeline, job: IngestionJob) -> None:
        await self._db.scalar(select(Paper).where(Paper.id == job.paper_id))
        raise ProcessingFailedError("This document cannot be read.")

    monkeypatch.setattr(IngestionPipeline, "run", fail)
    assert await run_worker() == 1
    body = (await registered_client.get(f"{api}/papers/{paper_id}")).json()
    assert body["status"] == "failed"
    assert body["failure_reason"] == "This document cannot be read."


async def test_factory_settings_are_used_by_request_dependencies(settings: Settings) -> None:
    configured = settings.model_copy(update={"max_upload_bytes": 12345})
    application = create_app(configured)

    @application.get("/test-settings")
    async def read_settings(current: SettingsDep) -> int:
        return current.max_upload_bytes

    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://testserver"
    ) as client:
        assert (await client.get("/test-settings")).json() == 12345


async def test_a_result_from_before_an_edit_stays_stale(
    registered_client: AsyncClient, api: str
) -> None:
    made = await registered_client.post(f"{api}/analyses", json={"title": "Race"})
    analysis = made.json()
    cell_url = f"{api}/analyses/{analysis['id']}/cells/{analysis['cells'][0]['id']}"
    await registered_client.put(cell_url, json={"source": "print(2)"})
    result = await registered_client.post(
        f"{cell_url}/run", json={"source": "print(1)", "output": "1"}
    )
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "stale"
    assert result.json()["source"] == "print(2)"


async def test_large_cell_output_is_truncated_over_http(
    registered_client: AsyncClient, api: str
) -> None:
    made = await registered_client.post(f"{api}/analyses", json={"title": "Long output"})
    analysis = made.json()
    cell_url = f"{api}/analyses/{analysis['id']}/cells/{analysis['cells'][0]['id']}"
    result = await registered_client.post(f"{cell_url}/run", json={"output": "x" * 200_001})
    assert result.status_code == 200, result.text
    assert "truncated" in result.json()["output"]


async def test_reader_filters_conversations_by_paper_before_limit(
    registered_client: AsyncClient, other_client: AsyncClient, api: str
) -> None:
    paper_id = await upload(registered_client, api)
    url = f"{api}/assistant/conversations"
    saved = await registered_client.post(url, json={"paper_id": paper_id})
    assert saved.status_code == 201
    # Older paper questions must remain available even after many general conversations.
    for _ in range(51):
        response = await registered_client.post(url, json={})
        assert response.status_code == 201
    filtered = await registered_client.get(url, params={"paper_id": paper_id})
    assert filtered.status_code == 200
    assert [row["id"] for row in filtered.json()] == [saved.json()["id"]]
    foreign = await other_client.get(url, params={"paper_id": paper_id})
    assert foreign.status_code == 200
    assert foreign.json() == []
    missing = await registered_client.get(url, params={"paper_id": str(uuid.uuid4())})
    assert missing.json() == []
