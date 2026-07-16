#!/usr/bin/env python3
"""
Build the Retrosheet ``Schedules`` table inside the Lahman SQLite database.

Downloads Retrosheet per-year *schedule* files and populates a ``Schedules``
table in ``data/lahman.sqlite`` — the day-by-day slate of matchups (who plays
whom, on which date) that the Lahman database does not carry. This is the data
foundation for historical season mode (see
``docs/specs/historical-season-mode.md`` and
``docs/adr/001-historical-schedule-data.md``).

This script is a thin CLI wrapper: the download/parse/insert core and the
Retrosheet record layout live in the runtime-importable module
``src/data/schedule_ingest.py`` (so the app's on-demand-fetch path and this
script share one implementation). The CLI adds a progress bar, argument
parsing, and post-build verification on top of that module.

The schedule data is copyrighted by and obtained free of charge from Retrosheet
(https://www.retrosheet.org/). See the attribution notice in ``README.md``.

Source: https://www.retrosheet.org/schedule/

Usage:
    python scripts/build_schedule_db.py --year 2016
    python scripts/build_schedule_db.py --years 1927,1969,2016,2020
    python scripts/build_schedule_db.py --start 2014 --end 2016
    python scripts/build_schedule_db.py --year 2016 --local-zip data/2016SKED.zip

Note: existing ``lahman.sqlite`` files predating the ``teamIDretro`` column
must be rebuilt with ``build_lahman_db.py`` before the historical-season join
key is available (this script only writes ``Schedules``; it does not touch the
Lahman tables).
"""

import argparse
import sqlite3
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data.schedule_ingest import (  # noqa: E402
    DOWNLOAD_TIMEOUT,
    SCHEDULE_URL,
    create_schedule_table,
    fetch_schedule_rows,
    ingest_rows,
    parse_schedule_rows,
    pick_schedule_member,
    replace_year,
)

__all__ = [
    # Re-exported from schedule_ingest so callers importing this script keep
    # working; the canonical home is src/data/schedule_ingest.py.
    "SCHEDULE_URL",
    "DOWNLOAD_TIMEOUT",
    "create_schedule_table",
    "replace_year",
    "parse_schedule_rows",
    "pick_schedule_member",
    "download_with_progress",
    "build_year",
    "resolve_years",
    "verify_database",
]


def download_with_progress(
    url: str, desc: str = "Downloading", timeout: int = DOWNLOAD_TIMEOUT
) -> bytes:
    """Download a URL with a simple progress bar, returning the raw bytes.

    The CLI-only, chatty counterpart of ``schedule_ingest.download_zip``: it
    prints a progress bar to stdout. The module's fetch stays quiet (a TUI
    can't render a progress bar). ZIP-magic validation happens downstream in
    ``schedule_ingest.parse_zip_bytes``.
    """
    print(f"{desc}: {url}")
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (baseball-sim-tui build script)"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        total_size = response.headers.get("Content-Length")
        if total_size:
            total_size = int(total_size)

        chunks = []
        downloaded = 0
        while True:
            chunk = response.read(8192)
            if not chunk:
                break
            chunks.append(chunk)
            downloaded += len(chunk)
            if total_size:
                pct = downloaded * 100 / total_size
                bar_len = 40
                filled = int(bar_len * downloaded / total_size)
                bar = "=" * filled + "-" * (bar_len - filled)
                print(f"\r  [{bar}] {pct:.1f}%", end="", flush=True)
        print()
        return b"".join(chunks)


