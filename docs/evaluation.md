# Evaluation

Atlas claims that retrieval finds the right passage and that every citation resolves to real
text. This is how those claims are measured rather than asserted.

---

## Running it

```bash
cd backend
EMBEDDING_PROVIDER=local python -m evaluation      # the retrieval benchmark, as a report
pytest tests/test_evaluation.py                    # the same numbers, as thresholds
pytest tests/test_authorization.py tests/test_security.py
pytest tests/test_query_counts.py                  # N+1 guards
```

The benchmark exits non-zero if it falls below the thresholds in `evaluation/thresholds.py`, so
the same numbers are checked by hand and in CI without two implementations of the check.

---

## What the retrieval benchmark measures

Three papers written for the purpose, eight queries whose answers are known, scored on
recall@1/3/5 and mean reciprocal rank.

The corpus is written rather than downloaded for three reasons: real papers cannot be committed
for licensing reasons, a benchmark that fetches over the network does not run in CI, and a
written corpus can contain **deliberate near-misses** — two papers on the same topic where only
one holds the answer. That last case is what separates retrieval that works from retrieval that
returns whatever mentions the query words.

Each query names its answer by a marker phrase that appears exactly once in the whole corpus,
asserted at load time. Scoring is per *passage*, not per paper: a paper-level match would count
a hit for returning the references section of the right document.

Queries go through the real parser, the real chunker, and the real hybrid search. A benchmark
that called the ranking function directly would score the ranking function — and every
retrieval bug found during development was somewhere else, in how pages were unwrapped or which
sections were skipped.

### Current numbers

| Metric | Value |
|---|---|
| recall@1 | 50% |
| recall@3 | 88% |
| recall@5 | 88% |
| MRR | 0.646 |

**These are floors for the offline embedder, not a claim about production quality.** CI has no
API key, so the benchmark runs against `HashingEmbeddingProvider` — a deterministic
bag-of-words stand-in with no semantics. It can match wording; it cannot connect *"which
proteins gained most"* to *"the gain concentrates in proteins with fewer than one hundred
effective sequences"*.

One query fails for exactly that reason. It is kept, and pinned by a test that fails if a
second query joins it or if it starts passing — a benchmark containing only cases the system
passes measures nothing. See [`docs/decisions.md`](decisions.md) D11.

With a real embedding provider configured, run the same harness with `EMBEDDING_PROVIDER=openai`
and expect materially better numbers.

### What writing it found

Two benchmark bugs and no retrieval bugs. Two queries had more than one correct answer;
retrieval returned a different valid one and the benchmark scored a miss. Both queries were
sharpened rather than the thresholds lowered — the failing runs are recorded in the `note`
field of each query in `evaluation/corpus.py`.

---

## Citation integrity

Checked across the whole database rather than per feature:

- every stored citation resolves to a chunk that exists
- the stored snapshot appears in the chunk it claims to quote
- re-ingesting a paper does not change what an existing citation says
- deleting a paper leaves no citation pointing at a chunk that is gone

The third is the reason citations carry a text snapshot at all.

---

## Model misbehaviour

A model that lies must not be able to make Atlas lie. The suite scripts specific failures that
real models produce and asserts nothing ungrounded reaches the database:

| Scripted behaviour | Required outcome |
|---|---|
| cites `[99]` when five sources were given | no citation stored for it |
| cites `[0]`, which numbering never produces | no citation stored for it |
| cites more markers than there were sources | citations never exceed retrieved passages |
| cites nothing | the turn is stored; no citations are invented |
| returns an empty answer | handled; nothing ungrounded persisted |

`used_in_answer` is asserted to reflect real usage, since the retrieved-versus-cited measure
depends on it.

---

## Authorization

Every route is checked by enumeration, not by example. The suite reads the application's own
OpenAPI schema and requires each route to answer 401 without a session unless it is named in
`PUBLIC_ROUTES` with a reason.

All routes pass. Six are public: register, login, refresh, logout, health, ready.

The per-feature suites separately prove that one account cannot reach another's data. What the
sweep adds is that the **next** endpoint someone registers is covered without anyone
remembering to write a test for it.

---

## Security properties

Checked as tests so the audit does not decay:

- no credential-shaped literals in backend or frontend source
- no vendor API key format anywhere in source
- `.env.example` carries no values for the key variables
- no SQL built by string interpolation
- production configuration refuses the development secret key, insecure cookies, and debug mode
- the log redactor never emits a reusable secret
- a wrong password and an unknown email produce byte-identical responses
- error envelopes carry only `code`, `message`, and `fields` — never internal detail
- an uploaded PDF containing a JavaScript action ingests as inert text
- a traversing filename cannot escape storage or be stored verbatim

The last one found a real issue: uploaded names were stored as given, so `../../etc/passwd.pdf`
was kept as the display name. Never a traversal risk — storage keys are content-addressed —
but it is shown in the library and exported into citations, so it is now reduced to a bare
filename at the point of storage.

---

## Query counts

Endpoints that grow with the library are tested for N+1 by *shape*: load a library, count the
SQL statements, load a bigger one, require the count to be unchanged.

Timing does not catch this. Every endpoint answered in under 80ms with four papers while the
knowledge graph was issuing one query per paper. The absolute count is deliberately not
asserted — it moves whenever a feature legitimately needs another query, and a test that fails
on every such change gets deleted rather than read.

---

## Measured at scale

44 papers, 120 indexed chunks, on a development machine:

| Endpoint | Time |
|---|---|
| `GET /papers?limit=50` | 11ms |
| `GET /papers/stats` | 7ms |
| `GET /papers?search=…` | 15ms |
| `GET /graph` | 60ms |
| `GET /recommendations` | 14ms |
| `GET /study/progress` | 26ms |
| `GET /assistant/search` | 24–26ms |

The graph is *faster* at 44 papers than it was at four before the N+1 fix.

**One verified non-bug.** With 40 near-identical papers the graph produced 40 nodes and zero
edges. That is the document-frequency ceiling working as designed: a term every paper uses
distinguishes nothing, so it is not a shared concept. Adding four genuinely distinct papers to
the same library produced 30 concepts and 78 edges immediately.

---

## Not measured

- **Answer quality.** No live model call has been made — no API key was available while
  building — so the assistant is exercised only with a scripted model. The retrieval half is
  fully verified; the generation half is verified for grounding and failure handling, not for
  whether a real model writes a good answer.
- **The reader in a browser.** No browser automation was available. PDF rendering, text
  selection, and highlight placement are verified by type-checking and a clean production
  build, which is not the same as being looked at.
