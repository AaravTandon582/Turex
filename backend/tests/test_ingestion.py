"""Unit tests for document processing.

These run without a database. They cover the parts of ingestion where correctness is not
obvious from the code: text repair, section detection, and the invariants chunking must hold
for citations to be trustworthy.
"""

from __future__ import annotations

import io
import pathlib

import pytest

from atlas.core.errors import ProcessingFailedError
from atlas.ingestion.chunking import MAX_CHARACTERS, chunk_document
from atlas.ingestion.equations import detect_equations, looks_like_an_equation
from atlas.ingestion.pdf import parse_pdf
from atlas.ingestion.references import parse_references
from atlas.ingestion.text import (
    clean_page,
    estimate_tokens,
    normalise_characters,
    rejoin_hyphenated_words,
    strip_page_furniture,
    unwrap_lines,
)
from tests.support.pdf_builder import build_paper_pdf, build_pdf


def write_pdf(tmp_path: pathlib.Path, data: bytes) -> str:
    path = tmp_path / "document.pdf"
    path.write_bytes(data)
    return str(path)


class TestTextRepair:
    def test_rejoins_words_split_across_lines(self) -> None:
        assert rejoin_hyphenated_words("signifi-\ncant") == "significant"

    def test_keeps_real_hyphens(self) -> None:
        """A hyphen inside a line is part of the word, not a typesetting artefact."""
        assert rejoin_hyphenated_words("state-of-the-art") == "state-of-the-art"

    def test_folds_ligatures(self) -> None:
        # A query typed on a keyboard must match text lifted from a typeset paper.
        assert normalise_characters("eﬃcient ﬂow") == "efficient flow"

    def test_normalises_typographic_quotes(self) -> None:
        assert normalise_characters("“quoted” and ‘single’") == ("\"quoted\" and 'single'")

    def test_unwraps_hard_wrapped_lines(self) -> None:
        wrapped = "The results show a clear\nimprovement over the baseline."
        assert unwrap_lines(wrapped) == "The results show a clear improvement over the baseline."

    def test_keeps_paragraph_breaks(self) -> None:
        assert "\n\n" in unwrap_lines("First paragraph.\n\nSecond paragraph.")

    def test_keeps_line_breaks_after_sentences(self) -> None:
        """A newline following a full stop is a real break, not wrapping."""
        assert unwrap_lines("Done.\nNext") == "Done.\nNext"

    def test_clean_page_preserves_line_structure(self) -> None:
        """Headings are found by their line breaks, so cleaning must not remove them."""
        cleaned = clean_page("3 Results\nWe observed an improvement\nacross every condition.")
        assert cleaned.splitlines()[0] == "3 Results"


class TestPageFurniture:
    def test_strips_a_repeated_running_header(self) -> None:
        pages = [f"Journal of Testing\nBody text for page {n}.\n{n}" for n in range(1, 9)]
        cleaned = strip_page_furniture(pages)

        assert all("Journal of Testing" not in page for page in cleaned)
        assert "Body text for page 3." in cleaned[2]

    def test_strips_bare_page_numbers(self) -> None:
        cleaned = strip_page_furniture(["Content here.\n7"] * 6)
        assert all(line.strip() != "7" for page in cleaned for line in page.splitlines())

    def test_leaves_short_documents_alone(self) -> None:
        """With three pages, 'appears on most pages' is not evidence of anything."""
        pages = ["Introduction\nSome text."] * 3
        assert all("Introduction" in page for page in strip_page_furniture(pages))


class TestTokenEstimate:
    def test_scales_with_length(self) -> None:
        assert estimate_tokens("word " * 100) > estimate_tokens("word " * 10)

    def test_never_returns_zero(self) -> None:
        # A zero would let an empty chunk slip past a context budget check.
        assert estimate_tokens("") == 1


