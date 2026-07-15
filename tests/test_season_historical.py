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
* **DB-backed integration** — one real year, ``pytest.skip``-guarded when
  ``data/lahman.sqlite`` or its schedule data is absent.
"""

import json
from pathlib import Path

import pytest

from src.data.models import ScheduleRow, TeamSeason
from src.season.historical import (
    HistoricalSeasonError,
    build_historical_season,
)
from src.season.state import LeagueTeam, SeasonState


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
        state = build_historical_season(FakeRepo(standard_schedule()), YEAR)
        # 3 distinct effective dates: 04-01, 04-02, 04-05. The cancelled
        # 04-03 game and the emptied 04-04 date produce no SeasonDay.
        assert len(state.schedule) == 3
        assert [len(day) for day in state.schedule] == [2, 2, 2]

    def test_day_equals_list_index(self):
        state = build_historical_season(FakeRepo(standard_schedule()), YEAR)
        for index, day in enumerate(state.schedule):
            for game in day:
                assert game.day == index

    def test_game_ids_sequential_in_play_order(self):
        state = build_historical_season(FakeRepo(standard_schedule()), YEAR)
        ids = [g.game_id for day in state.schedule for g in day]
        assert ids == [0, 1, 2, 3, 4, 5]

    def test_doubleheader_is_two_games_same_day_same_teams(self):
        state = build_historical_season(FakeRepo(standard_schedule()), YEAR)
        day1 = state.schedule[1]  # 19270402
        assert len(day1) == 2
        # Both games are TC (home) vs TA (away) — a doubleheader.
        assert all(g.home_key == "TC-1927" for g in day1)
        assert all(g.away_key == "TA-1927" for g in day1)

    def test_cancelled_game_absent(self):
        state = build_historical_season(FakeRepo(standard_schedule()), YEAR)
        # The dropped 04-03 game was TB (home) vs TD (away): never scheduled.
        for day in state.schedule:
            for g in day:
                assert not (g.home_key == "TB-1927" and g.away_key == "TD-1927")

    def test_makeup_game_lands_on_makeup_day(self):
        state = build_historical_season(FakeRepo(standard_schedule()), YEAR)
        day2 = state.schedule[2]  # effective date 19270405
        # The moved game (rB@rC -> TC home / TB away) shares day 2 with the
        # already-scheduled rD@rA (TA home / TD away) — a makeup doubleheader.
        pairs = {(g.home_key, g.away_key) for g in day2}
        assert ("TC-1927", "TB-1927") in pairs  # the makeup
        assert ("TA-1927", "TD-1927") in pairs  # the regularly scheduled game

    def test_home_away_from_fields(self):
        state = build_historical_season(FakeRepo(standard_schedule()), YEAR)
        first = state.schedule[0][0]  # rA (vis) @ rB (home)
        assert first.home_key == "TB-1927"
        assert first.away_key == "TA-1927"

    def test_league_teams_carry_league_and_division(self):
        state = build_historical_season(FakeRepo(standard_schedule()), YEAR)
        by_key = {t.key: t for t in state.teams}
        assert set(by_key) == {"TA-1927", "TB-1927", "TC-1927", "TD-1927"}
        assert by_key["TA-1927"].league == "AL"
        assert by_key["TA-1927"].division == "E"
        # Pre-division divID "" reads as None.
        assert by_key["TC-1927"].league == "NL"
        assert by_key["TC-1927"].division is None
        assert by_key["TA-1927"].display_name == "TA Club"

    def test_games_per_opponent_is_none(self):
        state = build_historical_season(FakeRepo(standard_schedule()), YEAR)
        assert state.games_per_opponent is None

    def test_user_team_key_accepted(self):
        state = build_historical_season(
            FakeRepo(standard_schedule()), YEAR, user_team_key="TA-1927"
        )
        assert state.user_team_key == "TA-1927"

    def test_watch_only_user_team_is_none(self):
        state = build_historical_season(FakeRepo(standard_schedule()), YEAR)
        assert state.user_team_key is None

    def test_unknown_user_team_key_rejected(self):
        with pytest.raises(ValueError, match="not a league team"):
            build_historical_season(
                FakeRepo(standard_schedule()), YEAR, user_team_key="ZZZ-1927"
            )


class TestBuildFailures:
    def test_unresolved_retro_id_blocks_build(self):
        retro_map = dict(RETRO_MAP)
        del retro_map["rD"]  # rD no longer resolves
        with pytest.raises(HistoricalSeasonError) as exc:
            build_historical_season(
                FakeRepo(standard_schedule(), retro_map=retro_map), YEAR
            )
        assert exc.value.year == YEAR
        assert any("rD" in p for p in exc.value.problem_teams)

    def test_missing_team_season_blocks_build(self):
        team_meta = dict(TEAM_META)
        del team_meta["TC"]  # resolves, but no Teams row
        with pytest.raises(HistoricalSeasonError) as exc:
            build_historical_season(
                FakeRepo(standard_schedule(), team_meta=team_meta), YEAR
            )
        assert any("TC" in p for p in exc.value.problem_teams)

    def test_empty_roster_blocks_build(self):
        rosters = {tid: ["player"] for tid in TEAM_META}
        rosters["TB"] = []  # resolves + has a Teams row, but no roster
        with pytest.raises(HistoricalSeasonError) as exc:
            build_historical_season(
                FakeRepo(standard_schedule(), rosters=rosters), YEAR
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
            )
        problems = " ".join(exc.value.problem_teams)
        assert "rD" in problems and "TB" in problems


# --- Model round-trip tests --------------------------------------------------


class TestModelRoundTrip:
    def test_from_schedule_round_trips_through_json(self):
        state = build_historical_season(FakeRepo(standard_schedule()), YEAR)
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


# --- DB-backed integration (guarded) ----------------------------------------

LAHMAN_DB_PATH = Path(__file__).parent.parent / "data" / "lahman.sqlite"
# Candidate years spanning eras (modern, division boundary, pre-division).
CANDIDATE_YEARS = (2016, 1969, 1927)


@pytest.fixture
def lahman_repo():
    if not LAHMAN_DB_PATH.exists():
        pytest.skip(f"Lahman database not found at {LAHMAN_DB_PATH}")
    from src.data.lahman import LahmanRepository

    repo = LahmanRepository(str(LAHMAN_DB_PATH))
    yield repo
    repo.close()


class TestBuildHistoricalSeasonDB:
    """Requires data/lahman.sqlite with ingested schedule data."""

    def test_build_real_year(self, lahman_repo):
        year = next(
            (y for y in CANDIDATE_YEARS if lahman_repo.has_schedule(y)), None
        )
        if year is None:
            pytest.skip("no schedule data for any candidate year")

        state = build_historical_season(lahman_repo, year)

        # A real full league is many teams, all league-tagged.
        assert len(state.teams) >= 2
        assert state.games_per_opponent is None
        assert all(t.league for t in state.teams)

        keys = set(state.team_keys)
        ids = []
        for index, day in enumerate(state.schedule):
            for game in day:
                assert game.day == index  # day == list index invariant
                assert game.home_key in keys  # every team is a league team
                assert game.away_key in keys
                ids.append(game.game_id)
        # game_ids are unique and contiguous from 0 in play order.
        assert ids == list(range(len(ids)))
        assert len(ids) > 0

    def test_real_year_round_trips(self, lahman_repo):
        year = next(
            (y for y in CANDIDATE_YEARS if lahman_repo.has_schedule(y)), None
        )
        if year is None:
            pytest.skip("no schedule data for any candidate year")
        state = build_historical_season(lahman_repo, year)
        restored = SeasonState.from_dict(
            json.loads(json.dumps(state.to_dict()))
        )
        assert restored.teams == state.teams
        assert restored.schedule == state.schedule
