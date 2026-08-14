"""Alembic environment.

The database URL is read from application settings rather than alembic.ini, so migrations and
the running application can never disagree about which database they mean.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from pgvector.sqlalchemy import Vector
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from atlas.core.config import get_settings
from atlas.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Fall back to application settings, but let a caller that already set the URL win — the test
# suite points Alembic at the test database this way.
if not config.get_main_option("sqlalchemy.url", default=None):
    config.set_main_option("sqlalchemy.url", str(get_settings().database_url))


def _render_item(type_: str, obj: object, autogen_context: object) -> str | bool:
    """Emit pgvector column types with the import they need.

    Autogenerate renders third-party types by their fully-qualified path but does not add the
    import, producing a migration that raises NameError the first time it runs. Registering the
    import here fixes it for every migration rather than one at a time.
    """
    if type_ == "type" and isinstance(obj, Vector):
        autogen_context.imports.add("import pgvector.sqlalchemy")  # type: ignore[attr-defined]
        return f"pgvector.sqlalchemy.Vector(dim={obj.dim})"
    return False


def _configure(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        render_item=_render_item,
        # Keep pgvector's own catalog objects out of autogenerate diffs.
        include_object=lambda obj, name, type_, reflected, compare_to: (
            not (type_ == "table" and name in {"vector", "spatial_ref_sys"})
        ),
    )


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run(connection: Connection) -> None:
    _configure(connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(_run)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
