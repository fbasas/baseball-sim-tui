"""Tests for Retrosheet schedule ingestion (FRE-116).

Two layers, house style:

- **Unit** — parse fixture schedule rows and exercise the build-script helpers
  (file selection, year resolution, table create/replace) against an in-memory
  or temp SQLite. No network, no ``data/lahman.sqlite``.
- **Integration** — ``LahmanRepository.get_schedule`` /
  ``retro_to_lahman_team`` / ``has_schedule`` against the real
  ``data/lahman.sqlite``, guarded when the database or schedule data is absent.
  The guard is **loud** (``warnings.warn``) so a skipped integration run is
  visible in the summary rather than indistinguishable from a pass (FRE-158).
"""

import importlib.util
import sqlite3
import warnings
from pathlib import Path

import pytest

from src.data.lahman import LahmanRepository
from src.data.models import ScheduleRow

# Real database — integration tests skip when it (or its schedule data) is absent.
LAHMAN_DB_PATH = Path(__file__).parent.parent / "data" / "lahman.sqlite"


def _load_build_module():
    """Import scripts/build_schedule_db.py by path (scripts is not a package)."""
    path = Path(__file__).parent.parent / "scripts" / "build_schedule_db.py"
    spec = importlib.util.spec_from_file_location("build_schedule_db", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build = _load_build_module()


# --- Fixture: a small schedule file body mirroring real Retrosheet output ---
# Includes a header row, a normal game, a doubleheader (game_num 1 & 2), a
# postponed-with-makeup game, a postponed-without-makeup (cancelled) game,
# and lowercase time-of-day (seen in the 2020 file).
FIXTURE_SCHEDULE = (
    'Date,Num,Day,Visitor,League,Game,Home,League,Game,Day/Night,Postponed,Makeup\n'
    '"20160403","0","Sun","NYN","NL",1,"KCA","AL",1,"N","",""\n'
    '"20160404","0","Mon","BOS","AL",1,"CLE","AL",1,"D","Cold","20160405"\n'
    '"20160705","1","Tue","CHN","NL",80,"CIN","NL",81,"d","",""\n'
    '"20160705","2","Tue","CHN","NL",81,"CIN","NL",82,"n","",""\n'
    '"20160908","0","Thu","SFN","NL",140,"SDN","NL",141,"N","Hurricane",""\n'
)


class TestScheduleRowModel:
    """The ScheduleRow dataclass."""

    def test_defaults(self):
        row = ScheduleRow(
            year=1927,
            date=19270412,
            game_num=0,
            dow="Tue",
            vis_team="BRO",
            vis_league="NL",
            home_team="BSN",
            home_league="NL",
            time_of_day="D",
        )
        assert row.postponed is None
        assert row.makeup_date is None


class TestParseScheduleRows:
    """build_schedule_db.parse_schedule_rows."""

    def test_skips_header(self):
        rows = build.parse_schedule_rows(FIXTURE_SCHEDULE, 2016)
        # 5 data rows, header dropped.
        assert len(rows) == 5
        assert all(r[0] == 2016 for r in rows)  # year injected

    def test_normal_row_fields(self):
        rows = build.parse_schedule_rows(FIXTURE_SCHEDULE, 2016)
        year, date, game_num, dow, vis, visl, home, homel, tod, post, makeup = rows[0]
        assert (date, game_num, dow) == (20160403, 0, "Sun")
        assert (vis, visl, home, homel) == ("NYN", "NL", "KCA", "AL")
        assert tod == "N"
        assert post is None and makeup is None

    def test_postponed_with_makeup(self):
        rows = build.parse_schedule_rows(FIXTURE_SCHEDULE, 2016)
        row = rows[1]
        assert row[9] == "Cold"  # postponed
        assert row[10] == 20160405  # makeup_date (int)

    def test_postponed_without_makeup(self):
        rows = build.parse_schedule_rows(FIXTURE_SCHEDULE, 2016)
        row = rows[4]
        assert row[9] == "Hurricane"
        assert row[10] is None  # cancelled — no makeup

    def test_doubleheader_game_numbers(self):
        rows = build.parse_schedule_rows(FIXTURE_SCHEDULE, 2016)
        dh = [r for r in rows if r[1] == 20160705]
        assert len(dh) == 2
        assert sorted(r[2] for r in dh) == [1, 2]

    def test_lowercase_time_of_day_preserved(self):
        rows = build.parse_schedule_rows(FIXTURE_SCHEDULE, 2016)
        dh = [r for r in rows if r[1] == 20160705]
        assert {r[8] for r in dh} == {"d", "n"}

    def test_empty_and_short_lines_ignored(self):
        text = FIXTURE_SCHEDULE + "\n" + '"bad","row"\n'
        rows = build.parse_schedule_rows(text, 2016)
        assert len(rows) == 5  # blank + short line dropped

    def test_raises_on_no_rows(self):
        # Header only → parses to zero rows (build_year turns this into an error).
        rows = build.parse_schedule_rows(FIXTURE_SCHEDULE.splitlines()[0], 2016)
        assert rows == []


class TestPickScheduleMember:
    """build_schedule_db.pick_schedule_member — ZIP member selection."""

    def test_exact_match(self):
        names = ["2016schedule.csv"]
        assert build.pick_schedule_member(names, 2016) == "2016schedule.csv"

    def test_2020_excludes_orig_prefers_played(self):
        names = ["2020sched-orig.csv", "2020schedule.csv"]
        assert build.pick_schedule_member(names, 2020) == "2020schedule.csv"

    def test_orig_only_is_rejected(self):
        # If the only member is an 'orig' file, none is selectable.
        assert build.pick_schedule_member(["2020sched-orig.csv"], 2020) is None

    def test_rev_fallback(self):
        names = ["2020rev.txt"]
        assert build.pick_schedule_member(names, 2020) == "2020rev.txt"

    def test_none_when_no_data_file(self):
        assert build.pick_schedule_member(["readme.md"], 2016) is None


class TestResolveYears:
    """build_schedule_db.resolve_years — CLI year selection."""

    def _ns(self, **kw):
        import argparse

        defaults = dict(year=None, years=None, start=None, end=None)
        defaults.update(kw)
        return argparse.Namespace(**defaults)

    def test_single_year(self):
        assert build.resolve_years(self._ns(year=2016)) == [2016]

    def test_list(self):
        assert build.resolve_years(self._ns(years="2016,1969,1927")) == [1927, 1969, 2016]

    def test_range(self):
        assert build.resolve_years(self._ns(start=2014, end=2016)) == [2014, 2015, 2016]

    def test_dedup_and_sort(self):
        got = build.resolve_years(self._ns(year=2016, years="2016,1927"))
        assert got == [1927, 2016]

    def test_empty(self):
        assert build.resolve_years(self._ns()) == []


class TestTableBuildIdempotent:
    """create_schedule_table + replace_year against a temp SQLite."""

    def test_create_and_replace_is_idempotent(self, tmp_path):
        db = tmp_path / "test.sqlite"
        conn = sqlite3.connect(str(db))
        try:
            build.create_schedule_table(conn)
            rows = build.parse_schedule_rows(FIXTURE_SCHEDULE, 2016)
            n1 = build.replace_year(conn, 2016, rows)
            n2 = build.replace_year(conn, 2016, rows)  # re-run same year
            assert n1 == n2 == 5
            total = conn.execute("SELECT COUNT(*) FROM Schedules").fetchone()[0]
            assert total == 5  # not doubled — clear+reinsert
            # Index exists.
            idx = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' "
                "AND name='schedules_year_idx'"
            ).fetchone()
            assert idx is not None
        finally:
            conn.close()

    def test_multiple_years_coexist(self, tmp_path):
        db = tmp_path / "test.sqlite"
        conn = sqlite3.connect(str(db))
        try:
            build.create_schedule_table(conn)
            build.replace_year(conn, 2016, build.parse_schedule_rows(FIXTURE_SCHEDULE, 2016))
            build.replace_year(conn, 1927, build.parse_schedule_rows(FIXTURE_SCHEDULE, 1927))
            years = [
                r[0]
                for r in conn.execute(
                    "SELECT DISTINCT year FROM Schedules ORDER BY year"
                ).fetchall()
            ]
            assert years == [1927, 2016]
        finally:
            conn.close()


