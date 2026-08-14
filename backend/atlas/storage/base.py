"""Document storage interface.

Uploaded PDFs are large, immutable, and served back verbatim to the reader — which makes them
object-storage shaped rather than database shaped. This interface keeps the rest of the
application from caring which backend is in use, so moving to S3 is a second implementation
rather than a rewrite.

Keys are opaque strings assigned by the store. Nothing outside a backend may construct or
parse one, because a caller that builds its own key is a path-traversal bug waiting to happen.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StoredObject:
    key: str
    size_bytes: int
    content_hash: str
    """SHA-256 of the bytes, used to recognise a re-upload of a file already held."""


class DocumentStore(ABC):
    @abstractmethod
    async def put(self, *, namespace: str, filename: str, data: bytes) -> StoredObject:
        """Store bytes and return the assigned key.

        `namespace` scopes the object to its owner so one user's documents are never
        addressable through another user's key space. `filename` only influences the
        extension; it never determines the path.
        """

    @abstractmethod
    async def get(self, key: str) -> bytes: ...

    @abstractmethod
    async def open_path(self, key: str) -> str:
        """A local filesystem path for the object.

        Parsers stream from disk rather than holding a whole PDF in memory. A remote backend
        satisfies this by materialising to a temporary file.
        """

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Remove the object. Succeeds if it is already gone."""

    @abstractmethod
    async def exists(self, key: str) -> bool: ...
