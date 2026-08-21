# Architecture

This describes how Turex is put together and why. It covers what exists today and names the
seams that later milestones plug into. It does not describe unbuilt features as though they
work — see [`../PROGRESS.md`](../PROGRESS.md) for what has shipped.

---

## Shape of the system

```
┌──────────────────────────────┐
│  Next.js app (port 3000)     │
│  • Landing + auth: static    │
│  • Workspace: client-side,   │
│    session held in a cookie  │
└──────────────┬───────────────┘
               │  fetch, credentials: include
               ▼
┌──────────────────────────────┐
│  FastAPI (port 8000)         │
│                              │
│  api/       HTTP concerns    │
│  services/  business rules   │
│  models/    persistence      │
│  ai/        model providers  │◄── Anthropic · OpenAI
│  ingestion/ document parsing │
│  retrieval/ search + context │
└──────────────┬───────────────┘
               ▼
┌──────────────────────────────┐
│  PostgreSQL + pgvector       │
│  rows and embeddings, one    │
│  transactional store         │
└──────────────────────────────┘
```

Two processes, one database. There is no message broker, no separate vector store, and no
cache tier — each of those would be a second thing to run and to keep consistent, and Turex
does not yet have a problem that needs one. The places where they would slot in are noted
below.

---

## Backend layering

Requests move in one direction. A layer may call the one beneath it and never the one above.

| Layer | Owns | Must not |
|-------|------|----------|
| `api/` | Routing, request parsing, cookies, status codes, dependency wiring | Contain business rules |
| `services/` | The rules: what is allowed, what happens, in what order | Know about HTTP, cookies, or FastAPI |
| `models/` | Table definitions and relationships | Contain query logic that belongs to a service |
| `core/` | Config, logging, errors, hashing, tokens | Import from any layer above |

Four domain packages sit beside `services/` and are called by it. Each is pure enough to test
without a database or a network:

| Package | Owns |
|---------|------|
| `ingestion/` | PDF parsing, text cleaning, section detection, chunking |
| `retrieval/` | Hybrid search, rank fusion, context assembly within a token budget |
| `ai/` | The provider interfaces, the two vendor implementations, prompts, JSON validation |
| `study/` | Spaced-repetition scheduling and the generation prompts |

The practical test: a service should be callable from a background worker or a seed script
with no HTTP request in sight. The ingestion worker reuses `PaperService` exactly that way.

### Errors

Every failure crosses the wire in one shape:

```json
{ "error": { "code": "not_found", "message": "We couldn't find that." } }
```

`code` is a stable identifier the frontend branches on; `message` is written for a person and
is always safe to display. Internal diagnostics travel in the `detail` field of the exception,
which is logged and **never serialised into a response** — not even in debug mode. That is a
deliberate constraint: it is what keeps a wrong password and an unknown email byte-identical to
a caller regardless of how the server is configured, which is exactly the kind of guarantee
that erodes when it depends on an environment flag.

Handlers raise domain errors from `core/errors.py`. Anything else that reaches the top-level
handler is a bug: it is logged with a stack trace and reported as a generic `internal_error`.

### Logging

Structured, JSON in production and human-readable locally. A `ContextVar` carries the request
id (and user id once authenticated) onto every record emitted while handling that request, so
one failing request can be traced across service and database layers without threading a
logger through every signature.

Never logged: credentials, tokens, or document contents.

---

## Authentication

Cookie sessions, not bearer tokens in web storage.

| Token | Lifetime | Form | Storage |
|-------|----------|------|---------|
| Access | 15 minutes | Signed JWT (`HS256`) | httpOnly cookie, path `/` |
| Refresh | 30 days | Opaque 384-bit random string | httpOnly cookie, path `/api/v1/auth`; only the SHA-256 hash is stored |

Three properties this buys:

- **XSS cannot steal a session.** No JavaScript on any origin can read an httpOnly cookie, so
  the entire token-exfiltration class is closed rather than mitigated.
- **A database leak yields no usable tokens.** Refresh tokens are stored hashed.
- **Theft is detected, not just survived.** Refresh tokens rotate on every use, and the
  previous hash is retained. Presenting an already-rotated token means two parties hold it, so
  the session is revoked instead of refreshed. That revocation is committed before the error is
  raised, because the request-scoped transaction would otherwise roll it back.

Authenticating a request checks both the token signature and the session row, so signing out
takes effect immediately rather than whenever the access token happens to expire. That is one
extra indexed lookup per request, bought deliberately: a logout that silently does nothing for
fifteen minutes is not a logout.

