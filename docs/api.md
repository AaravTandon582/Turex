# API

Base path `/api/v1`. JSON in, JSON out, except file upload (multipart) and download (PDF).

An interactive reference is generated from the code at `/docs` outside production. This page
covers the conventions and the reasoning that OpenAPI cannot express.

---

## Conventions

### Errors

Every failure has one shape:

```json
{ "error": { "code": "not_found", "message": "We couldn't find that paper." } }
```

`code` is stable and safe to branch on; `message` is written for a person and safe to display.
Validation failures add the offending fields:

```json
{
  "error": {
    "code": "validation_failed",
    "message": "Some of that information isn't valid.",
    "context": { "fields": [{ "field": "password", "message": "String should have at least 10 characters" }] }
  }
}
```

Internal diagnostics are never serialised into a response — not even in debug mode. See
[`architecture.md`](architecture.md) → Errors.

| Code | Status | Meaning |
|---|---|---|
| `validation_failed` | 422 | The request body or query is invalid |
| `unauthenticated` | 401 | No valid session |
| `invalid_credentials` | 401 | Sign-in failed |
| `not_found` | 404 | Missing — **or** owned by someone else |
| `conflict` | 409 | Already exists |
| `payload_too_large` | 413 | Upload exceeds the limit |
| `unsupported_media_type` | 415 | Not a file Atlas can read |
| `processing_failed` | 422 | The document could not be processed |
| `internal_error` | 500 | A bug; details are in the logs under the request id |

### Authentication

Session cookies, set by the auth endpoints. Browser clients send `credentials: "include"`; no
`Authorization` header is involved. Access tokens last 15 minutes, so a client should treat a
401 as "call `/auth/refresh` once and retry" rather than "sign the user out".

### Ownership

Everything is scoped to the signed-in user. A resource owned by another account returns **404,
never 403** — a 403 would confirm the identifier exists in someone else's library.

### Pagination

List endpoints take `limit` (1–100, default 24) and `offset`, and return:

```json
{ "items": [...], "total": 48, "limit": 24, "offset": 0 }
```

`total` is included so a client can render "1–24 of 48" without a second request.

### Request correlation

Every response carries `x-request-id`. Send your own to have it adopted. It appears on every
log line produced while handling the request, which is how a reported failure gets traced.

---

## Endpoints

### Auth

| Method | Path | Notes |
|---|---|---|
| `POST` | `/auth/register` | 201. Sets session cookies. |
| `POST` | `/auth/login` | Sets session cookies. |
| `POST` | `/auth/refresh` | Rotates the refresh token. Replay revokes the session. |
| `POST` | `/auth/logout` | 204. Effective immediately, not at token expiry. |
| `GET` | `/auth/me` | The signed-in user. |

### Papers

| Method | Path | Notes |
|---|---|---|
| `POST` | `/papers` | Multipart upload. **202** when queued, **200** when the file is already in the library. |
| `POST` | `/papers/from-reference` | Add by link, DOI, or arXiv id. Same 202/200 as upload. |
| `GET` | `/papers` | Filter, sort, paginate — see below. |
| `GET` | `/papers/stats` | Library counters in one query. |
| `GET` | `/papers/{id}` | Includes abstract, counts, and ingestion progress. |
| `PATCH` | `/papers/{id}` | Correct extracted metadata, or set reading status / favourite. |
| `POST` | `/papers/{id}/opened` | Records a read; promotes `unread` → `reading`. |
| `POST` | `/papers/{id}/reprocess` | 202. Re-runs ingestion, preserving user corrections. |
| `GET` | `/papers/{id}/sections` | The section outline. |
| `GET` | `/papers/{id}/equations` | Displayed equations found in the text. Heuristic; see below. |
| `GET` | `/papers/{id}/references` | The bibliography, split into entries. Heuristic. |
| `GET` | `/papers/{id}/file` | The original PDF, `inline`, `Cache-Control: private`. |
| `DELETE` | `/papers/{id}` | 204. Removes derived data and, if unreferenced, the stored file. |