class TestRepositoryScheduleMethodsUnit:
    """Repository schedule methods against a purpose-built temp DB (no network)."""

    @pytest.fixture
    def repo(self, tmp_path):
        db = tmp_path / "mini.sqlite"
        conn = sqlite3.connect(str(db))
        build.create_schedule_table(conn)
        build.replace_year(conn, 2016, build.parse_schedule_rows(FIXTURE_SCHEDULE, 2016))
        # Minimal Teams table with the teamIDretro join key.
        conn.execute(
            "CREATE TABLE Teams (yearID TEXT, teamID TEXT, teamIDretro TEXT, name TEXT)"
        )
        conn.executemany(
            "INSERT INTO Teams (yearID, teamID, teamIDretro, name) VALUES (?,?,?,?)",
            [
                ("2016", "NYN", "NYN", "New York Mets"),
                ("2016", "KCA", "KCA", "Kansas City Royals"),
                # A team whose Lahman id differs from its Retrosheet id.
                ("2016", "CHC", "CHN", "Chicago Cubs"),
            ],
        )
        conn.commit()
        conn.close()
        repo = LahmanRepository(str(db))
        yield repo
        repo.close()

    def test_get_schedule_ordered(self, repo):
        rows = repo.get_schedule(2016)
        assert len(rows) == 5
        assert all(isinstance(r, ScheduleRow) for r in rows)
        keys = [(r.date, r.game_num) for r in rows]
        assert keys == sorted(keys)
        # Doubleheader appears as two consecutive rows, game_num 1 then 2.
        dh = [r for r in rows if r.date == 20160705]
        assert [r.game_num for r in dh] == [1, 2]

    def test_get_schedule_empty_year(self, repo):
        assert repo.get_schedule(1999) == []

    def test_get_schedule_postponed_fields(self, repo):
        rows = repo.get_schedule(2016)
        cold = next(r for r in rows if r.date == 20160404)
        assert cold.postponed == "Cold"
        assert cold.makeup_date == 20160405
        cancelled = next(r for r in rows if r.date == 20160908)
        assert cancelled.postponed == "Hurricane"
        assert cancelled.makeup_date is None

    def test_has_schedule(self, repo):
        assert repo.has_schedule(2016) is True
        assert repo.has_schedule(1999) is False

    def test_retro_to_lahman_exact(self, repo):
        assert repo.retro_to_lahman_team("NYN", 2016) == "NYN"

    def test_retro_to_lahman_via_teamidretro(self, repo):
        # Retrosheet CHN → Lahman CHC via teamIDretro.
        assert repo.retro_to_lahman_team("CHN", 2016) == "CHC"

    def test_retro_to_lahman_unresolved(self, repo):
        assert repo.retro_to_lahman_team("ZZZ", 2016) is None

    def test_retro_to_lahman_wrong_year(self, repo):
        assert repo.retro_to_lahman_team("NYN", 1999) is None


