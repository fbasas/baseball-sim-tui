"""Real-format Retrosheet schedule fixtures + both-layout parser tests (FRE-157).

Closes the parser blind spot that let FRE-147 ship green: every prior schedule
fixture was a *synthetic* 12-column row, so the 13-column 2024+ layout — which
inserts a `Location` column and shifts Postponed/Makeup to indices 11/12 — was
never exercised. `parse_schedule_rows`' fixed indices passed every test while
corrupting every modern file. These tests exercise **committed real-format
fixtures** (`tests/fixtures/schedules/2012_head.csv`, `.../2024_head.csv`) that
reproduce the actual on-disk formats — quoting, day-name spelling, and case all
matter — against the FRE-147 format-aware parser in `src/data/schedule_ingest.py`.

No network and no `data/lahman.sqlite`: the committed CSVs are read from disk and
the 2020 two-member ZIP is built in-process with `zipfile`.

Row tuple layout (from `SCHEDULE_COLUMNS`): 0 year, 1 date, 2 game_num, 3 dow,
4 vis_team, 5 vis_league, 6 home_team, 7 home_league, 8 time_of_day,
9 postponed, 10 makeup_date.
"""

import io
import re
import zipfile
from pathlib import Path

import pytest

from src.data import schedule_ingest as si

FIXTURES = Path(__file__).parent / "fixtures" / "schedules"

# The park-code shape (three uppercase letters + two digits, e.g. SEO01) that a
# fixed-index parser wrote into `postponed` for every 13-column row — the exact
# FRE-147 corruption signature. Real postponement text ("Rain", "Cold") never
# matches it, so it is the discriminator the tests assert never leaks.
PARK_CODE = re.compile(r"^[A-Z]{3}\d{2}$")


def _load(name: str) -> str:
    """Read a committed fixture body from tests/fixtures/schedules/."""
    return (FIXTURES / name).read_text()


def _find(rows, date, game_num=0):
    """The single parsed row with this (date, game_num)."""
    return next(r for r in rows if r[1] == date and r[2] == game_num)


# --- 12-column (pre-2024) real layout: 2012_head.csv ------------------------


class TestParse12ColumnRealFixture:
    """The quoted, abbreviated-day 12-column layout — Postponed/Makeup at 10/11."""

    def _rows(self):
        return si.parse_schedule_rows(_load("2012_head.csv"), 2012)

    def test_header_skipped_and_year_injected(self):
        rows = self._rows()
        assert len(rows) == 6  # header dropped, 6 data rows
        assert all(r[0] == 2012 for r in rows)

    def test_normal_game_no_postponement(self):
        # Verbatim opening-day row: neither postponed nor makeup set.
        row = _find(self._rows(), 20120328)
        assert (row[4], row[6]) == ("SEA", "OAK")  # visitor, home
        assert row[9] is None and row[10] is None

    def test_postponed_with_makeup_lands_in_right_columns(self):
        # Verbatim rain-out: Postponed (idx 10) = "Rain", Makeup (idx 11) made up.
        row = _find(self._rows(), 20120410)
        assert row[9] == "Rain"
        assert row[10] == 20120507  # makeup_date as int

    def test_second_verbatim_makeup_row(self):
        row = _find(self._rows(), 20120420)
        assert row[9] == "Rain" and row[10] == 20120421

    def test_doubleheader_parses_as_two_games(self):
        dh = [r for r in self._rows() if r[1] == 20120507]
        assert len(dh) == 2
        assert sorted(r[2] for r in dh) == [1, 2]  # game_num 1 then 2
        # The doubleheader is the makeup slot for the 20120410 rain-out.
        assert all(r[9] is None and r[10] is None for r in dh)

    def test_cancelled_distinguished_from_made_up(self):
        # Postponed with an empty Makeup → cancelled: postponed text set, no date.
        cancelled = _find(self._rows(), 20120629)
        assert cancelled[9] == "Cold" and cancelled[10] is None
        # Contrast: the 20120410 row is postponed *and* made up.
        made_up = _find(self._rows(), 20120410)
        assert made_up[9] is not None and made_up[10] is not None

    def test_no_park_code_leak_in_12col(self):
        # Sanity: nothing in the 12-column layout looks like a park code.
        assert not any(r[9] and PARK_CODE.match(r[9]) for r in self._rows())


# --- 13-column (2024+) real layout: 2024_head.csv ---------------------------


