# Atlas

**Research, connected.** An intelligent workspace for reading scientific literature,
connecting what you learn, and turning it into questions you can actually test.

Atlas is built around the loop researchers actually work in:

> **Read → Understand → Connect → Question → Hypothesise → Test → Learn**

It is not a chat wrapper. The assistant reasons over *your* library, every claim resolves to a
real passage in a real document, and Atlas says so when it does not know.

---

## Status

Under active development. See [`PROGRESS.md`](PROGRESS.md) for the milestone roadmap and what
is built today.

| Area | State |
|------|-------|
| Application shell, navigation, theming | ✅ Working |
| Authentication and sessions | ✅ Working |
| Paper ingestion and library | 🔜 Milestone 2 |
| Retrieval and research assistant | 🔜 Milestone 3 |

Screens for unbuilt milestones exist in the navigation and say plainly that they are not
finished. Nothing in Atlas is mocked to look complete when it is not.

---

## Stack

| Layer | Choice | Why |
|-------|--------|-----|
| Frontend | Next.js (App Router), React, TypeScript, Tailwind CSS | Server components for static surfaces, a small client bundle for interaction |
| Backend | Python, FastAPI, SQLAlchemy 2 (async) | Async throughout, since most request time is spent waiting on the database or a model provider |
| Database | PostgreSQL + `pgvector` | Relational data and embeddings in one transactional store |
| Migrations | Alembic | |
| AI | Provider abstraction over Anthropic / OpenAI | No feature is coupled to a single vendor |

Architectural reasoning lives in [`docs/architecture.md`](docs/architecture.md); the decisions
and their trade-offs are recorded in [`docs/decisions.md`](docs/decisions.md).

---

## Running Atlas locally

Full setup, including troubleshooting, is in [`docs/development.md`](docs/development.md).
The short version:

### Prerequisites

- Python 3.11+
- Node.js 20+
- PostgreSQL 16+ with the `pgvector` extension available

```bash
# macOS
brew install postgresql@17 pgvector && brew services start postgresql@17
createdb atlas && createdb atlas_test
```

### Backend

```bash
cd backend
python3 -m venv .venv && ./.venv/bin/pip install -e ".[dev]"
cp .env.example .env          # then set SECRET_KEY
./.venv/bin/alembic upgrade head
./.venv/bin/uvicorn atlas.main:create_app --factory --reload
```

The API runs on <http://localhost:8000>, with interactive docs at `/docs` outside production.

### Frontend

```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev
```

The app runs on <http://localhost:3000>.

### Tests

```bash
cd backend && ./.venv/bin/pytest        # requires the atlas_test database
cd frontend && npm run build            # type-checks as part of the build
```

---

## Configuration

Every setting is an environment variable; nothing reads credentials from source. See
`backend/.env.example` and `frontend/.env.example` for the full list.

Atlas runs without any AI provider keys — features that need a model report themselves as
unavailable rather than failing at the point of use.

---

## Repository layout

```
backend/
  atlas/
    api/          HTTP layer: routing, dependencies, cookies, error translation
    core/         Config, logging, errors, security primitives
    db/           Engine, session lifecycle, model conventions
    models/       SQLAlchemy models
    schemas/      Pydantic request and response models
    services/     Business logic — the layer that owns the rules
  alembic/        Migrations
  tests/
frontend/
  src/
    app/          Routes: (auth) sign-in, (app) authenticated shell, landing page
    components/   UI primitives, layout, theming
    lib/          API client, session helpers
docs/             Architecture, decisions, development guide
```
