"""Tests for the year-scoped Retrosheet→Lahman alias fallback (FRE-154).

Covers the alias lookup in isolation and its wiring into
``LahmanRepository.retro_to_lahman_team`` as the *final* resolution step, using
fixture DBs built both with and without the ``teamIDretro`` column. No network
and no full roster DB required.
"""

import sqlite3

import pytest

from src.data.lahman import LahmanRepository
from src.data.retro_team_aliases import resolve_retro_alias


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
