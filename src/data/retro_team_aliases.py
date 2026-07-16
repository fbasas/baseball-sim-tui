"""Year-scoped Retrosheet→Lahman team-id alias table (stale-DB fallback).

Retrosheet schedule files key each game by a per-game team id (``vis_team`` /
``home_team``, e.g. ``ANA``), while Lahman rosters/stats are keyed by ``teamID``
(e.g. ``LAA``). The primary bridge is Lahman's ``Teams.teamIDretro`` column, but a
``lahman.sqlite`` built before that column existed cannot join on it and degrades
to an exact ``teamID == retro_id`` match — which fails for the handful of
franchises whose Retrosheet id differs from their Lahman ``teamID``.

This module holds a small, committed alias table used as a read-only *final*
resolution step (after the ``teamIDretro`` column and exact-match steps) so a
stale DB resolves those divergent franchises with no rebuild and no DB mutation.

Provenance: the table is derived directly from Lahman's own ``Teams`` data — the
complete set of ``(yearID, teamID)`` where ``teamIDretro != teamID`` computed from
the full Lahman ``Teams.csv`` (1871–2021). That set is exactly six distinct
franchise mappings (below). It is verified collision-free and unambiguous against
the same CSV: in no year does a wrong team's ``teamID`` equal a divergent
Retrosheet id (so exact-match-first is safe), and ``(retro_id, year) → teamID`` is
a function. See ``docs/specs/retro-lahman-team-join-fix.md`` (§ The alias table).
``scripts/build_retro_aliases.py`` regenerates this exact table from a
``teamIDretro``-bearing Lahman source (it reproduces the six entries below
byte-for-byte from the 2021-max CSV), so the table need not be hand-maintained as
new seasons land.

``ANA``→``LAA`` is extended through the schedule max year because the Angels remain
``LAA`` in Lahman; the source CSV merely stops at 2021.

2022–2025 (FRE-156): checked against the real Retrosheet schedule files and
``CurrentNames.csv``. The only relocations/rebrands are the Guardians (Retrosheet
keeps ``CLE``, matching Lahman ``CLE`` — no divergence) and the Athletics'
2024→2025 Oakland→Sacramento move (Retrosheet contemporary id ``OAK``→``ATH``).
The A's are **not** a new divergence: Lahman's ``teamID`` for this franchise has
always equalled its ``teamIDretro`` (``PHA``/``KC1``/``OAK``, and ``ATH`` for
2025), so the schedule id resolves by exact match with no alias row — unlike the
Angels, whose Lahman ``LAA`` diverges from Retrosheet ``ANA``. Hence no new entries
for 2022–2025; ``ANA``→``LAA`` (already present) covers the Angels throughout.

Lahman and Retrosheet attribution ships in the project README.
"""

from typing import Dict, Optional, Tuple

from src.data.schedule_ingest import SCHEDULE_MAX_YEAR

# Upper bound for the open-ended ``ANA``→``LAA`` mapping: the schedule max year.
# The Angels remain Lahman ``LAA`` from 2005 onward, so the alias holds through
# every schedule year currently supported. Bound to the schedule coverage so it
# tracks automatically when ``SCHEDULE_MAX_YEAR`` advances (and matches how
# ``scripts/build_retro_aliases.py`` extends still-active divergences).
_ANA_LAA_END_YEAR = SCHEDULE_MAX_YEAR

# Authoritative alias table: Retrosheet id → (Lahman teamID, first_year, last_year),
# inclusive year range. Derived from Lahman ``Teams.teamIDretro`` (see docstring).
_ALIASES: Dict[str, Tuple[str, int, int]] = {
    "CN4": ("CN1", 1880, 1880),
    "BL5": ("BL2", 1882, 1882),
    "WSN": ("WAS", 1892, 1899),
    "MLN": ("ML1", 1953, 1965),
    "MIL": ("ML4", 1970, 1997),
    "ANA": ("LAA", 2005, _ANA_LAA_END_YEAR),
}


def resolve_retro_alias(retro_id: str, year: int) -> Optional[str]:
    """Resolve a Retrosheet team id to a Lahman ``teamID`` via the alias table.

    This is the read-only fallback for divergent franchises on a DB that predates
    the ``teamIDretro`` join key. Only ``(retro_id, year)`` pairs inside a known
    divergence window resolve; everything else returns ``None`` so the caller can
    treat it as unresolved.

    Args:
        retro_id: Retrosheet team id from the schedule (e.g. ``ANA``).
        year: Season year (mappings are year-scoped — a Retrosheet id can map to
            different Lahman ids across a franchise's history).

    Returns:
        The Lahman ``teamID`` if the pair falls in a known divergence window,
        else ``None``.
    """
    entry = _ALIASES.get(retro_id)
    if entry is None:
        return None
    lahman_id, first_year, last_year = entry
    if first_year <= year <= last_year:
        return lahman_id
    return None