class TestParsing:
    def test_extracts_title_authors_and_abstract(self, tmp_path: pathlib.Path) -> None:
        document = parse_pdf(write_pdf(tmp_path, build_paper_pdf()))

        assert document.metadata.title == "A Study of Something Interesting"
        assert document.metadata.authors == ["Ada Lovelace", "Charles Babbage"]
        assert document.metadata.abstract is not None
        assert "whether the thing works" in document.metadata.abstract

    def test_detects_numbered_sections(self, tmp_path: pathlib.Path) -> None:
        document = parse_pdf(write_pdf(tmp_path, build_paper_pdf()))
        titles = [section.title for section in document.sections]

        assert "1 Introduction" in titles
        assert "2 Method" in titles
        assert "3 Results" in titles

    def test_records_section_depth(self, tmp_path: pathlib.Path) -> None:
        pdf = build_pdf([["1 Method", "Body text goes here.", "1.2 Ablation", "More body text."]])
        sections = {s.title: s.level for s in parse_pdf(write_pdf(tmp_path, pdf)).sections}

        assert sections["1 Method"] == 1
        assert sections["1.2 Ablation"] == 2

    def test_ignores_equation_fragments(self, tmp_path: pathlib.Path) -> None:
        """Rendered formulas read as all-caps lines and must not become sections."""
        pdf = build_pdf(
            [["1 Method", "The attention weights are given by", ")V (1)", "and so on."]]
        )
        titles = [section.title for section in parse_pdf(write_pdf(tmp_path, pdf)).sections]

        assert not any("(1)" in title for title in titles)

    def test_skips_licence_banners_when_reading_the_title(self, tmp_path: pathlib.Path) -> None:
        """Publishers print a multi-line permission notice above the title."""
        pdf = build_pdf(
            [
                [
                    "Provided proper attribution is provided, we hereby grant permission to",
                    "reproduce the tables and figures in this work solely for use in",
                    "scholarly works.",
                    "Attention Is All You Need",
                    "Ashish Vaswani",
                    "",
                    "Abstract",
                    "We propose a new architecture based entirely on attention mechanisms, "
                    "dispensing with recurrence and convolutions entirely in the encoder.",
                ]
            ]
        )
        metadata = parse_pdf(write_pdf(tmp_path, pdf)).metadata

        assert metadata.title == "Attention Is All You Need"

    def test_continues_a_title_across_a_line_break(self, tmp_path: pathlib.Path) -> None:
        """A title ending on a preposition obviously runs on to the next line."""
        pdf = build_pdf(
            [
                [
                    "Retrieval-Augmented Generation for",
                    "Knowledge-Intensive NLP Tasks",
                    "Patrick Lewis",
                ]
            ]
        )
        metadata = parse_pdf(write_pdf(tmp_path, pdf)).metadata

        assert metadata.title == "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks"

    def test_splits_a_byline_printed_without_separators(self, tmp_path: pathlib.Path) -> None:
        pdf = build_pdf(
            [
                [
                    "Deep Residual Learning for Image Recognition",
                    "Kaiming He Xiangyu Zhang Shaoqing Ren Jian Sun",
                    "",
                    "Abstract",
                    "Deeper neural networks are more difficult to train. We present a residual "
                    "learning framework to ease the training of networks substantially deeper.",
                ]
            ]
        )
        metadata = parse_pdf(write_pdf(tmp_path, pdf)).metadata

        assert metadata.authors == ["Kaiming He", "Xiangyu Zhang", "Shaoqing Ren", "Jian Sun"]

    def test_does_not_mistake_an_organisation_for_an_author(self, tmp_path: pathlib.Path) -> None:
        pdf = build_pdf([["A Title About Something", "Jane Doe", "Google Research", "Abstract"]])
        assert parse_pdf(write_pdf(tmp_path, pdf)).metadata.authors == ["Jane Doe"]

    def test_finds_identifiers(self, tmp_path: pathlib.Path) -> None:
        pdf = build_pdf([["A Paper With Identifiers", "arXiv:1706.03762", "doi:10.1000/xyz123"]])
        metadata = parse_pdf(write_pdf(tmp_path, pdf)).metadata

        assert metadata.arxiv_id == "1706.03762"
        assert metadata.doi == "10.1000/xyz123"

    def test_dates_a_preprint_from_its_arxiv_identifier(self, tmp_path: pathlib.Path) -> None:
        """A regenerated preprint carries the regeneration date in its PDF metadata; the
        identifier carries the real one."""
        pdf = build_pdf([["Some Paper Title Here", "arXiv:1706.03762", "Published 2024"]])
        assert parse_pdf(write_pdf(tmp_path, pdf)).metadata.publication_year == 2017

    def test_rejects_a_pdf_with_no_text(self, tmp_path: pathlib.Path) -> None:
        """A scanned document needs OCR, and the message must say so."""
        with pytest.raises(ProcessingFailedError) as caught:
            parse_pdf(write_pdf(tmp_path, build_pdf([[""]])))

        assert "text" in caught.value.message.lower()

    def test_rejects_a_corrupt_file(self, tmp_path: pathlib.Path) -> None:
        with pytest.raises(ProcessingFailedError):
            parse_pdf(write_pdf(tmp_path, b"%PDF-1.4\nthis is not really a pdf"))


