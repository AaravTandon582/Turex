"""Fill the catalog from OpenAlex — the papers arXiv does not have.

    python -m scripts.harvest_openalex --filter "topics.id:T10017" --max-records 50000
    python -m scripts.harvest_openalex --search "crispr gene editing" --max-records 20000
    python -m scripts.harvest_openalex --filter "publication_year:2024,has_abstract:true"

arXiv is preprints, and overwhelmingly physics, mathematics and computer science. OpenAlex
indexes over a hundred million works across every field — medicine, chemistry, biology, the
humanities — free and without a key.

A hundred million rows is roughly three hundred gigabytes, so this harvests **slices** rather
than everything, and which slices is your decision. Useful filters:

    has_abstract:true                       skip records with nothing to search
    publication_year:>2015                  recent work only
    primary_topic.field.id:fields/27        medicine (see the OpenAlex fields list)
    open_access.is_oa:true                  only papers Atlas can actually fetch
    type:article                            exclude datasets, theses, and errata

Combine them with commas. `--search` matches words in the title and abstract, and can be used
alongside a filter.

Identify yourself with --mailto: OpenAlex gives named clients a faster queue, and free
services stay free partly because heavy users say who they are.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import signal
import sys
import time
from pathlib import Path

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from atlas.catalog.harvest import MINIMUM_FREE_BYTES, analyze_catalog, count_catalog, free_bytes
from atlas.catalog.openalex import OpenAlexHarvester, count_openalex, store_works
from atlas.catalog.records import HarvestError
from atlas.core.config import get_settings
from atlas.db.session import dispose_engine, get_session_factory, init_engine

CURSOR_FILE = Path(".openalex-cursor")
"""Where a stopped run resumes from. Same reasoning as the arXiv token: an hour of harvesting
should survive a dropped connection."""

USER_AGENT = "Atlas/1.0 (research workspace)"


def _arguments() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="harvest_openalex",
        description="Fill the Atlas catalog from OpenAlex.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--filter", dest="filters", help="an OpenAlex filter expression")
    parser.add_argument("--search", help="words to match in the title and abstract")
    parser.add_argument("--max-records", type=int, help="stop after roughly this many works")
    parser.add_argument("--resume", help="a cursor from an earlier run")
    parser.add_argument(
        "--mailto",
        help="your email, for OpenAlex's polite pool (faster and more reliable)",
    )
    return parser


async def main() -> int:
    args = _arguments().parse_args()
    if not args.filters and not args.search:
        print(
            "Give --filter or --search. Harvesting all 100M+ works would need about 300GB.",
            file=sys.stderr,
        )
        return 2

    init_engine(get_settings())
    sessions = get_session_factory()

    stopping = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stopping.set)

    try:
        return await _run(args, sessions, stopping)
    finally:
        await dispose_engine()


async def _run(
    args: argparse.Namespace,
    sessions: async_sessionmaker[AsyncSession],
    stopping: asyncio.Event,
) -> int:
    async with sessions() as db:
        before = await count_catalog(db)
        print(f"catalog holds {before:,} papers ({await count_openalex(db):,} from OpenAlex)")
        print(f"harvesting {args.filters or ''} {args.search or ''}".strip())
        print()

        started = time.monotonic()
        seen = inserted = updated = pages = 0
        cursor = args.resume

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(120.0, connect=30.0),
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            harvester = OpenAlexHarvester(client, mailto=args.mailto)
            try:
                async for records, next_cursor, total in harvester.pages(
                    query=args.search, filters=args.filters, resume_from=args.resume
                ):
                    new, corrected = await store_works(db, records)
                    seen += len(records)
                    inserted += new
                    updated += corrected
                    pages += 1
                    cursor = next_cursor

                    if next_cursor:
                        CURSOR_FILE.write_text(next_cursor)
                    else:
                        CURSOR_FILE.unlink(missing_ok=True)

                    elapsed = max(time.monotonic() - started, 1e-6)
                    line = (
                        f"  {seen:>9,} works  ({inserted:,} new, {updated:,} updated)  "
                        f"{pages:>5,} pages  {seen / elapsed:>6.0f}/s"
                    )
                    if total:
                        line += f"  of {total:,}"
                    print(line.ljust(100), end="\r", flush=True)

                    if pages % 50 == 0:
                        await analyze_catalog(db)

                    if free_bytes() < MINIMUM_FREE_BYTES:
                        await analyze_catalog(db)
                        print(
                            f"\n\nstopping with {free_bytes() / 1e9:.1f}GB free — below the floor",
                            file=sys.stderr,
                        )
                        return 1

                    if stopping.is_set():
                        print("\n\nstopped — everything harvested so far is saved")
                        break

                    if args.max_records is not None and seen >= args.max_records:
                        print(f"\n\nreached the {args.max_records:,} record limit")
                        break
            except HarvestError as exc:
                await analyze_catalog(db)
                print(f"\n\nthe harvest stopped: {exc}", file=sys.stderr)
                if cursor:
                    print(f'resume with: --resume "$(cat {CURSOR_FILE})"', file=sys.stderr)
                return 1

        await analyze_catalog(db)
        after = await count_catalog(db)
        elapsed = time.monotonic() - started

    print(f"\n{after:,} papers in the catalog ({after - before:+,}) in {elapsed / 60:.1f} min")
    if CURSOR_FILE.exists() and CURSOR_FILE.read_text().strip():
        print(f'more remains — continue with: --resume "$(cat {CURSOR_FILE})"')
    else:
        print("the selection is complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
