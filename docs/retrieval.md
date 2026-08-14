# Retrieval

How Atlas finds the passages an answer is built from.

```
question
  ├── embed ──────────→ vector search   (cosine, HNSW)   ─┐
  └── as typed ───────→ lexical search  (tsvector, GIN)  ─┤
                                                          ├── reciprocal rank fusion
                                                          ├── rerank  (pass-through today)
                                                          └── context, numbered + budgeted
```

---

## Why hybrid

Vector search finds passages that *mean* something similar, which is what catches paraphrase —
a query about "reducing hallucination" matching a passage about "improving factual grounding".

Lexical search finds passages containing the exact terms: a gene name, an author, a dataset, an
equation label, `BLEU`, `10.1038/nature14539`. Scientific vocabulary is precisely where
embeddings are weakest, because these terms are rare and their neighbourhoods are noisy.
Dropping this half would make Atlas worse at exactly the literature it exists to read.

Each strategy retrieves 40 candidates before fusion — wider than the final count, so a passage
ranked poorly by one can still be rescued by the other.

## Fusion

The two scores are not comparable: cosine distance and `ts_rank_cd` live on different scales
with different distributions, and normalising them means tuning per corpus.

Reciprocal rank fusion sidesteps that by using only each result's *position* in its own list:

```
score(passage) = Σ  1 / (K + rank)      K = 60
```

A passage found by both strategies scores higher than one found by either alone, which is the
behaviour we want — agreement between independent signals is evidence. Every result records
`found_by` (`meaning`, `keyword`, or `both`) so a search result can explain why it surfaced.

Ties break on document order, so repeating a query returns a stable ranking.

## Scoping and isolation

Ownership and readiness are conditions **inside** the SQL, not a filter applied afterwards:

```sql
WHERE p.owner_id = :owner_id AND p.status = 'ready'
```

A retrieval path that forgot the owner filter would leak another user's private research into
an answer, so the filter lives where it cannot be forgotten by a caller. `tests/test_retrieval.py`
asserts that a second account searching for a first account's content gets nothing back.

An optional `paper_ids` filter scopes retrieval to specific papers — what "ask about this paper"
does. It is composed into the statement only when supplied, rather than written as
`:ids IS NULL OR ...`, which would defeat index use on the filtered path.

Queries go through `websearch_to_tsquery`, which accepts what a person actually types — quoted
phrases, `OR`, a leading minus — and never raises on malformed input, unlike `to_tsquery`.

## Indexes

| Index | Serves |
|---|---|
| HNSW on `paper_chunks.embedding`, `vector_cosine_ops` | Vector search |
| GIN on `paper_chunks.content_tsv` | Lexical search |
| B-tree on `(paper_id, ordinal)` | Reading a paper's passages in order |

`content_tsv` is a **generated column**, maintained by PostgreSQL. A trigger or an application
write that some code path forgets produces a search index that is quietly wrong.

## Chunking, from retrieval's point of view

Chunk boundaries determine what a citation can point at, so they are chosen for provenance
rather than for uniformity:

- **Never spans a section.** A passage straddling Methods and Results reads as incoherent when
  retrieved alone, and cannot honestly be attributed to either.
- **Carries its page and section.** A passage that cannot say where it came from is not
  evidence, and none is stored without a locator.
- **~1600 characters, overlapping by ~220.** Large enough to hold a complete argument, small
  enough that a retrieved passage is mostly relevant. The overlap means a claim spanning a
  boundary is still retrievable in full from at least one side.

## Context construction

Passages are numbered from 1 in relevance order and rendered with title, author, year, and
locator, until the token budget (12k) is spent. Building stops at the first passage that does
not fit rather than skipping ahead to a smaller one: markers must ascend with relevance for the
numbering to mean anything.

At least one passage is always kept, even if it exceeds the budget alone — an answer grounded
in one long passage beats an ungrounded one.

Dropped passages are counted and logged. Silent truncation would read as "this is everything
relevant", which would be false.

When nothing is retrieved, the prompt says so explicitly and instructs the model to tell the
user their library does not cover it — not to answer from general knowledge as though it were
sourced.

## Indexing

Embedding runs as the final ingestion stage and, separately, as a backfill for papers ingested
before a provider was configured. It considers only chunks whose embedding is null, so an
interrupted run resumes rather than paying twice.

A batch whose vector count does not match its chunk count raises rather than writing: mispaired
vectors would make retrieval confidently cite the wrong page, which is worse than failing.

Embedding dimensionality is fixed at the `pgvector` column. **Changing embedding model requires
a migration and a re-index**, not a configuration change — vectors from two models are not
comparable, and mixing them makes ranking meaningless. `ChunkIndexer.clear_paper` exists for
that path.

## Known limits

- **Reranking is a pass-through.** The stage exists; a cross-encoder would be a swap.
- **No query expansion.** A question using different vocabulary than the paper relies entirely
  on the vector half.
- **Fixed candidate depth.** 40 per strategy regardless of library size.
- **Retrieval runs per turn**, using the question as written. A follow-up like "what about the
  second one?" retrieves on those words alone; rewriting the query against conversation history
  would improve multi-turn grounding and is not implemented.
