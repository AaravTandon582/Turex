"""The catalog: papers Atlas knows about but has not read.

There are two distinct things a research workspace calls a "paper", and conflating them puts a
hard ceiling on how many papers it can hold.

A **library paper** is one this user has: the PDF is stored, the text is parsed into sections,
the sections are chunked, and every chunk carries an embedding. That is what makes the reader,
the assistant, and citation grounding possible, and it costs roughly a megabyte of disk and
fifty embedding calls per paper. Half a million of those is half a terabyte and twenty-five
million embedding calls. It is not a design that scales, and no amount of tuning makes it one.

A **catalog paper** is one Atlas knows exists: title, authors, abstract, categories, dates, and
where to get the file. About two kilobytes, no network calls, no model calls. Millions fit
comfortably, and an abstract is enough to search on — it is what a researcher scans to decide
whether a paper is worth opening, and it is what every literature-search tool actually indexes.

So the catalog is the wide, shallow half and the library is the narrow, deep half, and
`import` is the bridge: choosing a catalog paper fetches the real PDF and runs the ordinary
ingestion pipeline, producing a library paper indistinguishable from an uploaded one. Nothing
is faked in the process — a catalog entry never pretends to have full text it does not have,
and the assistant can only cite chunks, which only library papers possess.

The table is deliberately **not** owner-scoped, which makes it the only one in the schema that
is not. arXiv's metadata is the same for everybody, and a per-user copy would multiply
millions of rows by the number of accounts to store identical bytes. What a user *does* with
the catalog — importing a paper — lands in their own owner-scoped library, and that is where
the isolation boundary belongs.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, DateTime, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from atlas.db.base import Base, UUIDPrimaryKeyMixin


class CatalogPaper(UUIDPrimaryKeyMixin, Base):
    """One paper's metadata, harvested from a public index.

    `TimestampMixin` is deliberately not used. It carries an `updated_at` that SQLAlchemy sets
    per row on update, and harvesting writes in batches of a thousand through a single bulk
    upsert statement — there is no per-row Python step for it to hook. `harvested_at` is set
    by the same statement instead, which is the same information for a fraction of the work.
    """

    __tablename__ = "catalog_papers"
    __table_args__ = (
        # The search index. GIN over a stored tsvector of title and abstract: this is the one
        # index that has to stay fast as the table grows past a million rows, and it is why
        # search here is lexical rather than vector. Embedding a million abstracts would take
        # days of API calls and is not something a free key can do; a GIN index is built once
        # and answers ranked queries over millions of documents in milliseconds.
        Index("ix_catalog_papers_search_tsv", "search_tsv", postgresql_using="gin"),
        # Browsing by field and by recency, which is what the Discover page does before the
        # reader has typed anything.
        Index(
            "ix_catalog_papers_primary_category_published_on", "primary_category", "published_on"
        ),
        Index("ix_catalog_papers_published_on", "published_on"),
        # Filtering by category uses JSONB containment (`categories @> '["cs.LG"]'`) rather
        # than a match on `primary_category`, so a paper cross-listed into cs.LG is found when
        # someone browses cs.LG — which is what a reader means by the category. `jsonb_path_ops`
        # indexes only the containment operator, which makes it markedly smaller and faster
        # than the default operator class, and containment is the only thing asked of it here.
        Index(
            "ix_catalog_papers_categories",
            "categories",
            postgresql_using="gin",
            postgresql_ops={"categories": "jsonb_path_ops"},
        ),
    )

    arxiv_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    """Bare and version-less — `2103.14030`, not `2103.14030v2`.

    Unique because it is the natural key: a harvest run that overlaps a previous one must
    update the existing row rather than insert a second copy of the same paper. arXiv's
    incremental feed re-sends any paper whose metadata changed, so overlap is the normal case,
    not an edge one.
    """

    doi: Mapped[str | None] = mapped_column(String(255), index=True)

    title: Mapped[str] = mapped_column(Text, nullable=False)
    abstract: Mapped[str | None] = mapped_column(Text)

    authors: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    """`[{"name": "Ashish Vaswani"}, …]`, in the order the paper lists them.

    JSONB rather than a join table. An author here is a display string with no identity that
    can be relied upon — arXiv does not disambiguate people, so two "J. Smith" entries may or
    may not be the same person, and a table of author rows would assert an identity the source
    data does not support. The `Paper` model stores authors the same way, which also means
    importing copies the value straight across.
    """

    categories: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default="[]")
    """Every arXiv category, e.g. `["cs.CL", "cs.LG"]`."""

    primary_category: Mapped[str | None] = mapped_column(String(32))
    """The first, which is the one arXiv treats as the paper's home. Indexed for browsing."""

    journal_ref: Mapped[str | None] = mapped_column(Text)
    comments: Mapped[str | None] = mapped_column(Text)

    published_on: Mapped[date | None] = mapped_column(Date)
    updated_on: Mapped[date | None] = mapped_column(Date)

    search_tsv: Mapped[str] = mapped_column(
        TSVECTOR,
        nullable=False,
    )
    """Title and abstract, weighted, maintained by a database trigger.

    Not a `Computed` column, which is what `PaperChunk.content_tsv` uses. A generated column
    in PostgreSQL may only reference the row it belongs to through *immutable* expressions,
    and `setweight(to_tsvector(...))` over two columns is not accepted there. A trigger does
    the same job with the same guarantee that matters: application code cannot forget to
    update it, because application code never writes it at all.

    Title is weight A and abstract weight B, so a paper whose *title* is about diffusion
    models outranks one that mentions them once in passing. That single distinction is most of
    what makes ranked search over abstracts feel deliberate rather than arbitrary.
    """

    harvested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    @property
    def pdf_url(self) -> str:
        """Where the file is, if the reader chooses to import it.

        Derived rather than stored: it is a pure function of the id, and a stored copy is one
        more thing that can disagree with it.
        """
        return f"https://arxiv.org/pdf/{self.arxiv_id}"

    @property
    def abs_url(self) -> str:
        return f"https://arxiv.org/abs/{self.arxiv_id}"