class TestChunking:
    def test_every_chunk_knows_its_page(self, tmp_path: pathlib.Path) -> None:
        """The property citations depend on: a passage that cannot be located is not
        usable as evidence."""
        document = parse_pdf(write_pdf(tmp_path, build_paper_pdf()))

        for chunk in chunk_document(document):
            assert chunk.page_start >= 1
            assert chunk.page_end >= chunk.page_start

    def test_chunks_do_not_span_sections(self, tmp_path: pathlib.Path) -> None:
        document = parse_pdf(write_pdf(tmp_path, build_paper_pdf()))
        chunks = chunk_document(document)

        assert chunks, "expected the document to produce chunks"
        # Each chunk carries exactly one section, and ordinals never interleave.
        by_section: dict[int, list[int]] = {}
        for chunk in chunks:
            assert chunk.section_ordinal is not None
            by_section.setdefault(chunk.section_ordinal, []).append(chunk.ordinal)
        for ordinals in by_section.values():
            assert ordinals == sorted(ordinals)

    def test_ordinals_are_contiguous(self, tmp_path: pathlib.Path) -> None:
        chunks = chunk_document(parse_pdf(write_pdf(tmp_path, build_paper_pdf())))
        assert [chunk.ordinal for chunk in chunks] == list(range(len(chunks)))

    def test_splits_an_oversized_paragraph(self, tmp_path: pathlib.Path) -> None:
        long_paragraph = " ".join(
            f"Sentence number {index} describes another finding in detail." for index in range(200)
        )
        pdf = build_pdf([["1 Results", long_paragraph]])
        chunks = chunk_document(parse_pdf(write_pdf(tmp_path, pdf)))

        assert len(chunks) > 1
        assert all(len(chunk.content) <= MAX_CHARACTERS for chunk in chunks)

    def test_falls_back_to_pages_without_headings(self, tmp_path: pathlib.Path) -> None:
        """Posters and short preprints have no sections but must still be searchable."""
        body = (
            "This document has no headings whatsoever, only continuous prose that runs on "
            "for a while so that it comfortably exceeds the minimum chunk size and is worth "
            "indexing at all for later retrieval."
        )
        chunks = chunk_document(parse_pdf(write_pdf(tmp_path, build_pdf([[body]]))))

        assert len(chunks) >= 1
        assert chunks[0].section_ordinal is None

    def test_skips_the_reference_list(self, tmp_path: pathlib.Path) -> None:
        """A bibliography matches on vocabulary and asserts nothing — indexing it only
        produces retrieval hits that can never support a claim."""
        pdf = build_pdf(
            [
                [
                    "1 Introduction",
                    "We build on prior work in retrieval augmented generation for question "
                    "answering, which established the baseline we compare against here.",
                    "",
                    "References",
                    "[1] Lewis et al. Retrieval augmented generation for knowledge intensive "
                    "NLP tasks. NeurIPS, 2020.",
                    "[2] Devlin et al. BERT: pre-training of deep bidirectional transformers. "
                    "NAACL, 2019.",
                ]
            ]
        )
        chunks = chunk_document(parse_pdf(write_pdf(tmp_path, pdf)))

        assert chunks, "the body should still be indexed"
        assert not any("NeurIPS, 2020" in chunk.content for chunk in chunks)
        assert any("prior work" in chunk.content for chunk in chunks)

    def test_records_a_token_estimate(self, tmp_path: pathlib.Path) -> None:
        for chunk in chunk_document(parse_pdf(write_pdf(tmp_path, build_paper_pdf()))):
            assert chunk.token_estimate > 0


