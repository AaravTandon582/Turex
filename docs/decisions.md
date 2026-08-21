# Decision record

Decisions that were not obvious, with the reasoning and the cost. A decision belongs here when
a competent engineer could reasonably have chosen differently.

Format: what was decided, why, what it costs, and what would change it.

---

## D1 — PostgreSQL with `pgvector` for both rows and embeddings

**Decided.** One database holds relational data and vectors. No dedicated vector store.

**Why.** A chunk and its embedding are written in the same transaction, so they cannot diverge.
With a separate vector database, every ingestion becomes a two-phase write with no shared
transaction: a crash between the two leaves either an orphaned vector or a chunk that search
cannot find, and reconciling that is ongoing work forever. Hybrid retrieval also wants to
combine vector similarity with SQL filters — owner, collection, reading status, publication
year — and doing that across two systems means over-fetching from one and filtering in
application code.

**Cost.** `pgvector`'s ANN index is good, not best-in-class. At tens of millions of chunks a
specialised store would win on latency.

**Revisit when** a single user's library exceeds roughly a million chunks, or vector search
latency exceeds retrieval budget at p95.

---

## D2 — Database-backed job queue, not Celery or Redis

**Decided.** Ingestion jobs are rows. A poller claims them with `FOR UPDATE SKIP LOCKED`.

**Why.** PDF processing must not block the upload response, but it also must be *observable* —
the user is watching a progress indicator. With the job as a row, progress is a column the
existing API already reads; with Celery, surfacing progress means adding a result backend and
polling a second system. Enqueueing in the same transaction as the paper row also means an
upload cannot half-succeed. And there is no second service to run, which matters for a project
that has to be reproducible from a clone.

**Cost.** No cron scheduling, no fan-out primitives, no task chaining. Polling costs one
lightweight query per interval per worker. Throughput is bounded by one process.

**Revisit when** ingestion volume saturates a single worker process, or scheduled recurring
work appears. The first step is running the existing poller as its own process — no schema
change.

---

## D3 — Provider abstraction for chat and embeddings, as two separate interfaces

**Decided.** `ChatProvider` and `EmbeddingProvider` are distinct. Anthropic is the default for
chat. Embeddings default to OpenAI, with a deterministic offline embedder for tests.

**Why.** They are separate because the vendor sets differ — Anthropic does not offer an
embedding model, so a single "AI provider" abstraction would immediately need an exception.
Two narrow interfaces are honest about that.

The offline embedder matters more than it sounds: it makes the retrieval pipeline testable
without network access or API keys, which means retrieval quality can be regression-tested in
CI rather than only by hand.

**Cost.** The abstraction is the intersection of what providers offer. Provider-specific
features — Anthropic's citation blocks, OpenAI's structured outputs — are reachable only by
widening the interface for everyone or bypassing it.

**Note.** Embedding dimensionality is fixed in the `pgvector` column. Changing embedding model
is a migration plus a re-index, not a config change. This is called out in `.env.example`.

---

## D4 — Sessions in httpOnly cookies, not JWTs in web storage

**Decided.** Short-lived signed access token plus a rotating opaque refresh token, both in
httpOnly cookies. Refresh tokens stored hashed. Replay revokes the session.

**Why.** A token in `localStorage` is readable by any script on the origin, so one XSS bug
anywhere — including in a dependency — is a full session compromise. httpOnly removes that
class of attack rather than mitigating it. Storing refresh tokens hashed means a database dump
does not hand over live sessions. Rotation with replay detection turns a stolen token from a
silent 30-day compromise into a revoked session the moment either party uses it twice.

**Cost.** Cross-origin cookies need `credentials: "include"` and an explicitly named CORS
origin. The Next server cannot read the session while rendering, which is what forces the
authenticated workspace to be client-rendered (see D6). Checking the session row on every
request costs one indexed lookup.

**Alternative rejected.** Long-lived stateless JWTs with no server-side session. Cheaper per
request, but logout becomes advisory — the token stays valid until it expires, which is not an
acceptable answer for a product holding someone's private research.

---

## D5 — Hybrid retrieval with reciprocal-rank fusion, and citations bound to chunk ids

**Decided.** Vector search and lexical search run in parallel and their rankings are fused.
Citations reference persisted chunk ids, not free text.

