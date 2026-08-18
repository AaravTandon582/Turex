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
| M2 | Research Library | PDF upload, storage, async ingestion pipeline, parsing, metadata, chunking, library UI, collections, tags, reading status | ✅ Complete |
| M3 | AI Research Assistant | Provider abstraction, embeddings, hybrid retrieval, context construction, streaming chat, grounded citations, modes | ✅ Complete |
| M4 | Paper Reader | PDF viewer, highlights, annotations, selection → AI actions, equation explainer, citation export | ✅ Complete |
| M5 | Research Workspace | Projects, notebook, hypotheses, experiments, tasks | ✅ Complete |
| M6 | Intelligence Layer | Semantic search, recommendations, knowledge graph | ✅ Complete |
| M7 | Study Mode | Explanations by level, flashcards, quizzes, progress tracking | ✅ Complete |
| M8 | Polish | Motion, responsiveness, a11y, empty/loading/error states, onboarding | ✅ Complete |
| M9 | Evaluation | Retrieval + citation benchmark, hallucination checks, security review | ✅ Complete |
| M10 | Demo | Seeded demo account, curated papers, scripted walkthrough | 🔄 In progress |

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

## Completed: M2 — Research Library

A user can add a paper and Atlas genuinely reads it.

- [x] Content-addressed storage behind an interface, with a local filesystem driver
- [x] Schema for papers, sections, chunks, collections, tags, and jobs
- [x] Upload validated by magic bytes and size, not by the declared type
- [x] Database-backed queue with leases, retry backoff, and per-stage progress
- [x] PDF parsing: text repair, section outline, title / authors / abstract / identifiers
- [x] Chunking that never spans a section and carries page provenance on every passage
- [x] Library UI: drag-and-drop upload, live progress, search, filters, sort, pagination
- [x] Paper detail with outline, metadata, reading status, and reprocess
- [x] 89 backend tests; ruff, mypy, and the production build clean

**Parser validated against five real papers across four templates** (NeurIPS, CVPR/IEEE, ACL,
OpenAI). Titles, authors, and publication years extract correctly on all five.

**Verified end to end:** a 68-page paper uploaded through the API moves queued → extracting →
ready with progress visible at each step, producing 78 sections and 149 located chunks.

---

## Completed: M3 — AI Research Assistant

Ask a question, get an answer built from passages actually retrieved from your library.

- [x] Separate chat and embedding provider interfaces; Anthropic and OpenAI implementations
- [x] Deterministic offline embedder, so retrieval is regression-tested in CI with no API key
- [x] Embedding stage in ingestion, resumable and safe to re-run
- [x] Hybrid retrieval — vector + lexical, fused by reciprocal rank, owner-scoped in SQL
- [x] Context construction within a token budget, numbering passages for citation
- [x] SSE streaming: sources first, then the answer, then the stored message id
- [x] Citations written server-side from retrieved passages, with a text snapshot
- [x] Seven modes, each with its own prompt, reasoning effort, and retrieval breadth
- [x] Assistant UI with resolvable inline citations and a mode picker
- [x] 137 backend tests; ruff, mypy, and the production build clean

**Verified live** against three real papers: "how does multi-head attention work" returns
§3.2.2 Multi-Head Attention; "masked language model pre-training objective" returns the exact
MLM paragraph in BERT. All 153 chunks indexed.

**Not verified:** a real Anthropic round trip. No API key was available in this environment, so
the provider is covered only by tests with a scripted model. Set `ANTHROPIC_API_KEY` to confirm.

---

## Completed: M4 — Paper Reader

Read a paper inside Atlas, highlight it, and ask about a passage without leaving it.

- [x] PDF rendering with zoom, page markers, and jump-to-section from the outline
- [x] Text-anchored highlights that survive zoom and re-render (offset + length, not pixels)
- [x] Four highlight colours named by intent, with notes
- [x] Selection menu: highlight, Explain, Critique, or break down an equation
- [x] Paper-scoped assistant panel, so retrieval stays inside the paper being read
- [x] Citation export in BibTeX, APA, and MLA — built only from stored metadata
- [x] 170 backend tests; ruff, mypy, and the production build clean

**Verified live:** highlights create, recolour, and clear notes correctly; citations for a real
paper produce all eight authors, the correct year and arXiv id, and report the missing venue
rather than inventing one.

**Not verified:** the rendered reader in a browser. No browser automation was available in this
environment, so PDF rendering, text selection, and highlight placement are unexercised at
runtime — the route serves and the build is clean, but that is not the same thing.

---

## Completed: M5 — Research Workspace

A research question with everything gathered to answer it.