class TestEquationDetection:
    """PDF text carries no markup for mathematics, so equations are recognised by evidence.

    The thresholds were set against real papers, and the cases below are the ones that were
    actually getting through when they were wrong.
    """

    @pytest.mark.parametrize(
        "line",
        [
            "FFN(x) = max(0,xW 1 +b1)W2 +b2",
            "PE (pos,2i) =sin(pos/100002i/dmodel)",
            "y =F (x,{Wi}) + x.",
            "pη(z|x)∝ exp",
            "d(z) = BERTd(z), q(x) = BERTq(x)",
        ],
    )
    def test_recognises_displayed_equations(self, line: str) -> None:
        assert looks_like_an_equation(line), line

    @pytest.mark.parametrize(
        ("line", "why"),
        [
            (
                "We used the Adam optimizer [20] withβ1 = 0.9,β2 = 0.98 andε = 10-9. We varied it",
                "a sentence that mentions mathematics",
            ),
            ("i.e., 3072 for the H = 768 and 4096 for the H = 1024.", "prose with numbers"),
            ("Vaswani et al. (2017) is (L=6, H=1024, A=16)", "a citation"),
            ("warmup_steps = 4000.", "a hyperparameter, not an equation"),
            ("of 1√dk", "the tail of a wrapped sentence"),
            ("net/forum?id=rJl3yM-Ab.", "a URL from the bibliography"),
            ("Table 3 shows that accuracy = 91%", "a sentence about a table"),
        ],
    )
    def test_refuses_prose_that_contains_symbols(self, line: str, why: str) -> None:
        assert not looks_like_an_equation(line), f"{why}: {line}"

    def test_equation_numbers_are_split_from_the_equation(self) -> None:
        """The number is what a reader cites, so it is stored separately rather than left in
        the middle of the mathematics."""
        document = parse_pdf(
            io.BytesIO(
                build_pdf(
                    [
                        [
                            "A Paper With Mathematics",
                            "A Author",
                            "",
                            "1 Method",
                            "The residual mapping is defined below.",
                            "y = F(x, {Wi}) + x (1)",
                        ]
                    ]
                )
            )
        )
        equations = detect_equations(document)
        assert equations, "no equation was found"
        assert equations[0].label == "1"
        assert "(1)" not in equations[0].content


class TestReferenceParsing:
    def test_numbered_entries_are_split_and_keep_their_number(self) -> None:
        text = (
            "References\n"
            "[1] Jimmy Lei Ba, Jamie Ryan Kiros, and Geoffrey E Hinton. Layer normalization.\n"
            "arXiv preprint arXiv:1607.06450, 2016.\n"
            "[2] Dzmitry Bahdanau and Yoshua Bengio. Neural machine translation by jointly\n"
            "learning to align and translate. CoRR, abs/1409.0473, 2014.\n"
        )
        entries = parse_references(text)

        assert len(entries) == 2
        assert entries[0].marker == "1"
        assert entries[0].arxiv_id == "1607.06450"
        assert entries[0].year == 2016
        assert "Layer normalization" in entries[0].text
        # Wrapped lines are joined back rather than becoming separate references.
        assert "arXiv preprint" in entries[0].text

    def test_author_year_entries_are_split_without_a_number(self) -> None:
        """Author initials carry periods, and excluding them once reduced a whole bibliography
        to a single entry."""
        text = (
            "References\n"
            "Abramson, J., Ahuja, A., Barr, I., Brussee, A., and Carnevale, F. (2020).\n"
            "Imitating interactive intelligence. arXiv preprint arXiv:2012.05672.\n"
            "Achiam, J., Held, D., Tamar, A., and Abbeel, P. (2017). Constrained policy\n"
            "optimization. In International Conference on Machine Learning.\n"
        )
        entries = parse_references(text)

        assert len(entries) == 2
        assert all(entry.marker is None for entry in entries)
        assert entries[0].arxiv_id == "2012.05672"
        assert entries[1].year == 2017

    def test_a_doi_is_picked_up(self) -> None:
        entries = parse_references(
            "References\n[1] A Author. A title. Nature, 2015. doi:10.1038/nature14539.\n"
        )
        assert entries[0].doi == "10.1038/nature14539"

    def test_an_empty_section_yields_nothing(self) -> None:
        assert parse_references("References\n") == []
