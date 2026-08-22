"""A project as a folder of plain files.

The test of whether a research tool has kept your work is what happens when you stop using it.
So what is checked here is not that a zip was produced — it is that the files inside it are the
formats they claim to be, that they can be read without Turex, and that nothing in the project
is silently left behind.
"""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from datetime import UTC, datetime

import pytest

from turex.models.analysis import Analysis, AnalysisCell, CellKind, CellStatus
from turex.models.lab import GENESIS_HASH, LabEntry
from turex.models.paper import Paper, PaperSource
from turex.models.workspace import (
    Evidence,
    EvidenceStance,
    Experiment,
    ExperimentStatus,
    Hypothesis,
    HypothesisStatus,
    Note,
    Project,
)
from turex.services.project_bundle import build_bundle

PIXEL = (
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8"
    "BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _project() -> Project:
    return Project(
        id=uuid.uuid4(),
        owner_id=uuid.uuid4(),
        name="Retrieval vs parameters",
        research_question="Is retrieved knowledge more checkable than stored knowledge?",
        description="Comparing two ways of giving a model facts.",
    )


def _paper() -> Paper:
    return Paper(
        title="Attention Is All You Need",
        authors=[{"name": "Ashish Vaswani"}],
        publication_year=2017,
        arxiv_id="1706.03762",
        source=PaperSource.arxiv,
        original_filename="attention.pdf",
        storage_key="k",
        content_hash="h",
        file_size_bytes=1,
    )


def _analysis() -> Analysis:
    analysis = Analysis(id=uuid.uuid4(), owner_id=uuid.uuid4(), title="Latency analysis")
    analysis.cells = [
        AnalysisCell(
            id=uuid.uuid4(),
            ordinal=0,
            kind=CellKind.markdown,
            source="## Setup\nWhat this measures.",
            status=CellStatus.idle,
        ),
        AnalysisCell(
            id=uuid.uuid4(),
            ordinal=1,
            kind=CellKind.code,
            source="import numpy as np\nprint(np.mean([1, 2, 3]))",
            output="2.0\n",
            image=PIXEL,
            status=CellStatus.ok,
        ),
        AnalysisCell(
            id=uuid.uuid4(),
            ordinal=2,
            kind=CellKind.code,
            source="1 / 0",
            error="ZeroDivisionError: division by zero",
            status=CellStatus.error,
        ),
    ]
    return analysis


def _entries(count: int = 2) -> list[LabEntry]:
    entries: list[LabEntry] = []
    previous = GENESIS_HASH
    for index in range(1, count + 1):
        entry = LabEntry(
            id=uuid.uuid4(),
            owner_id=uuid.uuid4(),
            sequence=index,
            title=f"Run {index}",
            body=f"Observation {index}.",
            recorded_at=datetime.now(UTC),
            previous_hash=previous,
        )
        entry.entry_hash = entry.compute_hash()
        previous = entry.entry_hash
        entries.append(entry)
    return entries


@pytest.fixture
def bundle() -> zipfile.ZipFile:
    project = _project()
    hypothesis = Hypothesis(
        id=uuid.uuid4(),
        owner_id=project.owner_id,
        statement="Retrieval improves factual accuracy.",
        motivation="Parametric knowledge cannot be checked.",
        status=HypothesisStatus.testing,
    )
    evidence = Evidence(
        hypothesis_id=hypothesis.id,
        stance=EvidenceStance.supports,
        paper_title="Attention Is All You Need",
        locator="p. 3 · §Method",
        quoted_text="We propose the Transformer, based solely on attention mechanisms.",
        reasoning="Establishes the architecture the comparison uses.",
    )
    built = build_bundle(
        project,
        papers=[_paper()],
        notes=[
            Note(
                id=uuid.uuid4(),
                owner_id=project.owner_id,
                title="Results: 3/4 runs agree",
                content="# Findings\n\nThe cold start dominates.",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        ],
        hypotheses=[hypothesis],
        evidence={hypothesis.id: [evidence]},
        experiments=[
            Experiment(
                id=uuid.uuid4(),
                owner_id=project.owner_id,
                title="Cold versus warm cache",
                expected_result="No difference.",
                actual_result="A twofold difference.",
                status=ExperimentStatus.complete,
            )
        ],
        analyses=[_analysis()],
        entries=_entries(),
    )
    return zipfile.ZipFile(io.BytesIO(built.content))


def _read(bundle: zipfile.ZipFile, suffix: str) -> str:
    [name] = [n for n in bundle.namelist() if n.endswith(suffix)]
    return bundle.read(name).decode()


class TestTheFolderIsReadableWithoutTurex:
    def test_everything_in_the_project_is_present(self, bundle: zipfile.ZipFile) -> None:
        """A part left out is a part someone loses when they stop using this."""
        names = "\n".join(bundle.namelist())
        for expected in (
            "README.md",
            "references.bib",
            "references.ris",
            "references.json",
            "papers.md",
            "hypotheses.md",
            "experiments.md",
            "lab-notebook.md",
            "notes/",
            "analyses/",
        ):
            assert expected in names, f"{expected} missing from the bundle"

    def test_everything_sits_under_one_folder(self, bundle: zipfile.ZipFile) -> None:
        """Unzipping must not scatter files across the current directory."""
        roots = {name.split("/", 1)[0] for name in bundle.namelist()}
        assert len(roots) == 1

    def test_a_title_with_a_slash_does_not_become_a_directory(
        self, bundle: zipfile.ZipFile
    ) -> None:
        """The note is called "Results: 3/4 runs agree"."""
        [note] = [n for n in bundle.namelist() if "/notes/" in n]
        assert note.count("/") == 2, f"{note} has a path separator from its title"
        assert note.endswith(".md")

    def test_the_readme_says_what_each_part_is(self, bundle: zipfile.ZipFile) -> None:
        """An archive whose contents need explaining gets deleted by whoever inherits it."""
        readme = _read(bundle, "README.md")

        assert "Retrieval vs parameters" in readme
        assert "references.bib" in readme
        assert "pandoc" in readme

    def test_the_readme_counts_things_grammatically(self, bundle: zipfile.ZipFile) -> None:
        """A table that says "1 experiments" reads as unfinished."""
        readme = _read(bundle, "README.md")

        assert "1 paper," in readme
        assert "1 experiment," in readme
        assert "1 Jupyter notebook," in readme
        assert "1 hypothesis" in readme

    def test_the_readme_does_not_overclaim_what_the_hashes_prove(
        self, bundle: zipfile.ZipFile
    ) -> None:
        """The chain shows nothing was rewritten. It does not prove *when* anything happened,
        and a README that implied otherwise would be the dishonest part of this feature."""
        readme = _read(bundle, "README.md")
        assert "does **not** prove" in readme and "*when*" in readme


class TestTheFilesAreTheFormatsTheyClaim:
    def test_the_notebook_is_valid_nbformat(self, bundle: zipfile.ZipFile) -> None:
        notebook = json.loads(_read(bundle, ".ipynb"))

        assert notebook["nbformat"] == 4
        assert notebook["metadata"]["kernelspec"]["name"] == "python3"
        # nbformat 4.5 requires an id per cell and warns it will become a hard error.
        assert all(cell.get("id") for cell in notebook["cells"])

    def test_the_notebook_carries_its_output_so_it_reads_without_rerunning(
        self, bundle: zipfile.ZipFile
    ) -> None:
        notebook = json.loads(_read(bundle, ".ipynb"))
        code = [cell for cell in notebook["cells"] if cell["cell_type"] == "code"]

        streams = [o for cell in code for o in cell["outputs"] if o["output_type"] == "stream"]
        images = [o for cell in code for o in cell["outputs"] if o["output_type"] == "display_data"]
        assert "2.0\n" in "".join(streams[0]["text"])
        assert "image/png" in images[0]["data"]

    def test_a_failure_is_an_error_output_not_ordinary_text(self, bundle: zipfile.ZipFile) -> None:
        """A traceback presented as output reads as a result."""
        notebook = json.loads(_read(bundle, ".ipynb"))
        errors = [
            o
            for cell in notebook["cells"]
            for o in cell.get("outputs", [])
            if o["output_type"] == "error"
        ]
        assert errors and "ZeroDivisionError" in errors[0]["evalue"]

    def test_a_stale_cell_says_so_in_the_file(self, bundle: zipfile.ZipFile) -> None:
        """A number under code that has changed looks checked and is not — and that has to be
        visible in the exported file, not only inside Turex."""
        notebook = json.loads(_read(bundle, ".ipynb"))
        statuses = {
            cell["metadata"].get("turex", {}).get("status")
            for cell in notebook["cells"]
            if cell["cell_type"] == "code"
        }
        assert statuses == {"ok", "error"}

    def test_the_bibliography_is_bibtex_with_a_stable_key(self, bundle: zipfile.ZipFile) -> None:
        bib = _read(bundle, "references.bib")
        assert "@" in bib and "vaswani2017attention" in bib

    def test_csl_json_parses(self, bundle: zipfile.ZipFile) -> None:
        assert json.loads(_read(bundle, "references.json"))[0]["id"] == "vaswani2017attention"

    def test_notes_carry_front_matter_obsidian_and_quarto_read(
        self, bundle: zipfile.ZipFile
    ) -> None:
        note = _read(bundle, "runs-agree.md")
        assert note.startswith("---\n")
        assert 'title: "Results: 3/4 runs agree"' in note
        assert "# Findings" in note


class TestNothingIsInvented:
    def test_expected_and_actual_results_are_both_kept(self, bundle: zipfile.ZipFile) -> None:
        """Keeping both is the difference between an experiment and a story told afterwards."""
        experiments = _read(bundle, "experiments.md")
        assert "**Expected result**" in experiments and "No difference." in experiments
        assert "**Actual result**" in experiments and "A twofold difference." in experiments

    def test_evidence_keeps_its_quotation_and_its_locator(self, bundle: zipfile.ZipFile) -> None:
        """A paraphrase would break the link between the claim and its source."""
        hypotheses = _read(bundle, "hypotheses.md")
        assert "based solely on attention mechanisms" in hypotheses
        assert "p. 3 · §Method" in hypotheses

    def test_the_lab_notebook_carries_both_hashes(self, bundle: zipfile.ZipFile) -> None:
        """So the chain can be checked outside Turex. Evidence nobody can verify is not
        evidence."""
        notebook = _read(bundle, "lab-notebook.md")
        assert notebook.count("`hash ") == 2
        assert GENESIS_HASH in notebook

    def test_an_empty_project_still_produces_a_readable_folder(self) -> None:
        """A new project exports to something that explains itself rather than to a broken
        archive of empty files."""
        built = build_bundle(
            _project(),
            papers=[],
            notes=[],
            hypotheses=[],
            evidence={},
            experiments=[],
            analyses=[],
            entries=[],
        )
        archive = zipfile.ZipFile(io.BytesIO(built.content))

        assert "_None recorded._" in _read(archive, "hypotheses.md")
        assert "_No entries._" in _read(archive, "lab-notebook.md")
        assert _read(archive, "references.bib") == ""