**Query parameters on `GET /papers`:** `search`, `reading_status`, `status`, `collection_id`,
`tag`, `favorites_only`, `sort` (`recent` · `title` · `year` · `opened`), `limit`, `offset`.

`search` is substring matching over title, filename, abstract, and authors — for finding a
paper you know you have. Semantic search over the contents is a different endpoint,
`GET /assistant/search`.

**Equations and references are recognised, not marked up.** A PDF carries no structure for
either: an equation is a line that is mathematical rather than prosaic, and a bibliography is a
run of text where entries wrap unpredictably. Both endpoints are therefore approximate in a way
the rest of the API is not, and both say so in the interface rather than presenting a partial
list as complete. A reference carrying an arXiv id or a DOI can be added straight to the library
through `POST /papers/from-reference`.

**Adding by reference fetches a URL on the caller's behalf**, which is a server-side request
forgery risk. The fetcher resolves the hostname and refuses every non-public address, re-checks
on each redirect, caps the response while streaming, and permits only http and https. See
[`security.md`](security.md).

### Study

| Method | Path | Notes |
|---|---|---|
| `GET` | `/collections` | With paper counts. |
| `POST` | `/collections` | 201. Names are unique per user. |
| `DELETE` | `/collections/{id}` | 204. The papers inside are not deleted. |
| `PUT` | `/collections/{id}/papers/{paperId}` | 204. Idempotent. |
| `DELETE` | `/collections/{id}/papers/{paperId}` | 204. |

### Assistant

| Method | Path | Notes |
|---|---|---|
| `GET` | `/assistant/status` | Whether a model is configured, and the available modes. |
| `GET` | `/assistant/search` | Hybrid search over the library. `q`, `limit`, `paper_id`. |
| `GET` | `/assistant/conversations` | Most recently updated first. |
| `POST` | `/assistant/conversations` | 201. Optional `mode` and `paper_id`. |
| `GET` | `/assistant/conversations/{id}/messages` | The transcript, with citations. |
| `POST` | `/assistant/conversations/{id}/ask` | **Server-sent events.** See below. |
| `DELETE` | `/assistant/conversations/{id}` | 204. |

`ask` takes `{question, mode?, level?}` and responds with an SSE stream rather than JSON. It is
a POST, so a browser's `EventSource` cannot consume it — read `response.body` instead. Frames:

| Event | Payload |
|---|---|
| `sources` | The passages retrieved, numbered. Sent **before** any prose. |
| `text` | A fragment of the answer. |
| `done` | The turn finished; the message and its citations are persisted. |
| `error` | A message written for the reader. The turn is still saved. |

`mode` is one of `explain`, `research`, `critique`, `ideate`, `experiment`, `study`, `write`,
and becomes the conversation's default. `level` is `beginner`, `intermediate`, or `advanced`
and applies to that turn only.

### Annotations and citations

| Method | Path | Notes |
|---|---|---|
| `GET` | `/papers/{id}/annotations` | Highlights and margin notes. |
| `POST` | `/papers/{id}/annotations` | 201. Anchored by text offset, not by pixel position. |
| `PATCH` | `/annotations/{id}` | Change colour or note. |
| `DELETE` | `/annotations/{id}` | 204. |
| `GET` | `/papers/{id}/citations` | BibTeX, APA, and MLA, with `missing_fields` named. |

### Workspace

| Method | Path | Notes |
|---|---|---|
| `GET`, `POST` | `/projects` | 201 on create. |
| `GET`, `PATCH`, `DELETE` | `/projects/{id}` | Detail carries the counts its header shows. |
| `GET`, `PUT` | `/projects/{id}/papers` | `PUT` attaches; 204. |
| `DELETE` | `/projects/{id}/papers/{paperId}` | 204. |
| `GET`, `POST` | `/hypotheses` | Filter by `project_id`. |
| `GET`, `PATCH`, `DELETE` | `/hypotheses/{id}` | Detail includes its evidence. |
| `POST` | `/hypotheses/{id}/evidence` | Attach a passage as supporting or contradicting. |
| `DELETE` | `/evidence/{id}` | 204. |
| `GET`, `POST` | `/experiments` | |
| `GET`, `PATCH`, `DELETE` | `/experiments/{id}` | |
| `GET`, `POST` | `/notes` | Filter by `project_id`, `paper_id`, `search`. |
| `GET`, `PATCH`, `DELETE` | `/notes/{id}` | |
| `GET`, `POST` | `/projects/{id}/tasks` | |
| `PATCH`, `DELETE` | `/tasks/{id}` | |

