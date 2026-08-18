"""Build the demo account: a curated library, a real research question, and the work under it.

Run against a running API:

    python scripts/seed_demo.py                 # create or top up the demo account
    python scripts/seed_demo.py --reset         # delete it first and rebuild from nothing
    python scripts/seed_demo.py --with-study    # also generate flashcards (needs a model key)

Two decisions worth stating.

**It goes through the HTTP API, not the database.** Seeding by direct insert would be faster
and would prove nothing — the demo would exist in a state no real user could reach. Every
paper here was uploaded, parsed, chunked, and embedded by the same code path a visitor uses.

**The papers are downloaded, not committed.** They are arXiv preprints, freely available, and
a repository is the wrong place for thirty megabytes of PDF. They are cached under `var/` after
the first run, so seeding works offline afterwards.
"""

from __future__ import annotations

import argparse
import asyncio
import pathlib
import sys
from dataclasses import dataclass, field

import httpx

API = "http://localhost:8000/api/v1"
CACHE = pathlib.Path(__file__).resolve().parent.parent / "var" / "demo-papers"

DEMO_EMAIL = "demo@atlas.dev"
DEMO_PASSWORD = "atlas-demo-account-2026"
DEMO_NAME = "Demo Researcher"


@dataclass(frozen=True, slots=True)
class Source:
    arxiv_id: str
    filename: str
    short: str
    """How this paper is referred to below, so the script reads like the story it tells."""


# Chosen to make one argument, not to show off breadth. Four papers that genuinely bear on the
# question the demo project asks, and one — ResNet, from computer vision — so the library has a
# genuine outsider in it. The graph connects it through the general deep-learning vocabulary it
# really does share and through none of the language-specific terms, which is a better
# demonstration than an isolated node would have been.
SOURCES: list[Source] = [
    Source("1706.03762", "attention.pdf", "attention"),
    Source("1810.04805", "bert.pdf", "bert"),
    Source("2005.11401", "rag.pdf", "rag"),
    Source("2203.02155", "instructgpt.pdf", "instructgpt"),
    Source("1512.03385", "resnet.pdf", "resnet"),
]

RESEARCH_QUESTION = (
    "Is retrieving knowledge at inference time a better way to make a language model "
    "factual than storing that knowledge in its parameters?"
)


@dataclass
class Seeded:
    """What the run produced, so the summary reports facts rather than intentions."""

    papers: dict[str, str] = field(default_factory=dict)
    project_id: str = ""
    hypotheses: int = 0
    evidence: int = 0
    notes: int = 0
    annotations: int = 0
    cards: int = 0


async def fetch_pdf(client: httpx.AsyncClient, source: Source) -> bytes:
    """Return the paper's bytes, downloading it only if it is not already cached."""
    CACHE.mkdir(parents=True, exist_ok=True)
    cached = CACHE / source.filename
    if cached.exists():
        return cached.read_bytes()

    print(f"  downloading {source.arxiv_id} …", flush=True)
    response = await client.get(
        f"https://arxiv.org/pdf/{source.arxiv_id}",
        follow_redirects=True,
        timeout=120.0,
        headers={"User-Agent": "atlas-demo-seed/1.0 (research workspace; contact via repo)"},
    )
    response.raise_for_status()
    if not response.content.startswith(b"%PDF-"):
        raise RuntimeError(f"{source.arxiv_id} did not return a PDF")

    cached.write_bytes(response.content)
    return response.content


async def wait_for_ingestion(api: httpx.AsyncClient, expected: int, timeout: float = 300.0) -> None:
    """Poll until every paper is out of the queue, or say plainly that it did not finish."""
    waited = 0.0
    while waited < timeout:
        stats = (await api.get("/papers/stats")).json()
        if stats["processing"] == 0 and stats["total"] >= expected:
            if stats["failed"]:
                print(f"  WARNING: {stats['failed']} paper(s) failed to process")
            return
        print(f"  processing… {stats['total'] - stats['processing']}/{expected} ready", flush=True)
        await asyncio.sleep(5)
        waited += 5
    raise RuntimeError(f"ingestion did not finish within {timeout:.0f}s")


