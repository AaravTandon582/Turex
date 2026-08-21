"""Scores for a ranked list of results.

Three, chosen because they answer three different questions a reader would actually ask.

- **Recall@k** — did the passage I wanted appear at all in the top k? The question behind
  "why can't Turex find the thing I know is in there".
- **MRR** — how far down was it? The difference between an answer and a hunt.
- **Precision@1** — was the very first result right? What a reader who trusts the tool sees.

Deliberately not a single blended number. A change that trades recall for precision is a real
decision, and a composite score hides it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Scores:
    queries: int
    recall_at_1: float
    recall_at_3: float
    recall_at_5: float
    mean_reciprocal_rank: float
    misses: list[str]
    """Queries where the expected passage never appeared. The interesting part of a report:
    an average tells you how it did, this tells you what to fix."""

    def as_table(self) -> str:
        rows = [
            ("queries", f"{self.queries}"),
            ("recall@1", f"{self.recall_at_1:.0%}"),
            ("recall@3", f"{self.recall_at_3:.0%}"),
            ("recall@5", f"{self.recall_at_5:.0%}"),
            ("MRR", f"{self.mean_reciprocal_rank:.3f}"),
        ]
        width = max(len(name) for name, _ in rows)
        return "\n".join(f"  {name:<{width}}  {value}" for name, value in rows)


def reciprocal_rank(ranked: Sequence[bool]) -> float:
    """1/position of the first hit, or zero if there is none."""
    for index, hit in enumerate(ranked, start=1):
        if hit:
            return 1.0 / index
    return 0.0


def score(judgements: Mapping[str, Sequence[bool]]) -> Scores:
    """Aggregate per-query hit lists into a report.

    Each value is the ranked result list for one query, expressed as "was this result the
    passage we were looking for".
    """
    if not judgements:
        raise ValueError("nothing to score")

    def recall_at(k: int) -> float:
        return sum(any(ranked[:k]) for ranked in judgements.values()) / len(judgements)

    return Scores(
        queries=len(judgements),
        recall_at_1=recall_at(1),
        recall_at_3=recall_at(3),
        recall_at_5=recall_at(5),
        mean_reciprocal_rank=sum(reciprocal_rank(r) for r in judgements.values()) / len(judgements),
        misses=sorted(query for query, ranked in judgements.items() if not any(ranked)),
    )
