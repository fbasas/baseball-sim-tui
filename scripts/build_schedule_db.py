#!/usr/bin/env python3
"""
Build the Retrosheet ``Schedules`` table inside the Lahman SQLite database.

Downloads Retrosheet per-year *schedule* files and populates a ``Schedules``
table in ``data/lahman.sqlite`` — the day-by-day slate of matchups (who plays
whom, on which date) that the Lahman database does not carry. This is the data
foundation for historical season mode (see
``docs/specs/historical-season-mode.md`` and
``docs/adr/001-historical-schedule-data.md``).

The schedule data is copyrighted by and obtained free of charge from Retrosheet
(https://www.retrosheet.org/). See the attribution notice in ``README.md``.

Source: https://www.retrosheet.org/schedule/

Record layout (12 comma-separated fields per game; files are quoted CSV and,
in practice, carry a header row which this script skips):

    1  Date            yyyymmdd
    2  Game number     0 single · 1 first of DH · 2 second of DH
    3  Day of week     Sun..Sat
    4  Visiting team   Retrosheet team id (e.g. NYA)
    5  Visiting league AL / NL / AA / FL / ...
    6  Visitor season game number       (not stored)
    7  Home team       Retrosheet team id
    8  Home league
    9  Home season game number          (not stored)
    10 Time of day     D day · N night · A afternoon · E twilight
    11 Postponement    non-empty when NOT played as scheduled
    12 Makeup date     yyyymmdd if the postponed game was replayed (else empty)

The ``Schedules`` table stores every field except the two per-team season game
numbers, plus a ``year`` column. Re-running for a year clears that year's rows
first, so builds are idempotent.

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
import csv
import io
import sqlite3
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Download timeout in seconds.
DOWNLOAD_TIMEOUT = 120

# One ZIP per year. Coverage 1877-2026 (no 1876).
SCHEDULE_URL = "https://www.retrosheet.org/schedule/{year}SKED.zip"

# Ordered columns stored per schedule row (excludes the two per-team season
# game-number fields; adds a leading ``year``).
SCHEDULE_COLUMNS = [
    ("year", "INTEGER"),
    ("date", "INTEGER"),
    ("game_num", "INTEGER"),
    ("dow", "TEXT"),
    ("vis_team", "TEXT"),
    ("vis_league", "TEXT"),
    ("home_team", "TEXT"),
    ("home_league", "TEXT"),
    ("time_of_day", "TEXT"),
    ("postponed", "TEXT"),
    ("makeup_date", "INTEGER"),
]


def download_with_progress(
    url: str, desc: str = "Downloading", timeout: int = DOWNLOAD_TIMEOUT
) -> bytes:
    """Download a URL with a simple progress bar, returning the raw bytes."""
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


def pick_schedule_member(names: List[str], year: int) -> Optional[str]:
    """Choose the played-schedule file from a year's ZIP member names.

    Retrosheet names the file ``{year}schedule.csv``. For 2020 the ZIP holds
    two files — ``2020schedule.csv`` (the played 60-game slate) and
    ``2020sched-orig.csv`` (the pre-pandemic original); we always want the
    *played* one, so any member whose name contains "orig" is excluded.
    Falls back to the first non-orig ``.csv``/``.txt`` member.
    """
    candidates = [
        n for n in names
        if "orig" not in n.lower() and n.lower().endswith((".csv", ".txt"))
    ]
    if not candidates:
        return None
    exact = f"{year}schedule.csv"
    for n in candidates:
        if n.lower().endswith(exact):
            return n
    # Prefer an explicit "rev" (revised/played) member if one exists.
    for n in candidates:
        if "rev" in n.lower():
            return n
    return candidates[0]


def parse_schedule_rows(text: str, year: int) -> List[Tuple]:
    """Parse a Retrosheet schedule file into ``Schedules`` row tuples.

    ``text`` is the decoded file body. Rows whose first field is not an
    8-digit ``yyyymmdd`` date (the header row, blank lines) are skipped, so
    the function is header-tolerant regardless of Retrosheet's formatting.
    Empty postponement / makeup fields become ``None``.
    """
    rows: List[Tuple] = []
    reader = csv.reader(io.StringIO(text))
    for fields in reader:
        if len(fields) < 12:
            continue
        date_raw = fields[0].strip()
        if len(date_raw) != 8 or not date_raw.isdigit():
            # Header row or malformed line — skip.
            continue
        game_num_raw = fields[1].strip()
        makeup_raw = fields[11].strip()
        postponed_raw = fields[10].strip()
        rows.append(
            (
                year,
                int(date_raw),
                int(game_num_raw) if game_num_raw.isdigit() else 0,
                fields[2].strip(),
                fields[3].strip(),
                fields[4].strip(),
                fields[6].strip(),
                fields[7].strip(),
                fields[9].strip(),
                postponed_raw or None,
                int(makeup_raw) if makeup_raw.isdigit() and len(makeup_raw) == 8 else None,
            )
        )
    return rows


def create_schedule_table(conn: sqlite3.Connection) -> None:
    """Create the ``Schedules`` table and its ``(year)`` index if absent."""
    cols = ", ".join(f"{name} {typ}" for name, typ in SCHEDULE_COLUMNS)
    conn.execute(f"CREATE TABLE IF NOT EXISTS Schedules ({cols})")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS schedules_year_idx ON Schedules (year)"
    )


def replace_year(conn: sqlite3.Connection, year: int, rows: List[Tuple]) -> int:
    """Clear a year's rows and insert the parsed ones (idempotent per year)."""
    col_names = [name for name, _ in SCHEDULE_COLUMNS]
    placeholders = ", ".join("?" for _ in col_names)
    sql = f"INSERT INTO Schedules ({', '.join(col_names)}) VALUES ({placeholders})"
    conn.execute("DELETE FROM Schedules WHERE year = ?", (year,))
    conn.executemany(sql, rows)
    conn.commit()
    return len(rows)


def load_zip_for_year(
    year: int, url_template: str, local_zip: Optional[Path]
) -> bytes:
    """Return the ZIP bytes for a year, from a local file or download."""
    if local_zip is not None:
        data = local_zip.read_bytes()
    else:
        data = download_with_progress(
            url_template.format(year=year), desc=f"Downloading {year} schedule"
        )
    if data[:4] != b"PK\x03\x04":
        raise ValueError(f"{year}: downloaded file is not a valid ZIP archive")
    return data


def build_year(
    conn: sqlite3.Connection,
    year: int,
    url_template: str = SCHEDULE_URL,
    local_zip: Optional[Path] = None,
) -> int:
    """Download/parse/insert a single year. Returns rows inserted."""
    data = load_zip_for_year(year, url_template, local_zip)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        member = pick_schedule_member(zf.namelist(), year)
        if member is None:
            raise ValueError(
                f"{year}: no schedule file found in ZIP "
                f"(members: {zf.namelist()})"
            )
        print(f"  Using file: {member}")
        text = zf.read(member).decode("utf-8", "replace")
    rows = parse_schedule_rows(text, year)
    if not rows:
        raise ValueError(f"{year}: parsed 0 schedule rows")
    inserted = replace_year(conn, year, rows)
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
