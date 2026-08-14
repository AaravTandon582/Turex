# AI architecture

How Atlas talks to models, and what it does to make an answer trustworthy.

The governing constraint: **a fabricated citation is worse than no answer.** A research tool
that occasionally invents a source will be trusted, checked, and found to be wrong — and
everything else it says becomes suspect. Most of the design below exists to make fabrication
structurally impossible rather than merely discouraged.

---

## Provider abstraction

Two interfaces in `atlas/ai/base.py`, deliberately separate:

| Interface | Implementations |
|---|---|
| `ChatProvider` | `AnthropicChatProvider` (default, `claude-opus-5`), `OpenAIChatProvider` |
| `EmbeddingProvider` | `OpenAIEmbeddingProvider` (default), `HashingEmbeddingProvider` (offline) |

They are separate because the vendor sets differ: Anthropic offers no embedding model, so a
single "AI provider" abstraction would need an exception on its first day.

Nothing above `atlas/ai/` imports a vendor SDK. Providers are selected once from configuration
by `ProviderRegistry`, and everything downstream depends only on the interfaces.

**Atlas runs with no keys at all.** `chat_available` and `embeddings_available` are reported by
`GET /assistant/status`, and the UI explains that the feature needs configuration rather than
presenting a chat box that fails on first use. Conversation history stays readable on an
instance with no key — the provider is resolved lazily, per turn, so only the endpoint that
needs a model is affected.

### The offline embedder

`HashingEmbeddingProvider` is the signed hashing trick: tokens hashed into buckets, weighted by
sublinear term frequency, L2-normalised. Real lexical signal, no learned semantics.

It exists so **retrieval is testable in CI**. With only a hosted embedding model, the retrieval
pipeline could be exercised only by hand against a live account, which in practice means it
never gets a regression test and ranking quietly degrades. It is not for production — it cannot
match paraphrase — and Atlas logs a warning if it is selected outside tests.

### Anthropic specifics

- Adaptive thinking (`thinking: {"type": "adaptive"}`); depth controlled per mode by
  `output_config.effort` rather than a token budget.
- `max_tokens` bounds thinking *and* answer together, so the budget is deliberately generous
  (8192) — a tight limit truncates the answer rather than the reasoning.
- The system prompt carries `cache_control`, and is byte-stable per mode, so every turn after
  the first in a conversation reads it from cache.
- Server-side fallbacks (`fallbacks: "default"`) are enabled. Safety classifiers occasionally
  decline benign security or life-sciences reading; the fallback re-runs the request on a
  suitable model in the same call rather than refusing a legitimate research question.
- `stop_reason` is checked before the answer is used. A refusal can arrive with no text at all,
  and reading content without checking would present an empty answer as a real one.

---

## Modes

Seven modes, each with its own system prompt, reasoning effort, and retrieval breadth. Distinct
prompts rather than one that tries to be everything: critique and explanation want opposite
behaviour, and a prompt asked to do both does neither well.

| Mode | For | Effort | Passages |
|---|---|---|---|
| `explain` | A paper, concept, figure, or equation | medium | 5 |
| `research` | Answering across the library | high | 10 |
| `critique` | Finding weaknesses in a method or claim | high | 8 |
| `ideate` | Generating research directions | high | 10 |
| `experiment` | Designing an experiment and its controls | high | 8 |
| `study` | Learning, with comprehension checks | medium | 6 |
| `write` | Structure, and whether claims are supported | medium | 6 |

Effort is mapped to what the user is doing: someone mid-paragraph asking "what does this mean"
wants an answer now; someone asking "what is wrong with this method" would rather wait.

---

## Grounding

Every mode's prompt begins with the same rules (`GROUNDING_RULES` in `atlas/ai/prompts.py`):
cite the specific source for each claim, only the numbered sources exist, distinguish what a
source states from what you inferred from what you are speculating, surface disagreement rather
than averaging it away, and say plainly when the library does not contain the answer.

