"""Tests for the year-scoped Retrosheet→Lahman alias fallback (FRE-154, FRE-156).

Covers the alias lookup in isolation and its wiring into
``LahmanRepository.retro_to_lahman_team`` as the *final* resolution step, using
fixture DBs built both with and without the ``teamIDretro`` column. No network
and no full roster DB required.

FRE-156 adds two things: (1) the ``scripts/build_retro_aliases.py`` regenerator,
tested via ``compute_aliases`` — it must reproduce the committed ``_ALIASES`` from
Lahman ``Teams`` rows and must *not* invent an Athletics 2025 entry; and (2)
resolution over the **real** 2022–2025 Retrosheet schedule id sets on a stale DB,
so the only modern divergence stays the Angels (``ANA``→``LAA``).
"""

import importlib.util
import sqlite3
from pathlib import Path

import pytest

from src.data.lahman import LahmanRepository
from src.data.retro_team_aliases import _ALIASES, resolve_retro_alias


def _load_build_aliases():
    """Import scripts/build_retro_aliases.py by path (scripts is not a package)."""
    path = Path(__file__).parent.parent / "scripts" / "build_retro_aliases.py"
    spec = importlib.util.spec_from_file_location("build_retro_aliases", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build_aliases = _load_build_aliases()


class TestResolveRetroAliasUnit:
    """The pure alias-table lookup, independent of any DB."""

    def test_ana_laa_in_window(self):
        assert resolve_retro_alias("ANA", 2012) == "LAA"
        assert resolve_retro_alias("ANA", 2016) == "LAA"
        assert resolve_retro_alias("ANA", 2019) == "LAA"

    def test_ana_laa_extends_through_schedule_max(self):
        # Angels remain LAA in Lahman; alias holds through the schedule max year.
        assert resolve_retro_alias("ANA", 2005) == "LAA"
        assert resolve_retro_alias("ANA", 2026) == "LAA"

    def test_ana_before_window_is_none(self):
        # Before 2005 the Angels were ANA in both systems (exact match handles it).
        assert resolve_retro_alias("ANA", 2004) is None

    def test_mil_ml4_in_window(self):
        assert resolve_retro_alias("MIL", 1970) == "ML4"
        assert resolve_retro_alias("MIL", 1994) == "ML4"
        assert resolve_retro_alias("MIL", 1997) == "ML4"

    def test_mil_outside_window_is_none(self):
        # 1998+ MIL is the Lahman teamID itself (exact match), not ML4.
        assert resolve_retro_alias("MIL", 1998) is None
        assert resolve_retro_alias("MIL", 1969) is None

    def test_historic_franchises(self):
        assert resolve_retro_alias("CN4", 1880) == "CN1"
        assert resolve_retro_alias("BL5", 1882) == "BL2"
        assert resolve_retro_alias("WSN", 1895) == "WAS"
        assert resolve_retro_alias("MLN", 1957) == "ML1"

    def test_unknown_id_is_none(self):
        assert resolve_retro_alias("ZZZ", 2016) is None

    def test_known_id_wrong_year_is_none(self):
        assert resolve_retro_alias("MLN", 1970) is None


def _make_db(tmp_path, name, with_teamidretro):
    """Build a minimal Teams-only fixture DB and return an open repo.

    A handful of teams covering: divergent franchises (ANA/MIL), historic ones,
    and a non-divergent team (BOS). When ``with_teamidretro`` is True the join
    column is present and populated so step 1 can resolve.
    """
    db = tmp_path / name
    conn = sqlite3.connect(str(db))
    if with_teamidretro:
        conn.execute(
            "CREATE TABLE Teams (yearID TEXT, teamID TEXT, teamIDretro TEXT)"
        )
        rows = [
            ("2016", "LAA", "ANA"),
            ("1994", "ML4", "MIL"),
            ("2016", "BOS", "BOS"),
        ]
        conn.executemany(
            "INSERT INTO Teams (yearID, teamID, teamIDretro) VALUES (?,?,?)",
            rows,
        )
    else:
        # Stale DB: no teamIDretro column at all.
        conn.execute("CREATE TABLE Teams (yearID TEXT, teamID TEXT)")
        rows = [
            ("2012", "LAA"),
            ("2016", "LAA"),
            ("2019", "LAA"),
            ("1994", "ML4"),
            ("2016", "BOS"),
        ]
        conn.executemany(
            "INSERT INTO Teams (yearID, teamID) VALUES (?,?)", rows
        )
    conn.commit()
    conn.close()
    return LahmanRepository(str(db))


class TestRetroToLahmanStaleDB:
    """retro_to_lahman_team on a DB WITHOUT the teamIDretro column."""

    @pytest.fixture
    def repo(self, tmp_path):
        repo = _make_db(tmp_path, "stale.sqlite", with_teamidretro=False)
        yield repo
        repo.close()

    def test_ana_resolves_via_alias(self, repo):
        assert repo.retro_to_lahman_team("ANA", 2012) == "LAA"
        assert repo.retro_to_lahman_team("ANA", 2016) == "LAA"
        assert repo.retro_to_lahman_team("ANA", 2019) == "LAA"

    def test_mil_resolves_via_alias(self, repo):
        assert repo.retro_to_lahman_team("MIL", 1994) == "ML4"

    def test_non_divergent_via_exact_match(self, repo):
        # BOS == BOS: exact match (step 2) wins before the alias table.
        assert repo.retro_to_lahman_team("BOS", 2016) == "BOS"

    def test_unknown_returns_none(self, repo):
        assert repo.retro_to_lahman_team("ZZZ", 2016) is None

    def test_divergent_id_wrong_year_returns_none(self, repo):
        # ANA in 2004 is outside the alias window and has no row → unresolved.
        assert repo.retro_to_lahman_team("ANA", 2004) is None


class TestRetroToLahmanColumnWins:
    """No regression: the teamIDretro column still wins when present."""

    @pytest.fixture
    def repo(self, tmp_path):
        repo = _make_db(tmp_path, "fresh.sqlite", with_teamidretro=True)
        yield repo
        repo.close()

    def test_ana_resolves_via_column(self, repo):
        assert repo.retro_to_lahman_team("ANA", 2016) == "LAA"

    def test_mil_resolves_via_column(self, repo):
        assert repo.retro_to_lahman_team("MIL", 1994) == "ML4"

    def test_exact_match_still_works(self, repo):
        assert repo.retro_to_lahman_team("BOS", 2016) == "BOS"

    def test_column_takes_precedence_over_alias(self, tmp_path):
        # If the column maps ANA→SOMETHING for a year, step 1 wins over the
        # alias table (which would say LAA) — proving order, not coincidence.
        db = tmp_path / "precedence.sqlite"
        conn = sqlite3.connect(str(db))
        conn.execute(
            "CREATE TABLE Teams (yearID TEXT, teamID TEXT, teamIDretro TEXT)"
        )
        conn.execute(
            "INSERT INTO Teams (yearID, teamID, teamIDretro) VALUES (?,?,?)",
            ("2016", "XYZ", "ANA"),
        )
        conn.commit()
        conn.close()
        repo = LahmanRepository(str(db))
        try:
            assert repo.retro_to_lahman_team("ANA", 2016) == "XYZ"
        finally:
            repo.close()


# --- FRE-156: regenerator (scripts/build_retro_aliases.py) -------------------

# A synthetic Lahman ``Teams`` slice — (yearID, teamID, teamIDretro) — that
# encodes every known divergence plus the franchises FRE-156 had to rule on:
# the Athletics (teamID == teamIDretro every era, incl. ``ATH`` for 2025) and
# the Guardians (``CLE`` in both). ``teamIDretro`` mirrors what a current Lahman
# stores (the Retrosheet contemporary/schedule id). Source horizon is 2025, so a
# still-active divergence (the Angels) extends to the schedule max year.
_SYNTHETIC_TEAMS = [
    # Historic divergences (all closed windows).
    (1880, "CN1", "CN4"),
    (1882, "BL2", "BL5"),
    (1892, "WAS", "WSN"), (1899, "WAS", "WSN"),
    (1953, "ML1", "MLN"), (1965, "ML1", "MLN"),
    (1970, "ML4", "MIL"), (1997, "ML4", "MIL"),
    # Angels: the one still-active divergence (Lahman LAA vs Retrosheet ANA).
    (2005, "LAA", "ANA"), (2021, "LAA", "ANA"), (2025, "LAA", "ANA"),
    # Athletics: teamID has ALWAYS equalled teamIDretro — never a divergence,
    # including the 2025 Sacramento move (OAK→ATH in BOTH systems).
    (1901, "PHA", "PHA"), (1955, "KC1", "KC1"),
    (2021, "OAK", "OAK"), (2024, "OAK", "OAK"), (2025, "ATH", "ATH"),
    # Guardians: CLE in both systems across the 2022 rebrand.
    (2021, "CLE", "CLE"), (2022, "CLE", "CLE"), (2025, "CLE", "CLE"),
    # A plain non-divergent modern team, and a blank-retro row (ignored).
    (2025, "BOS", "BOS"), (2025, "MIL", "MIL"), (2025, "NYA", ""),
]


class TestComputeAliasesRegenerator:
    """``compute_aliases`` derives the table the way the committed one was built."""

    def test_reproduces_committed_table(self):
        # Fed a Lahman slice through 2025, the generator must emit exactly the
        # committed _ALIASES — same keys, ids and windows (ANA→LAA extended to
        # the schedule max because it is still active at the 2025 horizon).
        table = build_aliases.compute_aliases(_SYNTHETIC_TEAMS)
        assert table == dict(_ALIASES)

    def test_no_athletics_2025_entry(self):
        # The heart of FRE-156: the A's relocation is NOT a divergence, so no
        # ATH/OAK/SAC alias row is emitted — exact match handles it.
        table = build_aliases.compute_aliases(_SYNTHETIC_TEAMS)
        assert "ATH" not in table
        assert "SAC" not in table
        assert "OAK" not in table

    def test_guardians_not_an_entry(self):
        table = build_aliases.compute_aliases(_SYNTHETIC_TEAMS)
        assert "CLE" not in table

    def test_still_active_extends_to_schedule_max(self):
        # ANA→LAA is open at the source horizon (2025) → runs to SCHEDULE_MAX_YEAR.
        table = build_aliases.compute_aliases(_SYNTHETIC_TEAMS)
        _, first, last = table["ANA"]
        assert first == 2005
        assert last == build_aliases.SCHEDULE_MAX_YEAR

    def test_closed_window_not_extended(self):
        # MIL→ML4 ended in 1997, well before the horizon → left untouched.
        table = build_aliases.compute_aliases(_SYNTHETIC_TEAMS)
        assert table["MIL"] == ("ML4", 1970, 1997)

    def test_blank_and_equal_ids_ignored(self):
        # Rows with a blank retro id or teamID == teamIDretro never produce entries.
        rows = [(2025, "NYA", ""), (2025, "BOS", "BOS"), (2025, "", "ZZZ")]
        assert build_aliases.compute_aliases(rows) == {}

    def test_ambiguous_id_raises(self):
        # If a Retrosheet id ever mapped to two Lahman teamIDs, the single-teamID
        # _ALIASES shape can't hold it — the generator must refuse, not silently
        # pick one.
        rows = [(1900, "AAA", "XXX"), (1950, "BBB", "XXX")]
        with pytest.raises(ValueError, match="multiple Lahman teamIDs"):
            build_aliases.compute_aliases(rows)


# --- FRE-156: resolution over the REAL 2022–2025 schedule id sets ------------

# The distinct team ids in each real Retrosheet ``{year}SKED`` file, extracted
# from the published schedule zips (retrosheet.org) for this issue. 2022–2024 use
# ``OAK`` (Oakland); 2025 swaps in ``ATH`` (Sacramento). ``ANA`` (Angels) and
# ``CLE`` (Guardians) appear throughout. Captured as a fixture so the test stays
# offline and deterministic.
_REAL_SCHEDULE_TEAM_IDS = {
    2022: ["ANA", "ARI", "ATL", "BAL", "BOS", "CHA", "CHN", "CIN", "CLE", "COL",
           "DET", "HOU", "KCA", "LAN", "MIA", "MIL", "MIN", "NYA", "NYN", "OAK",
           "PHI", "PIT", "SDN", "SEA", "SFN", "SLN", "TBA", "TEX", "TOR", "WAS"],
    2023: ["ANA", "ARI", "ATL", "BAL", "BOS", "CHA", "CHN", "CIN", "CLE", "COL",
           "DET", "HOU", "KCA", "LAN", "MIA", "MIL", "MIN", "NYA", "NYN", "OAK",
           "PHI", "PIT", "SDN", "SEA", "SFN", "SLN", "TBA", "TEX", "TOR", "WAS"],
    2024: ["ANA", "ARI", "ATL", "BAL", "BOS", "CHA", "CHN", "CIN", "CLE", "COL",
           "DET", "HOU", "KCA", "LAN", "MIA", "MIL", "MIN", "NYA", "NYN", "OAK",
           "PHI", "PIT", "SDN", "SEA", "SFN", "SLN", "TBA", "TEX", "TOR", "WAS"],
    2025: ["ANA", "ARI", "ATH", "ATL", "BAL", "BOS", "CHA", "CHN", "CIN", "CLE",
           "COL", "DET", "HOU", "KCA", "LAN", "MIA", "MIL", "MIN", "NYA", "NYN",
           "PHI", "PIT", "SDN", "SEA", "SFN", "SLN", "TBA", "TEX", "TOR", "WAS"],
}


def _lahman_team_id(schedule_id):
    """The Lahman teamID a real 2022–2025 schedule id must resolve to.

    Everything is an identity match except the Angels: Retrosheet ``ANA`` →
    Lahman ``LAA`` (the only modern divergence). ``OAK`` and ``ATH`` are the
    Athletics in both systems; ``CLE`` is the Guardians in both.
    """
    return "LAA" if schedule_id == "ANA" else schedule_id


def _make_stale_schedule_db(tmp_path):
    """A stale (no teamIDretro column) Teams DB seeded from the real id sets.

    For each real (year, schedule id) it inserts the corresponding Lahman
    ``teamID`` row, so exact-match resolves the identity teams and the alias
    table is exercised only for the genuinely divergent ``ANA``.
    """
    db = tmp_path / "stale_schedule.sqlite"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE Teams (yearID TEXT, teamID TEXT)")
    rows = [
        (str(year), _lahman_team_id(sid))
        for year, sids in _REAL_SCHEDULE_TEAM_IDS.items()
        for sid in sids
    ]
    conn.executemany("INSERT INTO Teams (yearID, teamID) VALUES (?,?)", rows)
    conn.commit()
    conn.close()
    return LahmanRepository(str(db))


class TestRealScheduleResolutionStaleDB:
    """Every real 2022–2025 schedule id resolves on a stale DB (FRE-156 DoD)."""

    @pytest.fixture
    def repo(self, tmp_path):
        repo = _make_stale_schedule_db(tmp_path)
        yield repo
        repo.close()

    @pytest.mark.parametrize("year", sorted(_REAL_SCHEDULE_TEAM_IDS))
    def test_all_ids_resolve(self, repo, year):
        # No schedule id in any supported year strands the join as unresolved.
        for sid in _REAL_SCHEDULE_TEAM_IDS[year]:
            resolved = repo.retro_to_lahman_team(sid, year)
            assert resolved == _lahman_team_id(sid), (
                f"{sid} {year} resolved to {resolved!r}"
            )

    def test_angels_diverge_via_alias_each_year(self, repo):
        # The one modern divergence, checked across the whole 2022–2025 window.
        for year in _REAL_SCHEDULE_TEAM_IDS:
            assert repo.retro_to_lahman_team("ANA", year) == "LAA"

    def test_athletics_exact_match_both_eras(self, repo):
        # Oakland (OAK, 2022–2024) and Sacramento (ATH, 2025) both resolve by
        # exact match — no alias row involved.
        assert repo.retro_to_lahman_team("OAK", 2024) == "OAK"
        assert repo.retro_to_lahman_team("ATH", 2025) == "ATH"
        # And the pre-move id is absent from 2025 / new id absent from 2024.
        assert "ATH" not in _REAL_SCHEDULE_TEAM_IDS[2024]
        assert "OAK" not in _REAL_SCHEDULE_TEAM_IDS[2025]

    def test_guardians_stay_cle(self, repo):
        for year in _REAL_SCHEDULE_TEAM_IDS:
            assert repo.retro_to_lahman_team("CLE", year) == "CLE"
