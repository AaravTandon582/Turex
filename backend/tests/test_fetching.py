"""Adding a paper by link, DOI, or arXiv id — and refusing to be used as a proxy.

Fetching a URL a caller supplied is the most dangerous thing Turex does. The server has a
network position the caller does not: cloud metadata endpoints, admin services on localhost,
databases on a private subnet. Every one of those is reachable from the application server and
from nowhere else, which is exactly what makes SSRF worth an attacker's time.

The address checks are unit-tested because they must hold for inputs that cannot be produced
on demand — a hostname resolving to a private address, a redirect into link-local space.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from turex.core.errors import ValidationError
from turex.ingestion.fetching import _is_public, assert_safe_url
from turex.ingestion.identifiers import IdentifierKind, parse_identifier


class TestIdentifierParsing:
    @pytest.mark.parametrize(
        ("reference", "kind", "value"),
        [
            ("https://arxiv.org/abs/1706.03762", IdentifierKind.arxiv, "1706.03762"),
            ("https://arxiv.org/pdf/2005.11401v2", IdentifierKind.arxiv, "2005.11401"),
            ("1706.03762", IdentifierKind.arxiv, "1706.03762"),
            ("arXiv:2203.02155", IdentifierKind.arxiv, "2203.02155"),
            ("cs/0112017", IdentifierKind.arxiv, "cs/0112017"),
            ("10.1038/nature14539", IdentifierKind.doi, "10.1038/nature14539"),
            ("doi:10.1145/3292500.3330701", IdentifierKind.doi, "10.1145/3292500.3330701"),
            (
                "https://doi.org/10.1038/s41586-021-03819-2",
                IdentifierKind.doi,
                "10.1038/s41586-021-03819-2",
            ),
            ("https://example.org/paper.pdf", IdentifierKind.url, "https://example.org/paper.pdf"),
        ],
    )
    def test_recognises_what_people_actually_paste(
        self, reference: str, kind: IdentifierKind, value: str
    ) -> None:
        resolved = parse_identifier(reference)
        assert resolved.kind is kind
        assert resolved.value == value

    def test_the_arxiv_version_is_dropped(self) -> None:
        """arXiv serves the latest version at the unversioned URL, and someone pasting v1 and
        someone pasting v3 mean the same paper — which is also what makes deduplication work."""
        assert parse_identifier("arxiv.org/abs/2005.11401v7").pdf_url.endswith("2005.11401")

    @pytest.mark.parametrize("junk", ["", "   ", "hello world", "not/an/id", "12345"])
    def test_refuses_things_that_are_not_references(self, junk: str) -> None:
        with pytest.raises(ValueError):
            parse_identifier(junk)


class TestAddressChecks:
    @pytest.mark.parametrize(
        "address",
        [
            "127.0.0.1",  # loopback
            "10.0.0.5",  # RFC 1918
            "172.16.4.1",
            "192.168.1.1",
            "169.254.169.254",  # cloud metadata, the prize in most SSRF attempts
            "0.0.0.0",
            "::1",
            "fc00::1",  # unique local
            "fe80::1",  # link-local
            "224.0.0.1",  # multicast
        ],
    )
    def test_every_internal_address_is_refused(self, address: str) -> None:
        assert not _is_public(address), f"{address} was treated as public"

    @pytest.mark.parametrize("address", ["8.8.8.8", "1.1.1.1", "93.184.216.34", "2606:4700::1111"])
    def test_public_addresses_are_allowed(self, address: str) -> None:
        assert _is_public(address)

    def test_a_hostname_resolving_to_loopback_is_refused(self) -> None:
        """The reason hostname checks are useless on their own: a name is whatever its owner
        points it at, and pointing it at 127.0.0.1 costs nothing."""
        with pytest.raises(ValidationError):
            assert_safe_url("http://localhost:8000/internal")

    @pytest.mark.parametrize(
        "url",
        [
            "file:///etc/passwd",
            "gopher://example.org/",
            "ftp://example.org/paper.pdf",
            "data:application/pdf;base64,JVBERi0=",
        ],
    )
    def test_only_http_and_https_are_fetched(self, url: str) -> None:
        with pytest.raises(ValidationError):
            assert_safe_url(url)

    def test_a_url_with_no_host_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            assert_safe_url("http:///nowhere")

    def test_an_unresolvable_host_fails_cleanly(self) -> None:
        with pytest.raises(ValidationError):
            assert_safe_url("https://this-name-does-not-resolve.invalid/paper.pdf")


class TestAddByReferenceEndpoint:
    async def test_a_reference_that_is_not_one_is_rejected(
        self, registered_client: AsyncClient, api: str
    ) -> None:
        response = await registered_client.post(
            f"{api}/papers/from-reference", json={"reference": "just some words"}
        )
        assert response.status_code == 422

    @pytest.mark.parametrize(
        "reference",
        [
            "http://localhost:8000/api/v1/papers",
            "http://127.0.0.1/admin",
            "http://169.254.169.254/latest/meta-data/",
            "file:///etc/passwd",
        ],
    )
    async def test_the_server_will_not_fetch_its_own_network(
        self, registered_client: AsyncClient, api: str, reference: str
    ) -> None:
        """The endpoint must not become a proxy into the network the server sits in."""
        response = await registered_client.post(
            f"{api}/papers/from-reference", json={"reference": reference}
        )
        # Refused, but not always at the same layer: `file://` never parses as a reference,
        # while an http URL parses and is then refused on the address it resolves to. Both are
        # rejections; asserting the wording would pin an implementation detail.
        assert response.status_code == 422, response.text
        assert "error" in response.json(), "the response was not an error envelope"
        assert "id" not in response.json(), "a paper was created from a refused reference"

    async def test_it_requires_a_session(self, client: AsyncClient, api: str) -> None:
        response = await client.post(
            f"{api}/papers/from-reference", json={"reference": "1706.03762"}
        )
        assert response.status_code == 401