async def sign_in(api: httpx.AsyncClient, *, reset: bool) -> None:
    """Create the demo account, or sign in to the existing one."""
    if reset:
        login = await api.post("/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD})
        if login.status_code == 200:
            print("  removing the previous demo library")
            for paper in (await api.get("/papers?limit=100")).json()["items"]:
                await api.delete(f"/papers/{paper['id']}")
            for project in (await api.get("/projects")).json():
                await api.delete(f"/projects/{project['id']}")
            return

    registered = await api.post(
        "/auth/register",
        json={"email": DEMO_EMAIL, "full_name": DEMO_NAME, "password": DEMO_PASSWORD},
    )
    if registered.status_code == 201:
        print(f"  created {DEMO_EMAIL}")
        return

    login = await api.post("/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD})
    if login.status_code != 200:
        # The account exists but this password does not open it — almost always a leftover
        # from an earlier run with different credentials. Say so, rather than failing with a
        # bare 401 that reads like the API is broken.
        raise SystemExit(
            f"{DEMO_EMAIL} already exists but the demo password does not work.\n"
            f"An older account is probably in the way. Remove it and run this again:\n"
            f"  psql -d atlas -c \"delete from users where email='{DEMO_EMAIL}'\""
        )
    print(f"  signed in as {DEMO_EMAIL}")


async def upload_library(api: httpx.AsyncClient, downloader: httpx.AsyncClient) -> dict[str, str]:
    """Upload every source paper, returning short name to paper id."""
    existing = {
        paper["display_title"]: paper["id"]
        for paper in (await api.get("/papers?limit=100")).json()["items"]
    }
    if existing:
        print(f"  {len(existing)} paper(s) already present")

    ids: dict[str, str] = {}
    for source in SOURCES:
        data = await fetch_pdf(downloader, source)
        response = await api.post(
            "/papers",
            files={"file": (source.filename, data, "application/pdf")},
            timeout=120.0,
        )
        response.raise_for_status()
        ids[source.short] = response.json()["id"]

    await wait_for_ingestion(api, expected=len(SOURCES))
    return ids


async def find_passage(api: httpx.AsyncClient, query: str, paper_id: str | None = None) -> dict:
    """Search the library for a passage, so evidence is attached to text that really exists.

    The demo must not contain a single hand-written quotation. Every piece of evidence below is
    whatever retrieval actually returns for its query — which also means running the seed is a
    small end-to-end test of retrieval.
    """
    url = f"/assistant/search?q={httpx.QueryParams({'q': query})['q']}&limit=3"
    if paper_id:
        url += f"&paper_id={paper_id}"
    results = (await api.get(url)).json()["results"]
    if not results:
        raise RuntimeError(f"no passage found for {query!r} — has the library been indexed?")
    return results[0]


def _expect(response: httpx.Response, action: str) -> dict:
    """Return the JSON body, or fail with the API's own message rather than a KeyError.

    Seeding drives a dozen endpoints in sequence, and a schema mismatch three calls in used to
    surface as `KeyError: 'id'` — which says nothing about what went wrong or where.
    """
    if response.status_code not in {200, 201}:
        body = response.json()
        detail = body.get("error", {}).get("message", response.text[:200])
        raise SystemExit(f"could not {action}: HTTP {response.status_code} — {detail}")
    return response.json()


async def build_project(api: httpx.AsyncClient, papers: dict[str, str], seeded: Seeded) -> None:
    """Create the project, its hypotheses, and evidence drawn from real passages."""
    project = _expect(
        await api.post(
            "/projects",
            json={
                "name": "Parametric vs retrieved knowledge",
                "research_question": RESEARCH_QUESTION,
                "description": (
                    "Comparing two ways of giving a language model facts: training them into "
                    "its weights, or fetching them when the question is asked. The second is "
                    "checkable, which is the property this project cares about."
                ),
            },
        ),
        "create the project",
    )
    seeded.project_id = project["id"]

    # The paper id goes in the body, not the path — the path form silently did nothing and
    # produced a project showing "0 papers", which is why the response is checked now.
    for short, why in (
        ("rag", "The paper the question is really about"),
        ("bert", "The parametric-knowledge baseline being argued against"),
        ("attention", "The architecture both approaches are built on"),
        ("instructgpt", "Evidence that scale alone does not produce truthfulness"),
    ):
        attached = await api.put(
            f"/projects/{project['id']}/papers",
            json={"paper_id": papers[short], "relevance_note": why},
        )
        if attached.status_code != 204:
            raise SystemExit(f"could not attach {short}: HTTP {attached.status_code}")

    hypotheses = [
        {
            "statement": (
                "A model that retrieves passages at inference time produces more specific and "
                "more checkable claims than one relying only on its parameters."
            ),
            "status": "supported",
            "assumptions": (
                "Assumes the retrieval corpus contains the answer, and that specificity is a "
                "reasonable proxy for checkability."
            ),
            "evidence": [("rag", "retrieval augmented generation factual specificity", "supports")],
        },
        {
            "statement": (
                "Knowledge stored in parameters cannot be inspected or updated without "
                "retraining the model."
            ),
            "status": "supported",
            "assumptions": "Assumes no post-hoc editing method is applied.",
            "evidence": [("rag", "parametric knowledge cannot be expanded or revised", "supports")],
        },
        {
            "statement": (
                "Making a language model larger is sufficient on its own to make it truthful."
            ),
            "status": "contradicted",
            "assumptions": (
                "Stated deliberately as something the library argues against — a project should "
                "record what was ruled out, not only what survived."
            ),
            # Phrased close to the paper's own opening sentence on purpose. A looser query
            # returned a passage about RLHF that was real, from the right paper, and did not
            # actually contradict the claim — which in a demo about checkable citations is
            # worse than no citation, because anyone who reads it will notice.
            "evidence": [
                (
                    "instructgpt",
                    "making language models bigger does not make them better at following intent",
                    "contradicts",
                )
            ],
        },
    ]

    for entry in hypotheses:
        response = await api.post(
            "/hypotheses",
            json={
                "project_id": project["id"],
                "statement": entry["statement"],
                "status": entry["status"],
                "assumptions": entry["assumptions"],
            },
        )
        created = _expect(response, "create a hypothesis")
        seeded.hypotheses += 1

        for short, query, stance in entry["evidence"]:  # type: ignore[misc]
            passage = await find_passage(api, query, papers[short])
            attached = await api.post(
                f"/hypotheses/{created['id']}/evidence",
                json={"chunk_id": passage["chunk_id"], "stance": stance, "note": query},
            )
            if attached.status_code in {200, 201}:
                seeded.evidence += 1

    await api.post(
        "/experiments",
        json={
            "project_id": project["id"],
            "title": "Compare answer specificity with and without retrieval",
            "hypothesis": (
                "Answers built from retrieved passages will name more concrete entities and "
                "numbers than answers written from parameters alone."
            ),
            "method": (
                "Ask the same twenty questions in both modes. Count claims that carry a "
                "specific figure, name, or date, and check each against the cited passage."
            ),
            "variables": "Retrieval on or off",
            "controls": "Same questions, same model, same decoding settings",
            "confounders": "Question difficulty; whether the corpus contains the answer at all",
            "metrics": "Specific-claim count; proportion of claims that check out",
            "status": "planned",
        },
    )


async def add_notes_and_highlights(
    api: httpx.AsyncClient, papers: dict[str, str], seeded: Seeded
) -> None:
    """A notebook entry and a highlight, both anchored to text that exists."""
    notes = [
        {
            "title": "Why this question is worth asking",
            "content": (
                "Both approaches produce fluent text. Only one of them can be checked.\n\n"
                "If a model states a figure from its parameters, there is no way to ask where "
                "it came from — the weights do not remember. If it states a figure from a "
                "retrieved passage, the passage is right there, and a wrong answer becomes a "
                "*findable* wrong answer rather than a convincing one.\n\n"
                "That is the whole reason Atlas stores the passage behind every citation."
            ),
            "project_id": seeded.project_id,
        },
        {
            "title": "Open thread — what retrieval does not fix",
            "content": (
                "Retrieval moves the failure rather than removing it. If the corpus is wrong, "
                "the answer is wrong and now carries a citation, which makes it *more* "
                "persuasive, not less.\n\n"
                "Worth testing: how often does a confidently cited claim rest on a passage "
                "that does not actually say it?"
            ),
            "project_id": seeded.project_id,
        },
    ]
    for note in notes:
        if (await api.post("/notes", json=note)).status_code == 201:
            seeded.notes += 1

    # Anchored by searching for the text, so the highlight lands on a real offset rather than
    # a guessed one.
    passage = await find_passage(api, "scaled dot-product attention softmax", papers["attention"])
    excerpt = passage["content"][:180].strip()
    created = await api.post(
        f"/papers/{papers['attention']}/annotations",
        json={
            "page_number": passage.get("page_start") or 1,
            "text_offset": 0,
            "selected_text": excerpt,
            "colour": "important",
            "note": "The scaling term is the whole trick — without it the softmax saturates.",
        },
    )
    if created.status_code == 201:
        seeded.annotations += 1


async def generate_study_material(
    api: httpx.AsyncClient, papers: dict[str, str], seeded: Seeded
) -> None:
    """Optional: needs a configured model provider, and costs real requests."""
    status = (await api.get("/assistant/status")).json()
    if not status["chat_available"]:
        print("  skipping study material — no model provider configured")
        return

    response = await api.post(
        f"/papers/{papers['rag']}/flashcards", json={"count": 6}, timeout=300.0
    )
    if response.status_code == 201:
        seeded.cards = len(response.json())
    else:
        print(f"  flashcards failed: {response.json().get('error', {}).get('message')}")


async def main() -> int:
    parser = argparse.ArgumentParser(description="Seed the Atlas demo account.")
    parser.add_argument("--reset", action="store_true", help="clear the demo library first")
    parser.add_argument(
        "--with-study", action="store_true", help="also generate flashcards (uses the model API)"
    )
    args = parser.parse_args()

    seeded = Seeded()

    async with (
        httpx.AsyncClient() as downloader,
        httpx.AsyncClient(base_url=API, timeout=60.0) as api,
    ):
        try:
            await api.get("/health")
        except httpx.ConnectError:
            print("Atlas is not running. Start it first:")
            print("  uvicorn atlas.main:create_app --factory")
            return 1

        print("account")
        await sign_in(api, reset=args.reset)

        print("library")
        seeded.papers = await upload_library(api, downloader)

        print("project")
        await build_project(api, seeded.papers, seeded)

        print("notebook and highlights")
        await add_notes_and_highlights(api, seeded.papers, seeded)

        if args.with_study:
            print("study material")
            await generate_study_material(api, seeded.papers, seeded)

        graph = (await api.get("/graph")).json()

    print(
        f"""
demo account ready

  sign in     {DEMO_EMAIL} / {DEMO_PASSWORD}
  papers      {len(seeded.papers)}
  project     1, with {seeded.hypotheses} hypotheses and {seeded.evidence} pieces of evidence
  notebook    {seeded.notes} notes, {seeded.annotations} highlight
  graph       {len(graph["nodes"])} nodes, {len(graph["edges"])} connections
  flashcards  {seeded.cards or "none — pass --with-study"}

walkthrough: docs/demo.md"""
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
