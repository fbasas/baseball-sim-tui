"""Runtime-importable Retrosheet schedule ingestion (FRE-144).

The download → parse → insert core that populates the ``Schedules`` table in
``data/lahman.sqlite`` — the day-by-day slate of matchups (who plays whom, on
which date) that the Lahman database does not carry. This module is the single
place the Retrosheet schedule format lives; both the CLI
(``scripts/build_schedule_db.py``) and the app's on-demand-fetch path import it,
so parsing, the 2020 two-file special case, and the idempotent per-year replace
have exactly one implementation.

The schedule data is copyrighted by and obtained free of charge from Retrosheet
(https://www.retrosheet.org/). See the attribution notice in ``README.md`` and
``docs/adr/001-historical-schedule-data.md``.

Record layout (12 comma-separated fields per game; files are quoted CSV and,
in practice, carry a header row which the parser skips):

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
numbers, plus a leading ``year`` column. Re-ingesting a year clears that year's
rows first, so ingestion is idempotent per year.

This module has **no network access at import time** and no import-time side
effects: every top-level name is a constant or a function. Callers that must
stay off the network (tests, pure parsing) never trigger one — only
``download_zip`` (and ``fetch_schedule_rows`` without an injected ``fetch`` or
``local_zip``) reach out.
"""

import csv
import io
import sqlite3
import urllib.request
import zipfile
from pathlib import Path
from typing import List, Optional, Tuple, Union

# Download timeout in seconds.
DOWNLOAD_TIMEOUT = 120

# One ZIP per year. Coverage 1877-2026 (no 1876).
SCHEDULE_URL = "https://www.retrosheet.org/schedule/{year}SKED.zip"

# Retrosheet publishes ``{year}SKED.zip`` for 1877-2026 inclusive, except 1876
# (which returns a 404 HTML page, caught by the ZIP-magic-byte check). These
# bounds drive which years the historical-season picker offers.
SCHEDULE_MIN_YEAR = 1877
SCHEDULE_MAX_YEAR = 2026

# The first four bytes of every real ZIP archive; a 404 HTML error page fails
# this check, giving a clear "not a ZIP" error instead of a confusing parse.
_ZIP_MAGIC = b"PK\x03\x04"

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


def schedule_available_for(year: int) -> bool:
    """Whether Retrosheet publishes a schedule ZIP for ``year``.

    Coverage is ``SCHEDULE_MIN_YEAR..SCHEDULE_MAX_YEAR`` inclusive, minus 1876
    (the one gap in the range). This is a static availability check — it does
    not touch the network or the database.
    """
    return SCHEDULE_MIN_YEAR <= year <= SCHEDULE_MAX_YEAR and year != 1876


def download_zip(url: str, *, timeout: int = DOWNLOAD_TIMEOUT) -> bytes:
    """Download a schedule ZIP and return its raw bytes — quiet, no stdout.

    A TUI cannot print a progress bar, so this fetch is silent; the CLI wraps
    its own progress-bar version. Validates the ZIP magic bytes and raises a
    clear :class:`ValueError` otherwise (e.g. a 404 HTML page for a
    non-published year).
    """
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (baseball-sim-tui)"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        data = response.read()
    if data[:4] != _ZIP_MAGIC:
        raise ValueError(f"{url}: downloaded file is not a valid ZIP archive")
    return data


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
    """Parse a Retrosheet schedule file body into ``Schedules`` row tuples.

    ``text`` is the decoded file body. Rows whose first field is not an
    8-digit ``yyyymmdd`` date (the header row, blank lines) are skipped, so
    the function is header-tolerant regardless of Retrosheet's formatting.
    Empty postponement / makeup fields become ``None``. Pure: no network,
    no DB.
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


def parse_zip_bytes(data: bytes, year: int) -> List[Tuple]:
    """Turn schedule-ZIP bytes into ``Schedules`` row tuples.

    Validates the ZIP magic bytes, picks the played-schedule member
    (:func:`pick_schedule_member`, incl. the 2020 non-``orig`` rule), decodes
    it, and parses the rows (:func:`parse_schedule_rows`). Pure: no network,
    no DB. Raises :class:`ValueError` on non-ZIP bytes or a ZIP with no
    schedule member.
    """
    if data[:4] != _ZIP_MAGIC:
        raise ValueError(f"{year}: file is not a valid ZIP archive")
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        member = pick_schedule_member(zf.namelist(), year)
        if member is None:
            raise ValueError(
                f"{year}: no schedule file found in ZIP "
                f"(members: {zf.namelist()})"
            )
        text = zf.read(member).decode("utf-8", "replace")
    return parse_schedule_rows(text, year)


def fetch_schedule_rows(
    year: int,
    *,
    fetch=download_zip,
    url_template: str = SCHEDULE_URL,
    local_zip: Optional[Union[str, Path]] = None,
) -> List[Tuple]:
    """Fetch and parse a year's schedule into ``Schedules`` row tuples.

    Orchestrates fetch + parse without touching the database. ``fetch`` (a
    callable taking the resolved URL and returning ZIP bytes) and ``local_zip``
    (a path to a ZIP on disk) are injectable so callers — including tests —
    need never hit the network: pass ``local_zip`` to read from disk, or an
    ``fetch`` stub to return canned bytes. When ``local_zip`` is given it takes
    precedence and no download happens.
    """
    if local_zip is not None:
        data = Path(local_zip).read_bytes()
    else:
        data = fetch(url_template.format(year=year))
    return parse_zip_bytes(data, year)


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


def ingest_rows(conn: sqlite3.Connection, year: int, rows: List[Tuple]) -> int:
    """Persist a year's parsed rows into ``Schedules``, returning rows inserted.

    Ensures the table exists (:func:`create_schedule_table`), then replaces the
    year's rows (:func:`replace_year`) — idempotent per year, so re-ingesting a
    year yields the same row count rather than duplicating. Takes a
    :class:`sqlite3.Connection` so both the CLI and the app's repository can
    call the one write path.
    """
    create_schedule_table(conn)
    return replace_year(conn, year, rows)
