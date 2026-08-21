"""Fill the catalog from arXiv.

    python -m scripts.harvest_arxiv --set cs --max-records 100000
    python -m scripts.harvest_arxiv --since 2026-01-01
    python -m scripts.harvest_arxiv --resume "$(cat .harvest-token)"

Measured, not estimated: 1,300 papers per request, ~66 papers a second once the mandatory
three-second spacing is counted, and 3.4KB of database each.

    100,000 papers    ~25 minutes     ~340MB
    500,000 papers    ~2 hours        ~1.7GB
  2,600,000 papers    ~11 hours       ~8.7GB     (all of arXiv)

Run `df -h` before the last one. Filling a disk mid-harvest is recoverable — pages are already
committed — but everything else on the machine stops working first.

Stopping is safe at any moment. Every page is committed as it lands, and the token printed on
exit resumes exactly where it stopped — it is also written to `.harvest-token` so a resume does
not depend on the terminal scrollback still being there.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import signal
import sys
import time
from datetime import date
from pathlib import Path

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from atlas.catalog.harvest import (
    MINIMUM_DELAY_SECONDS,
    ArxivHarvester,
    HarvestProgress,
    analyze_catalog,
    count_catalog,
    harvest,
)
from atlas.catalog.records import HarvestError
from atlas.core.config import get_settings
from atlas.db.session import dispose_engine, get_session_factory, init_engine

TOKEN_FILE = Path(".harvest-token")

USER_AGENT = "Atlas/1.0 (research workspace; +https://github.com/atlas)"
"""arXiv asks automated clients to identify themselves. A request without this is the kind
that gets an IP blocked, and being blocked is indistinguishable from the service being down.
"""


def _parse_date(raw: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:  # pragma: no cover - argparse renders this
        raise argparse.ArgumentTypeError(f"{raw!r} is not a date like 2026-01-31") from exc


def _arguments() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="harvest_arxiv",
        description="Fill the Atlas catalog with paper metadata from arXiv.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Sets are arXiv's top-level archives: cs, math, physics, q-bio, q-fin, stat,\n"
            "eess, econ. Omit --set to harvest everything.\n\n"
            "Examples:\n"
            "  python -m scripts.harvest_arxiv --set cs --max-records 100000\n"
            "  python -m scripts.harvest_arxiv --set stat --since 2024-01-01\n"
            '  python -m scripts.harvest_arxiv --resume "$(cat .harvest-token)"\n'
        ),
    )
    parser.add_argument("--set", dest="set_spec", help="an arXiv archive, e.g. cs or q-bio")
    parser.add_argument("--since", type=_parse_date, help="only papers updated on or after this")
    parser.add_argument("--until", type=_parse_date, help="only papers updated on or before this")
    parser.add_argument(
        "--max-records",
        type=int,
        help="stop after roughly this many papers (the last page is not cut short)",
    )
    parser.add_argument("--resume", help="a resumption token from an earlier run")
    parser.add_argument(
        "--delay",
        type=float,
        default=MINIMUM_DELAY_SECONDS,
        help=(
            f"seconds between requests (default {MINIMUM_DELAY_SECONDS:g}). "
            "Going below arXiv's guidance risks being blocked."
        ),
    )
    return parser


def _report(started: float, progress: HarvestProgress) -> None:
    """One line, rewritten in place, so a six-hour run says something without filling a log."""
    elapsed = max(time.monotonic() - started, 1e-6)
    rate = progress.records / elapsed
    line = (
        f"  {progress.records:>9,} papers  "
        f"({progress.inserted:,} new, {progress.updated:,} updated)  "
        f"{progress.pages:>5,} pages  {rate:>6.0f}/s"
    )
    if progress.estimated_total:
        share = min(100.0, 100.0 * progress.records / progress.estimated_total)
        remaining = max(0, progress.estimated_total - progress.records)
        eta = remaining / rate if rate > 0 else 0
        line += f"  {share:5.1f}% of {progress.estimated_total:,}  eta {eta / 60:.0f}m"
    print(line.ljust(110), end="\r", flush=True)


def _save_token(token: str | None) -> None:
    if token:
        TOKEN_FILE.write_text(token)
    else:
        TOKEN_FILE.unlink(missing_ok=True)


async def main() -> int:
    args = _arguments().parse_args()
    init_engine(get_settings())
    sessions = get_session_factory()

    if args.resume and (args.set_spec or args.since or args.until):
        # OAI-PMH forbids it and arXiv answers `badArgument`. Saying so here is friendlier
        # than letting the first request fail three seconds later with a protocol error.
        print(
            "--resume carries the whole original query, so it cannot be combined with "
            "--set, --since, or --until.",
            file=sys.stderr,
        )
        return 2

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
        print(f"catalog holds {before:,} papers")
        if args.resume:
            print("resuming from a saved token")
        else:
            scope = args.set_spec or "all of arXiv"
            window = ""
            if args.since or args.until:
                window = f", {args.since or 'the beginning'} to {args.until or 'now'}"
            print(f"harvesting {scope}{window}")
        print()

        started = time.monotonic()
        progress = HarvestProgress()

        def on_page(current: HarvestProgress) -> None:
            _report(started, current)
            _save_token(current.resumption_token)
            if stopping.is_set():
                # Raising from the callback unwinds the harvest loop after the current page
                # has been committed, so Ctrl-C never costs more than the page in flight.
                raise KeyboardInterrupt

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(120.0),
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            harvester = ArxivHarvester(client, min_delay=args.delay)
            try:
                progress = await harvest(
                    db,
                    harvester,
                    set_spec=args.set_spec,
                    since=args.since,
                    until=args.until,
                    resume_from=args.resume,
                    max_records=args.max_records,
                    on_page=on_page,
                )
            except KeyboardInterrupt:
                print("\n\nstopped — everything harvested so far is saved")
                await analyze_catalog(db)
            except HarvestError as exc:
                # Before reporting, so a run cut short by a dropped connection still leaves
                # the planner able to use the index over everything it did manage to fetch.
                await analyze_catalog(db)
                print(f"\n\nthe harvest stopped: {exc}", file=sys.stderr)
                if TOKEN_FILE.exists():
                    print(f'resume with: --resume "$(cat {TOKEN_FILE})"', file=sys.stderr)
                return 1

        after = await count_catalog(db)
        elapsed = time.monotonic() - started

    print(f"\n\n{after:,} papers in the catalog ({after - before:+,}) in {elapsed / 60:.1f} min")
    if progress.skipped:
        print(f"{progress.skipped:,} records skipped (withdrawn papers and tombstones)")

    if TOKEN_FILE.exists() and TOKEN_FILE.read_text().strip():
        print(f'more remains — continue with: --resume "$(cat {TOKEN_FILE})"')
    else:
        print("the selection is complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
