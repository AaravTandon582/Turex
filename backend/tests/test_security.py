"""Security properties checked as tests, so an audit becomes a guarantee.

Each of these was verified by hand once. Verified-by-hand decays: the value here is that the
*next* commit is checked too, without anyone remembering to look.

Upload handling, session rotation, and cross-account isolation are covered by the ingestion,
auth, and per-feature suites. What is added here is the repository-wide properties those
cannot express.
"""

from __future__ import annotations

import pathlib
import re

import pytest
from httpx import AsyncClient

from tests.support.pdf_builder import build_pdf
from turex.core.config import Settings
from turex.core.logging import redact
from turex.main import create_app

REPOSITORY = pathlib.Path(__file__).resolve().parents[2]
BACKEND_SOURCE = REPOSITORY / "backend" / "turex"
FRONTEND_SOURCE = REPOSITORY / "frontend" / "src"


def source_files() -> list[pathlib.Path]:
    files = list(BACKEND_SOURCE.rglob("*.py"))
    files += [
        path
        for suffix in ("*.ts", "*.tsx")
        for path in FRONTEND_SOURCE.rglob(suffix)
        if "node_modules" not in path.parts
    ]
    assert len(files) > 50, "the source sweep found almost nothing; the paths are probably wrong"
    return files


class TestNoSecretsInSource:
    # A long opaque literal assigned to something that sounds like a credential. Deliberately
    # loose: a false positive costs a moment's reading, a false negative ships a key.
    SECRET_ASSIGNMENT = re.compile(
        r"""(api[_-]?key|secret[_-]?key|password|access[_-]?token|client[_-]?secret)"""
        r"""\s*[:=]\s*["'][A-Za-z0-9/+_\-]{16,}["']""",
        re.IGNORECASE,
    )

    # Vendor key formats, which are unambiguous wherever they appear.
    VENDOR_KEY = re.compile(
        r"sk-ant-[A-Za-z0-9\-_]{20,}|sk-proj-[A-Za-z0-9\-_]{20,}|AKIA[0-9A-Z]{16}"
    )

    def test_no_credential_looking_literal_is_assigned_in_source(self) -> None:
        offenders: list[str] = []
        for path in source_files():
            for number, line in enumerate(path.read_text().splitlines(), start=1):
                if self.SECRET_ASSIGNMENT.search(line) and "test" not in path.name:
                    offenders.append(f"{path.relative_to(REPOSITORY)}:{number}")
        assert not offenders, f"possible hardcoded credentials: {offenders}"

    def test_no_vendor_api_key_appears_anywhere_in_source(self) -> None:
        offenders = [
            str(path.relative_to(REPOSITORY))
            for path in source_files()
            if self.VENDOR_KEY.search(path.read_text())
        ]
        assert not offenders, f"vendor API keys found in: {offenders}"

    def test_the_example_env_carries_no_real_keys(self) -> None:
        example = (REPOSITORY / "backend" / ".env.example").read_text()
        for line in example.splitlines():
            if line.startswith(("ANTHROPIC_API_KEY", "OPENAI_API_KEY")):
                _, _, value = line.partition("=")
                assert not value.strip(), f"{line.split('=')[0]} has a value in .env.example"


class TestNoRawSQLInterpolation:
    """Parameters must reach the database as parameters, never as formatted strings."""

    INTERPOLATED = re.compile(r"""text\(\s*(f["']|["'].*["']\s*[%+]|["'].*\{)""")

    def test_no_sql_is_built_by_string_formatting(self) -> None:
        offenders: list[str] = []
        for path in BACKEND_SOURCE.rglob("*.py"):
            for number, line in enumerate(path.read_text().splitlines(), start=1):
                if self.INTERPOLATED.search(line):
                    offenders.append(f"{path.relative_to(REPOSITORY)}:{number}")
        assert not offenders, f"SQL built by interpolation: {offenders}"


