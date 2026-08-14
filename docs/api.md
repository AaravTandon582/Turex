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
| `GET` | `/papers` | Filter, sort, paginate — see below. |
| `GET` | `/papers/stats` | Library counters in one query. |
| `GET` | `/papers/{id}` | Includes abstract, counts, and ingestion progress. |
| `PATCH` | `/papers/{id}` | Correct extracted metadata, or set reading status / favourite. |
| `POST` | `/papers/{id}/opened` | Records a read; promotes `unread` → `reading`. |
| `POST` | `/papers/{id}/reprocess` | 202. Re-runs ingestion, preserving user corrections. |
| `GET` | `/papers/{id}/sections` | The section outline. |
| `GET` | `/papers/{id}/file` | The original PDF, `inline`, `Cache-Control: private`. |
| `DELETE` | `/papers/{id}` | 204. Removes derived data and, if unreferenced, the stored file. |

**Query parameters on `GET /papers`:** `search`, `reading_status`, `status`, `collection_id`,
`tag`, `favorites_only`, `sort` (`recent` · `title` · `year` · `opened`), `limit`, `offset`.

`search` is substring matching over title, filename, abstract, and authors — for finding a
paper you know you have. Semantic search over contents is a separate feature arriving with
Milestone 3.

### Collections

| Method | Path | Notes |
|---|---|---|
| `GET` | `/collections` | With paper counts. |
| `POST` | `/collections` | 201. Names are unique per user. |
| `DELETE` | `/collections/{id}` | 204. The papers inside are not deleted. |
| `PUT` | `/collections/{id}/papers/{paperId}` | 204. Idempotent. |
| `DELETE` | `/collections/{id}/papers/{paperId}` | 204. |

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
