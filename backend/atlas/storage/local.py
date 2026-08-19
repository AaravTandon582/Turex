"""Filesystem-backed document store.

Layout: ``<root>/<namespace>/<ab>/<hash><ext>``

Content-addressed, so the same bytes uploaded twice occupy one file. The two-character shard
directory keeps any single directory from accumulating tens of thousands of entries, which
degrades listing on most filesystems.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import uuid
from pathlib import Path

from atlas.core.logging import get_logger
from atlas.storage.base import DocumentStore, StoredObject

logger = get_logger(__name__)

_SAFE_NAMESPACE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_SAFE_EXTENSION = re.compile(r"^\.[A-Za-z0-9]{1,8}$")


class LocalDocumentStore(DocumentStore):
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    # -- writing ----------------------------------------------------------------

    async def put(self, *, namespace: str, filename: str, data: bytes) -> StoredObject:
        self._validate_namespace(namespace)
        extension = self._safe_extension(filename)
        content_hash = hashlib.sha256(data).hexdigest()
        key = f"{namespace}/{content_hash[:2]}/{content_hash}{extension}"

        await asyncio.to_thread(self._write, key, data)
        return StoredObject(key=key, size_bytes=len(data), content_hash=content_hash)

    def _write(self, key: str, data: bytes) -> None:
        path = self._resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            # Content-addressed: identical bytes, nothing to do.
            return

        # Write to a sibling then rename, so a crash mid-write cannot leave a truncated file
        # that later reads would treat as a valid document.
        #
        # The sibling's name must be unique per write, not derived from the key. Two uploads
        # of the same file produce the same key, so a shared temporary name meant both wrote
        # to one path, the first rename consumed it, and the second failed with
        # FileNotFoundError — a 500 for one of two people uploading the same paper at once.
        temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.partial")
        try:
            temporary.write_bytes(data)
            # `replace` is atomic on POSIX, so a concurrent writer either sees no file or the
            # complete one. Losing the race is not an error: the bytes are identical by
            # construction, and the winner's file is exactly what this one would have written.
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    # -- reading ----------------------------------------------------------------

    async def get(self, key: str) -> bytes:
        return await asyncio.to_thread(self._resolve(key).read_bytes)

    async def open_path(self, key: str) -> str:
        return str(self._resolve(key))

    async def exists(self, key: str) -> bool:
        return await asyncio.to_thread(self._resolve(key).is_file)

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._resolve(key).unlink, True)

    # -- path safety --------------------------------------------------------------

    def _resolve(self, key: str) -> Path:
        """Turn a key into a path, refusing anything that escapes the storage root.

        Keys are generated internally, but this is the last line of defence: if a key ever
        reaches here from a request parameter, traversal must fail closed rather than read an
        arbitrary file.
        """
        candidate = (self._root / key).resolve()
        if not candidate.is_relative_to(self._root):
            logger.error("rejected storage key escaping the root", extra={"key": key})
            raise ValueError("Storage key resolves outside the storage root")
        return candidate

    @staticmethod
    def _validate_namespace(namespace: str) -> None:
        if not _SAFE_NAMESPACE.match(namespace):
            raise ValueError(f"Unsafe storage namespace: {namespace!r}")

    @staticmethod
    def _safe_extension(filename: str) -> str:
        """Keep a recognisable extension, discard everything else about the name.

        The uploaded filename is attacker-controlled, so it is recorded on the paper row for
        display and never used to build a path.
        """
        suffix = Path(filename).suffix.lower()
        return suffix if _SAFE_EXTENSION.match(suffix) else ".bin"