They are written as descriptions of good behaviour, not as prohibitions in capitals. Current
models follow a plainly-stated instruction; stacking emphasis makes them over-trigger and hedge
in every answer.

**But the prompt is not the mechanism.** The guarantee is structural:

1. Retrieval returns chunks with their database ids.
2. The context builder numbers them `[1]`, `[2]`, … and renders them into the prompt.
3. When the turn completes, the server writes one `MessageCitation` per **retrieved** passage,
   carrying its `chunk_id`, `paper_id`, and locator.
4. Answer text is parsed only to record *which markers were used* (`used_in_answer`).

A citation is therefore a foreign key the server wrote, not a claim the model made. If the
model writes `[9]` when five sources were supplied, no ninth citation exists — there is nothing
to render, and the UI shows the marker as plain text rather than as a live reference. This is
tested directly in `tests/test_assistant.py`.

Citations also store a **snapshot** of the passage text alongside the reference. Chunks are
rewritten when a paper is re-ingested; a citation that silently began pointing at different
text would be a fabricated quotation. When the chunk is gone the snapshot still shows what was
cited, and only the jump-to-passage link stops working.

---

## A turn

```
question
  → persist it                     (survives a failure mid-answer)
  → retrieve (hybrid, owner-scoped)
  → build SOURCES within a token budget
  → stream: `sources` frame first, then `text`, then `done`
  → persist the answer + citations
```

Sources are sent **before** any prose. The reader sees what the answer is being built from
before the answer exists, which is also what makes an ungrounded answer visibly ungrounded.

Streaming is Server-Sent Events over `POST`: the channel is one-directional, survives proxies
that mangle WebSocket upgrades, and the client can abort it. Aborting matters — generation
keeps running, and costing, until the connection closes.

Failures are recorded, not discarded. The question stays in the transcript and the assistant
turn carries `error_message`, so the user is not left with a question that vanished. Failed
turns are excluded from replayed history: feeding an empty answer back teaches the model that
empty answers are acceptable.

---

## Generated study material

Flashcards and quiz questions are generated, which makes them the same hazard as an answer: a
plausible card about something the paper never said is worse than no card, because it will be
memorised.

The mechanism is the same one that keeps citations honest, applied a step earlier:

1. The service selects passages from the paper — content sections only, spread across the
   document — and numbers them in the prompt.
2. The model must attach a passage number to every card or question it writes.
3. The service maps that number back to a chunk id. **A number it was never shown is dropped.**
4. What is stored keeps both the chunk id and a snapshot of the passage text, so re-ingesting
   the paper cannot silently change what a card claims its source says.

If nothing survives step 3, the request fails with 422 rather than returning an empty deck —
"this paper produced no cards" and "every card cited a passage that does not exist" are
different things and must not look the same.

The reader sees the passage behind every card and every quiz answer, which is what makes the
guarantee checkable rather than merely claimed.

### Why the JSON is parsed rather than constrained

Both vendors offer a native structured-output mode, and they offer different ones. Asking for
JSON in the prompt and validating it in `ai/structured.py` keeps the provider interface free of
vendor-specific request shapes (D3), at the cost of handling responses that are truncated,
fenced in Markdown, or wrapped in prose. That handling is written and tested, and treating the
model's output as untrusted input is the correct posture regardless.

Entries that fail validation are dropped; a response with no JSON array at all is a provider
failure and raises.

---

## What is not built

- **Reranking.** The pipeline has the stage; it is currently a pass-through. A cross-encoder
  would be a swap, not surgery.
- **Evaluation harness.** Milestone 9. `used_in_answer` is recorded now specifically so
  precision of retrieved-versus-cited can be measured then.
- **Live-provider verification.** The Anthropic path is written against the documented API and
  covered by tests with a scripted provider, but no key was available in this environment, so
  a real round trip has not been exercised. Set `ANTHROPIC_API_KEY` to confirm it.
