"""Tests for the historical-season schedule builder (FRE-117).

Two layers, house style:

* **Unit** — a pure, DB-free ``FakeRepo`` feeds synthetic ``ScheduleRow``s
  through ``build_historical_season``, exercising the postponed/makeup rule (a
  doubleheader, a cancelled drop, a makeup move), team-resolution failures, and
  the ``day == list index`` / sequential-``game_id`` invariants. Plus the model
  round-trips: ``SeasonState.from_schedule``, the now-``Optional``
  ``games_per_opponent``, and ``LeagueTeam`` league/division — including an
  existing round-robin save (int game count, no league/division keys) still
  loading unchanged.
* **Offline integration** — a full-league-shaped season built entirely
  in-process via ``tests.support.mini_lahman`` and checked with the
  ``assert_season_invariants`` harness. This **always runs** (no skip), closing
  the "integration tests never execute" gap (FRE-158), and a negative case
  proves the harness rejects a degenerate 2-team/1-game season.
* **DB-backed integration** — one real year, guarded when ``data/lahman.sqlite``
  or its schedule data is absent. The guard is **loud** (``warnings.warn``) so a
  skipped run is visible in the summary, not indistinguishable from a pass, and
  the assertion is the same ``assert_season_invariants`` harness.
"""

import json
import warnings
from pathlib import Path

import pytest

from src.data.models import ScheduleRow, TeamSeason
from src.season.historical import (
    MIN_GAME_RETENTION,
    MIN_GAMES_PER_TEAM,
    DegenerateHistoricalSeasonError,
    HistoricalSeasonError,
    build_historical_season,
)
from src.season.state import LeagueTeam, SeasonState
from tests.support.mini_lahman import build_mini_lahman
from tests.support.season_invariants import assert_season_invariants


# --- DB-free fixtures --------------------------------------------------------

YEAR = 1927


def srow(date, game_num, vis, home, postponed=None, makeup=None):
    """A synthetic Retrosheet schedule row (Retrosheet team ids)."""
    return ScheduleRow(
        year=YEAR,
        date=date,
        game_num=game_num,
        dow="Fri",
        vis_team=vis,
        vis_league="AL",
        home_team=home,
        home_league="AL",
        time_of_day="D",
        postponed=postponed,
        makeup_date=makeup,
    )


# Retrosheet id -> Lahman teamID (deliberately different ids to exercise the
# retro->lahman resolution rather than an identity passthrough).
RETRO_MAP = {"rA": "TA", "rB": "TB", "rC": "TC", "rD": "TD"}

# Lahman team_id -> (league, division). TA/TB in AL East, TC/TD in NL (no div).
TEAM_META = {
    "TA": ("AL", "E"),
    "TB": ("AL", "E"),
    "TC": ("NL", ""),
    "TD": ("NL", ""),
}


class FakeRepo:
    """Minimal stand-in for ``LahmanRepository`` for the builder.

    Only the four methods the builder calls are implemented. ``retro_map`` /
    ``team_meta`` / ``rosters`` can be overridden to simulate failures.
    """

    def __init__(self, schedule, retro_map=None, team_meta=None, rosters=None):
        self._schedule = list(schedule)
        self._retro_map = RETRO_MAP if retro_map is None else retro_map
        self._team_meta = TEAM_META if team_meta is None else team_meta
        # Default: every team with metadata has a non-empty roster.
        if rosters is None:
            rosters = {tid: ["player"] for tid in self._team_meta}
        self._rosters = rosters

    def get_schedule(self, year):
        return list(self._schedule)

    def retro_to_lahman_team(self, retro_id, year):
        return self._retro_map.get(retro_id)

    def get_team_season(self, team_id, year):
        meta = self._team_meta.get(team_id)
        if meta is None:
            return None
        league, division = meta
        return TeamSeason(
            team_id=team_id,
            year=year,
            league_id=league,
            team_name=f"{team_id} Club",
            division=division,
        )

    def get_team_roster(self, team_id, year):
        return list(self._rosters.get(team_id, []))