**Why.** Vector search alone misses exact terms — a specific gene name, an author, an equation
label — which is precisely the vocabulary that matters in scientific literature. Lexical search
alone misses paraphrase. Reciprocal-rank fusion combines the two rankings without needing the
two scores to be on a comparable scale, which they are not.

Binding citations to chunk ids is the load-bearing decision for the product's central claim. A
citation is not text the model produced; it is a foreign key. The server resolves it to a real
paper, page, and passage, and a claim that cannot be resolved cannot be rendered as a citation.
That makes "Turex does not fabricate citations" a property of the data model rather than a
property of a prompt.

**Cost.** Two searches per query. Chunks must be immutable once cited, so re-ingesting a paper
creates a new chunk generation rather than mutating rows.

---

## D6 — Client-rendered authenticated workspace

**Decided.** The landing page and auth screens are static server components. The workspace
resolves its session on the client.

**Why.** A consequence of D4 rather than a preference. The session cookie is scoped to the API
origin, so the Next server does not receive it and cannot render a personalised page.

**Cost.** A brief loading state on first entry to the workspace, covered by a skeleton with the
same geometry as the real frame so nothing shifts.

**Alternative rejected for now.** Proxying the API through Next route handlers would make
cookies first-party and enable server-side session reads, at the cost of an extra network hop
on every request and route definitions maintained in two places.

**Revisit when** Turex is deployed behind a single domain, which removes the cost of the proxy
approach.

---

## D7 — Real PostgreSQL in the test suite, not SQLite

**Decided.** Tests run against a real `turex_test` database, migrated from `base` each session.

**Why.** Turex depends on Postgres-specific behaviour throughout: `pgvector` operators,
`gen_random_uuid()`, `JSONB`, `FOR UPDATE SKIP LOCKED`, full-text search. A suite passing on
SQLite would be testing a different system than the one that ships, and would be silent on
exactly the parts most likely to break.

**Cost.** Contributors need PostgreSQL running. Tests are slower than in-memory.

---

## D8 — IBM Plex as the typeface family

**Decided.** Plex Sans for interface, Plex Serif for long-form reading, Plex Mono for code,
metadata, and citation locators.

**Why.** Turex should read as a scientific instrument. Plex has genuine technical character and
a matched serif and mono, so the three registers are visibly one family — which the standard
neutral-sans choices cannot offer without mixing families. The serif is reserved for sustained
reading, where it measurably helps, rather than used decoratively.

---

## D9 — Study material is grounded by construction, not by instruction

**Decided.** The generator is shown numbered passages and must cite one per item. The server
resolves that number to a chunk id and stores the passage text alongside the card. An item
citing a number it was never shown is discarded; if none survive, the request fails.

**Why.** "Only use the passages provided" is an instruction, and instructions are followed most
of the time. A flashcard is memorised, so a wrong one is worse than a wrong answer — it is
rehearsed. Making the link a foreign key the server writes turns a request into a guarantee,
and the same mechanism already backs assistant citations.

**Cost.** Fewer cards from a given run, since anything unattributable is thrown away. The
prompt has to carry the passages, so generation is a large request.

---

## D10 — Prompt-requested JSON, validated locally, over vendor structured output

**Decided.** Study generation asks for JSON in the prompt and validates it in
`ai/structured.py`, rather than using Anthropic's or OpenAI's native structured-output mode.

**Why.** The two vendors express it differently, and D3 keeps vendor-specific request shapes
out of the provider interface. Adding a structured-output parameter to `ChatRequest` would mean
a shape that only one provider could honour, or a lowest-common-denominator abstraction over
two APIs for one feature.

**Cost.** Responses arrive malformed sometimes — truncated, fenced, or wrapped in prose — so
the parser handles all three, and entries that fail validation are dropped rather than fixed.

**Revisit when** more than one feature needs constrained output, at which point the cost of a
real abstraction is spread over enough call sites to be worth it.

---

## D11 — The benchmark measures the offline embedder, and says so

**Decided.** The retrieval benchmark runs in CI against `HashingEmbeddingProvider`, a
deterministic bag-of-words stand-in, and its thresholds are set from what that embedder
achieves — not from what a real embedding model would.

**Why.** CI has no API key. The alternatives were worse: skipping the benchmark without one
means it never runs; setting thresholds for a real model means CI fails permanently; and
quietly setting them low while implying they describe production quality would make the
numbers a lie, which is the specific failure mode this whole product is built to avoid.

