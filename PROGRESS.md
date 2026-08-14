# Atlas — Implementation Progress

Atlas is an intelligent research workspace: **Read → Understand → Connect → Question → Hypothesize → Test → Learn.**

This file is the living record of what is built, what is in flight, and what was decided.
Architectural rationale lives in [`docs/decisions.md`](docs/decisions.md).

---

## Milestone roadmap

| # | Milestone | Scope | Status |
|---|-----------|-------|--------|
| M0 | Architecture | Repo layout, stack selection, schema, API contract, design system, env config, docs | ✅ Complete |
| M1 | Foundation | Config, logging, error envelope, DB + migrations, auth, app shell, navigation, landing page | ✅ Complete |
| M2 | Research Library | PDF upload, storage, async ingestion pipeline, parsing, metadata, chunking, library UI, collections, tags, reading status | 🔄 In progress |
| M3 | AI Research Assistant | Provider abstraction, embeddings, hybrid retrieval, context construction, streaming chat, grounded citations, modes | ⏳ Not started |
| M4 | Paper Reader | PDF viewer, highlights, annotations, selection → AI actions, equation explainer, citation export | ⏳ Not started |
| M5 | Research Workspace | Projects, notebook, hypotheses, experiments, tasks | ⏳ Not started |
| M6 | Intelligence Layer | Semantic search, recommendations, knowledge graph | ⏳ Not started |
| M7 | Study Mode | Explanations by level, flashcards, quizzes, progress tracking | ⏳ Not started |
| M8 | Polish | Motion, responsiveness, a11y, empty/loading/error states, onboarding | ⏳ Not started |
| M9 | Evaluation | Retrieval + citation benchmark, hallucination checks, security review | ⏳ Not started |
| M10 | Demo | Seeded demo account, curated papers, scripted walkthrough | ⏳ Not started |

Each milestone is delivered as vertical slices — UI → API → service → database → tests — not as
disconnected layers.

---

## Completed: M1 — Foundation

A running, authenticated, navigable application with a real database and a design system the
rest of the product is built from.

- [x] Repository layout and tooling (`backend/`, `frontend/`, `docs/`)
- [x] Configuration, structured logging with request correlation, single error envelope
- [x] Async SQLAlchemy over PostgreSQL, Alembic migrations, `pgvector` enabled
- [x] Authentication: register, login, refresh with rotation, logout, current user
- [x] Design system — OKLCH tokens, typography, motion, light and dark themes
- [x] Application shell: sidebar, mobile drawer, `g`-chord navigation shortcuts
- [x] Landing page, sign-in and registration, 404
- [x] 21 backend tests passing; ruff, mypy, and the production build all clean

**Verified end to end:** register → authenticated request → token rotation → immediate logout,
exercised through the real frontend origin with browser-equivalent cookie handling.

---

## Current milestone: M2 — Research Library

**Goal:** a user can add a paper and Atlas genuinely reads it — parsed into sections and
chunks, with metadata extracted and progress visible while it happens.

- [ ] Storage abstraction with a local filesystem driver
- [ ] Paper, section, chunk, collection, tag, and job schema
- [ ] Upload endpoint with validation (type, size, and content sniffing)
- [ ] Database-backed job queue and in-process worker
- [ ] PDF parsing: text, structure, metadata, references
- [ ] Chunking that preserves page and section provenance
- [ ] Library UI: grid, filters, reading status, collections
- [ ] Tests across the whole path — upload through to queryable chunks

---

## Decisions log (summary)

Full rationale in [`docs/decisions.md`](docs/decisions.md).

| ID | Decision |
|----|----------|
| D1 | PostgreSQL + `pgvector` for relational data *and* embeddings — one datastore, transactional consistency between a chunk and its vector |
| D2 | Database-backed job queue instead of Celery/Redis — ingestion progress is queryable, deployment stays single-service |
| D3 | Provider abstraction for both chat and embeddings; Anthropic is the default chat provider, embeddings are pluggable with a deterministic offline fallback for tests |
| D4 | httpOnly cookie sessions with rotating refresh tokens rather than localStorage JWTs — removes the XSS token-theft class entirely |
| D5 | Retrieval is hybrid (vector + lexical) with reciprocal-rank fusion; citations reference persisted chunk IDs so every claim resolves to a real source location |
| D6 | Next.js App Router with server components by default; client components only where interaction demands it |

---

## Known issues

_None recorded yet._

---

## Future improvements

- S3-compatible object storage backend (the storage interface exists; only the local driver is implemented)
- Reranking model in the retrieval pipeline (the pipeline has the stage; it is currently a no-op pass-through)
- Multi-user project collaboration (schema is single-owner today)
