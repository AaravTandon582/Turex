"""Every route is checked for authentication, by enumeration rather than by example.

The per-feature suites already prove that one account cannot read another's papers, notes, or
cards. What they cannot prove is that the *next* endpoint someone adds is scoped too — a test
written by hand covers the routes its author remembered.

So these walk the application's own route table. A new endpoint is included the moment it is
registered, and an unauthenticated one fails here unless it is named in `PUBLIC_ROUTES` with a
reason. That list is the entire public surface of Turex, in one place, reviewable in a diff.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import AsyncClient

# Routes that must work without a session, and why. Anything added here is a deliberate
# widening of the attack surface and should be justified in review.
PUBLIC_ROUTES: dict[tuple[str, str], str] = {
    ("POST", "/api/v1/auth/register"): "creating an account is how you get a session",
    ("POST", "/api/v1/auth/login"): "same",
    ("POST", "/api/v1/auth/refresh"): "authenticated by the refresh cookie, not the access one",
    ("POST", "/api/v1/auth/logout"): "must succeed even with an expired session",
    ("GET", "/api/v1/health"): "liveness probe, reports no data",
    ("GET", "/api/v1/ready"): "readiness probe, reports no data",
}

# A body that passes schema validation is not needed: authentication is checked before the
# request is parsed, so an empty body still produces 401 rather than 422 on a guarded route.
SAMPLE_UUID = str(uuid.uuid4())


def routes_of(app: Any) -> list[tuple[str, str]]:
    """Every (method, path) pair the application serves, excluding docs and OpenAPI.

    Read from the OpenAPI schema rather than by walking `app.routes`, because included
    routers are nested rather than flattened and the nesting is an internal detail — the
    schema is the framework's own answer to "what does this application serve".
    """
    schema = app.openapi()
    found: list[tuple[str, str]] = []
    for path, operations in schema["paths"].items():
        if not path.startswith("/api/v1"):
            continue
        for method in operations:
            if method.upper() in {"GET", "POST", "PATCH", "PUT", "DELETE"}:
                found.append((method.upper(), path))
    return sorted(found)


def concrete(path: str) -> str:
    """Fill path parameters with a syntactically valid id that belongs to nobody."""
    result = path
    while "{" in result:
        start = result.index("{")
        end = result.index("}", start)
        result = result[:start] + SAMPLE_UUID + result[end + 1 :]
    return result


class TestEveryRouteIsGuarded:
    async def test_the_route_table_is_not_empty(self, app: Any) -> None:
        """Guards the guard: a bug that returned no routes would make every test below pass."""
        assert len(routes_of(app)) > 50

    async def test_no_route_is_public_by_accident(self, app: Any, client: AsyncClient) -> None:
        """Request every route with no session. Anything that answers must be on the list."""
        unguarded: list[tuple[str, str]] = []

        for method, path in routes_of(app):
            if (method, path) in PUBLIC_ROUTES:
                continue
            response = await client.request(method, concrete(path))
            if response.status_code != 401:
                unguarded.append((method, path, response.status_code))  # type: ignore[arg-type]

        assert not unguarded, (
            f"these routes answered without a session and are not declared public: {unguarded}"
        )

    async def test_declared_public_routes_still_exist(self, app: Any) -> None:
        """Stops the list rotting into a set of exemptions for routes that are long gone."""
        existing = set(routes_of(app))
        stale = [route for route in PUBLIC_ROUTES if route not in existing]
        assert not stale, f"PUBLIC_ROUTES names routes that no longer exist: {stale}"

    @pytest.mark.parametrize(
        "cookie",
        [
            "not-a-token",
            "a.b.c",
            # A structurally valid JWT signed with the wrong key.
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
            "eyJzdWIiOiIwMDAwMDAwMC0wMDAwLTAwMDAtMDAwMC0wMDAwMDAwMDAwMDAifQ."
            "ZmFrZXNpZ25hdHVyZQ",
            "",
        ],
    )
    async def test_a_forged_access_cookie_is_rejected(
        self, client: AsyncClient, api: str, cookie: str
    ) -> None:
        client.cookies.set("turex_access", cookie)
        response = await client.get(f"{api}/papers")
        assert response.status_code == 401


class TestOwnershipIsUniformAcrossResources:
    """One account must not be able to name another's resources into existence.

    Checked by asking for a well-formed id that belongs to nobody: the answer must be 404 on
    every resource type. A resource that answered 403 would confirm the id exists, which is
    itself a disclosure — and one that answered 500 would mean a missing ownership filter is
    reaching the database.
    """

    @pytest.mark.parametrize(
        "path",
        [
            "/papers/{id}",
            "/papers/{id}/sections",
            "/papers/{id}/annotations",
            "/papers/{id}/citations",
            "/projects/{id}",
            "/hypotheses/{id}",
            "/experiments/{id}",
            "/notes/{id}",
            "/quizzes/{id}",
            "/assistant/conversations/{id}/messages",
        ],
    )
    async def test_an_unknown_id_is_not_found_rather_than_forbidden(
        self, registered_client: AsyncClient, api: str, path: str
    ) -> None:
        response = await registered_client.get(f"{api}{path.replace('{id}', SAMPLE_UUID)}")
        assert response.status_code == 404, (
            f"{path} answered {response.status_code}; an id belonging to nobody must be "
            "indistinguishable from one belonging to someone else"
        )

    @pytest.mark.parametrize(
        "path",
        ["/papers/{id}", "/projects/{id}", "/notes/{id}", "/flashcards/{id}", "/quizzes/{id}"],
    )
    async def test_deleting_something_that_is_not_yours_is_not_found(
        self, registered_client: AsyncClient, api: str, path: str
    ) -> None:
        response = await registered_client.delete(f"{api}{path.replace('{id}', SAMPLE_UUID)}")
        assert response.status_code == 404

    async def test_a_malformed_id_is_rejected_before_the_database(
        self, registered_client: AsyncClient, api: str
    ) -> None:
        response = await registered_client.get(f"{api}/papers/not-a-uuid")
        assert response.status_code == 422