- [x] Projects built around a research question, with counts of what is inside
- [x] Hypotheses with six states, assumptions, and evidence tracked on both sides
- [x] Evidence linked to real passages — the server reads the chunk, the client sends only an id
- [x] Experiments with variables, controls, confounders, metrics, and prediction vs outcome
- [x] Notebook with autosaving Markdown notes, linkable to a project or paper
- [x] Tasks per project
- [x] 207 backend tests; ruff, mypy, and the production build clean

**Verified live, as one continuous loop:** project → gather a paper → write a hypothesis →
search the library → attach a real passage as evidence → design an experiment with a recorded
prediction → record the actual result → downgrade the hypothesis to weakly supported.

---

## Completed: M6 — Intelligence Layer

**Goal:** surface what the library already knows but has not been asked.

- Recommendations from mean-pooled document embeddings, cosine-scored against the rest of the
  library. Each one states which paper it came from; nothing is recommended without a reason.
- Knowledge graph over papers, shared concepts, projects, and research questions. Concepts are
  corpus statistics — unigrams and bigrams that several papers actually use — not a model's guess.
- Dashboard reading from the real stats, project, and recommendation endpoints.

**Verified live** against four downloaded papers (Attention, BERT, RAG, ResNet): 30 concepts,
78 edges, with `question answering`, `transformer`, `encoder`, `representations`, and
`architecture` as the strongest shared terms.

**Tuning done against measured values, not guesses:**

- `SIMILARITY_THRESHOLD = 0.25` — the genuinely related pair measured 0.409 and the unrelated
  pair 0.097. The first value tried (0.45) excluded the pair the feature exists to find.
- `DOCUMENT_FREQUENCY_FLOOR = 5` — the "too common to be interesting" ceiling is meaningless
  below five papers, where it excluded exactly the terms shared by most of the library.
- `MIN_TERM_FREQUENCY = 3` — filters incidental words like "percent" and "median".

**Two bugs worth remembering:**

- Concept extraction originally matched Title Case and acronyms. On real text this matched
  across heading boundaries ("Abstract Transformer") and missed every lowercase technical term.
  Replaced with corpus statistics.
- Ruff reformatted the stopword `frozenset` into a one-word-per-line list, after which several
  string-replace additions to it silently no-opped. The list is now built by splitting a text
  block, which no formatter can rewrite.

---

## Completed: M7 — Study Mode

**Goal:** turn a paper you have read into something you can actually recall.

- Flashcards generated from a paper's own passages, each storing the chunk id **and** a
  snapshot of the passage text. A card citing a passage number the model was never shown is
  discarded; if none survive, the request fails with 422 rather than returning an empty deck.
- Quizzes with the same grounding. The answer key is withheld from the response until the quiz
  has been submitted, and scoring happens server-side.
- Spaced repetition — a trimmed SM-2 with a per-card ease factor, four grades, and a lapse
  path that keeps a forgotten card in the same session.
- Explanations pitched at beginner / intermediate / advanced, selectable per turn in the
  assistant.
- Progress counted, not estimated: cards, due, mastered (interval ≥ 21 days), reviews in the
  last seven days, and the best quiz score per paper.

**Tested:** 26 new tests. The generator is deliberately driven off the rails — citing passage
numbers it was never shown, wrapping JSON in a Markdown fence, returning truncated JSON,
returning prose with no JSON at all — and Atlas is asserted to drop, recover, or fail loudly
rather than store something ungrounded.

**Three bugs worth remembering:**

- FastAPI's `response_model` serialises a returned subclass as the declared base class, so the
  submitted quiz came back with the answer key stripped off again. The field is now a union.
- A hard 320-character floor on passages made short papers un-studyable. The length bar is now
  a preference that drops when a paper does not clear it.
- The notebook's autosave wrote a ref during render to keep the debounced save current. The
  effect already re-runs per keystroke and cancels the pending timer, so the ref was both
  unnecessary and a React violation. Removed.

---

## Completed: M8 — Polish

**Goal:** make the whole thing feel finished rather than assembled.

The audit found three real defects rather than cosmetic ones.

**Every screen told the truth about failure.** Twenty places caught a failed request and set
an empty array, so a page whose data could not load reported that the reader had nothing — no
projects, no notes, no search results. Added `useAsync` and `AsyncBoundary`, which keep
*loading*, *failed*, *empty*, and *loaded* apart; failures now carry a message and a retry.
The dashboard also loads each panel separately, so a failing recommendation service no longer
blanks the projects beside it.

**The mobile drawer was not a dialog.** It covered the page without trapping focus, so Tab
walked into content behind it. It now has dialog semantics, keeps Tab inside, and restores
focus to the button that opened it.

**Two screens were unusable on a phone.** The notebook put a 288px list beside the editor,
leaving under 90px to write in; it now shows one pane at a time. The reader put a 320px
sidebar beside the PDF; that is now an overlay below `md`.

