# Turex

**Research, connected.** An intelligent workspace for reading scientific literature,
connecting what you learn, and turning it into questions you can actually test.

Turex is built around the loop researchers actually work in:

> **Read → Understand → Connect → Question → Hypothesise → Test → Learn**

It is not a chat wrapper. The assistant reasons over *your* library, every claim resolves to a
real passage in a real document, and Turex says so when it does not know.

---

## Status

Under active development. See [`PROGRESS.md`](PROGRESS.md) for the milestone roadmap and what
is built today.

| Area | State |
|------|-------|
| Application shell, navigation, theming | ✅ Working |
| Authentication and sessions | ✅ Working |
| Paper ingestion and library | ✅ Working |
| Hybrid retrieval and the research assistant | ✅ Working |
| PDF reader, highlights, citation export | ✅ Working |
| Projects, hypotheses, experiments, notes | ✅ Working |
| Recommendations and the knowledge graph | ✅ Working |
| Flashcards, quizzes, spaced repetition | ✅ Working |
| Polish: accessibility, responsiveness, error states | ✅ Working |
| Evaluation: retrieval benchmark, security suite | ✅ Working |
| Demo account and walkthrough | ✅ Working |

Everything answering a model needs `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` set; without one,
those endpoints say so rather than failing obscurely, and the rest of Turex keeps working.
Nothing is mocked to look complete when it is not.

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
and their trade-offs are recorded in [`docs/decisions.md`](docs/decisions.md); what is actually
measured, and what is not, is in [`docs/evaluation.md`](docs/evaluation.md); the defences and
their limits are in [`docs/security.md`](docs/security.md).

---

## Running Turex locally

The quickest way is `docker compose up --build`, which brings up the database, runs the
migrations, and serves both halves. Full setup, including running it without containers and
troubleshooting, is in [`docs/development.md`](docs/development.md).
To see Turex with a library already in it, run `python scripts/seed_demo.py` and follow
[`docs/demo.md`](docs/demo.md).
The short version:

### Prerequisites

- Python 3.11+
- Node.js 20+
- PostgreSQL 16+ with the `pgvector` extension available

```bash
# macOS
brew install postgresql@17 pgvector && brew services start postgresql@17
createdb turex && createdb turex_test
```

### Backend

```bash
cd backend
python3 -m venv .venv && ./.venv/bin/pip install -e ".[dev]"
cp .env.example .env          # then set SECRET_KEY
./.venv/bin/alembic upgrade head
./.venv/bin/uvicorn turex.main:create_app --factory --reload
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
cd backend && ./.venv/bin/pytest        # requires the turex_test database
cd frontend && npm run build            # type-checks as part of the build
```

---

## Configuration

Every setting is an environment variable; nothing reads credentials from source. See
`backend/.env.example` and `frontend/.env.example` for the full list.

Turex runs without any AI provider keys — features that need a model report themselves as
unavailable rather than failing at the point of use.

---

## Repository layout

```
backend/
  turex/
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