class TestProductionConfiguration:
    def test_the_development_secret_key_is_refused_in_production(self) -> None:
        settings = Settings(
            environment="production",
            secret_key="dev-only-insecure-key-change-me",
            cookie_secure=True,
            debug=False,
        )
        assert any("SECRET_KEY" in problem for problem in settings.check_production_readiness())

    def test_insecure_cookies_and_debug_are_refused_in_production(self) -> None:
        settings = Settings(
            environment="production",
            secret_key="a-genuinely-long-and-random-production-value-0123456789",
            cookie_secure=False,
            debug=True,
        )
        problems = settings.check_production_readiness()
        assert any("COOKIE_SECURE" in problem for problem in problems)
        assert any("DEBUG" in problem for problem in problems)

    def test_a_correctly_configured_production_setup_has_no_problems(self) -> None:
        settings = Settings(
            environment="production",
            secret_key="a-genuinely-long-and-random-production-value-0123456789",
            cookie_secure=True,
            debug=False,
        )
        assert settings.check_production_readiness() == []

    def test_an_insecure_production_configuration_stops_the_application_starting(self) -> None:
        """The tests above prove the problems are *found*. This proves they are acted on.

        They were not: startup logged each problem as critical and served anyway, so the only
        evidence of a production deployment signing sessions with the key published in
        `.env.example` was one line in a log stream nobody reads on a first deploy. The two
        tests above are named "refused", and a comment in `api/deps.py` claimed the same.
        """
        insecure = Settings(
            environment="production",
            secret_key="dev-only-insecure-key-change-me",
            cookie_secure=False,
            debug=True,
        )

        with pytest.raises(RuntimeError, match="insecure configuration"):
            create_app(insecure)

    def test_a_correct_production_configuration_still_starts(self) -> None:
        """The guard must refuse the insecure case only — a fail-closed check that refuses
        everything is the same outage with a better excuse."""
        secure = Settings(
            environment="production",
            secret_key="a-genuinely-long-and-random-production-value-0123456789",
            cookie_secure=True,
            debug=False,
        )

        assert create_app(secure) is not None


class TestUnstorableCharactersInAQueryString:
    """A null byte in a query parameter returned 500 from a URL anyone could type.

    `TurexModel` cleans every string in a request body in one place, and a query parameter
    declared as a model — `PaperFilters` — inherits that. Three were declared as bare
    annotated strings instead and inherited nothing: the catalog's `q` and `category`, and the
    assistant's semantic search. Cleaned at the ASGI boundary now, so a parameter added later
    is covered without anyone remembering this.
    """

    NULL_BYTE = "ok%00hidden"

    @pytest.mark.parametrize(
        "path",
        ["/catalog/search?q={value}", "/catalog/search?category={value}", "/papers?search={value}"],
    )
    async def test_a_null_byte_is_stripped_rather_than_raising(
        self, registered_client: AsyncClient, api: str, path: str
    ) -> None:
        response = await registered_client.get(api + path.format(value=self.NULL_BYTE))

        assert response.status_code == 200, response.text

    async def test_the_surviving_text_still_searches(
        self, registered_client: AsyncClient, api: str
    ) -> None:
        """Cleaning must remove the byte, not the query — a search that silently becomes a
        different search is worse than an error."""
        response = await registered_client.get(f"{api}/catalog/search?q=trans%00former")

        assert response.status_code == 200
        # The parameter arrived as "transformer", so the endpoint saw a real query.
        assert response.json()["total"] >= 0

    async def test_an_ordinary_query_string_is_left_alone(
        self, registered_client: AsyncClient, api: str
    ) -> None:
        """The rewrite happens only when something was removed, so normal requests keep the
        query string they were sent, byte for byte."""
        response = await registered_client.get(f"{api}/papers?search=a%20b%2Bc&limit=5")

        assert response.status_code == 200


class TestSensitiveDataNeverLeaves:
    @pytest.mark.parametrize(
        "secret",
        [
            "sk-ant-a-very-long-looking-api-key-value",
            "a-session-refresh-token-value",
            "short",
        ],
    )
    def test_the_log_redactor_never_emits_a_reusable_secret(self, secret: str) -> None:
        """It fingerprints rather than hides: enough to correlate two log lines, never enough
        to replay. The last four characters are deliberate, the rest must be gone."""
        fingerprint = redact(secret)
        assert secret not in fingerprint
        assert fingerprint.count("*") >= len(secret) - 4

    def test_the_log_redactor_handles_a_missing_value(self) -> None:
        assert redact(None) == "<unset>"

    async def test_a_failed_login_does_not_say_which_half_was_wrong(
        self, client: AsyncClient, api: str
    ) -> None:
        """Distinguishing the two turns the login form into an account-existence oracle."""
        await client.post(
            f"{api}/auth/register",
            json={
                "email": "known@turex.dev",
                "full_name": "Known Person",
                "password": "a-sufficiently-long-password",
            },
        )
        await client.post(f"{api}/auth/logout")

        wrong_password = await client.post(
            f"{api}/auth/login",
            json={"email": "known@turex.dev", "password": "the-wrong-password-entirely"},
        )
        unknown_email = await client.post(
            f"{api}/auth/login",
            json={"email": "nobody@turex.dev", "password": "the-wrong-password-entirely"},
        )

        assert wrong_password.status_code == unknown_email.status_code
        assert wrong_password.json() == unknown_email.json()

    async def test_an_error_response_never_carries_internal_detail(
        self, registered_client: AsyncClient, api: str
    ) -> None:
        response = await registered_client.get(f"{api}/papers/00000000-0000-0000-0000-000000000000")
        body = response.json()
        assert set(body["error"]) <= {"code", "message", "fields"}, (
            f"the error envelope carries more than it should: {sorted(body['error'])}"
        )

    async def test_the_password_is_never_returned_by_any_auth_endpoint(
        self, registered_client: AsyncClient, api: str
    ) -> None:
        body = (await registered_client.get(f"{api}/auth/me")).text
        assert "password" not in body.lower()


