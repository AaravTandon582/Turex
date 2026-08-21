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

Measured both ways, because the embedder makes more difference than anything else in the
pipeline:

| Metric | Offline embedder | Real embedding model |
|---|---|---|
| recall@1 | 50% | 38% |
| recall@3 | 88% | **100%** |
| recall@5 | 88% | **100%** |
| MRR | 0.646 | 0.646 |

The **offline** column is what CI enforces. It has no API key, so it runs against
`HashingEmbeddingProvider` — a deterministic bag-of-words stand-in with no semantics. It can
match wording; it cannot connect *"which proteins gained most"* to *"the gain concentrates in
proteins with fewer than one hundred effective sequences"*. That query fails there, and is
pinned by a test that fails if a second joins it **or if it starts passing** — a benchmark
containing only cases the system passes measures nothing. See [`decisions.md`](decisions.md) D11.

The **real** column is `qwen/qwen3-embedding-8b` through an OpenAI-compatible endpoint, asked
for 1536 dimensions so it fits the existing `pgvector` column. Its native width is 4096, which
would not have fit: pgvector's HNSW index stops at 2000 dimensions, so a wider vector means no
fast search at all. Truncation is what makes it usable without a migration.

Every query finds its answer within three results, including the one the offline embedder
cannot. recall@1 is *lower* — semantic retrieval finds everything but orders the very top
slightly differently — which is a real trade and worth stating rather than hiding behind the
headline.

```bash
EMBEDDING_PROVIDER=openai python -m evaluation              # the real column
EMBEDDING_PROVIDER=local  python -m evaluation              # the CI column
EMBEDDING_PROVIDER=openai python -m evaluation --no-rerank  # what reranking is worth
```

### What writing it found

Two benchmark bugs and no retrieval bugs. Two queries had more than one correct answer;
retrieval returned a different valid one and the benchmark scored a miss. Both queries were
sharpened rather than the thresholds lowered — the failing runs are recorded in the `note`
field of each query in `evaluation/corpus.py`.

---

## Reranking

Fusion combines the vector and lexical rankings by position and never looks at the passages.
Reranking looks: whether the query's terms appear, whether they appear *together*, whether the
passage is a paragraph or a caption, and what kind of section it sits in — a weak section
(acknowledgements, references, appendix) multiplies the score down rather than subtracting a
little, because the query's words appearing there means less, not slightly less.

**What it is worth depends entirely on the embedder**, which is the useful finding:

| | recall@3 | MRR |
|---|---|---|
| Offline embedder, fusion alone | 88% | 0.646 |
| Offline embedder, reranked | 88% | 0.646 |
| Real embeddings, fusion alone | 88% | 0.635 |
| Real embeddings, reranked | **100%** | **0.646** |

With the bag-of-words embedder it changes nothing: a lexical reranker reinforces the signal
that already produced the ranking. With a semantic embedder it is worth twelve points of
recall@3, because the two halves are then measuring different things and the lexical half
corrects the top of the order.

That is the whole argument for keeping it, and it only became visible once a real embedding
model was available to measure against. Before that the honest report was "it changes nothing",
which is what this document said.

The first version was worse than useless: a reciprocal position prior halves between the first
and second result, a gap no content signal can close, so it reordered nothing while appearing
to work. Only measuring it showed that.

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

## The catalog, at scale

885,097 papers — 657,534 from arXiv and 227,563 from OpenAlex — on a development machine.
Times are warm, three runs each, through the API rather than against the database:

| Query | Time |
|---|---|
| `transformer attention` (390 matches) | 45ms |
| `learning` (203,846 matches — the widest word in the corpus) | 320ms |
| browse `cs.LG` (147,406 papers) | 20ms |
| browse newest, no query | 12ms |
| `GET /catalog/stats` | 14ms |

**Three separate problems, found by measuring at each size rather than once.**

*Stale statistics.* At 192,400 rows, common-word searches took 0.8–1.8 seconds because
PostgreSQL was mis-estimating how many rows a word matches and abandoning the GIN index for a
sequential scan. The harvester now runs `ANALYZE` every fifty pages and at the end of every
run, including runs that fail — 1,776ms to 170ms on the same index. See
[`decisions.md`](decisions.md) D13.

*An index that did not match its query.* Browsing a large category took 6.5 seconds at 885,000
rows: an index on `published_on` existed and could not be used, because the ordering is
`DESC NULLS LAST` and a default btree walked backwards gives `DESC NULLS FIRST`. Spelling the
index the way the query spells the ordering took it to 3.4ms. Migration 0017.

*Ranking with no index behind it.* `ts_rank_cd` has to be computed for every match and the
whole set sorted, which is fine until a common word matches a fifth of a large catalog —
`learning` at 885,000 rows took **18 seconds**. Ranking is now bounded to a pool of 3,000
candidates. Below that many matches nothing changes at all, since the bound is a `LIMIT` on
the inner query and a search matching two thousand papers never reaches it. Above it, the
twenty shown are the best of three thousand relevant papers rather than the best of two
hundred thousand — a real trade, made because the alternative was a ranking nobody waits to
see. See [`decisions.md`](decisions.md) D13.

*The header's summary* counts every row and expands every paper's category list, which is five
seconds of scanning for a sentence. It is cached for five minutes, per process, because none of
it changes meaningfully in that time.

**The result counter is bounded.** A `count(*)` over a text search is proportional to how many
rows *match*, not how many are returned. Counting all 40,670 matches for `learning` costs more
than finding the twenty anyone will read, so the count stops at 1,000 and the response carries
`total_is_exact` so the UI renders `1,000+` rather than a precise-looking number that is not
the truth.

---

## Not measured

- **Answer quality, systematically.** Live model calls are made and the assistant has been
  driven end to end against a real model, so the claim that it is exercised only by a script
  is no longer true. What is still missing is a *scored* generation benchmark: nothing
  measures whether an answer is good, only that it is grounded, that its citations resolve,
  and that a model which misbehaves cannot make Atlas misbehave.
- **Semantic search over the catalog.** Catalog search is lexical, so it cannot connect a
  description to a paper that uses different words for the same idea. This is a stated
  limitation rather than an untested one — see [`decisions.md`](decisions.md) D13.
- **A full arXiv mirror.** Measured to 192,400 papers. The whole of arXiv is roughly 2.6
  million, which the same code should reach in about eleven hours and 8.7GB, but that has not
  been run — and 8.7GB is more free disk than the development machine had.