CSRF is addressed by `SameSite=Lax` plus a CORS policy that names the frontend origin
explicitly — a wildcard origin is invalid alongside `allow_credentials`, so the configuration
cannot silently degrade.

---

## Frontend

**Server components by default; client components only where interaction requires them.** The
landing page, the auth shell, and every unbuilt-milestone screen are fully static — they ship
no component JavaScript.

The authenticated workspace is client-rendered, and this is a consequence of the deployment
shape rather than a preference: the session cookie is scoped to the API origin, so the Next
server cannot read it while rendering. The client resolves the session once on mount and
renders a skeleton with the same geometry as the real frame in the meantime, so nothing shifts
when it arrives.

The alternative — proxying API routes through Next so cookies become first-party — would enable
server-side session reads at the cost of a second hop on every request and duplicated route
definitions. If Turex is later deployed behind a single domain, this becomes worth revisiting.

### API client

`lib/api.ts` centralises two things worth centralising:

- **Error translation.** Every failure becomes an `ApiError` carrying the stable `code`, the
  human `message`, and per-field validation errors, so forms can render errors beside the
  input that caused them.
- **Silent re-authentication.** Access tokens last minutes. On a 401 the client rotates the
  refresh token once and replays the request; concurrent callers share a single refresh rather
  than racing. A long reading session is never interrupted by an expiry the user did not cause.

### Design system

Tokens live in `globals.css`, authored in OKLCH and exposed to Tailwind via `@theme inline`.
Both themes define every token, so "muted" is perceptually equally muted in light and dark —
which is not true of hand-picked hex pairs.

The theme is applied by a blocking inline script before first paint, so navigating into the app
in dark mode never flashes white.

---

## Two kinds of paper

Turex stores a paper two ways, and the distinction runs through the whole system.

A **catalog paper** (`catalog_papers`) is one Turex knows exists: title, authors, abstract,
categories, dates. About 3.4KB, harvested in bulk from arXiv's OAI-PMH feed by
`scripts/harvest_arxiv.py`, shared by every account, searched with PostgreSQL full text.
Hundreds of thousands fit comfortably.

A **library paper** (`papers`) is one a reader has: the stored PDF, parsed sections, chunks,
embeddings. About a megabyte and fifty embedding calls. This is what the reader renders, what
retrieval searches, and what a citation can point at.

`POST /catalog/{id}/import` is the bridge, and it deliberately goes through
`add_from_identifier` — the same path the "add by reference" box uses — rather than a shortcut
of its own. The download gets the same SSRF checks, the file is validated by its bytes,
identical files deduplicate, and ingestion is the pipeline an upload gets. An imported paper
has nothing special about it, which is the point: everything downstream works without knowing
where the paper came from.

Nothing blurs the line. A catalog entry never pretends to have full text, and the assistant
can only cite chunks, which only library papers have. See [`decisions.md`](decisions.md) D12.

## Cross-cutting mechanisms

**Document ingestion** is asynchronous and database-backed. An upload writes the file to
storage and enqueues a job row; a poller in the API process claims jobs with
`SELECT … FOR UPDATE SKIP LOCKED` and advances them through parse → chunk → embed. Progress is
a column, which means the UI can show real progress by reading it, and a crash mid-parse leaves
a retryable row rather than a lost upload. If throughput ever outgrows one process, the poller
moves to its own container with no schema change.

**Storage** sits behind an interface with a local-filesystem implementation. Object storage is
a second implementation, not a rewrite.

**AI providers** sit behind two interfaces — chat and embeddings — because they have
different vendors: Anthropic has no embedding model. A deterministic offline embedder backs the
test suite so retrieval can be tested without network access or API keys.

**Retrieval** is a pipeline of named stages: retrieve → fuse → rerank → build context.
Reranking is a real stage with a pass-through implementation, so adding a cross-encoder later
is a swap rather than surgery. Citations reference persisted chunk ids, which is what makes
"every claim resolves to a real passage" enforceable rather than aspirational.

**Generated content is tied to its source by the server, never by the model.** Assistant
citations, flashcards, and quiz questions all follow the same rule: the model is given numbered
passages and refers to them by number, and the server turns that number into a foreign key plus
a snapshot of the passage text. A reference to a number the model was never given is discarded
rather than stored. This is the single mechanism behind Turex's central claim, and it lives in
three places — `services/assistant_service.py`, `services/study_service.py`, and the models
that hold the snapshots.
