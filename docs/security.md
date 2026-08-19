# Security

What Atlas defends against, how, and what it does not defend against.

---

## The threat that was real

Before rate limiting existed, thirty wrong-password attempts against a real account took **two
seconds** and none were refused — roughly nine hundred guesses a minute. Against a ten-character
minimum that is not immediately fatal, but it is the difference between a password being a
secret and being a speed bump.

After: eight attempts per account per fifteen minutes. The same attack now gets 8 guesses
instead of 13,500 in the same period.

```
before:  401 401 401 401 401 401 … 401   (30 of 30 answered)
after:   401 401 401 401 401 401 401 401 429 429 429 …
```

---

## Rate limits

| Scope | Limit | Keyed on | Why |
|---|---|---|---|
| Login | 8 per 15 min | account | Stops guessing one password from many addresses |
| Login | 30 per 15 min | address | Stops one host spraying attempts across many accounts |
| Registration | 5 per hour | address | Stops bulk account creation |
| Refresh | 120 per 15 min | address | Generous — several tabs refresh legitimately |
| Model calls | 40 per hour | user | Cost control as much as security |
| Uploads | 60 per hour | user | Ingestion is the heaviest work per request |
| Search | 300 per hour | user | Cheap, but the debounced UI fires often |

Login is limited **twice**, because either limit alone is bypassable — per-account defeats IP
rotation, per-address defeats account spraying. Both are checked *before* the password is
verified, so a rejected attempt costs no argon2 hashing; otherwise the limiter itself would be
a way to burn CPU on purpose.

A correct password clears the account's counter, so someone who mistypes four times and then
succeeds is not left throttled.

Refusals answer **429** with a `Retry-After` header and a message that says how long to wait.

**Account enumeration through timing** is handled: a login for an address that does not exist
still verifies the supplied password against a dummy hash, so the miss path costs the same
argon2 work as the hit path.

### What the implementation does and does not do

A sliding window, not fixed buckets — a fixed window lets an attacker spend the full allowance
at the end of one window and again at the start of the next, which is double the intended rate
at exactly the wrong moment.

**It is per-process.** Four workers enforce roughly four times the configured limit, and a
restart clears every counter. That is acceptable for a single-process deployment and is not
acceptable at scale, which is why `RateLimiter` is an interface with the in-memory class behind
it — a shared backend is a second implementation, not a rewrite.

The key map is swept of inactive entries every thousand requests. Without that it grows once
per distinct client address and never shrinks, which is a slow leak that only appears in
production.

---

## Client addresses behind a proxy

`X-Forwarded-For` is read **only** when `TRUST_PROXY_HEADERS` is set, and it is off by default.
A client can send that header itself, so trusting it on a directly-exposed deployment hands an
attacker a fresh identity on every request and defeats rate limiting completely. Turn it on
only when a proxy you control sets the header.

---

## Response headers

Every response carries:

| Header | Value |
|---|---|
| `X-Content-Type-Options` | `nosniff` |
| `X-Frame-Options` | `DENY` |
| `Referrer-Policy` | `strict-origin-when-cross-origin` |
| `Content-Security-Policy` | `default-src 'none'; frame-ancestors 'none'` |
| `Cache-Control` | `no-store` |

`Strict-Transport-Security` is added **only** when `COOKIE_SECURE` is on. Sending it from a
development server would pin the whole of localhost to HTTPS in the developer's browser, which
is unpleasant to undo, and browsers ignore it over plain HTTP anyway.

---

## Sessions

- Short-lived signed access token (15 minutes) in an httpOnly cookie
- Opaque refresh token (30 days), stored only as a SHA-256 hash
- Rotation on every refresh, with **replay detection**: presenting an already-used refresh
  token revokes the whole session
- A **10-second grace window** on that detection, because two browser tabs refreshing at the
  same moment both present the token that was just rotated away — indistinguishable from a
  replay by the token alone. They are told apart by *when*: inside the window it is a
  concurrent client and a fresh token is issued; outside it, the session is revoked. Without
  this, five concurrent refreshes left the session dead and the user logged out for having
  tabs open, which is the failure that makes teams disable rotation altogether
- `SameSite=Lax`, so a cross-site form post cannot ride the session
- The session row is checked on every request, so signing out takes effect immediately rather
  than when the access token happens to expire