def standard_schedule():
    """A 4-team slate covering a DH, a cancelled drop, and a makeup move.

    * 19270401 — two normal games (rA@rB, rC@rD)          -> day 0 (2 games)
    * 19270402 — a doubleheader (rA@rC game 1 & 2)        -> day 1 (2 games)
    * 19270403 — rB@rD postponed, no makeup               -> dropped
    * 19270404 — rB@rC postponed, made up 19270405        -> moves to day 2
    * 19270405 — rD@rA normal                             -> day 2 (2 games)
    """
    return [
        srow(19270401, 0, "rA", "rB"),
        srow(19270401, 0, "rC", "rD"),
        srow(19270402, 1, "rA", "rC"),
        srow(19270402, 2, "rA", "rC"),
        srow(19270403, 0, "rB", "rD", postponed="rain", makeup=None),
        srow(19270404, 0, "rB", "rC", postponed="rain", makeup=19270405),
        srow(19270405, 0, "rD", "rA"),
    ]


# --- Realistic-slate builders (for the season-shape validation tests) --------
#
# These synthesize slates the *shape* gate can judge: enough teams and enough
# games per team to look like a real season (or, deliberately, not). They use
# generic Retrosheet ids ``r0..rN`` mapped to Lahman ``R0..RN`` so a passing
# slate also builds end-to-end.


