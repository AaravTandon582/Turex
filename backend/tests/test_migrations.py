"""Migrations must be reversible, and reversible against real data.

The suite migrates from `base` every session, so an upgrade path is exercised constantly. A
*downgrade* is not, and one was broken for days without anything noticing: migration 0010 made
`correct_index` nullable so short-answer questions could exist, and its generated downgrade
restored NOT NULL — which fails on any database that holds one.

An empty database hides that entirely. These fill the tables first.
"""

from __future__ import annotations

import asyncio
import pathlib

from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from alembic import command

BACKEND = pathlib.Path(__file__).resolve().parents[1]


def alembic_config(database_url: str) -> Config:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


class TestReversibility:
    async def test_every_migration_reverses_with_data_in_the_tables(
        self, db: AsyncSession, settings
    ) -> None:
        """The case autogenerate cannot see.

        A generated downgrade is written against the schema, not against what is in it. This
        inserts a row that only the *new* schema permits — a question with no correct option —
        and then walks all the way down and back up.
        """
        await db.execute(
            text(
                """
                INSERT INTO users (id, email, full_name, password_hash)
                VALUES (gen_random_uuid(), 'downgrade@turex.test', 'Downgrade', 'x')
                """
            )
        )
        owner = await db.scalar(text("SELECT id FROM users WHERE email = 'downgrade@turex.test'"))
        await db.execute(
            text(
                """
                INSERT INTO papers
                    (id, owner_id, original_filename, storage_key, content_hash,
                     file_size_bytes, source, status, reading_status, authors, is_favorite)
                VALUES
                    (gen_random_uuid(), :owner, 'p.pdf', 'k', 'h', 1,
                     'upload', 'ready', 'unread', '[]'::jsonb, false)
                """
            ),
            {"owner": owner},
        )
        paper = await db.scalar(text("SELECT id FROM papers WHERE owner_id = :o"), {"o": owner})
        await db.execute(
            text(
                """
                INSERT INTO quizzes (id, owner_id, paper_id, title)
                VALUES (gen_random_uuid(), :owner, :paper, 'Reversibility')
                """
            ),
            {"owner": owner, "paper": paper},
        )
        quiz = await db.scalar(text("SELECT id FROM quizzes WHERE owner_id = :o"), {"o": owner})
        await db.execute(
            text(
                """
                INSERT INTO quiz_questions
                    (id, quiz_id, position, prompt, kind, options, correct_index,
                     explanation, source_text)
                VALUES
                    (gen_random_uuid(), :quiz, 0, 'Recall this.', 'short_answer',
                     '[]'::jsonb, NULL, 'because', 'passage')
                """
            ),
            {"quiz": quiz},
        )
        await db.commit()

        config = alembic_config(str(settings.database_url))

        # Alembic's env.py calls `asyncio.run`, which cannot nest inside this test's loop, so
        # the migrations run on a worker thread with a loop of their own.
        def migrate() -> None:
            command.downgrade(config, "base")
            command.upgrade(config, "head")

        await asyncio.to_thread(migrate)

    def test_every_revision_defines_a_downgrade(self) -> None:
        """A migration with `pass` for a downgrade is one nobody can undo, which is only
        discovered at the moment someone needs to."""
        empty = []
        for revision in sorted((BACKEND / "alembic" / "versions").glob("*.py")):
            source = revision.read_text()
            body = source.split("def downgrade()", 1)
            if len(body) < 2:
                empty.append(f"{revision.name}: no downgrade at all")
                continue
            statements = [
                line.strip()
                for line in body[1].splitlines()
                if line.strip() and not line.strip().startswith("#")
            ]
            meaningful = [line for line in statements[1:] if line not in {"pass", '"""', "..."}]
            if not meaningful:
                empty.append(f"{revision.name}: downgrade does nothing")
        assert not empty, empty
