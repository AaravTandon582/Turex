"""Getting a library in and out in formats other tools read.

A research tool that can only be read from inside itself is a liability, so the property that
matters most here is the **round trip**: what Turex writes, Turex can read back. That is not a
tautology — the first version could not. Its exporter wrote arXiv ids into RIS as
`https://arxiv.org/abs/…` and its importer only recognised a bare `arXiv:` prefix, so sixteen
of nineteen entries came back with no identifier and would have been silently unimportable.

The other rule with teeth: nothing is invented. A paper with no year exports with no year,
because a bibliography entry with a guessed date looks finished and gets pasted into a
manuscript unchecked.
"""

from __future__ import annotations

import json

import pytest

from turex.ingestion.bibliography import parse_bibliography, parse_bibtex, parse_ris
from turex.models.paper import Paper, PaperSource
from turex.services.library_export import ExportFormat, export_papers


def _paper(**overrides: object) -> Paper:
    """A paper with only the fields citation formats read."""
    defaults: dict[str, object] = {
        "title": "Attention Is All You Need",
        "authors": [{"name": "Ashish Vaswani"}, {"name": "Noam Shazeer"}],
        "publication_year": 2017,
        "venue": None,
        "doi": None,
        "arxiv_id": "1706.03762",
        "abstract": None,
        "source": PaperSource.arxiv,
        "source_url": None,
        "original_filename": "attention.pdf",
        "storage_key": "k",
        "content_hash": "h",
        "file_size_bytes": 1,
    }
    return Paper(**(defaults | overrides))  # type: ignore[arg-type]


class TestRoundTrip:
    """What Turex writes, Turex reads back. The property the first version did not have."""

    @pytest.mark.parametrize("fmt", [ExportFormat.bibtex, ExportFormat.ris])
    def test_an_arxiv_paper_survives_export_and_reimport(self, fmt: ExportFormat) -> None:
        text = export_papers([_paper()], fmt)
        [entry] = parse_bibliography(text).entries

        assert entry.identifier == "1706.03762", f"{fmt} lost the identifier"
        assert entry.year == 2017

    @pytest.mark.parametrize("fmt", [ExportFormat.bibtex, ExportFormat.ris])
    def test_a_doi_paper_survives_export_and_reimport(self, fmt: ExportFormat) -> None:
        paper = _paper(arxiv_id=None, doi="10.1038/nature14539", venue="Nature")
        [entry] = parse_bibliography(export_papers([paper], fmt)).entries

        assert entry.identifier == "10.1038/nature14539"

    def test_a_whole_library_round_trips_without_losing_one(self) -> None:
        papers = [
            _paper(title=f"Paper {index}", arxiv_id=f"2101.{index:05d}") for index in range(25)
        ]
        parsed = parse_bibliography(export_papers(papers, ExportFormat.ris))

        assert len(parsed.entries) == 25
        assert parsed.skipped == 0
        assert {entry.identifier for entry in parsed.entries} == {
            f"2101.{index:05d}" for index in range(25)
        }


class TestExportShape:
    def test_bibtex_keys_are_stable_across_exports(self) -> None:
        """A `\\cite{}` written last year has to still resolve after a re-export, which is the
        only reason a manuscript can survive its bibliography being regenerated."""
        first = export_papers([_paper()], ExportFormat.bibtex)
        second = export_papers([_paper()], ExportFormat.bibtex)
        assert first == second
        assert "vaswani2017attention" in first

    def test_ris_uses_the_two_space_separator_importers_expect(self) -> None:
        """Several importers parse by column position and silently drop a single-space tag."""
        text = export_papers([_paper()], ExportFormat.ris)
        assert text.startswith("TY  - ")
        assert "\nER  - " in text
        assert "TY - " not in text

    def test_csl_json_is_what_pandoc_reads(self) -> None:
        entries = json.loads(export_papers([_paper()], ExportFormat.csl))
        [entry] = entries

        assert entry["id"] == "vaswani2017attention"
        assert entry["issued"] == {"date-parts": [[2017]]}
        assert entry["author"][0] == {"family": "Vaswani", "given": "Ashish"}

    def test_a_name_that_does_not_split_is_kept_whole(self) -> None:
        """CSL's `literal` exists for collaborations and mononyms. Inventing a surname for
        "ATLAS Collaboration" would put a wrong name in a bibliography."""
        paper = _paper(authors=[{"name": "ATLAS Collaboration"}])
        [entry] = json.loads(export_papers([paper], ExportFormat.csl))
        assert entry["author"][0] == {"literal": "ATLAS Collaboration"}

    def test_a_preprint_is_not_claimed_as_a_journal_article(self) -> None:
        """Turex knows this paper has no venue. Saying `article-journal` would assert a
        publication that has not happened."""
        [entry] = json.loads(export_papers([_paper(venue=None)], ExportFormat.csl))
        assert entry["type"] == "manuscript"

        [published] = json.loads(export_papers([_paper(venue="NeurIPS")], ExportFormat.csl))
        assert published["type"] == "article-journal"

    def test_a_missing_year_is_absent_rather_than_guessed(self) -> None:
        [entry] = json.loads(export_papers([_paper(publication_year=None)], ExportFormat.csl))
        assert "issued" not in entry

    @pytest.mark.parametrize("fmt", list(ExportFormat))
    def test_an_empty_library_exports_a_valid_empty_file(self, fmt: ExportFormat) -> None:
        text = export_papers([], fmt)
        if fmt is ExportFormat.csl:
            assert json.loads(text) == []
        else:
            assert text.strip() == ""