**One N+1, found by shape rather than by timing.** The knowledge graph read each paper's
opening passages in its own query — 204 queries for 200 papers. Every endpoint still answered
in under 80ms with four papers, which is exactly the reading that hides this. New tests count
statements at two library sizes and require the count not to grow. Five other endpoints were
checked the same way and were already flat.

**Verified in place rather than rebuilt:** reduced-motion handling, the skip link, live
regions, focus-visible styles, the empty-state onboarding for a new account, the `g`-chord
shortcut hints in the sidebar, and the notice shown when no model provider is configured.

**Tested:** 252 backend tests (6 new), mypy clean, ruff clean, eslint 0 errors, build clean.

---

## Completed: M9 — Evaluation

**Goal:** measure the claims rather than assert them. Full detail in
[`docs/evaluation.md`](docs/evaluation.md).

- A scored retrieval benchmark — three purpose-written papers, eight queries with known
  answers, recall@k and MRR. Runnable as `python -m evaluation`, enforced as thresholds in the
  test suite. Currently recall@3 88%, MRR 0.646.
- Citation integrity across the whole database: every citation resolves, snapshots match, and
  neither re-ingestion nor deleting a paper can leave one pointing at nothing.
- Model-misbehaviour suite: markers for sources that were never provided, zero markers, more
  markers than sources, no markers, and an empty answer — none may store anything ungrounded.
- Authorisation by enumeration: every route read from the app's own schema must answer 401
  without a session unless declared public with a reason. All pass; six are public.
- Security properties as tests: no credential literals or vendor keys in source, no
  interpolated SQL, production config refusing the dev secret key, byte-identical login
  failures, error envelopes carrying no internal detail, and inert handling of hostile uploads.
- Scale check at 44 papers and 120 chunks: every endpoint under 60ms.

**One real issue found and fixed:** uploaded filenames were stored verbatim, so
`../../etc/passwd.pdf` was kept as the display name. Never a traversal risk — storage keys are
content-addressed and the download header already stripped what would break it — but it is
shown in the library and exported into citations, so it is now reduced to a bare filename at
the point of storage.

**Two benchmark bugs, no retrieval bugs.** Two queries had more than one correct answer;
retrieval returned a different valid one and the benchmark scored a miss. The queries were
sharpened rather than the thresholds lowered, and each carries a note recording what it got
wrong. One query remains a permanent failure — the offline bag-of-words embedder genuinely
cannot answer it — and is pinned by a test rather than deleted.

**One verified non-bug:** 40 near-identical papers produced a graph with zero edges. That is
the document-frequency ceiling working as designed; four distinct papers added to the same
library produced 78 edges immediately.

**Tested:** 308 backend tests (56 new), mypy clean over 81 files, ruff clean.

---

## Current milestone: M10 — Demo

**Goal:** something someone can be walked through in five minutes.

- [ ] A seeded demo account with a curated library
- [ ] A demo project carrying a real research question end to end
- [ ] A scripted walkthrough that survives being followed exactly
- [ ] Presentation material and a recorded run

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
| D7 | Tests run against real PostgreSQL, not SQLite — Atlas depends on pgvector, JSONB, and `SKIP LOCKED` |
| D8 | IBM Plex as the typeface family — technical character, with a matched serif and mono |

---

## Known issues

- **One unexplained 401 on an upload during manual testing.** Observed once; not reproducible
  across six subsequent uploads, and no 401 appeared in the server log. The session path is
  covered by the auth suite. Recorded rather than claimed fixed — if it recurs, start with the
  cookie `Path` scoping in `api/cookies.py`.
- **No live model call has been made.** No `ANTHROPIC_API_KEY` was available while building, so
  the Anthropic provider is exercised only through tests with a scripted model. The retrieval
  half is fully verified live.
- **Reranking is a pass-through.** The pipeline stage exists but does nothing yet.
- **The reader has not been exercised in a browser.** No browser automation was available, so
  PDF rendering, text selection, and highlight placement are verified only by type-checking and
  a clean production build. The anchoring logic in `lib/text-layer.ts` is the part most likely
  to need adjustment against a real document.
- **No study material has been generated by a real model.** Same cause as the assistant: no
  API key was available. The grounding, discarding, parsing, and failure paths are covered by
  tests with a scripted model, and the endpoints degrade to a clear 503 without a provider.
- **`react-hooks/set-state-in-effect` is a warning, not an error.** The rule cannot see across
  an `await`, so it flags every client-side fetch-on-mount. Downgraded with a note in
  `eslint.config.mjs` rather than silenced per call site.
- **Multi-turn retrieval uses the question verbatim.** A follow-up like "what about the second
  one?" retrieves on those words alone; query rewriting against history is not implemented.

---

## Future improvements

- S3-compatible object storage backend (the storage interface exists; only the local driver is implemented)
- Reranking model in the retrieval pipeline (the pipeline has the stage; it is currently a no-op pass-through)
- Multi-user project collaboration (schema is single-owner today)
