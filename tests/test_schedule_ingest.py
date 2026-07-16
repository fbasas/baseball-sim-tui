"""Tests for the runtime-importable schedule ingest module (FRE-144).

`src/data/schedule_ingest.py` is the single home of the Retrosheet
download/parse/insert core. These tests exercise it **without any network or
fixture download** — the schedule ZIP is synthesized in-test with ``zipfile``,
and fetch is either injected or read from a ``local_zip`` on disk. They cover:

- ``schedule_available_for`` bounds + the 1876 gap;
- ``fetch_schedule_rows`` via an injected fetcher and via ``local_zip`` —
  header skip, a normal year, doubleheader, postponed-with-makeup,
  postponed-no-makeup, and the 2020 two-file (``orig``) member pick;
- ``ingest_rows`` into an **in-memory** DB — idempotent per year, and rows
  round-trip through the existing ``LahmanRepository.get_schedule``.
"""

import io
import sqlite3
import zipfile

import pytest

from src.data import schedule_ingest as si
from src.data.lahman import LahmanRepository
from src.data.models import ScheduleRow

# --- A small schedule file body mirroring real Retrosheet output ------------
# Header row, a normal game, a doubleheader (game_num 1 & 2), a
# postponed-with-makeup game, a postponed-without-makeup (cancelled) game, and
# lowercase time-of-day (as seen in the 2020 file).
FIXTURE_SCHEDULE = (
    'Date,Num,Day,Visitor,League,Game,Home,League,Game,Day/Night,Postponed,Makeup\n'
    '"20160403","0","Sun","NYN","NL",1,"KCA","AL",1,"N","",""\n'
    '"20160404","0","Mon","BOS","AL",1,"CLE","AL",1,"D","Cold","20160405"\n'
    '"20160705","1","Tue","CHN","NL",80,"CIN","NL",81,"d","",""\n'
    '"20160705","2","Tue","CHN","NL",81,"CIN","NL",82,"n","",""\n'
    '"20160908","0","Thu","SFN","NL",140,"SDN","NL",141,"N","Hurricane",""\n'
)

# --- The 2024+ 13-column layout (FRE-147) -----------------------------------
# Retrosheet inserted a 13th `Location` (ballpark-code) column between
# `Day/Night` and `Postponed` starting with the 2024 file. A normal game, a
# postponed-with-makeup game, and a postponed-without-makeup game — each row
# carries a park code that must never leak into `postponed`.
FIXTURE_SCHEDULE_13COL = (
    'Date,Num,Day,Visitor,League,Game,Home,League,Game,Day/Night,Location,Postponed,Makeup\n'
    '"20240328","0","Thu","OAK","AL",1,"SEA","AL",1,"N","SEO01","",""\n'
    '"20240402","0","Tue","BOS","AL",1,"OAK","AL",1,"D","OAK01","Rain","20240403"\n'
    '"20240615","0","Sat","SDN","NL",1,"CHN","NL",1,"D","TOK01","Hurricane",""\n'
)