class TestParse13ColumnRealFixture:
    """The unquoted, full-day, Location-bearing 13-column layout (FRE-147).

    These assertions fail on the old fixed-index parser (which read the park
    code at index 10 as `postponed`) and pass only against the FRE-147
    header-name / column-count parser — see `test_regresses_on_fixed_indices`
    for the explicit demonstration.
    """

    def _rows(self):
        return si.parse_schedule_rows(_load("2024_head.csv"), 2024)

    def test_header_skipped_and_year_injected(self):
        rows = self._rows()
        assert len(rows) == 7
        assert all(r[0] == 2024 for r in rows)

    def test_mil_nyn_postponement_lands_in_right_columns(self):
        # The target case: Location=NYC20, Postponed=Rain (idx 11), Makeup=... (12).
        # The MIL@NYN row, not the ANA@BAL row that shares the date.
        row = next(
            r for r in self._rows()
            if r[1] == 20240328 and r[4] == "MIL"
        )
        assert (row[4], row[6]) == ("MIL", "NYN")
        assert row[9] == "Rain"
        assert row[10] == 20240329  # makeup_date as int — not the park code

    def test_seoul_row_is_a_played_game(self):
        # LAN@SDN at SEO01 (Seoul Series) is played, NOT cancelled: the park
        # code must not leak into postponed, and makeup stays empty.
        row = next(r for r in self._rows() if r[1] == 20240320)
        assert (row[4], row[6]) == ("LAN", "SDN")
        assert row[8] == "n"  # lowercase Day/Night preserved
        assert row[9] is None and row[10] is None

    def test_both_seoul_rows_played(self):
        seoul = [r for r in self._rows() if r[1] in (20240320, 20240321)]
        assert len(seoul) == 2
        assert all(r[9] is None and r[10] is None for r in seoul)

    def test_normal_ana_bal_row_played(self):
        row = next(
            r for r in self._rows()
            if r[1] == 20240328 and r[4] == "ANA"
        )
        assert (row[4], row[6]) == ("ANA", "BAL")
        assert row[9] is None and row[10] is None

    def test_doubleheader_parses_as_two_games(self):
        dh = [r for r in self._rows() if r[1] == 20240329]
        assert len(dh) == 2
        assert sorted(r[2] for r in dh) == [1, 2]

    def test_cancelled_distinguished_from_made_up(self):
        # 20240615 COL@SFN: Postponed="Rain" (idx 11), empty Makeup → cancelled.
        cancelled = next(r for r in self._rows() if r[1] == 20240615)
        assert cancelled[9] == "Rain" and cancelled[10] is None

    def test_no_park_code_leaks_into_postponed(self):
        # The core FRE-147 guarantee: across every row, no postponed value has
        # the park-code shape — the Location column is skipped, never stored.
        assert not any(r[9] and PARK_CODE.match(r[9]) for r in self._rows())

    def test_stored_tuple_shape_matches_12col(self):
        # 13-column parse emits the same 11-field tuple as the 12-column parse;
        # Location is parsed-and-skipped, not persisted.
        rows12 = si.parse_schedule_rows(_load("2012_head.csv"), 2012)
        rows13 = self._rows()
        assert len(rows12[0]) == len(rows13[0]) == 11

    def test_regresses_on_fixed_indices(self):
        # Demonstrates the fixture *would* fail a fixed-index parser: reading the
        # 13-column MIL@NYN row at the pre-FRE-147 positions (postponed=fields[10],
        # makeup=fields[11]) mis-reads the park code as postponed and drops the
        # real reason. This is the assertion that regresses if the parser ever
        # reverts to fixed indices.
        header, *body = _load("2024_head.csv").splitlines()
        mil_line = next(l for l in body if l.startswith("20240328,0,Thursday,MIL"))
        fields = mil_line.split(",")
        # Old fixed-index behaviour on a 13-column row:
        old_postponed = fields[10]  # Location — WRONG
        old_makeup = fields[11]     # the real Postponed reason — WRONG
        assert old_postponed == "NYC20"       # park code mistaken for postponed
        assert old_makeup == "Rain"           # reason mistaken for a makeup date
        assert not old_makeup.isdigit()       # → would fail the 8-digit check → None
        # The FRE-147 parser gets it right instead:
        good = next(
            r for r in self._rows()
            if r[1] == 20240328 and r[4] == "MIL"
        )
        assert good[9] == "Rain" and good[10] == 20240329


# --- 2020 two-member ZIP: constructed in-process ----------------------------

# 12-column quoted members mirroring the real 2020SKED.zip. The played slate's
# first row is verbatim from the spec; the orig member carries a distinct row so
# member selection is provable.
_2020_ORIG = (
    'Date,Num,Day,Visitor,League,Game,Home,League,Game,Day/Night,Postponed,Makeup\n'
    '"20200326","0","Thu","SEA","AL",1,"OAK","AL",1,"D","",""\n'
    '"20200328","0","Sat","SEA","AL",2,"OAK","AL",2,"D","",""\n'
)
_2020_PLAYED = (
    'Date,Num,Day,Visitor,League,Game,Home,League,Game,Day/Night,Postponed,Makeup\n'
    '"20200723","0","Thu","NYA","AL",1,"WAS","NL",1,"n","",""\n'
    '"20200724","0","Fri","NYA","AL",2,"WAS","NL",2,"n","Rain","20200725"\n'
)


def _build_2020_zip() -> bytes:
    """A two-member 2020 schedule ZIP (played slate + pre-pandemic original)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("2020sched-orig.csv", _2020_ORIG)
        zf.writestr("2020schedule.csv", _2020_PLAYED)
    return buf.getvalue()


class TestParse2020TwoMemberZip:
    """The 2020 ZIP holds two files; the played (non-`orig`) one must win."""

    def test_pick_schedule_member_selects_played(self):
        member = si.pick_schedule_member(
            ["2020sched-orig.csv", "2020schedule.csv"], 2020
        )
        assert member == "2020schedule.csv"

    def test_pick_schedule_member_order_independent(self):
        # Selection must not depend on member ordering in the archive.
        member = si.pick_schedule_member(
            ["2020schedule.csv", "2020sched-orig.csv"], 2020
        )
        assert member == "2020schedule.csv"

    def test_parse_zip_bytes_reads_only_the_played_member(self):
        rows = si.parse_zip_bytes(_build_2020_zip(), 2020)
        # Only the played slate's two rows — the orig member (which starts in
        # March) was excluded.
        assert len(rows) == 2
        dates = sorted(r[1] for r in rows)
        assert dates == [20200723, 20200724]
        # No March original-schedule dates leaked in.
        assert all(r[1] >= 20200723 for r in rows)

    def test_played_rows_parse_sanely(self):
        rows = si.parse_zip_bytes(_build_2020_zip(), 2020)
        opener = _find(rows, 20200723)
        assert (opener[4], opener[6]) == ("NYA", "WAS")
        assert opener[8] == "n"  # lowercase time-of-day, as in the real 2020 file
        assert opener[9] is None and opener[10] is None
        made_up = _find(rows, 20200724)
        assert made_up[9] == "Rain" and made_up[10] == 20200725
