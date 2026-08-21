# Demo

A five-minute walkthrough of Turex, and how to set it up.

The whole demo rests on one claim — **Turex does not make things up** — so the script below is
built to let someone test that claim rather than watch it be asserted. Two of the five steps
invite the audience to try to catch it lying.

---

## Setting it up

With PostgreSQL running and the API started:

```bash
cd backend
uvicorn turex.main:create_app --factory        # in one terminal
python scripts/seed_demo.py                    # in another
```

Then start the frontend with `npm run dev` and sign in as:

```
demo@turex.dev / turex-demo-account-2026
```

The seed downloads five arXiv papers on first run and caches them under `backend/var/`, so
later runs work offline. `--reset` clears the library and rebuilds it. `--with-study` also
generates flashcards, which needs a model provider configured and makes real API calls.

Seeding takes about two minutes, almost all of it ingestion.

**It goes through the HTTP API, not the database.** Every paper in the demo was uploaded,
parsed, chunked, and embedded by the same code a visitor's upload would hit. A demo seeded by
direct insert would sit in a state no real user could reach, and would prove nothing.

**Nothing in the demo is hand-written.** Every quotation attached to a hypothesis is whatever
retrieval actually returned for its query. That means running the seed is itself a small
end-to-end test — if retrieval breaks, seeding fails rather than quietly producing a demo full
of stale text.

---

## What is in the demo account

| | |
|---|---|
| Library | 5 papers — Attention, BERT, RAG, InstructGPT, ResNet |
| Project | *Parametric vs retrieved knowledge*, with 3 hypotheses and 3 pieces of evidence |
| Notebook | 2 notes |
| Reader | 1 highlight, on the scaled dot-product attention passage |
| Graph | ~36 nodes, ~89 connections |

The research question is:

> Is retrieving knowledge at inference time a better way to make a language model factual than
> storing that knowledge in its parameters?

Four of the five papers bear on it directly. ResNet is from computer vision and is there
deliberately — a library where every paper is about one topic is not a real library, and the
graph should have to cope with a genuine outsider.

---

## The five-minute script

### 1. The problem (30 seconds)

Open the **dashboard**. Five papers, one project, work in progress.

> "Reading research is not the hard part. Keeping track of what you have read, what it
> actually said, and which of your questions it answered — that is the hard part. Most AI
> tools will summarise a paper for you. The summary sounds right whether or not it is."

### 2. Ask a real question (90 seconds)

Go to **Assistant** and ask:

> How does multi-head attention work, and why use multiple heads instead of one?

Point at the **sources appearing before any text does**. That ordering is deliberate — the
audience sees what the answer is being built from before the answer exists.

When it finishes, click a citation. It jumps to the passage in the actual PDF.

> "Every bracketed number is a foreign key the server wrote, not something the model claimed.
> The model never gets to tell us where its answer came from — it can only point at passages
> we handed it."

### 3. Try to catch it lying (60 seconds) — **the important one**

Invite someone in the audience to ask about something that is not in the library. A good
prompt, if nobody volunteers:

> What did the 2024 Zhang et al. study find about CRISPR off-target effects in zebrafish?

It answers, in substance:

> Nothing in the provided sources addresses this. […] I have no way to check whether the study
> you are describing exists. I can only read what is above, and I won't guess at findings for a
> paper I haven't seen.

> "That is the whole product. Not that it is clever — that it knows the edge of what it knows,
> and stops there."

If someone asks how you know it is not just refusing everything, go back to step 2 and note it
answered that one in detail.

### 4. The research loop (90 seconds)

Open the **project**. Walk down it:

- the research question at the top
- three hypotheses, one of them marked **contradicted**
- open that one — the evidence against it is the opening line of the InstructGPT abstract:
  *"Making language models bigger does not inherently make them better at following a user's
  intent."*

> "This is the part I care about most. A tool that only collects support for what you already
> believe is a tool for being confidently wrong. Turex tracks what your library argues
> *against* too, and every piece of evidence is a passage you can go and read."

### 5. Connections and study (60 seconds)

Open the **graph**. Papers connect through terms they genuinely share — extracted by counting
what several papers use and most do not, never by asking a model to guess a topic.

Click **ResNet**, the computer-vision paper. It connects to the others through the vocabulary
they really do share — *training*, *neural*, *architecture*, *representations* — and through
none of the language-specific ones: not *transformer*, not *encoder*, not *question answering*.

> "Nobody told it that ResNet is a vision paper. It has never seen a topic label. It counted
> which words several papers use and most do not, and the shape of the field fell out of that."

Finish on **Study**: flashcards written from the papers' own passages, each showing the passage
behind the answer.

> "You can check every card against the paragraph it came from. If a card is wrong, you can
> see *why* it is wrong, which is the difference between a study tool and a rumour."

---

## Questions worth preparing for

**"How do you know it isn't making up the citations?"**
Show it. Click one — it lands on the passage. Then explain the mechanism: citations are written
from the passages that were retrieved and placed in the model's context, before the model
answers. Markers the model invents that do not match a retrieved passage are discarded rather
than stored. There is a test that scripts a model citing source `[99]` when five sources were
given, and asserts nothing is saved.

**"What happens if the model is down?"**
The library, the reader, search, notes, projects, and reviewing existing flashcards all keep
working — none of them call a model. The assistant says the provider is unavailable rather than
failing obscurely.

**"Is it just a wrapper around ChatGPT?"**
The model is one component and is replaceable — the provider sits behind an interface and can
point at Anthropic, OpenAI, or any OpenAI-compatible service by changing a setting. The parts
that make Turex useful — ingestion, hybrid search over your own library, the citation
mechanism, the project structure — are Turex's own and would still be there with a different
model behind them.

**"What is it worst at?"**
Answer honestly, and have specifics ready — see *Known limitations* below. An evaluation
section that admits nothing reads as one that measured nothing.

---

## Known limitations, stated plainly

- **Retrieval is only as good as the library.** If the answer is not in a paper you have added,
  Turex will tell you so — which is correct, and still not an answer.
- **Search quality depends on the embedding model.** With the offline embedder the benchmark
  scores recall@3 of 88% and MRR 0.646; one benchmark query fails outright because a
  bag-of-words embedder cannot match a paraphrase. See [`evaluation.md`](evaluation.md).
- **Retrieval moves a failure rather than removing it.** If a paper is wrong, Turex will cite it
  accurately — and a wrong claim carrying a citation is more persuasive, not less. This is
  written up as an open thread in the demo notebook, because it is a real limitation and not a
  bug to be fixed.
- **The reader has not been exercised in a browser by an automated test.** It is verified by
  type-checking and a clean build, which is not the same thing.

---

## If something goes wrong mid-demo

| Symptom | Cause | What to do |
|---|---|---|
| Assistant says it is not configured | no model key set | Show search and the project instead; both work without one |
| A paper sits at "processing" | the ingestion worker is not running | It runs inside the API process; restart the API |
| Seeding fails on the demo account | an older account with a different password | The script prints the exact command to remove it |
| Answers are slow | a large paper and a long question | Say so — sources appear first, so there is something to talk about while it writes |