---

## Data isolation

Every query is owner-scoped in SQL, not filtered after the fact. A resource belonging to
another account is **404, not 403** — a 403 confirms the id exists, which is itself a
disclosure.

This is enforced by enumeration rather than by example: a test reads the application's own
OpenAPI schema and requires every route to answer 401 without a session unless it is named in
`PUBLIC_ROUTES` with a reason. Six routes are public: register, login, refresh, logout, health,
ready. A new endpoint is covered the moment it is registered.

---

## Prompt injection through uploaded documents

Anyone can upload a PDF, and a PDF can contain text shaped like a command — *"ignore previous
instructions"*, *"system override"*, *"reveal your prompt"*. Retrieval puts that text in front
of the model, which makes every uploaded document an untrusted input to the assistant.

Two defences, and the order matters.

**Structural, and model-independent.** Citations are written from the passages the server
retrieved, never parsed from the model's prose. A model that has been completely taken over
still cannot make Atlas store a citation to a passage that was never retrieved — a marker it
invents is discarded. This holds whatever model is configured and however badly it behaves,
and it is tested with a scripted model that *does* obey the injected instruction.

**Instructional, as depth.** The grounding rules state plainly that sources are documents,
that a document cannot issue instructions, and that text attempting it is content to be
reported rather than acted on.

Verified live against Claude Opus 5 with a deliberately hostile paper: the assistant refused
both injected instructions, reported them to the user unprompted, answered the real question,
and separated its own general knowledge from anything found in the library.

The instructional half is defence in depth, not the guarantee. The guarantee is the structural
half, because it does not depend on the model choosing to cooperate.

---

## Text arriving from a client

Every request and response schema inherits a base that strips characters which cannot be stored
or displayed safely — null, which PostgreSQL rejects outright, and the C0 control characters,
which make logs and terminals behave strangely. Tab, newline, and carriage return survive,
because notes are Markdown and legitimately contain them.

This lives on the base model rather than on individual fields on purpose. A per-field validator
has to be remembered on every new field, and the one that gets forgotten is the one that breaks.

Before it existed, a null byte in any text field raised `CharacterNotInRepertoireError` inside
asyncpg and surfaced as **HTTP 500** — an unhandled server error from ordinary user input, on
every text field in the API at once.

---

## Uploads

- Validated by **magic bytes**, not by the declared content type or the file extension — both
  are attacker-controlled
- Size-capped before anything is read into memory
- Stored under a content-addressed key, so the uploaded filename never reaches the filesystem
- Written to a uniquely-named temporary and renamed into place, so a crash cannot leave a
  truncated file that later reads treat as a valid document — and two people uploading the
  same paper at once cannot collide on one temporary path
- The filename is reduced to a bare basename before storage, and stripped again in the
  `Content-Disposition` header
- Nothing in a PDF is executed. Text is extracted; document actions and embedded JavaScript are
  never evaluated. There is a test that ingests a PDF carrying an `/OpenAction … /JavaScript`
  payload and asserts it is treated as characters

---

## Secrets

- No credential-shaped literals in backend or frontend source, checked by a test that sweeps
  every file on every run
- No vendor API key format anywhere in source, same sweep
- `.env` is gitignored; `.env.example` carries empty values
- The log redactor fingerprints secrets rather than printing them — enough to correlate two log
  lines, never enough to replay
- Production configuration refuses to start quietly with the development secret key, insecure
  cookies, debug mode, or rate limiting disabled

---

## What Atlas does not defend against

Stated plainly, because a security section that claims everything is one that measured nothing.

- **Multi-process rate limiting.** See above. One process enforces the documented limits; four
  processes enforce roughly four times them.
- **Distributed brute force.** Per-account limits hold regardless of source, but a large botnet
  spreading attempts across many accounts stays under the per-address limit on each host.
- **CSRF beyond `SameSite=Lax`.** Lax covers the realistic cases for a JSON API that never
  accepts form posts. A token would be needed if that changed.
- **Denial of service.** Rate limits bound a single client. They are not a substitute for
  infrastructure that absorbs volume.
- **A malicious PDF exploiting the parser itself.** `pypdf` is pure Python and is not evaluating
  document logic, which removes the usual class of PDF exploits, but a parser bug is still a
  parser bug.
