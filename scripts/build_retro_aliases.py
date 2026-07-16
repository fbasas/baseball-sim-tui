#!/usr/bin/env python3
"""Regenerate the Retrosheet→Lahman alias table from Lahman ``Teams`` data.

The runtime alias table lives in ``src/data/retro_team_aliases.py`` (``_ALIASES``)
and is the read-only *final* fallback that lets a stale ``lahman.sqlite`` (built
before the ``teamIDretro`` join column existed) still resolve the handful of
franchises whose Retrosheet schedule id differs from their Lahman ``teamID``.

That table is *derived* — not invented: it is exactly the set of ``teamIDretro``
values that never equal their own row's ``teamID`` in Lahman's ``Teams`` table.
This script recomputes it from a ``teamIDretro``-bearing Lahman source so the
table stays correct as new seasons land, instead of being hand-maintained. Point
it at a Lahman DB (or a raw ``Teams.csv``) that includes recent seasons and paste
its output over ``_ALIASES``; a future relocation that *does* introduce a new
divergence (unlike the 2024/2025 Athletics move, which does not — see below) is
then a one-command regenerate rather than a manual audit.

Why the Athletics 2025 move adds no entry (FRE-156): a divergence exists only when
Lahman's ``teamID`` != its ``teamIDretro`` for a season. For the A's franchise
Lahman's ``teamID`` has always equalled the Retrosheet contemporary id
(``PHA``/``KC1``/``OAK`` — and ``ATH`` for 2025 Sacramento), so the schedule id
resolves by exact match with no alias row. Contrast the Angels, whose Lahman
``teamID`` (``LAA``) diverges from the Retrosheet id (``ANA``) — the one modern
entry. The Guardians keep ``CLE`` in both systems. See the spec
``docs/specs/retro-lahman-team-join-fix.md`` (§ The alias table) and FRE-156.

Open-ended (still-active) divergences — those whose last observed season is the
Lahman source's most recent year — are extended forward to the schedule's max
year (``schedule_ingest.SCHEDULE_MAX_YEAR``), because the Lahman CSV trails the
schedule by a season or two while the franchise mapping keeps holding. This is why
``ANA``→``LAA`` runs ``2005``–``2026`` off a 2021-max CSV.

Regenerate:

    # from a built Lahman DB (default: data/lahman.sqlite)
    python scripts/build_retro_aliases.py
    python scripts/build_retro_aliases.py --lahman-db path/to/lahman.sqlite

    # or straight from a raw Lahman Teams.csv
    python scripts/build_retro_aliases.py --lahman-csv path/to/Teams.csv

The script prints a ready-to-paste ``_ALIASES`` literal (and the divergence list)
to stdout; it never writes files or touches the network.

The Lahman and Retrosheet data are used under their respective terms; attribution
ships in ``README.md``.
"""

import argparse
import csv
import sqlite3
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data.schedule_ingest import SCHEDULE_MAX_YEAR  # noqa: E402

# A Lahman ``Teams`` row reduced to the three fields the alias derivation needs.
TeamsRow = Tuple[int, str, str]  # (yearID, teamID, teamIDretro)

# Alias entry shape mirrors ``retro_team_aliases._ALIASES``:
# retro_id -> (lahman teamID, first_year, last_year), inclusive.
AliasTable = Dict[str, Tuple[str, int, int]]


