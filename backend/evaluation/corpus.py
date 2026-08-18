"""The benchmark corpus, and the queries whose answers are known.

Written rather than downloaded, for three reasons. Real papers cannot be committed to the
repository for licensing reasons; a benchmark that needs a network fetch does not run in CI;
and a corpus written here can contain *deliberate near-misses* — two papers that discuss the
same topic where only one holds the answer — which is the case that separates retrieval that
works from retrieval that returns whatever mentions the query words.

Each query names the passage that answers it by a marker string. Retrieval is scored on
whether the passage containing that marker comes back, not on which paper it belongs to: a
paper-level match would score a hit for returning the references section of the right paper.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Document:
    slug: str
    title: str
    pages: list[list[str]]


@dataclass(frozen=True, slots=True)
class Query:
    text: str
    answer_marker: str
    """A phrase that appears in the passage that answers this query, and nowhere else in the
    corpus. Uniqueness is asserted at load time, so a corpus edit cannot silently make a query
    unscoreable."""

    note: str
    """Why this query is in the set — what it is testing that the others are not."""


CORPUS: list[Document] = [
    Document(
        slug="sparse-attention",
        title="Strided Sparse Attention for Long-Context Inference",
        pages=[
            [
                "Strided Sparse Attention for Long-Context Inference",
                "Marta Oyelaran, Devin Cho",
                "",
                "Abstract",
                "Dense attention over long inputs is bounded by a quadratic memory term. We "
                "restrict each query to a strided neighbourhood of keys, reducing peak memory "
                "by forty-one percent at a context length of thirty-two thousand tokens while "
                "remaining within one point of the dense baseline on retrieval benchmarks.",
                "",
                "1 Introduction",
                "Serving a long-context model is usually memory-bound rather than "
                "compute-bound. The attention matrix grows with the square of sequence "
                "length, so a context window that doubles quadruples the memory the layer "
                "needs at once.",
            ],
            [
                "2 Method",
                "Each query attends to a fixed stride of preceding keys together with a small "
                "set of global tokens. The stride is sixty-four positions, chosen because "
                "shorter strides lost accuracy on multi-hop questions and longer ones "
                "recovered no further memory.",
                "",
                "3 Results",
                "Peak memory falls from 41.2 gigabytes to 24.3 gigabytes at thirty-two "
                "thousand tokens. Accuracy on the retrieval suite drops by 0.8 points, which "
                "we consider the cost of the sparsity pattern rather than of the training "
                "recipe, since the recipe is unchanged.",
            ],
        ],
    ),
    Document(
        slug="quantised-cache",
        title="Four-Bit Key-Value Cache Quantisation",
        pages=[
            [
                "Four-Bit Key-Value Cache Quantisation",
                "Priya Raghunathan, Tomas Lindqvist",
                "",
                "Abstract",
                "The key-value cache dominates memory during autoregressive decoding. We "
                "quantise cached keys and values to four bits with per-channel scales, "
                "cutting cache memory by seventy-three percent with no measurable change in "
                "perplexity.",
                "",
                "1 Introduction",
                "Decoding is memory-bound for the same reason attention is: every generated "
                "token must read the entire cache. Unlike attention, the cache can be "
                "compressed after the fact, without retraining.",
            ],
            [
                "2 Method",
                "Keys and values are quantised separately, because their distributions "
                "differ: key outliers concentrate in a few channels while value outliers are "
                "spread across positions. Per-channel scales for keys and per-token scales "
                "for values preserved accuracy where a single shared scale did not.",
                "",
                "3 Results",
                "Cache memory falls by seventy-three percent. Perplexity moves by 0.02, "
                "within run-to-run variance. Throughput improves by 1.4 times, which comes "
                "from the reduced memory traffic rather than from any change in arithmetic.",
            ],
        ],
    ),
    Document(
        slug="protein-folding",
        title="Contact Map Refinement for Protein Structure Prediction",
        pages=[
            [
                "Contact Map Refinement for Protein Structure Prediction",
                "Aiko Tanabe, Ruth Mensah",
                "",
                "Abstract",
                "Predicted contact maps carry systematic errors at domain boundaries. We "
                "refine them with a residual network conditioned on multiple sequence "
                "alignment depth, improving long-range contact precision by nine points on "
                "the held-out set.",
                "",
                "1 Introduction",
                "Structure prediction quality tracks alignment depth closely. Shallow "
                "alignments produce contact maps that are confident and wrong, particularly "
                "where two domains meet.",
            ],
            [
                "2 Method",
                "The refinement network takes the predicted map and the alignment depth "
                "profile as separate channels. Conditioning on depth matters because the "
                "error the network must correct is itself a function of depth.",
                "",
                "3 Results",
                "Long-range precision rises from sixty-one to seventy percent. The gain "
                "concentrates in proteins with fewer than one hundred effective sequences, "
                "where the uncorrected maps were worst.",
            ],
        ],
    ),
]


QUERIES: list[Query] = [
    Query(
        text="peak memory in gigabytes before and after the stride",
        answer_marker="41.2 gigabytes to 24.3 gigabytes",
        note="A number stated only in the results. The first draft of this query was 'how "
        "much memory does sparse attention save', which the abstract answers too — retrieval "
        "returned the abstract and the benchmark scored it a miss. The benchmark was wrong.",
    ),
    Query(
        text="why quantise keys and values with different scales",
        answer_marker="key outliers concentrate in a few channels",
        note="Answered by a method paragraph, not by the abstract that shares its vocabulary.",
    ),
    Query(
        text="what stride length was chosen and why",
        answer_marker="stride is sixty-four positions",
        note="Two papers discuss memory reduction; only one has a stride. A near-miss test.",
    ),
    Query(
        text="which proteins gained most from contact map refinement",
        answer_marker="fewer than one hundred effective sequences",
        note="Asks which proteins, which only the results answer. The introduction states the "
        "depth relationship but names no group, so a loose query scored a false miss.",
    ),
    Query(
        text="reducing memory during autoregressive decoding",
        answer_marker="every generated token must read the entire cache",
        note="Paraphrase only: the passage never uses the word 'reducing' or 'memory-bound' "
        "in the queried form. Tests the vector half rather than the lexical half.",
    ),
    Query(
        text="does compressing the cache hurt perplexity",
        answer_marker="Perplexity moves by 0.02",
        note="The answer is a non-effect. A system that only matches topic words would return "
        "the abstract instead.",
    ),
    Query(
        text="quadratic memory term in attention",
        answer_marker="grows with the square of sequence length",
        note="Exact-ish terminology, testing the lexical half.",
    ),
    Query(
        text="where do contact maps go wrong",
        answer_marker="confident and wrong, particularly",
        note="Colloquial phrasing against formal text.",
    ),
]


def assert_markers_are_unique() -> None:
    """Every answer marker must appear exactly once across the whole corpus.

    Called at load time by the runner and by the tests. Without it, an edit to the corpus
    could make a query ambiguous, and the benchmark would quietly start scoring something
    other than what it claims to measure.
    """
    body = "\n".join(line for document in CORPUS for page in document.pages for line in page)
    for query in QUERIES:
        occurrences = body.count(query.answer_marker)
        if occurrences != 1:
            raise AssertionError(
                f"marker {query.answer_marker!r} for query {query.text!r} appears "
                f"{occurrences} times in the corpus; it must appear exactly once"
            )