class TestRetroLahmanAliasEras:
    """``retro_to_lahman_team`` across the real Retrosheet≠Lahman franchise eras.

    Asserts the ``teamIDretro``-column-present resolution path (a fresh / rebuilt
    DB) for the divergences that broke historical seasons at runtime (FRE-148):
    ``ANA``→``LAA`` (2005+) and ``MIL``→``ML4`` (1970–1997), each contrasted with
    a year where the same Retrosheet id maps to itself — so the *year-scoping* is
    what's under test, not just a static alias. Mappings are from FRE-154's
    authoritative six-mapping table (``docs/specs/retro-lahman-team-join-fix.md``).

    Boundary (do not duplicate FRE-154): the column-*absent* stale-DB path, where
    a committed alias table becomes the resolver, is FRE-154's ``risk:high``
    regression surface and is intentionally not exercised here — every fixture DB
    below carries a ``teamIDretro`` column.
    """

    @pytest.fixture
    def alias_repo(self, tmp_path):
        db = tmp_path / "alias.sqlite"
        conn = sqlite3.connect(str(db))
        conn.execute(
            "CREATE TABLE Teams (yearID TEXT, teamID TEXT, teamIDretro TEXT, name TEXT)"
        )
        conn.executemany(
            "INSERT INTO Teams (yearID, teamID, teamIDretro, name) VALUES (?,?,?,?)",
            [
                # ANA: same Retrosheet id, different year → different Lahman id.
                ("2004", "ANA", "ANA", "Anaheim Angels"),
                ("2019", "LAA", "ANA", "Los Angeles Angels of Anaheim"),
                # MIL: divergent 1970–1997 (ML4), converges to itself in the modern era.
                ("1994", "ML4", "MIL", "Milwaukee Brewers"),
                ("2019", "MIL", "MIL", "Milwaukee Brewers"),
                # Pre-war divergence.
                ("1899", "WAS", "WSN", "Washington Senators"),
                # Exact-match control (Retrosheet id == Lahman teamID).
                ("2019", "NYA", "NYA", "New York Yankees"),
            ],
        )
        conn.commit()
        conn.close()
        repo = LahmanRepository(str(db))
        yield repo
        repo.close()

    def test_ana_resolves_to_laa_modern(self, alias_repo):
        # 2005+ : Retrosheet keeps ANA, Lahman teamID is LAA.
        assert alias_repo.retro_to_lahman_team("ANA", 2019) == "LAA"

    def test_ana_resolves_to_ana_2004(self, alias_repo):
        # Pre-2005 : the same Retrosheet id maps to Lahman ANA.
        assert alias_repo.retro_to_lahman_team("ANA", 2004) == "ANA"

    def test_ana_is_year_scoped(self, alias_repo):
        # The same Retrosheet id must resolve differently by year — the exact
        # silent-exact-match blind spot from FRE-148.
        assert alias_repo.retro_to_lahman_team("ANA", 2019) != alias_repo.retro_to_lahman_team(
            "ANA", 2004
        )

    def test_mil_resolves_to_ml4_1994(self, alias_repo):
        # 1970–1997 : Retrosheet MIL, Lahman teamID is ML4.
        assert alias_repo.retro_to_lahman_team("MIL", 1994) == "ML4"

    def test_mil_resolves_to_mil_modern(self, alias_repo):
        # Modern era : Retrosheet id and Lahman teamID have converged.
        assert alias_repo.retro_to_lahman_team("MIL", 2019) == "MIL"

    def test_mil_is_year_scoped(self, alias_repo):
        assert alias_repo.retro_to_lahman_team("MIL", 1994) != alias_repo.retro_to_lahman_team(
            "MIL", 2019
        )

    def test_wsn_resolves_to_was_prewar(self, alias_repo):
        # Pre-war divergence (WSN → WAS).
        assert alias_repo.retro_to_lahman_team("WSN", 1899) == "WAS"

    def test_exact_match_control(self, alias_repo):
        assert alias_repo.retro_to_lahman_team("NYA", 2019) == "NYA"

    def test_unknown_retro_id_unresolved(self, alias_repo):
        assert alias_repo.retro_to_lahman_team("ZZZ", 2019) is None

    def test_right_id_wrong_year_unresolved(self, alias_repo):
        # ANA is a real Retrosheet id, but no team carries it (as teamIDretro or
        # teamID) in 1994 → unresolved rather than silently mismatched.
        assert alias_repo.retro_to_lahman_team("ANA", 1994) is None