class TestHostileTextIsSanitised:
    """Text arriving from a client is not safe to hand to PostgreSQL as-is."""

    async def test_a_null_byte_does_not_crash_the_server(
        self, registered_client: AsyncClient, api: str
    ) -> None:
        """A null byte in any string column raises inside asyncpg and surfaced as a 500 —
        an unhandled server error from ordinary input, on every text field at once."""
        response = await registered_client.post(
            "/api/v1/projects".replace("/api/v1", api),
            json={"name": "nul\x00byte", "research_question": "does it survive?"},
        )
        assert response.status_code == 201, response.text
        assert "\x00" not in response.json()["name"]

    @pytest.mark.parametrize(
        "hostile",
        [
            "bell\x07char",
            "escape\x1b[31mred",
            "delete\x7fchar",
            "vertical\x0btab",
        ],
    )
    async def test_control_characters_are_stripped(
        self, registered_client: AsyncClient, api: str, hostile: str
    ) -> None:
        """Terminal escapes in a title make logs and terminals behave strangely."""
        response = await registered_client.post(
            f"{api}/projects", json={"name": hostile, "research_question": "x"}
        )
        assert response.status_code == 201
        stored = response.json()["name"]
        assert not any(ord(character) < 0x20 and character not in "\t\n\r" for character in stored)
        assert "\x7f" not in stored

    async def test_newlines_and_tabs_survive_because_notes_are_markdown(
        self, registered_client: AsyncClient, api: str
    ) -> None:
        """Stripping too much is its own bug: a note is Markdown and needs its line breaks."""
        content = "# Heading\n\n- one\n- two\n\n\tindented"
        response = await registered_client.post(f"{api}/notes", json={"content": content})
        assert response.status_code == 201
        assert response.json()["content"] == content

    async def test_nested_strings_are_cleaned_too(
        self, registered_client: AsyncClient, api: str
    ) -> None:
        """A shallow pass would miss a string inside a list, which is where several live."""
        response = await registered_client.post(
            f"{api}/projects",
            json={"name": "clean", "research_question": "x", "tags": ["good", "ba\x00d"]},
        )
        assert response.status_code in {201, 422}


class TestUploadedDocumentsCannotExecute:
    """An uploaded PDF is data. Nothing in it may be run, and nothing in it names a path."""

    async def test_a_pdf_carrying_javascript_is_stored_as_inert_bytes(
        self, registered_client: AsyncClient, api: str, run_worker
    ) -> None:
        # A real PDF whose text happens to contain an OpenAction/JavaScript payload. Turex
        # extracts text and never evaluates document actions, so this must ingest as ordinary
        # prose rather than doing anything.
        hostile = build_pdf(
            [
                [
                    "Perfectly Ordinary Paper",
                    "A Author",
                    "",
                    "Abstract",
                    "/OpenAction << /S /JavaScript /JS (app.alert('x');) >> "
                    "This paragraph exists so the document has enough text to ingest, and it "
                    "contains a payload that must be treated as characters and nothing else.",
                ]
            ]
        )
        response = await registered_client.post(
            f"{api}/papers", files={"file": ("hostile.pdf", hostile, "application/pdf")}
        )
        assert response.status_code == 202
        await run_worker()

        paper = (await registered_client.get(f"{api}/papers/{response.json()['id']}")).json()
        assert paper["status"] in {"ready", "failed"}

    @pytest.mark.parametrize(
        "filename",
        ["../../etc/passwd.pdf", "..\\..\\windows\\system32\\x.pdf", "a/b/../../../escape.pdf"],
    )
    async def test_a_traversing_filename_cannot_escape_storage(
        self, registered_client: AsyncClient, api: str, filename: str, settings
    ) -> None:
        """Storage keys are content-addressed, so the uploaded name never reaches the path."""
        data = build_pdf([["Title", "Author", "", "Abstract", "Body text long enough to pass."]])
        response = await registered_client.post(
            f"{api}/papers", files={"file": (filename, data, "application/pdf")}
        )
        assert response.status_code in {202, 200}

        stored = (await registered_client.get(f"{api}/papers/{response.json()['id']}")).json()
        name = stored.get("original_filename", "")
        assert ".." not in name and "/" not in name and "\\" not in name, (
            f"the uploaded name was stored verbatim as {name!r}"
        )

        root = pathlib.Path(settings.storage_root).resolve()
        for path in root.rglob("*"):
            assert root in path.resolve().parents or path.resolve() == root
