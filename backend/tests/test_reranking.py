"""Reordering fused candidates by what the passages actually say.

Fusion combines two rankings by position and never looks at the text. Reranking looks.

**It does not move the offline benchmark.** Measured: recall@3 88% and MRR 0.646 with and
without it, while demonstrably reordering two of the eight benchmark queries. That is stated
plainly rather than quietly implied, because the offline embedder is itself bag-of-words, so a
lexical reranker mostly reinforces the signal that already ranked those results. It is kept for
the failure it does fix — shown below — and because it is where a cross-encoder would slot in.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from atlas.retrieval.reranking import (
    PRIOR_WEIGHT,
    rerank,
    score_passage,
)


@dataclass
class Candidate:
    """The fields reranking reads. A real `RetrievedChunk` carries far more."""

    content: str
    section_title: str | None


METHOD = Candidate(
    "Keys and values are quantised separately, because their distributions differ: key "
    "outliers concentrate in a few channels while value outliers are spread across positions. "
    "Per-channel scales for keys and per-token scales for values preserved accuracy where a "
    "single shared scale did not.",
    "2 Method",
)
ACKNOWLEDGEMENT = Candidate(
    "Acknowledgements. We thank the reviewers for their comments on quantise keys values "
    "scales and the wider discussion.",
    "Acknowledgements",
)


class TestScoring:
    def test_a_passage_containing_the_query_phrase_scores_above_one_that_scatters_it(
        self,
    ) -> None:
        """Coverage alone cannot tell these apart, which is why the phrase signal exists."""
        query = "scaled dot product attention"
        together = score_passage(
            query, "We call our attention scaled dot product attention.", "3 Method"
        )
        scattered = score_passage(
            query, "Attention is scaled. The dot of the product is discussed.", "3 Method"
        )
        assert together.phrase > scattered.phrase
        assert together.total > scattered.total

    def test_a_weak_section_discounts_everything_rather_than_subtracting_a_little(self) -> None:
        """The words appearing in an acknowledgement means less, not slightly less."""
        query = "why quantise keys and values with different scales"
        strong = score_passage(query, METHOD.content, "2 Method")
        weak = score_passage(query, METHOD.content, "Acknowledgements")
        assert weak.total < strong.total / 2

    def test_an_unknown_section_is_barely_penalised(self) -> None:
        """Most of a paper is neither obviously strong nor weak, and guessing there would hurt."""
        query = "quantisation"
        unknown = score_passage(query, METHOD.content, "7 Something Unusual")
        strong = score_passage(query, METHOD.content, "2 Method")
        assert unknown.total > strong.total * 0.7

    def test_a_caption_sized_fragment_scores_below_a_paragraph(self) -> None:
        query = "residual connection"
        fragment = score_passage(query, "Figure 2: residual connection.", "3 Method")
        paragraph = score_passage(query, "The residual connection " * 40, "3 Method")
        assert fragment.length < paragraph.length

    def test_an_empty_query_does_not_divide_by_zero(self) -> None:
        assert score_passage("", METHOD.content, "2 Method").coverage == 0.0

    def test_an_empty_passage_scores_nothing(self) -> None:
        assert score_passage("attention", "", None).total == 0.0


class TestReordering:
    def test_a_better_passage_can_overtake_the_fused_leader(self) -> None:
        """The failure this exists to fix.

        An acknowledgements paragraph that happens to contain the query's words was ranked
        first by fusion. The first attempt at reranking could not overturn it: a reciprocal
        position prior halves between the first and second result, a gap no content signal can
        close, so reranking was a no-op that looked like it worked.
        """
        assert (
            rerank("why quantise keys and values with different scales", [ACKNOWLEDGEMENT, METHOD])[
                0
            ]
            is METHOD
        )

    def test_the_fused_order_still_leads_when_nothing_beats_it(self) -> None:
        """Reranking adjusts the order; it does not replace it. The vector model's judgement is
        not reproducible from word matching."""
        first = Candidate(METHOD.content, "2 Method")
        second = Candidate(METHOD.content, "2 Method")
        assert rerank("quantisation of keys and values", [first, second])[0] is first

    def test_the_prior_leads_without_deciding(self) -> None:
        assert 0.2 < PRIOR_WEIGHT < 0.5, "the fused order should lead, not decide"

    @pytest.mark.parametrize("candidates", [[], [METHOD]])
    def test_nothing_to_reorder_is_returned_unchanged(self, candidates: list[Candidate]) -> None:
        assert rerank("anything", candidates) == candidates

    def test_ordering_is_stable_across_runs(self) -> None:
        """Position breaks ties, so a search run twice returns the same order — otherwise a
        citation marker could point at a different passage on a refresh."""
        pool = [METHOD, ACKNOWLEDGEMENT, Candidate(METHOD.content, None)]
        first = rerank("quantise keys", list(pool))
        second = rerank("quantise keys", list(pool))
        assert [id(x) for x in first] == [id(x) for x in second]