def compute_aliases(
    rows: Iterable[TeamsRow], schedule_max_year: int = SCHEDULE_MAX_YEAR
) -> AliasTable:
    """Derive the Retrosheet→Lahman alias table from Lahman ``Teams`` rows.

    A divergence is any season where a team's ``teamIDretro`` (its Retrosheet
    schedule id) differs from its Lahman ``teamID``; those are exactly the pairs
    the exact-match fallback cannot resolve on a stale DB. For each divergent
    Retrosheet id this collapses every observed season into one inclusive
    ``(teamID, first_year, last_year)`` window.

    Still-active divergences — whose last observed season equals the source's most
    recent year — are extended to ``schedule_max_year``, since the Lahman data
    trails the schedule while the mapping keeps holding (e.g. ``ANA``→``LAA``).

    Args:
        rows: Lahman ``Teams`` rows as ``(yearID, teamID, teamIDretro)``. Rows
            with a missing/blank ``teamID`` or ``teamIDretro`` are ignored.
        schedule_max_year: Upper bound applied to still-active divergences.

    Returns:
        The alias table keyed by Retrosheet id, structurally identical to
        ``retro_team_aliases._ALIASES``.

    Raises:
        ValueError: If a Retrosheet id maps to more than one Lahman ``teamID``
            across history — the single-``teamID``-per-id shape ``_ALIASES``
            assumes would not hold, and the table (and this script) would need to
            grow a year-scoped, multi-window representation.
    """
    # Retrosheet id -> {lahman teamID -> [first_year, last_year]}
    by_retro: Dict[str, Dict[str, List[int]]] = {}
    source_max_year: Optional[int] = None

    for year, team_id, retro_id in rows:
        if source_max_year is None or year > source_max_year:
            source_max_year = year
        team_id = (team_id or "").strip()
        retro_id = (retro_id or "").strip()
        if not team_id or not retro_id or retro_id == team_id:
            continue
        windows = by_retro.setdefault(retro_id, {})
        span = windows.get(team_id)
        if span is None:
            windows[team_id] = [year, year]
        else:
            span[0] = min(span[0], year)
            span[1] = max(span[1], year)

    table: AliasTable = {}
    for retro_id, windows in by_retro.items():
        if len(windows) > 1:
            mappings = ", ".join(
                f"{tid} ({lo}-{hi})" for tid, (lo, hi) in sorted(windows.items())
            )
            raise ValueError(
                f"Retrosheet id {retro_id!r} maps to multiple Lahman teamIDs "
                f"[{mappings}]; the single-teamID _ALIASES shape cannot represent "
                f"this. The table needs a year-scoped multi-window form."
            )
        (team_id, (first_year, last_year)) = next(iter(windows.items()))
        # Still active at the data horizon → extend to schedule coverage.
        if source_max_year is not None and last_year >= source_max_year:
            last_year = max(last_year, schedule_max_year)
        table[retro_id] = (team_id, first_year, last_year)

    return table


def _rows_from_csv(path: Path) -> List[TeamsRow]:
    """Read ``(yearID, teamID, teamIDretro)`` from a Lahman ``Teams.csv``."""
    with path.open(newline="", encoding="latin-1") as fh:
        reader = csv.DictReader(fh)
        missing = {"yearID", "teamID", "teamIDretro"} - set(reader.fieldnames or [])
        if missing:
            raise ValueError(
                f"{path}: Teams.csv is missing required column(s) {sorted(missing)}"
            )
        return [
            (int(r["yearID"]), r["teamID"], r["teamIDretro"])
            for r in reader
            if r.get("yearID")
        ]


def _rows_from_db(path: Path) -> List[TeamsRow]:
    """Read ``(yearID, teamID, teamIDretro)`` from a Lahman SQLite ``Teams``."""
    conn = sqlite3.connect(str(path))
    try:
        try:
            cur = conn.execute("SELECT yearID, teamID, teamIDretro FROM Teams")
        except sqlite3.OperationalError as exc:
            raise ValueError(
                f"{path}: Teams table has no teamIDretro column — this DB predates "
                f"the join key and cannot seed the alias table. Rebuild it with "
                f"scripts/build_lahman_db.py."
            ) from exc
        return [(int(y), t, tr) for (y, t, tr) in cur.fetchall()]
    finally:
        conn.close()


def _format_table(table: AliasTable) -> str:
    """Render the alias table as a paste-ready ``_ALIASES`` literal."""
    lines = ["_ALIASES = {"]
    for retro_id, (team_id, first_year, last_year) in sorted(
        table.items(), key=lambda kv: kv[1][1]
    ):
        lines.append(
            f'    "{retro_id}": ("{team_id}", {first_year}, {last_year}),'
        )
    lines.append("}")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    src = parser.add_mutually_exclusive_group()
    src.add_argument(
        "--lahman-db",
        type=Path,
        help="Path to a Lahman SQLite DB (default: data/lahman.sqlite).",
    )
    src.add_argument(
        "--lahman-csv",
        type=Path,
        help="Path to a raw Lahman Teams.csv (must carry teamIDretro).",
    )
    args = parser.parse_args(argv)

    if args.lahman_csv is not None:
        rows = _rows_from_csv(args.lahman_csv)
    else:
        db = args.lahman_db or (Path(__file__).parent.parent / "data" / "lahman.sqlite")
        if not db.exists():
            parser.error(
                f"Lahman DB not found at {db}. Build it with "
                f"scripts/build_lahman_db.py, or pass --lahman-db/--lahman-csv."
            )
        rows = _rows_from_db(db)

    table = compute_aliases(rows)

    print(f"# {len(table)} divergent franchises (teamIDretro != teamID), "
          f"still-active extended to schedule max {SCHEDULE_MAX_YEAR}:")
    for retro_id, (team_id, first_year, last_year) in sorted(
        table.items(), key=lambda kv: kv[1][1]
    ):
        print(f"#   {retro_id} -> {team_id}  {first_year}-{last_year}")
    print()
    print(_format_table(table))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
