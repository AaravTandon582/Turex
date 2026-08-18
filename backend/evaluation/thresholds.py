"""What counts as working — and what these numbers do and do not measure.

**These are floors for the offline embedder, not a claim about production quality.**

CI has no API key, so the benchmark runs against `HashingEmbeddingProvider`, a deterministic
bag-of-words stand-in that exists so retrieval is regression-testable without a network. It has
no semantics: it can match wording, and it cannot connect "which proteins gained most" to "the
gain concentrates in proteins with fewer than one hundred effective sequences". One query in
the set fails for exactly that reason and is kept rather than removed, because a benchmark that
only contains cases the system passes measures nothing.

So these thresholds are set from measured offline behaviour. They catch a regression in
chunking, section filtering, rank fusion, or scoping — all of which are embedder-independent
and all of which have broken at least once during development. They do not tell you how good
retrieval is for a user with a real embedding model configured; for that, run the same harness
with `EMBEDDING_PROVIDER=openai` and expect materially better numbers.

Raising these after a genuine improvement is the point of having them. Lowering one to make a
failing run pass is how a benchmark becomes decoration.
"""

MINIMUM_RECALL_AT_3 = 0.85
"""Measured: 0.875. Nearly every question answered within the first three passages — a reader
scans three, they do not scan ten."""

MINIMUM_MRR = 0.60
"""Measured: 0.646. Roughly, the answer is usually first or second. Held below the measured
value by enough to absorb ordinary variation, and no further."""
