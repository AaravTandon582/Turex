"""Reader tests: highlights, notes, and citation export.

Citation formatting gets close attention because it is a place where being *plausibly* wrong
is worse than being visibly incomplete — a bibliography entry with an invented year gets
pasted, submitted, and only caught by a reviewer.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.support.pdf_builder import build_paper_pdf
from turex.models.paper import Paper
from turex.services.citations import CitationStyle, format_all, to_apa, to_bibtex, to_mla


def make_paper(**overrides: object) -> Paper:
    """A paper with full metadata, for exercising the formatters directly."""
    defaults: dict[str, object] = {
        "title": "Attention Is All You Need",
        "authors": [
            {"name": "Ashish Vaswani"},
            {"name": "Noam Shazeer"},
            {"name": "Niki Parmar"},
        ],
        "publication_year": 2017,
        "venue": "Advances in Neural Information Processing Systems",
        "doi": "10.5555/3295222.3295349",
        "arxiv_id": "1706.03762",
        "original_filename": "attention.pdf",
    }
    return Paper(**{**defaults, **overrides})  # type: ignore[arg-type]


async def upload(client: AsyncClient, api: str) -> str:
    response = await client.post(
        f"{api}/papers", files={"file": ("paper.pdf", build_paper_pdf(), "application/pdf")}
    )
    assert response.status_code == 202, response.text
    return response.json()["id"]


class TestBibtex:
    def test_produces_a_conventional_key(self) -> None:
        assert "@article{vaswani2017attention," in to_bibtex(make_paper()).text

    def test_braces_the_title_to_preserve_capitalisation(self) -> None:
        """Without braces, most BibTeX styles lowercase acronyms and proper nouns."""
        assert "title = {{Attention Is All You Need}}" in to_bibtex(make_paper()).text

    def test_joins_authors_the_way_bibtex_expects(self) -> None:
        text = to_bibtex(make_paper()).text
        assert "Vaswani, Ashish and Shazeer, Noam" in text

    def test_falls_back_to_misc_without_a_venue_or_doi(self) -> None:
        paper = make_paper(venue=None, doi=None)
        assert to_bibtex(paper).text.startswith("@misc{")

    def test_handles_an_accented_surname(self) -> None:
        paper = make_paper(authors=[{"name": "Heinrich Küttler"}])
        assert "kuttler2017" in to_bibtex(paper).text

    def test_never_invents_a_missing_field(self) -> None:
        paper = make_paper(publication_year=None, venue=None)
        text = to_bibtex(paper).text

        assert "year" not in text
        assert "journal" not in text
        assert "nd" in text  # the key marks the unknown date rather than guessing one


class TestApa:
    def test_formats_authors_as_family_then_initials(self) -> None:
        assert to_apa(make_paper()).text.startswith("Vaswani, A., Shazeer, N., & Parmar, N.")

    def test_closes_the_date_element_with_a_period(self) -> None:
        assert "(2017). Attention Is All You Need." in to_apa(make_paper()).text

    def test_marks_an_unknown_date(self) -> None:
        """`n.d.` is the standard marker. Omitting the year silently would read as an error."""
        assert "(n.d.)." in to_apa(make_paper(publication_year=None)).text

    def test_prefers_a_doi_over_an_arxiv_identifier(self) -> None:
        assert "https://doi.org/10.5555" in to_apa(make_paper()).text

    def test_falls_back_to_arxiv_without_a_doi(self) -> None:
        assert "arXiv:1706.03762" in to_apa(make_paper(doi=None)).text


class TestMla:
    def test_uses_et_al_for_three_or_more_authors(self) -> None:
        assert to_mla(make_paper()).text.startswith("Vaswani, Ashish, et al.")

    def test_names_both_of_two_authors(self) -> None:
        paper = make_paper(authors=[{"name": "Ada Lovelace"}, {"name": "Charles Babbage"}])
        assert to_mla(paper).text.startswith("Lovelace, Ada, and Charles Babbage.")

    def test_quotes_the_title(self) -> None:
        assert '"Attention Is All You Need."' in to_mla(make_paper()).text


class TestMissingMetadata:
    def test_reports_what_each_style_needs(self) -> None:
        """The UI prompts for these rather than letting a gap reach a bibliography."""
        paper = make_paper(title=None, publication_year=None, authors=[])

        for formatted in format_all(paper):
            assert set(formatted.missing_fields) >= {"title", "authors", "year"}

    def test_a_complete_paper_reports_no_gaps(self) -> None:
        assert to_apa(make_paper()).missing_fields == []

    def test_falls_back_to_the_filename_when_there_is_no_title(self) -> None:
        assert "attention.pdf" in to_apa(make_paper(title=None)).text

    @pytest.mark.parametrize("style", list(CitationStyle))
    def test_every_style_survives_empty_metadata(self, style: CitationStyle) -> None:
        """A paper mid-ingestion has almost nothing. Formatting must not raise."""
        bare = Paper(title=None, authors=[], original_filename="unknown.pdf")
        formatted = next(f for f in format_all(bare) if f.style is style)
        assert formatted.text.strip()


class TestCitationEndpoint:
    async def test_returns_every_style(
        self,
        registered_client: AsyncClient,
        api: str,
        run_worker,  # type: ignore[no-untyped-def]
    ) -> None:
        paper_id = await upload(registered_client, api)
        await run_worker()

        body = (await registered_client.get(f"{api}/papers/{paper_id}/citations")).json()

        assert {entry["style"] for entry in body["formats"]} == {"bibtex", "apa", "mla"}
        assert all(entry["text"].strip() for entry in body["formats"])

    async def test_another_user_cannot_export_a_citation(
        self, registered_client: AsyncClient, other_client: AsyncClient, api: str
    ) -> None:
        paper_id = await upload(registered_client, api)
        assert (await other_client.get(f"{api}/papers/{paper_id}/citations")).status_code == 404


class TestAnnotations:
    async def test_creates_a_highlight(self, registered_client: AsyncClient, api: str) -> None:
        paper_id = await upload(registered_client, api)

        response = await registered_client.post(
            f"{api}/papers/{paper_id}/annotations",
            json={
                "page_number": 1,
                "text_offset": 120,
                "selected_text": "the thing works",
                "colour": "result",
            },
        )

        assert response.status_code == 201
        body = response.json()
        assert body["selected_text"] == "the thing works"
        assert body["text_length"] == len("the thing works")
        assert body["colour"] == "result"

    async def test_stores_a_note_with_a_highlight(
        self, registered_client: AsyncClient, api: str
    ) -> None:
        paper_id = await upload(registered_client, api)

        body = (
            await registered_client.post(
                f"{api}/papers/{paper_id}/annotations",
                json={
                    "page_number": 2,
                    "text_offset": 0,
                    "selected_text": "Accuracy improved",
                    "note": "Compared against what baseline?",
                },
            )
        ).json()

        assert body["note"] == "Compared against what baseline?"

    async def test_lists_in_reading_order(self, registered_client: AsyncClient, api: str) -> None:
        """Page then position: the order a reader encounters them."""
        paper_id = await upload(registered_client, api)
        for page, offset in [(2, 50), (1, 300), (1, 10)]:
            await registered_client.post(
                f"{api}/papers/{paper_id}/annotations",
                json={
                    "page_number": page,
                    "text_offset": offset,
                    "selected_text": f"passage {page}-{offset}",
                },
            )

        listed = (await registered_client.get(f"{api}/papers/{paper_id}/annotations")).json()

        assert [(a["page_number"], a["text_offset"]) for a in listed] == [
            (1, 10),
            (1, 300),
            (2, 50),
        ]

    async def test_rejects_a_page_beyond_the_document(
        self,
        registered_client: AsyncClient,
        api: str,
        run_worker,  # type: ignore[no-untyped-def]
    ) -> None:
        paper_id = await upload(registered_client, api)
        await run_worker()  # page_count is only known after parsing

        response = await registered_client.post(
            f"{api}/papers/{paper_id}/annotations",
            json={"page_number": 999, "text_offset": 0, "selected_text": "nowhere"},
        )

        assert response.status_code == 422

    async def test_rejects_an_empty_selection(
        self, registered_client: AsyncClient, api: str
    ) -> None:
        paper_id = await upload(registered_client, api)
        response = await registered_client.post(
            f"{api}/papers/{paper_id}/annotations",
            json={"page_number": 1, "text_offset": 0, "selected_text": "   "},
        )
        assert response.status_code == 422

    async def test_updates_colour_and_note(self, registered_client: AsyncClient, api: str) -> None:
        paper_id = await upload(registered_client, api)
        annotation_id = (
            await registered_client.post(
                f"{api}/papers/{paper_id}/annotations",
                json={"page_number": 1, "text_offset": 0, "selected_text": "a passage"},
            )
        ).json()["id"]

        body = (
            await registered_client.patch(
                f"{api}/annotations/{annotation_id}",
                json={"colour": "question", "note": "Why this baseline?"},
            )
        ).json()

        assert body["colour"] == "question"
        assert body["note"] == "Why this baseline?"

    async def test_clearing_a_note_is_explicit(
        self, registered_client: AsyncClient, api: str
    ) -> None:
        """An absent `note` leaves it alone; removing it needs `clear_note`."""
        paper_id = await upload(registered_client, api)
        annotation_id = (
            await registered_client.post(
                f"{api}/papers/{paper_id}/annotations",
                json={
                    "page_number": 1,
                    "text_offset": 0,
                    "selected_text": "a passage",
                    "note": "original",
                },
            )
        ).json()["id"]

        unchanged = (
            await registered_client.patch(
                f"{api}/annotations/{annotation_id}", json={"colour": "method"}
            )
        ).json()
        assert unchanged["note"] == "original"

        cleared = (
            await registered_client.patch(
                f"{api}/annotations/{annotation_id}", json={"clear_note": True}
            )
        ).json()
        assert cleared["note"] is None

    async def test_deletes(self, registered_client: AsyncClient, api: str) -> None:
        paper_id = await upload(registered_client, api)
        annotation_id = (
            await registered_client.post(
                f"{api}/papers/{paper_id}/annotations",
                json={"page_number": 1, "text_offset": 0, "selected_text": "a passage"},
            )
        ).json()["id"]

        assert (
            await registered_client.delete(f"{api}/annotations/{annotation_id}")
        ).status_code == 204
        assert (await registered_client.get(f"{api}/papers/{paper_id}/annotations")).json() == []

    async def test_deleting_a_paper_removes_its_highlights(
        self, registered_client: AsyncClient, api: str
    ) -> None:
        paper_id = await upload(registered_client, api)
        await registered_client.post(
            f"{api}/papers/{paper_id}/annotations",
            json={"page_number": 1, "text_offset": 0, "selected_text": "a passage"},
        )

        await registered_client.delete(f"{api}/papers/{paper_id}")

        assert (
            await registered_client.get(f"{api}/papers/{paper_id}/annotations")
        ).status_code == 404


class TestAnnotationPrivacy:
    async def test_another_user_cannot_read_highlights(
        self, registered_client: AsyncClient, other_client: AsyncClient, api: str
    ) -> None:
        paper_id = await upload(registered_client, api)
        await registered_client.post(
            f"{api}/papers/{paper_id}/annotations",
            json={"page_number": 1, "text_offset": 0, "selected_text": "private thought"},
        )

        assert (await other_client.get(f"{api}/papers/{paper_id}/annotations")).status_code == 404

    async def test_another_user_cannot_edit_a_highlight(
        self, registered_client: AsyncClient, other_client: AsyncClient, api: str
    ) -> None:
        paper_id = await upload(registered_client, api)
        annotation_id = (
            await registered_client.post(
                f"{api}/papers/{paper_id}/annotations",
                json={"page_number": 1, "text_offset": 0, "selected_text": "private"},
            )
        ).json()["id"]

        response = await other_client.patch(
            f"{api}/annotations/{annotation_id}", json={"note": "tampered"}
        )
        assert response.status_code == 404