class TestHasScheduleNoTable:
    """has_schedule returns False (not raising) when the Schedules table is absent."""

    def test_missing_table(self, tmp_path):
        db = tmp_path / "noschedule.sqlite"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE Teams (yearID TEXT, teamID TEXT)")
        conn.commit()
        conn.close()
        repo = LahmanRepository(str(db))
        try:
            assert repo.has_schedule(2016) is False
        finally:
            repo.close()


# --- Integration: real data/lahman.sqlite, guarded ---


@pytest.fixture
def lahman_repo():
    if not LAHMAN_DB_PATH.exists():
        warnings.warn(
            f"Lahman database not found at {LAHMAN_DB_PATH} — schedule "
            "integration tests skipped (build data/lahman.sqlite to run them)",
            stacklevel=2,
        )
        pytest.skip(f"Lahman database not found at {LAHMAN_DB_PATH}")
    repo = LahmanRepository(str(LAHMAN_DB_PATH))
    yield repo
    repo.close()


def _skip_without_schedule(repo, year):
    if not repo.has_schedule(year):
        warnings.warn(
            f"No ingested schedule data for {year} — schedule integration "
            "skipped (run build_schedule_db.py to populate it)",
            stacklevel=2,
        )
        pytest.skip(f"No schedule data for {year} — run build_schedule_db.py")


class TestScheduleIntegration:
    """DB-backed assertions — skip when schedule data is absent."""

    def test_get_schedule_2016(self, lahman_repo):
        _skip_without_schedule(lahman_repo, 2016)
        rows = lahman_repo.get_schedule(2016)
        assert len(rows) > 2000  # ~2430 games in a modern season
        keys = [(r.date, r.game_num) for r in rows]
        assert keys == sorted(keys)

    def test_retro_to_lahman_2016(self, lahman_repo):
        _skip_without_schedule(lahman_repo, 2016)
        # Every team id in the schedule must resolve to a Lahman teamID.
        rows = lahman_repo.get_schedule(2016)
        retro_ids = {r.vis_team for r in rows} | {r.home_team for r in rows}
        unresolved = [
            rid for rid in retro_ids
            if lahman_repo.retro_to_lahman_team(rid, 2016) is None
        ]
        assert unresolved == []
