"""Fetching a document from a URL the user supplied.

This is the most dangerous thing Turex does. A server that fetches an arbitrary URL on request
is a server-side request forgery primitive: the attacker borrows the server's network position
to reach things they cannot reach themselves — a metadata endpoint on a cloud host, an admin
service on localhost, a database on a private subnet.

The defences here, in the order they matter:

1. **Only http and https.** `file://`, `gopher://`, and friends have no business here.
2. **Resolve the hostname, then check every address it resolved to.** Checking the hostname
   alone is useless: `evil.example` can simply have an A record pointing at `127.0.0.1`.
3. **Re-check on every redirect.** A public URL that redirects to `169.254.169.254` defeats a
   check performed only on the original URL, which is the classic bypass.
4. **Cap the size while streaming**, so a response that never ends cannot exhaust memory.
5. **A short timeout**, because a hung fetch holds a worker.

The list of blocked ranges is deliberately broad. A false rejection is an inconvenience; a
false acceptance is an internal service exposed to the internet.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from turex.core.errors import ValidationError
from turex.core.logging import get_logger

logger = get_logger(__name__)

MAX_REDIRECTS = 3
FETCH_TIMEOUT_SECONDS = 20.0
USER_AGENT = "turex-research-workspace/1.0 (+https://github.com/turex)"

ALLOWED_SCHEMES = frozenset({"http", "https"})


@dataclass(frozen=True, slots=True)
class FetchedDocument:
    data: bytes
    final_url: str
    content_type: str | None


def _is_public(address: str) -> bool:
    """Whether an IP is one the server should be willing to talk to.

    Everything reserved is refused, not just loopback and the RFC 1918 ranges: link-local
    covers the cloud metadata endpoints at 169.254.169.254, and the catch-all `is_reserved`
    covers ranges that are not routable today and may be tomorrow.
    """
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False

    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _resolve(host: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise ValidationError(
            "Turex couldn't find that address.", detail=f"DNS lookup failed for {host}"
        ) from exc
    # `getaddrinfo` types the sockaddr loosely because it differs by family; the first element
    # is the address string for both IPv4 and IPv6.
    return [str(info[4][0]) for info in infos]


def assert_safe_url(url: str) -> None:
    """Refuse anything that would point the server at itself or a private network.

    Called for the original URL and again for every redirect, because a redirect is a fresh
    URL chosen by someone else.
    """
    parsed = urlparse(url)

    if parsed.scheme not in ALLOWED_SCHEMES:
        raise ValidationError(
            "Turex can only fetch http and https links.",
            detail=f"refused scheme {parsed.scheme!r}",
        )
    if not parsed.hostname:
        raise ValidationError("That doesn't look like a complete link.", detail="no hostname")

    addresses = _resolve(parsed.hostname)
    unsafe = [address for address in addresses if not _is_public(address)]
    if unsafe or not addresses:
        # The address is not echoed back: telling a caller which internal IP a name resolves
        # to is itself a small disclosure.
        logger.warning(
            "refused a fetch to a non-public address",
            extra={"host": parsed.hostname, "addresses": len(addresses)},
        )
        raise ValidationError(
            "Turex won't fetch that address.",
            detail=f"{parsed.hostname} resolves to a non-public address",
        )


async def fetch_document(url: str, *, max_bytes: int) -> FetchedDocument:
    """Download a document, refusing anything that looks like an internal target.

    Redirects are followed by hand rather than by the client, so each hop can be checked
    before it is taken.
    """
    current = url
    async with httpx.AsyncClient(
        follow_redirects=False,
        timeout=FETCH_TIMEOUT_SECONDS,
        headers={"user-agent": USER_AGENT},
    ) as client:
        for _ in range(MAX_REDIRECTS + 1):
            assert_safe_url(current)

            try:
                async with client.stream("GET", current) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise ValidationError("That link redirected nowhere.")
                        current = str(httpx.URL(current).join(location))
                        continue

                    if response.status_code >= 400:
                        raise ValidationError(
                            "That link didn't return a document.",
                            detail=f"HTTP {response.status_code} from {current}",
                        )

                    # Trust the declared length only to reject early; the real limit is
                    # enforced while reading, because the header can lie.
                    declared = response.headers.get("content-length")
                    if declared and declared.isdigit() and int(declared) > max_bytes:
                        raise ValidationError("That file is too large to add.")

                    chunks: list[bytes] = []
                    total = 0
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > max_bytes:
                            raise ValidationError("That file is too large to add.")
                        chunks.append(chunk)

                    return FetchedDocument(
                        data=b"".join(chunks),
                        final_url=current,
                        content_type=response.headers.get("content-type"),
                    )
            except httpx.HTTPError as exc:
                raise ValidationError(
                    "Turex couldn't reach that link.", detail=f"{type(exc).__name__}: {exc}"
                ) from exc

    raise ValidationError("That link redirected too many times.")