### Discovery

| Method | Path | Notes |
|---|---|---|
| `GET` | `/recommendations` | Each result carries the paper it was derived from. |
| `GET` | `/graph` | Papers, shared concepts, projects, and questions, with their edges. |

### Study

| Method | Path | Notes |
|---|---|---|
| `POST` | `/papers/{id}/flashcards` | 201. Generates up to `count` (max 20) cards. |
| `GET` | `/flashcards` | `paper_id`, `due_only`, `limit`. Most overdue first. |
| `POST` | `/flashcards/{id}/reviews` | `{rating}` — `forgot`, `hard`, `good`, or `easy`. |
| `DELETE` | `/flashcards/{id}` | 204. |
| `POST` | `/papers/{id}/quizzes` | 201. Generates up to `count` (max 10) multiple-choice questions. |
| `POST` | `/papers/{id}/short-answers` | 201. Recall questions, returned as a quiz. Never scored — see below. |
| `GET` | `/papers/{id}/prerequisites` | What the paper assumes a reader already knows. Generated per request. |
| `GET` | `/quizzes` | Most recent first. |
| `GET` | `/quizzes/{id}` | |
| `POST` | `/quizzes/{id}/submission` | `{answers: {questionId: optionIndex}}`. Scored server-side. |
| `DELETE` | `/quizzes/{id}` | 204. |
| `GET` | `/study/progress` | Counts per paper and across the library. |

**Short answers are deliberately not scored.** Comparing free text to a model answer by string
matching marks a correct answer wrong for choosing different words, so `correct_index` is null
on those questions and the quiz reports zero scored rather than claiming a score nobody graded.
What the learner wrote and what the paper says are both returned after submission, side by side.

**Prerequisites are generated on request rather than stored.** They are read once, while
deciding whether to attempt a paper, and a stale copy would be worse than regenerating. Each
entry carries the passage where the assumption shows, so it can be checked like everything else.

**A quiz does not send its answer key until it has been submitted.** Before submission a
question carries only `id`, `position`, `prompt`, and `options`. Afterwards the same question
also carries `correct_index`, `explanation`, `selected_index`, and the source passage.

Generation returns **503 `not_configured`** when no model provider is set up, and **422** when
nothing the model produced could be tied to a passage of the paper.

### Health

`GET /health` does no I/O and reports that the process is up. `GET /ready` checks the database
and reports `ready` or `degraded`.

---

## Uploading a paper

Ingestion is asynchronous, so upload is a two-step interaction.

```
POST /papers                      → 202, status "pending"
GET  /papers/{id}   (or the list) → watch `ingestion.progress` climb
                                  → status "ready", or "failed" with a reason
```

Both the detail endpoint and each item in the list carry an `ingestion` object while a paper is
being read:

```json
{
  "stage": "building_chunks",
  "label": "Preparing passages",
  "progress": 70,
  "attempts": 1,
  "error_message": null
}
```

`label` is written for display, so a client renders "Preparing passages" rather than mapping
stage names itself. Progress is carried on list items specifically so a library of forty papers
costs one request to render, not forty.

Poll while any paper is `pending` or `processing`, and stop when none are.

**Uploads are validated by content, not by the declared type or the file extension** — both are
attacker-controlled. A file that does not begin with `%PDF-` is rejected with 415 whatever it
claims to be.

**A failed paper explains itself.** `failure_reason` is written for the user ("Atlas couldn't
find any text in that PDF. Scanned documents need OCR first."), and documents that would fail
identically on a retry are not retried.