def _make_zip(members: dict) -> bytes:
    """Build an in-memory ZIP from ``{member_name: text}`` — no network, no fs."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, text in members.items():
            zf.writestr(name, text)
    return buf.getvalue()


def _year_zip(year: int, text: str = FIXTURE_SCHEDULE) -> bytes:
    """A single-member schedule ZIP named the way Retrosheet names them."""
    return _make_zip({f"{year}schedule.csv": text})


class TestScheduleAvailableFor:
    """schedule_available_for — coverage bounds and the 1876 gap."""

    def test_bounds_inclusive(self):
        assert si.schedule_available_for(si.SCHEDULE_MIN_YEAR) is True
        assert si.schedule_available_for(si.SCHEDULE_MAX_YEAR) is True
        assert si.schedule_available_for(1877) is True
        assert si.schedule_available_for(2026) is True

    def test_1876_gap(self):
        # 1876 sits inside the numeric range but Retrosheet has no ZIP for it.
        assert si.schedule_available_for(1876) is False

    def test_outside_bounds(self):
        assert si.schedule_available_for(si.SCHEDULE_MIN_YEAR - 1) is False
        assert si.schedule_available_for(si.SCHEDULE_MAX_YEAR + 1) is False
        assert si.schedule_available_for(1875) is False
        assert si.schedule_available_for(2027) is False

    def test_constants(self):
        assert si.SCHEDULE_MIN_YEAR == 1877
        assert si.SCHEDULE_MAX_YEAR == 2026


class TestFetchScheduleRowsInjected:
    """fetch_schedule_rows with an injected fetcher — never touches the network."""

    def test_parses_normal_year_and_skips_header(self):
        captured = {}

        def fake_fetch(url):
            captured["url"] = url
            return _year_zip(2016)

        rows = si.fetch_schedule_rows(2016, fetch=fake_fetch)
        # 5 data rows; the header row is dropped.
        assert len(rows) == 5
        assert all(r[0] == 2016 for r in rows)  # year injected
        # The default URL template was formatted with the year.
        assert captured["url"] == si.SCHEDULE_URL.format(year=2016)

    def test_normal_row_fields(self):
        rows = si.fetch_schedule_rows(2016, fetch=lambda url: _year_zip(2016))
        year, date, game_num, dow, vis, visl, home, homel, tod, post, makeup = rows[0]
        assert (date, game_num, dow) == (20160403, 0, "Sun")
        assert (vis, visl, home, homel) == ("NYN", "NL", "KCA", "AL")
        assert tod == "N"
        assert post is None and makeup is None

    def test_doubleheader(self):
        rows = si.fetch_schedule_rows(2016, fetch=lambda url: _year_zip(2016))
        dh = [r for r in rows if r[1] == 20160705]
        assert sorted(r[2] for r in dh) == [1, 2]

    def test_postponed_with_makeup(self):
        rows = si.fetch_schedule_rows(2016, fetch=lambda url: _year_zip(2016))
        row = next(r for r in rows if r[1] == 20160404)
        assert row[9] == "Cold"       # postponed reason
        assert row[10] == 20160405    # makeup_date as int

    def test_postponed_without_makeup(self):
        rows = si.fetch_schedule_rows(2016, fetch=lambda url: _year_zip(2016))
        row = next(r for r in rows if r[1] == 20160908)
        assert row[9] == "Hurricane"
        assert row[10] is None        # cancelled — no makeup

    def test_url_template_override(self):
        captured = {}

        def fake_fetch(url):
            captured["url"] = url
            return _year_zip(1927)

        si.fetch_schedule_rows(
            1927, fetch=fake_fetch, url_template="http://example.test/{year}.zip"
        )
        assert captured["url"] == "http://example.test/1927.zip"

    def test_2020_excludes_orig_member(self):
        # The 2020 ZIP carries the played slate and a pre-pandemic 'orig' file;
        # the played one must win. Give them distinct bodies to prove selection.
        orig = FIXTURE_SCHEDULE.replace("20160403", "20200723")
        played = (
            'Date,Num,Day,Visitor,League,Game,Home,League,Game,Day/Night,Postponed,Makeup\n'
            '"20200724","0","Fri","NYN","NL",1,"WAS","NL",1,"N","",""\n'
        )
        data = _make_zip({"2020sched-orig.csv": orig, "2020schedule.csv": played})
        rows = si.fetch_schedule_rows(2020, fetch=lambda url: data)
        # Only the played file's single row — the orig member was excluded.
        assert len(rows) == 1
        assert rows[0][1] == 20200724


class TestFetchScheduleRowsLocalZip:
    """fetch_schedule_rows via local_zip — reads a ZIP on disk, no network."""

    def test_local_zip_parses(self, tmp_path):
        zip_path = tmp_path / "2016SKED.zip"
        zip_path.write_bytes(_year_zip(2016))
        rows = si.fetch_schedule_rows(2016, local_zip=zip_path)
        assert len(rows) == 5

    def test_local_zip_takes_precedence_over_fetch(self, tmp_path):
        # local_zip wins; the fetch stub must never be called.
        zip_path = tmp_path / "2016SKED.zip"
        zip_path.write_bytes(_year_zip(2016))

        def boom(url):
            raise AssertionError("fetch should not be called when local_zip is set")

        rows = si.fetch_schedule_rows(2016, fetch=boom, local_zip=zip_path)
        assert len(rows) == 5

    def test_non_zip_bytes_raise(self, tmp_path):
        # A 404 HTML page (no ZIP magic) → clear error, not a confusing parse.
        bad = tmp_path / "bad.zip"
        bad.write_bytes(b"<html>404 Not Found</html>")
        with pytest.raises(ValueError, match="not a valid ZIP"):
            si.fetch_schedule_rows(1876, local_zip=bad)

    def test_zip_without_schedule_member_raises(self, tmp_path):
        # No .csv/.txt member → nothing selectable → clear error.
        data = _make_zip({"readme.md": "no schedule here"})
        path = tmp_path / "empty.zip"
        path.write_bytes(data)
        with pytest.raises(ValueError, match="no schedule file"):
            si.fetch_schedule_rows(2016, local_zip=path)


class TestParseZipBytes:
    """parse_zip_bytes — pure ZIP→rows with a magic-byte guard, no network/DB."""

    def test_rejects_non_zip(self):
        with pytest.raises(ValueError, match="not a valid ZIP"):
            si.parse_zip_bytes(b"<html>nope</html>", 1876)

    def test_parses_valid_zip(self):
        rows = si.parse_zip_bytes(_year_zip(2016), 2016)
        assert len(rows) == 5


class TestIngestRows:
    """ingest_rows into an in-memory DB — idempotent, and rows round-trip."""

    def test_idempotent_per_year(self):
        conn = sqlite3.connect(":memory:")
        try:
            rows = si.fetch_schedule_rows(2016, fetch=lambda url: _year_zip(2016))
            n1 = si.ingest_rows(conn, 2016, rows)
            n2 = si.ingest_rows(conn, 2016, rows)  # re-ingest same year
            assert n1 == n2 == 5
            total = conn.execute("SELECT COUNT(*) FROM Schedules").fetchone()[0]
            assert total == 5  # clear+reinsert, not doubled
        finally:
            conn.close()

    def test_creates_table_and_index(self):
        conn = sqlite3.connect(":memory:")
        try:
            rows = si.fetch_schedule_rows(2016, fetch=lambda url: _year_zip(2016))
            si.ingest_rows(conn, 2016, rows)
            idx = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' "
                "AND name='schedules_year_idx'"
            ).fetchone()
            assert idx is not None
        finally:
            conn.close()

    def test_multiple_years_coexist(self):
        conn = sqlite3.connect(":memory:")
        try:
            si.ingest_rows(
                conn, 2016, si.fetch_schedule_rows(2016, fetch=lambda url: _year_zip(2016))
            )
            si.ingest_rows(
                conn, 1927, si.fetch_schedule_rows(1927, fetch=lambda url: _year_zip(1927))
            )
            years = [
                r[0]
                for r in conn.execute(
                    "SELECT DISTINCT year FROM Schedules ORDER BY year"
                ).fetchall()
            ]
            assert years == [1927, 2016]
        finally:
            conn.close()

    def test_rows_round_trip_through_get_schedule(self, tmp_path):
        # Ingest into a real (on-disk) DB, then read back through the existing
        # repository API — the round trip the app depends on.
        db = tmp_path / "mini.sqlite"
        conn = sqlite3.connect(str(db))
        rows = si.fetch_schedule_rows(2016, fetch=lambda url: _year_zip(2016))
        si.ingest_rows(conn, 2016, rows)
        conn.close()

        repo = LahmanRepository(str(db))
        try:
            assert repo.has_schedule(2016) is True
            got = repo.get_schedule(2016)
            assert len(got) == 5
            assert all(isinstance(r, ScheduleRow) for r in got)
            # Ordered by (date, game_num); the doubleheader is 1 then 2.
            keys = [(r.date, r.game_num) for r in got]
            assert keys == sorted(keys)
            dh = [r for r in got if r.date == 20160705]
            assert [r.game_num for r in dh] == [1, 2]
            # Postponed fields survive the round trip.
            cold = next(r for r in got if r.date == 20160404)
            assert cold.postponed == "Cold" and cold.makeup_date == 20160405
            cancelled = next(r for r in got if r.date == 20160908)
            assert cancelled.postponed == "Hurricane" and cancelled.makeup_date is None
        finally:
            repo.close()


class TestParse13ColumnLayout:
    """parse_schedule_rows on the 2024+ 13-column (Location) layout (FRE-147)."""

    def _rows(self):
        return si.parse_schedule_rows(FIXTURE_SCHEDULE_13COL, 2024)

    def test_row_count_and_year_header_skipped(self):
        rows = self._rows()
        assert len(rows) == 3               # header dropped
        assert all(r[0] == 2024 for r in rows)

    def test_normal_game_park_code_not_in_postponed(self):
        row = next(r for r in self._rows() if r[1] == 20240328)
        # postponed (idx 9) and makeup_date (idx 10) are both empty — the park
        # code SEO01 must NOT have landed in postponed.
        assert row[9] is None and row[10] is None

    def test_postponed_with_makeup(self):
        row = next(r for r in self._rows() if r[1] == 20240402)
        assert row[9] == "Rain"
        assert row[10] == 20240403          # makeup_date as int

    def test_postponed_without_makeup(self):
        row = next(r for r in self._rows() if r[1] == 20240615)
        assert row[9] == "Hurricane"
        assert row[10] is None              # cancelled — no makeup

    def test_no_park_code_leaks_into_postponed(self):
        # No row's postponed value looks like a park code (^[A-Z]{3}\d{2}$).
        import re

        park = re.compile(r"^[A-Z]{3}\d{2}$")
        assert not any(r[9] and park.match(r[9]) for r in self._rows())

    def test_stored_fields_identical_shape_to_12col(self):
        # The 2024+ parse emits the same 11-field tuple as the 12-column parse;
        # Location is skipped, not stored.
        rows12 = si.parse_schedule_rows(FIXTURE_SCHEDULE, 2016)
        rows13 = self._rows()
        assert len(rows12[0]) == len(rows13[0]) == 11

    def test_12col_fixture_unchanged(self):
        # No regression: the pre-2024 layout still parses exactly as before.
        rows = si.parse_schedule_rows(FIXTURE_SCHEDULE, 2016)
        assert len(rows) == 5
        cold = next(r for r in rows if r[1] == 20160404)
        assert cold[9] == "Cold" and cold[10] == 20160405
        normal = next(r for r in rows if r[1] == 20160403)
        assert normal[9] is None and normal[10] is None

    def test_headerless_13col_falls_back_to_column_count(self):
        # A headerless 13-column body still parses via the column-count fallback
        # (Location at idx 10, postponed at 11, makeup at 12).
        body = "\n".join(FIXTURE_SCHEDULE_13COL.splitlines()[1:])  # drop header
        rows = si.parse_schedule_rows(body, 2024)
        assert len(rows) == 3
        row = next(r for r in rows if r[1] == 20240402)
        assert row[9] == "Rain" and row[10] == 20240403
        normal = next(r for r in rows if r[1] == 20240328)
        assert normal[9] is None and normal[10] is None

    def test_headerless_12col_falls_back_to_column_count(self):
        body = "\n".join(FIXTURE_SCHEDULE.splitlines()[1:])  # drop header
        rows = si.parse_schedule_rows(body, 2016)
        assert len(rows) == 5
        cold = next(r for r in rows if r[1] == 20160404)
        assert cold[9] == "Cold" and cold[10] == 20160405


class TestScheduleYearIsCorrupt:
    """schedule_year_is_corrupt — the stale-cache corruption signature (FRE-147)."""

    def _ingest_and_read(self, tmp_path, text, year):
        """Round-trip a fixture body through ingest_rows + get_schedule."""
        db = tmp_path / "sched.sqlite"
        conn = sqlite3.connect(str(db))
        si.ingest_rows(conn, year, si.parse_schedule_rows(text, year))
        conn.close()
        repo = LahmanRepository(str(db))
        try:
            return repo.get_schedule(year), repo
        finally:
            pass  # repo returned so the caller can also exercise repo methods

    def test_empty_year_not_corrupt(self):
        assert si.schedule_year_is_corrupt([]) is False

    def test_corrupt_year_flagged(self, tmp_path):
        # Simulate the pre-fix parse of a 13-column file: read the fixture with
        # the OLD fixed-index behavior so the park code lands in postponed.
        corrupt_body = (
            'Date,Num,Day,Visitor,League,Game,Home,League,Game,Day/Night,Postponed,Makeup\n'
            '"20240328","0","Thu","OAK","AL",1,"SEA","AL",1,"N","SEO01",""\n'
            '"20240402","0","Tue","BOS","AL",1,"OAK","AL",1,"D","OAK01","Rain"\n'
            '"20240615","0","Sat","SDN","NL",1,"CHN","NL",1,"D","TOK01","Hurricane"\n'
        )
        rows, repo = self._ingest_and_read(tmp_path, corrupt_body, 2024)
        try:
            assert all(r.postponed for r in rows)  # every row has a park code
            assert si.schedule_year_is_corrupt(rows) is True
            assert repo.schedule_needs_repair(2024) is True
        finally:
            repo.close()

    def test_healthy_year_not_flagged(self, tmp_path):
        # The 12-column fixture: two real postponed rows, the rest empty.
        rows, repo = self._ingest_and_read(tmp_path, FIXTURE_SCHEDULE, 2016)
        try:
            assert si.schedule_year_is_corrupt(rows) is False
            assert repo.schedule_needs_repair(2016) is False
        finally:
            repo.close()

    def test_fixed_13col_parse_not_flagged(self, tmp_path):
        # After the parser fix, a real 2024 file parses healthily and must NOT
        # be flagged corrupt (only the genuinely postponed rows carry postponed).
        rows, repo = self._ingest_and_read(tmp_path, FIXTURE_SCHEDULE_13COL, 2024)
        try:
            assert si.schedule_year_is_corrupt(rows) is False
            assert repo.schedule_needs_repair(2024) is False
        finally:
            repo.close()


class TestNoImportSideEffects:
    """The module must be importable with no network and no side effects."""

    def test_reimport_is_clean(self):
        import importlib

        # Re-importing must not raise or perform I/O.
        importlib.reload(si)
        assert si.SCHEDULE_URL.endswith("{year}SKED.zip")