class TestReadingOtherTools:
    def test_a_zotero_bibtex_export_is_understood(self) -> None:
        text = """
        @article{lecun2015deep,
          title = {Deep learning},
          author = {LeCun, Yann and Bengio, Yoshua and Hinton, Geoffrey},
          journal = {Nature},
          year = {2015},
          doi = {10.1038/nature14539}
        }
        """
        [entry] = parse_bibtex(text).entries

        assert entry.title == "Deep learning"
        assert entry.authors == ["LeCun, Yann", "Bengio, Yoshua", "Hinton, Geoffrey"]
        assert entry.year == 2015
        assert entry.identifier == "10.1038/nature14539"

    def test_protective_braces_are_removed_from_values(self) -> None:
        """`{BERT}` is protection against a style lowercasing it, not part of the title."""
        [entry] = parse_bibtex("@article{a, title = {{BERT}: Pre-training}, year={2019}}").entries
        assert entry.title == "BERT: Pre-training"

    def test_an_entry_body_containing_braces_does_not_swallow_the_next_one(self) -> None:
        """A lazy regex stops at the first `}` inside a title and a greedy one eats the file,
        which is why entries are split by counting brace depth."""
        text = (
            "@article{a, title = {A {nested} title}, eprint={1111.1111}}\n"
            "@article{b, eprint={2222.2222}}"
        )
        entries = parse_bibtex(text).entries

        assert [entry.identifier for entry in entries] == ["1111.1111", "2222.2222"]

    def test_bibtex_macros_are_not_mistaken_for_references(self) -> None:
        text = '@string{nips = "NeurIPS"}\n@comment{ignore me}\n@article{a, eprint={1234.5678}}'
        assert len(parse_bibtex(text).entries) == 1

    def test_a_truncated_file_yields_what_it_can(self) -> None:
        """Half a download is a real thing to receive, and the complete entries in it are
        still worth having."""
        text = "@article{a, eprint={1111.1111}}\n@article{b, title = {unterminated"
        assert [entry.identifier for entry in parse_bibtex(text).entries] == ["1111.1111"]

    def test_a_wrapped_ris_abstract_keeps_its_continuation_lines(self) -> None:
        text = (
            "TY  - JOUR\nTI  - Residual Learning\n"
            "AB  - Deeper networks are harder to train. We\n"
            "      present a residual framework.\n"
            "DO  - 10.1109/CVPR.2016.90\nER  - \n"
        )
        [entry] = parse_ris(text).entries
        assert entry.identifier == "10.1109/CVPR.2016.90"

    def test_a_final_record_with_no_terminator_is_still_read(self) -> None:
        assert len(parse_ris("TY  - JOUR\nTI  - X\nDO  - 10.1/x\n").entries) == 1

    def test_an_entry_with_no_identifier_is_counted_not_dropped(self) -> None:
        """ "42 of 60 imported" needs the other eighteen explained."""
        parsed = parse_bibtex("@book{a, title = {A book}, author = {Nobody}, year = {2020}}")

        assert len(parsed.entries) == 1
        assert parsed.skipped == 1
        assert parsed.entries[0].identifier is None

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("UR  - https://arxiv.org/abs/2512.01093", "2512.01093"),
            ("UR  - https://arxiv.org/pdf/1706.03762", "1706.03762"),
            ("N1  - arXiv:1412.6980", "1412.6980"),
            ("UR  - https://arxiv.org/abs/cs/0508010", "cs/0508010"),
        ],
    )
    def test_every_form_an_arxiv_id_arrives_in(self, text: str, expected: str) -> None:
        """The URL form is the one Turex's own RIS export writes, and the one the importer
        originally could not read."""
        [entry] = parse_ris(f"TY  - JOUR\nTI  - X\n{text}\nER  - \n").entries
        assert entry.identifier == expected


class TestFormatDetection:
    def test_the_contents_decide_rather_than_the_name(self) -> None:
        """A file's name is whatever someone typed."""
        bib = "@article{a, eprint={1234.5678}}"
        assert parse_bibliography(bib, filename="library.ris").entries[0].identifier == "1234.5678"

        ris = "TY  - JOUR\nDO  - 10.1/x\nER  - \n"
        assert parse_bibliography(ris, filename="library.bib").entries[0].identifier == "10.1/x"
