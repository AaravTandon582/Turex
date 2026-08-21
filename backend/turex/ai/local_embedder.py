"""A deterministic embedder that needs no network and no API key.

This is what makes retrieval testable. With a hosted embedding model, the retrieval pipeline
can only be exercised by hand against a live account — so in practice it never gets a
regression test, and ranking quietly breaks. This implementation runs in CI.

It is the hashing trick: tokens are hashed into a fixed number of buckets, weighted by
sublinear term frequency, and the result is L2-normalised so cosine distance behaves. That
gives it real lexical signal — documents sharing vocabulary land near each other — without any
learned semantics. It is a genuine, if shallow, embedding, not random noise.

**Not for production.** It cannot match paraphrase, which is most of what semantic search is
for. Turex logs a warning when it is selected outside tests.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from collections.abc import Sequence

from turex.ai.base import EmbeddingProvider

_TOKEN = re.compile(r"[a-z0-9]+")

# Words carrying no topical signal. Kept short deliberately: an aggressive stop list would
# throw away terms that matter in scientific text.
_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "the",
        "of",
        "and",
        "or",
        "in",
        "on",
        "at",
        "to",
        "for",
        "from",
        "by",
        "with",
        "as",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "this",
        "that",
        "these",
        "those",
        "it",
        "its",
        "we",
        "our",
        "their",
        "they",
        "them",
        "he",
        "she",
        "his",
        "her",
        "you",
        "your",
        "i",
        "not",
        "no",
        "but",
        "if",
        "then",
        "than",
        "so",
        "such",
        "can",
        "could",
        "may",
        "might",
        "will",
        "would",
        "shall",
        "should",
        "do",
        "does",
        "did",
        "have",
        "has",
        "had",
        "which",
        "who",
        "whom",
        "what",
        "when",
        "where",
        "how",
        "why",
    ]
)


def _tokenise(text: str) -> list[str]:
    return [token for token in _TOKEN.findall(text.lower()) if token not in _STOPWORDS]


class HashingEmbeddingProvider(EmbeddingProvider):
    name = "local-hashing"

    def __init__(self, *, dimensions: int) -> None:
        self.dimensions = dimensions

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        counts = Counter(_tokenise(text))

        for token, count in counts.items():
            bucket, sign = self._bucket(token)
            # Sublinear scaling: the tenth occurrence of a word says far less than the first.
            vector[bucket] += sign * (1.0 + math.log(count))

        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0.0:
            # An empty or all-stopword passage. A zero vector is undefined under cosine
            # distance, so give it a fixed unit direction instead: it will simply never be
            # anyone's nearest neighbour.
            vector[0] = 1.0
            return vector

        return [value / norm for value in vector]

    def _bucket(self, token: str) -> tuple[int, float]:
        """Map a token to a dimension and a sign.

        The signed variant of the hashing trick: signs make collisions cancel on average
        rather than accumulate, so unrelated documents do not drift together.
        """
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        value = int.from_bytes(digest, "big")
        return value % self.dimensions, 1.0 if (value >> 63) & 1 else -1.0
