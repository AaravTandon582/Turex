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

from turex.catalog.harvest import (
    ARXIV_SETS,
    MINIMUM_DELAY_SECONDS,
    ArxivHarvester,
    DiskFullError,
    HarvestProgress,
    analyze_catalog,
    count_catalog,
    harvest,
)
from turex.catalog.records import HarvestError
from turex.core.config import get_settings
from turex.db.session import dispose_engine, get_session_factory, init_engine

TOKEN_FILE = Path(".harvest-token")

DONE_FILE = Path(".harvest-done")
"""Archives already harvested to completion, one per line.

`--all` is a sequence of eight long runs, and losing the ninth hour to a dropped connection
should not mean re-fetching the first eight. Written only when an archive's feed actually
ends, so an archive interrupted part-way is retried in full next time rather than being
recorded as finished — the alternative silently leaves a permanent hole in the catalog.
"""


def completed_sets() -> set[str]:
    if not DONE_FILE.exists():
        return set()
    return {line.strip() for line in DONE_FILE.read_text().splitlines() if line.strip()}


def mark_complete(set_spec: str) -> None:
    with DONE_FILE.open("a") as handle:
        handle.write(f"{set_spec}\n")


USER_AGENT = "Turex/1.0 (research workspace; +https://github.com/turex)"
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
        description="Fill the Turex catalog with paper metadata from arXiv.",
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
    parser.add_argument(
        "--all",
        action="store_true",
        help="every archive in turn — the whole of arXiv (~2.6M papers, ~8GB, ~11 hours)",
    )
    parser.add_argument("--since", type=_parse_date, help="only papers updated on or after this")
    parser.add_argument("--until", type=_parse_date, help="only papers updated on or before this")
    parser.add_argument(
        "--max-records",
        type=int,
        help="stop after roughly this many papers (the last page is not cut short)",
    )
    parser.add_argument("--resume", help="a resumption token from an earlier run")
    parser.add_argument(
        "--restart",
        action="store_true",
        help="with --all, start over rather than skipping archives already completed",
    )
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

    if args.all and (args.set_spec or args.resume):
        print(
            "--all covers every archive, so it cannot be combined with --set or --resume.",
            file=sys.stderr,
        )
        return 2

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
    """One archive, or every archive in turn."""
    if not args.all:
        return await _harvest_one(args, sessions, stopping, set_spec=args.set_spec)

    if args.restart:
        DONE_FILE.unlink(missing_ok=True)

    done = completed_sets()
    remaining = [name for name in ARXIV_SETS if name not in done]

    if done:
        print(f"already complete: {', '.join(sorted(done))}")
    if not remaining:
        print("every archive is already harvested. Use --restart to do them again.")
        return 0
    print(f"harvesting {len(remaining)} archives: {', '.join(remaining)}\n")

    finished: list[str] = []
    failed: list[str] = []

    for name in remaining:
        print(f"── {name} " + "─" * 56)
        # Each archive is its own run with its own token, so a failure in one does not
        # discard the others and a resume knows which feed it is resuming.
        TOKEN_FILE.unlink(missing_ok=True)
        code = await _harvest_one(args, sessions, stopping, set_spec=name)

        if code == 0 and not (TOKEN_FILE.exists() and TOKEN_FILE.read_text().strip()):
            mark_complete(name)
            finished.append(name)
        elif stopping.is_set():
            print("\nstopped. Re-run with --all to continue from the next archive.")
            return 0
        else:
            # Recorded as unfinished, so the next --all retries this archive in full rather
            # than leaving a permanent hole nobody notices.
            failed.append(name)
            print(f"\n{name} did not finish; it will be retried by the next --all run.")

    # Reported by what actually happened rather than by having reached the end of the loop.
    # Printing "every archive harvested" after three of them failed is the kind of status line
    # that makes someone believe they have the whole corpus when they have a third of it.
    if failed:
        print(f"\n{len(finished)} archives complete: {', '.join(finished) or 'none'}")
        print(f"{len(failed)} did not finish: {', '.join(failed)}")
        print("Re-run with --all to retry those; the complete ones are skipped.")
        return 1

    print("\nevery archive harvested.")
    return 0


async def _harvest_one(
    args: argparse.Namespace,
    sessions: async_sessionmaker[AsyncSession],
    stopping: asyncio.Event,
    *,
    set_spec: str | None,
) -> int:
    async with sessions() as db:
        before = await count_catalog(db)
        print(f"catalog holds {before:,} papers")
        if args.resume:
            print("resuming from a saved token")
        else:
            scope = set_spec or "all of arXiv"
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
            # Generous, because a throttled connection delivering a 3MB page slowly is not a
            # failure — it is the service asking for patience, and treating it as an error is
            # how a long harvest dies two hours in with everything working.
            timeout=httpx.Timeout(300.0, connect=30.0),
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            harvester = ArxivHarvester(client, min_delay=args.delay)
            try:
                progress = await harvest(
                    db,
                    harvester,
                    set_spec=set_spec,
                    since=args.since,
                    until=args.until,
                    resume_from=args.resume,
                    max_records=args.max_records,
                    on_page=on_page,
                )
            except KeyboardInterrupt:
                print("\n\nstopped — everything harvested so far is saved")
                await analyze_catalog(db)
            except DiskFullError as exc:
                print(f"\n\n{exc}", file=sys.stderr)
                print(
                    f'Free some space, then resume with: --resume "$(cat {TOKEN_FILE})"',
                    file=sys.stderr,
                )
                return 1
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