def round_robin(team_ids, rounds, start_date=19270401, cancelled=False):
    """A circle-method schedule: every team plays exactly ``rounds`` games.

    Each round pairs the teams up (one game per team) via the standard circle
    rotation; every game gets its own date so nothing is read as a
    doubleheader. With ``cancelled=True`` every row is a postponed-no-makeup
    drop (contributes to the raw slate but never to the played slate). Requires
    an even ``len(team_ids)``.
    """
    order = list(team_ids)
    n = len(order)
    rows = []
    date = start_date
    for _ in range(rounds):
        for i in range(n // 2):
            rows.append(
                srow(
                    date,
                    0,
                    order[i],
                    order[n - 1 - i],
                    postponed="rain" if cancelled else None,
                )
            )
            date += 1
        # Circle rotation: fix the first team, rotate the rest.
        order = [order[0]] + [order[-1]] + order[1:-1]
    return rows


def team_ids(n):
    """``["r0", "r1", ...]`` — n generic Retrosheet ids."""
    return [f"r{i}" for i in range(n)]


def realistic_repo(ids, rows):
    """A ``FakeRepo`` whose metadata resolves every id in ``ids``.

    ``rN`` -> Lahman ``RN``; leagues alternate AL/NL, no divisions. Lets a
    slate that *passes* validation also build all the way to a ``SeasonState``.
    """
    retro_map = {t: t.upper() for t in ids}
    team_meta = {
        t.upper(): ("AL" if i % 2 == 0 else "NL", "")
        for i, t in enumerate(ids)
    }
    rosters = {t.upper(): ["player"] for t in ids}
    return FakeRepo(
        rows, retro_map=retro_map, team_meta=team_meta, rosters=rosters
    )


def corrupt_2024_slate():
    """The 2024 bug reproduced in miniature: 2430 raw rows, 1 playable game.

    A full 30-team schedule where every game but one is cancelled — so 30 teams
    are scheduled but only 2 ever play, retention is ~0.04%, and the surviving
    team plays a single game. Trips all three shape checks at once.
    """
    ids = team_ids(30)
    rows = round_robin(ids, 162, cancelled=True)  # 30/2 * 162 = 2430 rows
    first = rows[0]  # r0 (vis) @ r29 (home) — flip it back to played
    rows[0] = srow(first.date, 0, first.vis_team, first.home_team)
    return ids, rows


# --- Builder unit tests ------------------------------------------------------


class TestBuildHistoricalSeason:
    def test_empty_schedule_raises_value_error(self):
        with pytest.raises(ValueError, match="no schedule data for 1927"):
            build_historical_season(FakeRepo([]), YEAR)

    def test_all_cancelled_raises_value_error(self):
        rows = [srow(19270401, 0, "rA", "rB", postponed="rain", makeup=None)]
        with pytest.raises(ValueError, match="no played games"):
            build_historical_season(FakeRepo(rows), YEAR)

    def test_day_count_drops_cancelled_and_moves_makeup(self):
        state = build_historical_season(
            FakeRepo(standard_schedule()), YEAR, validate=False
        )
        # 3 distinct effective dates: 04-01, 04-02, 04-05. The cancelled
        # 04-03 game and the emptied 04-04 date produce no SeasonDay.
        assert len(state.schedule) == 3
        assert [len(day) for day in state.schedule] == [2, 2, 2]

    def test_day_equals_list_index(self):
        state = build_historical_season(
            FakeRepo(standard_schedule()), YEAR, validate=False
        )
        for index, day in enumerate(state.schedule):
            for game in day:
                assert game.day == index

    def test_game_ids_sequential_in_play_order(self):
        state = build_historical_season(
            FakeRepo(standard_schedule()), YEAR, validate=False
        )
        ids = [g.game_id for day in state.schedule for g in day]
        assert ids == [0, 1, 2, 3, 4, 5]

    def test_doubleheader_is_two_games_same_day_same_teams(self):
        state = build_historical_season(
            FakeRepo(standard_schedule()), YEAR, validate=False
        )
        day1 = state.schedule[1]  # 19270402
        assert len(day1) == 2
        # Both games are TC (home) vs TA (away) — a doubleheader.
        assert all(g.home_key == "TC-1927" for g in day1)
        assert all(g.away_key == "TA-1927" for g in day1)

    def test_cancelled_game_absent(self):
        state = build_historical_season(
            FakeRepo(standard_schedule()), YEAR, validate=False
        )
        # The dropped 04-03 game was TB (home) vs TD (away): never scheduled.
        for day in state.schedule:
            for g in day:
                assert not (g.home_key == "TB-1927" and g.away_key == "TD-1927")

    def test_makeup_game_lands_on_makeup_day(self):
        state = build_historical_season(
            FakeRepo(standard_schedule()), YEAR, validate=False
        )
        day2 = state.schedule[2]  # effective date 19270405
        # The moved game (rB@rC -> TC home / TB away) shares day 2 with the
        # already-scheduled rD@rA (TA home / TD away) — a makeup doubleheader.
        pairs = {(g.home_key, g.away_key) for g in day2}
        assert ("TC-1927", "TB-1927") in pairs  # the makeup
        assert ("TA-1927", "TD-1927") in pairs  # the regularly scheduled game

    def test_home_away_from_fields(self):
        state = build_historical_season(
            FakeRepo(standard_schedule()), YEAR, validate=False
        )
        first = state.schedule[0][0]  # rA (vis) @ rB (home)
        assert first.home_key == "TB-1927"
        assert first.away_key == "TA-1927"

    def test_league_teams_carry_league_and_division(self):
        state = build_historical_season(
            FakeRepo(standard_schedule()), YEAR, validate=False
        )
        by_key = {t.key: t for t in state.teams}
        assert set(by_key) == {"TA-1927", "TB-1927", "TC-1927", "TD-1927"}
        assert by_key["TA-1927"].league == "AL"
        assert by_key["TA-1927"].division == "E"
        # Pre-division divID "" reads as None.
        assert by_key["TC-1927"].league == "NL"
        assert by_key["TC-1927"].division is None
        assert by_key["TA-1927"].display_name == "TA Club"

    def test_games_per_opponent_is_none(self):
        state = build_historical_season(
            FakeRepo(standard_schedule()), YEAR, validate=False
        )
        assert state.games_per_opponent is None

    def test_user_team_key_accepted(self):
        state = build_historical_season(
            FakeRepo(standard_schedule()),
            YEAR,
            user_team_key="TA-1927",
            validate=False,
        )
        assert state.user_team_key == "TA-1927"

    def test_watch_only_user_team_is_none(self):
        state = build_historical_season(
            FakeRepo(standard_schedule()), YEAR, validate=False
        )
        assert state.user_team_key is None

    def test_unknown_user_team_key_rejected(self):
        with pytest.raises(ValueError, match="not a league team"):
            build_historical_season(
                FakeRepo(standard_schedule()),
                YEAR,
                user_team_key="ZZZ-1927",
                validate=False,
            )


class TestBuildFailures:
    def test_unresolved_retro_id_blocks_build(self):
        retro_map = dict(RETRO_MAP)
        del retro_map["rD"]  # rD no longer resolves
        with pytest.raises(HistoricalSeasonError) as exc:
            build_historical_season(
                FakeRepo(standard_schedule(), retro_map=retro_map),
                YEAR,
                validate=False,
            )
        assert exc.value.year == YEAR
        assert any("rD" in p for p in exc.value.problem_teams)

    def test_missing_team_season_blocks_build(self):
        team_meta = dict(TEAM_META)
        del team_meta["TC"]  # resolves, but no Teams row
        with pytest.raises(HistoricalSeasonError) as exc:
            build_historical_season(
                FakeRepo(standard_schedule(), team_meta=team_meta),
                YEAR,
                validate=False,
            )
        assert any("TC" in p for p in exc.value.problem_teams)

    def test_empty_roster_blocks_build(self):
        rosters = {tid: ["player"] for tid in TEAM_META}
        rosters["TB"] = []  # resolves + has a Teams row, but no roster
        with pytest.raises(HistoricalSeasonError) as exc:
            build_historical_season(
                FakeRepo(standard_schedule(), rosters=rosters),
                YEAR,
                validate=False,
            )
        assert any("TB" in p for p in exc.value.problem_teams)

    def test_all_problem_teams_collected_together(self):
        retro_map = dict(RETRO_MAP)
        del retro_map["rD"]
        rosters = {tid: ["player"] for tid in TEAM_META}
        rosters["TB"] = []
        with pytest.raises(HistoricalSeasonError) as exc:
            build_historical_season(
                FakeRepo(
                    standard_schedule(), retro_map=retro_map, rosters=rosters
                ),
                YEAR,
                validate=False,
            )
        problems = " ".join(exc.value.problem_teams)
        assert "rD" in problems and "TB" in problems


# --- Season-shape validation (degenerate-league guard, FRE-149) --------------


class TestSeasonShapeValidationRejects:
    """Slates that fail one or more shape checks are blocked at build time."""

    def test_corrupt_2024_slate_rejected_with_all_reasons(self):
        ids, rows = corrupt_2024_slate()
        with pytest.raises(DegenerateHistoricalSeasonError) as exc:
            # Built as "2024" so the message names the real year of the bug;
            # validation runs on raw ids/counts, before any team resolution.
            build_historical_season(realistic_repo(ids, rows), 2024)
        err = exc.value
        # Headline numbers the issue asked for.
        assert err.year == 2024
        assert err.raw_rows == 2430
        assert err.played_games == 1
        assert "2430 scheduled row(s)" in str(err)
        assert "only 1 playable game(s)" in str(err)
        assert "Re-fetch the schedule data." in str(err)
        # All three checks fire and are collected together.
        assert len(err.reasons) == 3
        joined = " ".join(err.reasons)
        assert "teams are missing" in joined  # check 1
        assert "survived" in joined  # check 2
        assert "per team" in joined  # check 3

    def test_vanished_team_rejected(self):
        # Six teams play a healthy 50-game slate; a seventh (r6) appears only
        # in cancelled rows. Retention and per-team both pass, so only the
        # missing-team check fires.
        ids = team_ids(6)
        rows = round_robin(ids, 50)  # 6 teams, 50 games each, all played
        ghost = [
            srow(19280401 + i, 0, "r6", ids[i % 6], postponed="rain")
            for i in range(10)
        ]
        with pytest.raises(DegenerateHistoricalSeasonError) as exc:
            build_historical_season(FakeRepo(rows + ghost), YEAR)
        assert exc.value.reasons == [
            "entire teams are missing (7 teams scheduled, only 6 play)"
        ]

    def test_low_retention_rejected(self):
        # All six teams play (no vanish) 50 games each, but more than half the
        # raw slate is cancelled — only the retention check fires.
        ids = team_ids(6)
        played = round_robin(ids, 50)  # 300 rows
        cancelled = round_robin(
            ids, 120, start_date=19290401, cancelled=True
        )  # 360 rows -> retention 300/660 ≈ 0.45
        rows = played + cancelled
        with pytest.raises(DegenerateHistoricalSeasonError) as exc:
            build_historical_season(FakeRepo(rows), YEAR)
        assert len(exc.value.reasons) == 1
        reason = exc.value.reasons[0]
        assert "survived" in reason and ">= 50%" in reason

    def test_thin_per_team_rejected(self):
        # Four core teams play a full 50-game round robin; a fifth/sixth team
        # (r4, r5) play only 30 games against each other. Retention is 100% and
        # no team vanishes, so only the per-team floor fires.
        core = round_robin(team_ids(4), 50)  # r0..r3, 50 games each
        thin = [srow(19280401 + i, 0, "r4", "r5") for i in range(30)]
        with pytest.raises(DegenerateHistoricalSeasonError) as exc:
            build_historical_season(FakeRepo(core + thin), YEAR)
        assert len(exc.value.reasons) == 1
        reason = exc.value.reasons[0]
        assert "30 game(s)" in reason and "per team" in reason
        assert ("r4" in reason) or ("r5" in reason)

    def test_is_a_value_error_but_not_historical_season_error(self):
        # Setup-flow contract: the flow's `except ValueError` branch surfaces
        # this error and returns to the year picker, while its earlier
        # `except HistoricalSeasonError` (team-oriented) does NOT catch it.
        ids, rows = corrupt_2024_slate()
        with pytest.raises(ValueError):
            build_historical_season(FakeRepo(rows), 2024)
        try:
            build_historical_season(FakeRepo(rows), 2024)
        except DegenerateHistoricalSeasonError as exc:
            assert isinstance(exc, ValueError)
            assert not isinstance(exc, HistoricalSeasonError)

    def test_validate_false_skips_the_gate(self):
        # The escape hatch the structural tests rely on: a degenerate slate
        # builds without complaint when validation is turned off.
        ids, rows = corrupt_2024_slate()
        state = build_historical_season(
            realistic_repo(ids, rows), 2024, validate=False
        )
        assert len(state.schedule) >= 1


class TestSeasonShapeValidationAccepts:
    """Realistic slates mirroring the verified era baselines pass the gate."""

    def test_clean_full_season_passes(self):
        # 16 teams × 154 games, 5 cancelled → ~99.6% retained (1927-like). The
        # cancelled games are spread over distinct rows, so no team vanishes and
        # every team stays far above the per-team floor.
        ids = team_ids(16)
        rows = round_robin(ids, 154)  # 16/2 * 154 = 1232 rows
        for i in range(5):
            r = rows[i]
            rows[i] = srow(r.date, 0, r.vis_team, r.home_team, postponed="rain")
        state = build_historical_season(realistic_repo(ids, rows), YEAR)
        assert len(state.teams) == 16

    def test_strike_year_retention_passes(self):
        # ~66% retention (1981/1994-like): all teams play, a third of games
        # cancelled — clears the 50% floor with margin.
        ids = team_ids(8)
        played = round_robin(ids, 100)  # 400 rows
        cancelled = round_robin(
            ids, 50, start_date=19290401, cancelled=True
        )  # 200 rows -> retention 400/600 ≈ 0.667
        state = build_historical_season(
            realistic_repo(ids, played + cancelled), YEAR
        )
        assert len(state.teams) == 8

    def test_short_60_game_season_passes(self):
        # ~60 games/team (2020 COVID-like) — above the 40 floor.
        ids = team_ids(10)
        played = round_robin(ids, 60)
        state = build_historical_season(realistic_repo(ids, played), YEAR)
        assert len(state.teams) == 10

    def test_six_team_league_passes(self):
        # Proves there is no absolute league-size floor: the smallest real
        # league (1877/1878 NL, 6 teams) must build.
        ids = team_ids(6)
        played = round_robin(ids, 60)
        state = build_historical_season(realistic_repo(ids, played), YEAR)
        assert len(state.teams) == 6

    def test_thresholds_are_named_constants(self):
        # The spec pins these as tunable module constants; guard the values so
        # a silent retune is caught.
        assert MIN_GAME_RETENTION == 0.5
        assert MIN_GAMES_PER_TEAM == 40


# --- Model round-trip tests --------------------------------------------------


class TestModelRoundTrip:
    def test_from_schedule_round_trips_through_json(self):
        state = build_historical_season(
            FakeRepo(standard_schedule()), YEAR, validate=False
        )
        restored = SeasonState.from_dict(json.loads(json.dumps(state.to_dict())))
        assert restored.games_per_opponent is None
        assert restored.teams == state.teams
        assert restored.schedule == state.schedule
        assert restored.user_team_key == state.user_team_key

    def test_league_team_league_division_round_trip(self):
        team = LeagueTeam("NYA", 1927, "Yankees", league="AL", division="E")
        assert LeagueTeam.from_dict(team.to_dict()) == team

    def test_league_team_defaults_none(self):
        team = LeagueTeam("NYA", 1927, "Yankees")
        assert team.league is None and team.division is None

    def test_legacy_round_robin_save_still_loads(self):
        # A save written before this change: int games_per_opponent and
        # LeagueTeam dicts with no league/division keys.
        legacy = {
            "teams": [
                {"team_id": "NYA", "year": 1927, "display_name": "Yankees"},
                {"team_id": "BOS", "year": 1927, "display_name": "Red Sox"},
            ],
            "games_per_opponent": 2,
            "user_team_key": "NYA-1927",
            "schedule": [],
            "results": [],
        }
        state = SeasonState.from_dict(legacy)
        assert state.games_per_opponent == 2
        assert state.teams[0].league is None
        assert state.teams[0].division is None
        assert state.user_team_key == "NYA-1927"

    def test_from_schedule_skips_round_robin_size_checks(self):
        # A single-team, single-game "league" would fail generate_schedule's
        # size/game-count validation; from_schedule accepts it.
        from src.season.schedule import ScheduledGame

        teams = [LeagueTeam("NYA", 1927, "Yankees", league="AL")]
        schedule = [[ScheduledGame(0, 0, "NYA-1927", "NYA-1927")]]
        state = SeasonState.from_schedule(teams, schedule)
        assert state.games_per_opponent is None
        assert len(state.schedule) == 1


# --- Offline integration (always runs) ---------------------------------------


class TestOfflineIntegrationSeason:
    """A full-league-shaped season built entirely in-process — no DB, no skip.

    This is the always-running end-to-end coverage FRE-158 adds: a real
    :class:`~src.data.lahman.LahmanRepository` over a mini SQLite that
    ``tests.support.mini_lahman`` builds in ``tmp_path``, run through
    ``build_historical_season`` and checked with ``assert_season_invariants``.
    Because it never skips, a regression in the build or the join surfaces as a
    red test on every run.
    """

    YEAR = 1927
    MIN_LEAGUE_SIZE = 8

    def _build(self, tmp_path, **kwargs):
        from src.data.lahman import LahmanRepository

        mini = build_mini_lahman(str(tmp_path / "mini.sqlite"), **kwargs)
        repo = LahmanRepository(mini.db_path)
        return mini, repo

    def test_full_league_season_passes_invariants(self, tmp_path):
        # 8-team double round-robin, a couple of cancellations (so retention is
        # a real fraction, not a trivial 1.0) and a made-up game.
        mini, repo = self._build(
            tmp_path, year=self.YEAR, rounds=2, cancellations=2, makeups=1
        )
        try:
            state = build_historical_season(repo, self.YEAR)
            assert state.games_per_opponent is None
            assert len(state.teams) == self.MIN_LEAGUE_SIZE
            assert_season_invariants(
                state,
                raw_row_count=mini.raw_row_count,
                lahman_games_by_team=mini.lahman_games_by_team,
                min_league_size=self.MIN_LEAGUE_SIZE,
                min_retention=0.8,
                min_team_games=mini.min_played_per_team,
            )
        finally:
            repo.close()

    def test_alias_team_resolved_inside_build(self, tmp_path):
        # DEFAULT_TEAMS carries teamID='LAA' with teamIDretro='ANA'; the schedule
        # uses the Retrosheet id 'ANA', so a resolved LAA-1927 league team proves
        # retro_to_lahman_team ran inside the build (not just in a unit test).
        mini, repo = self._build(tmp_path, year=self.YEAR, rounds=2)
        try:
            state = build_historical_season(repo, self.YEAR)
            assert "LAA-1927" in set(state.team_keys)
            assert "ANA-1927" not in set(state.team_keys)
        finally:
            repo.close()

    def test_full_round_trips_through_json(self, tmp_path):
        mini, repo = self._build(tmp_path, year=self.YEAR, rounds=2)
        try:
            state = build_historical_season(repo, self.YEAR)
            restored = SeasonState.from_dict(
                json.loads(json.dumps(state.to_dict()))
            )
            assert restored.teams == state.teams
            assert restored.schedule == state.schedule
        finally:
            repo.close()

    def test_degenerate_season_rejected_by_harness(self):
        # The exact corrupted-2024-cache shape: a 2-team "league" whose only
        # played game survived a slate of thousands. The harness must reject it,
        # naming the retention and league-size numbers (the FRE-149 catch).
        from src.season.schedule import ScheduledGame

        teams = [
            LeagueTeam("SEA", 2024, "Mariners", league="AL", division="W"),
            LeagueTeam("OAK", 2024, "Athletics", league="AL", division="W"),
        ]
        schedule = [[ScheduledGame(0, 0, "SEA-2024", "OAK-2024")]]
        state = SeasonState.from_schedule(teams, schedule)

        with pytest.raises(AssertionError) as exc:
            assert_season_invariants(
                state,
                raw_row_count=2430,
                lahman_games_by_team={"SEA-2024": 162, "OAK-2024": 162},
                min_league_size=self.MIN_LEAGUE_SIZE,
            )
        message = str(exc.value)
        # Names the offending numbers: league size and retention.
        assert "league too small" in message
        assert "2" in message and str(self.MIN_LEAGUE_SIZE) in message
        assert "retention too low" in message
        assert "2430" in message


# --- DB-backed integration (guarded, loud on skip) ---------------------------

LAHMAN_DB_PATH = Path(__file__).parent.parent / "data" / "lahman.sqlite"
# Candidate years spanning eras (modern, division boundary, pre-division).
CANDIDATE_YEARS = (2016, 1969, 1927)


@pytest.fixture
def lahman_repo():
    if not LAHMAN_DB_PATH.exists():
        warnings.warn(
            f"Lahman database not found at {LAHMAN_DB_PATH} — DB-backed "
            "integration tests skipped (build data/lahman.sqlite to run them)",
            stacklevel=2,
        )
        pytest.skip(f"Lahman database not found at {LAHMAN_DB_PATH}")
    from src.data.lahman import LahmanRepository

    repo = LahmanRepository(str(LAHMAN_DB_PATH))
    yield repo
    repo.close()


def _first_year_with_schedule(repo):
    """First candidate year with schedule data, or ``None`` with a loud warn."""
    year = next(
        (y for y in CANDIDATE_YEARS if repo.has_schedule(y)), None
    )
    if year is None:
        warnings.warn(
            f"no ingested schedule data for any of {CANDIDATE_YEARS} — "
            "DB-backed season integration skipped (run build_schedule_db.py)",
            stacklevel=2,
        )
    return year


class TestBuildHistoricalSeasonDB:
    """Requires data/lahman.sqlite with ingested schedule data."""

    def test_build_real_year(self, lahman_repo):
        year = _first_year_with_schedule(lahman_repo)
        if year is None:
            pytest.skip("no schedule data for any candidate year")

        state = build_historical_season(lahman_repo, year)

        assert state.games_per_opponent is None
        assert all(t.league for t in state.teams)

        # The full invariant harness replaces the old `len(teams) >= 2`, which
        # a degenerate 2-team/1-game season would have passed. G comes from the
        # real Teams rows so the per-team band is checked against Lahman.
        raw_row_count = len(lahman_repo.get_schedule(year))
        lahman_games_by_team = {}
        for team in state.teams:
            team_season = lahman_repo.get_team_season(team.team_id, year)
            if team_season is not None:
                lahman_games_by_team[team.key] = team_season.games
        assert_season_invariants(
            state,
            raw_row_count=raw_row_count,
            lahman_games_by_team=lahman_games_by_team,
            min_league_size=8,  # any real MLB season has >= 8 teams
        )

    def test_real_year_round_trips(self, lahman_repo):
        year = _first_year_with_schedule(lahman_repo)
        if year is None:
            pytest.skip("no schedule data for any candidate year")
        state = build_historical_season(lahman_repo, year)
        restored = SeasonState.from_dict(
            json.loads(json.dumps(state.to_dict()))
        )
        assert restored.teams == state.teams
        assert restored.schedule == state.schedule
