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
That makes "Atlas does not fabricate citations" a property of the data model rather than a
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

**Revisit when** Atlas is deployed behind a single domain, which removes the cost of the proxy
approach.

---

## D7 — Real PostgreSQL in the test suite, not SQLite

**Decided.** Tests run against a real `atlas_test` database, migrated from `base` each session.

**Why.** Atlas depends on Postgres-specific behaviour throughout: `pgvector` operators,
`gen_random_uuid()`, `JSONB`, `FOR UPDATE SKIP LOCKED`, full-text search. A suite passing on
SQLite would be testing a different system than the one that ships, and would be silent on
exactly the parts most likely to break.

**Cost.** Contributors need PostgreSQL running. Tests are slower than in-memory.

---

## D8 — IBM Plex as the typeface family

**Decided.** Plex Sans for interface, Plex Serif for long-form reading, Plex Mono for code,
metadata, and citation locators.

**Why.** Atlas should read as a scientific instrument. Plex has genuine technical character and
a matched serif and mono, so the three registers are visibly one family — which the standard
neutral-sans choices cannot offer without mixing families. The serif is reserved for sustained
reading, where it measurably helps, rather than used decoratively.