What the offline benchmark does catch is every embedder-independent regression — chunking,
section filtering, rank fusion, owner scoping — and each of those has broken at least once.

**Cost.** The published numbers understate real retrieval quality, and one benchmark query is a
permanent known failure because a bag-of-words embedder cannot answer it. That query is kept
and pinned by a test rather than deleted: a benchmark containing only cases the system passes
measures nothing.

**Revisit when** a key is available in CI, at which point the same harness runs unchanged with
`EMBEDDING_PROVIDER=openai` and the thresholds should be raised to match.

## D12 — The catalog is metadata only, and full text is fetched on demand

**Decided.** Two tables for two different things. `catalog_papers` holds title, authors,
abstract, categories, and dates for as many papers as have been harvested — hundreds of
thousands, unowned, shared by every account. `papers` holds the ones a reader actually has:
the stored PDF, the parsed sections, the chunks, the embeddings. Choosing a catalog entry
downloads the real PDF and runs the ordinary ingestion pipeline.

**Why.** They have costs that differ by three orders of magnitude. A library paper is about a
megabyte of disk and fifty embedding calls; a catalog paper is 3.4KB and neither. Measured on
the harvested corpus:

| | per paper | 200,000 papers |
|---|---|---|
| Catalog entry | 3.4KB, no network, no model | ~650MB |
| Library paper | ~1MB, one download, ~50 embeddings | ~200GB, ~10M embedding calls |

The second column is why "hundreds of thousands of papers" cannot mean full text. It is not a
tuning problem — 10 million embedding calls is weeks of API time and the disk is not there.
An abstract, though, is what a researcher actually reads to decide whether to open a paper,
and it is what every literature-search tool indexes. So the wide half is genuinely useful on
its own, and the narrow half stays as deep as it was.

**Cost.** A catalog paper cannot be read, cited, or asked about until it is imported, and the
UI has to say so rather than implying otherwise. The Discover card therefore polls after an
import and only offers *Read* once ingestion finishes — an earlier version linked straight
away and sent people to a page that told them to come back later.

The catalog is also the only table in the schema that is not owner-scoped. arXiv's metadata is
identical for everybody and a per-user copy would multiply hundreds of thousands of rows by
the number of accounts to store the same bytes. What is kept private is which papers a given
account has imported, which lives in that account's own library.

**Revisit when** abstracts alone stop being enough to choose a paper — a cheap enough embedding
model would make semantic search over the catalog worth its cost, and the column and index
would be the only additions.

## D13 — Catalog search is lexical, and the harvester keeps the planner honest

**Decided.** Search over the catalog is PostgreSQL full text — a GIN index over a weighted
tsvector of title and abstract — not vector search. The harvester runs `ANALYZE` every fifty
pages and at the end of every run, including runs that fail.

**Why.** Embedding 200,000 abstracts is 200,000 API calls before anyone can search at all, and
several million for a full arXiv mirror. A GIN index is built once, needs no key, and answers
ranked queries over the whole corpus in milliseconds. Weighting the title above the abstract
recovers most of what people want from relevance: a paper *about* diffusion models outranks
one that mentions them in passing.

The `ANALYZE` half is not housekeeping. Autovacuum's threshold is proportional to a table's
existing size, so a table growing from 5,000 rows to 200,000 keeps statistics describing the
5,000 for a long while — and with those, PostgreSQL mis-estimates how many rows a common word
matches and abandons the GIN index for a sequential scan. Measured on the same 192,400 rows
with the same index:

| Query | Stale statistics | After `ANALYZE` |
|---|---|---|
| `learning` (widest possible) | 1,080ms | 210ms |
| `neural network` | 1,776ms | 170ms |
| `transformer attention` | — | 14ms |

`ANALYZE` costs 2.2 seconds at that size, against the twenty minutes those pages take to
arrive. It was found by measuring the API at scale rather than by reading the plan, which is
the argument for measuring at scale.

**Cost.** Lexical search cannot connect *"models that make images from noise"* to *"denoising
diffusion probabilistic models"*. That is a real limitation and the Discover page does not
pretend otherwise; the semantic half of Turex begins once a paper is in the library, where
there are chunks to embed.

**Revisit when** the catalog is large enough that the result counter's 1,000 ceiling stops
being a reasonable answer, or an embedding model is cheap enough to run over every abstract.