def build_year(
    conn: sqlite3.Connection,
    year: int,
    url_template: str = SCHEDULE_URL,
    local_zip: Optional[Path] = None,
) -> int:
    """Download/parse/insert a single year via the shared ingest module.

    Wraps ``schedule_ingest.fetch_schedule_rows`` with the CLI progress bar
    (for the network path) and ``ingest_rows`` for persistence. Returns rows
    inserted; raises ``ValueError`` when a year parses to zero rows.
    """
    if local_zip is not None:
        rows = fetch_schedule_rows(year, local_zip=local_zip)
    else:
        def fetch(url: str) -> bytes:
            return download_with_progress(url, desc=f"Downloading {year} schedule")

        rows = fetch_schedule_rows(year, fetch=fetch, url_template=url_template)
    if not rows:
        raise ValueError(f"{year}: parsed 0 schedule rows")
    inserted = ingest_rows(conn, year, rows)
    print(f"  {year}: inserted {inserted} rows")
    return inserted


def resolve_years(args: argparse.Namespace) -> List[int]:
    """Turn --year / --years / --start/--end into a sorted unique year list."""
    years: List[int] = []
    if args.year is not None:
        years.append(args.year)
    if args.years:
        years.extend(int(y.strip()) for y in args.years.split(",") if y.strip())
    if args.start is not None or args.end is not None:
        if args.start is None or args.end is None:
            print("ERROR: --start and --end must be given together")
            sys.exit(2)
        if args.end < args.start:
            print("ERROR: --end must be >= --start")
            sys.exit(2)
        years.extend(range(args.start, args.end + 1))
    return sorted(set(years))


def verify_database(db_path: Path, years: List[int]) -> bool:
    """Print per-year row counts and confirm every requested year has data."""
    print("\nVerifying Schedules table...")
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        ok = True
        for year in years:
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM Schedules WHERE year = ?", (year,)
            ).fetchone()
            cnt = row["cnt"]
            print(f"  {year}: {cnt:,} rows")
            if cnt == 0:
                print(f"  ERROR: {year} has no rows")
                ok = False
        return ok
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the Retrosheet Schedules table in lahman.sqlite",
        epilog=(
            "Schedule data is copyrighted by and obtained free of charge from "
            "Retrosheet (www.retrosheet.org)."
        ),
    )
    parser.add_argument("--year", type=int, help="A single season year")
    parser.add_argument(
        "--years", type=str, help="Comma-separated list of years, e.g. 1927,1969,2016"
    )
    parser.add_argument("--start", type=int, help="Range start (inclusive)")
    parser.add_argument("--end", type=int, help="Range end (inclusive)")
    parser.add_argument(
        "--output-path",
        type=Path,
        default=Path("data/lahman.sqlite"),
        help="SQLite database to populate (default: data/lahman.sqlite)",
    )
    parser.add_argument(
        "--local-zip",
        type=Path,
        help="Use a local schedule ZIP instead of downloading (requires a single --year)",
    )
    parser.add_argument(
        "--url",
        type=str,
        default=SCHEDULE_URL,
        help="Override the download URL template (must contain {year})",
    )
    args = parser.parse_args()

    years = resolve_years(args)
    if not years:
        parser.error("specify at least one of --year, --years, or --start/--end")
    if args.local_zip is not None and len(years) != 1:
        parser.error("--local-zip requires exactly one --year")

    args.output_path.parent.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("Retrosheet Schedule Builder")
    print("Source: Retrosheet (www.retrosheet.org)")
    print(f"Years: {', '.join(str(y) for y in years)}")
    print("=" * 60)

    conn = sqlite3.connect(str(args.output_path))
    stats: Dict[int, int] = {}
    try:
        create_schedule_table(conn)
        for year in years:
            try:
                stats[year] = build_year(conn, year, args.url, args.local_zip)
            except (urllib.error.URLError, ValueError, zipfile.BadZipFile) as e:
                print(f"  ERROR building {year}: {e}")
                sys.exit(1)
    finally:
        conn.close()

    if not verify_database(args.output_path, years):
        print("\nERROR: verification failed")
        sys.exit(1)

    total = sum(stats.values())
    print("\n" + "=" * 60)
    print("SUCCESS!")
    print(f"Populated Schedules for {len(years)} year(s), {total:,} rows total")
    print(f"Database: {args.output_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
