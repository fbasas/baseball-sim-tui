"""Tests for the season model state (FRE-91).

Pure, DB-free, house-style: synthetic ``LeagueTeam``s and hand-built
``results`` fixtures for standings math and the three champion tiebreak
levels, plus ``current_day`` advancement and a JSON round-trip. Mirrors
``tests/test_rest_and_series.py`` (SeriesState) and
``tests/test_series_persistence.py`` (round-trip).
"""

import json

import pytest

from src.season.schedule import ScheduledGame
from src.season.state import (
    LeagueTeam,
    SeasonGameRecord,
    SeasonState,
)

# --- Factories --------------------------------------------------------------

# Four synthetic teams; keys are A/B/C/D via team_id T0..T3, year 2000.
A, B, C, D = "T0-2000", "T1-2000", "T2-2000", "T3-2000"


def make_teams(n: int = 4) -> list:
    return [LeagueTeam(team_id=f"T{i}", year=2000, display_name=f"Team {i}")
            for i in range(n)]


def rec(home_key, away_key, home_score, away_score, game_id=0, day=0, innings=9):
    return SeasonGameRecord(
        game_id=game_id, day=day, home_key=home_key, away_key=away_key,
        home_score=home_score, away_score=away_score, innings=innings,
    )


def make_season(n: int = 4, g: int = 2, user_team_key=None) -> SeasonState:
    return SeasonState.create(make_teams(n), g, user_team_key=user_team_key)


# --- League config / validation ---------------------------------------------


class TestLeagueTeam:
    def test_key(self):
        assert LeagueTeam("NYA", 1927, "Yankees").key == "NYA-1927"

    def test_round_trip(self):
        team = LeagueTeam("NYA", 1927, "1927 Yankees")
        assert LeagueTeam.from_dict(team.to_dict()) == team


class TestSeasonValidation:
    def test_duplicate_team_season_rejected(self):
        teams = [
            LeagueTeam("NYA", 1927, "Yankees"),
            LeagueTeam("NYA", 1927, "Yankees again"),
            LeagueTeam("CHN", 1906, "Cubs"),
            LeagueTeam("BOS", 2004, "Red Sox"),
        ]
        with pytest.raises(ValueError, match="Duplicate league entry"):
            SeasonState.create(teams, 2)

    def test_unknown_user_team_key_rejected(self):
        with pytest.raises(ValueError, match="not a league team"):
            make_season(user_team_key="ZZZ-1999")

    def test_watch_only_user_team_is_none(self):
        assert make_season().user_team_key is None

    def test_user_team_key_accepted(self):
        assert make_season(user_team_key=A).user_team_key == A

    def test_invalid_size_rejected_via_create(self):
        with pytest.raises(ValueError, match="League must have"):
            SeasonState.create(make_teams(5), 2)


class TestCreate:
    def test_schedule_generated(self):
        season = make_season(n=4, g=2)
        # 4 teams, G=2 -> (N-1)*G = 6 days, N/2 = 2 games/day, 12 games total.
        assert len(season.schedule) == 6
        assert season.total_games == 12
        assert season.team_keys == [A, B, C, D]


# --- Standings math ---------------------------------------------------------


class TestStandings:
    """Hand-built results with known W/L/GB/RS/RA.

    A: beat B 1-0, beat C 10-0, beat D 10-0, lost to B 0-1  -> 3-1, RS21 RA1
    B: lost to A 0-1, beat A 1-0, beat C 1-0, beat D 1-0    -> 3-1, RS3  RA1
    C: lost to A 0-10, lost to B 0-1                        -> 0-2, RS0  RA11
    D: lost to A 0-10, lost to B 0-1                        -> 0-2, RS0  RA11
    """

    def make_state(self) -> SeasonState:
        season = make_season(n=4, g=2)
        season.results = [
            rec(A, B, 1, 0, game_id=0),   # A beats B
            rec(B, A, 1, 0, game_id=1),   # B beats A
            rec(A, C, 10, 0, game_id=2),  # A beats C
            rec(A, D, 10, 0, game_id=3),  # A beats D
            rec(B, C, 1, 0, game_id=4),   # B beats C
            rec(B, D, 1, 0, game_id=5),   # B beats D
        ]
        return season

    def test_records_and_runs(self):
        rows = {row.key: row for row in self.make_state().standings}
        assert (rows[A].wins, rows[A].losses) == (3, 1)
        assert (rows[A].runs_scored, rows[A].runs_allowed) == (21, 1)
        assert (rows[B].wins, rows[B].losses) == (3, 1)
        assert (rows[B].runs_scored, rows[B].runs_allowed) == (3, 1)
        assert (rows[C].wins, rows[C].losses) == (0, 2)
        assert (rows[C].runs_scored, rows[C].runs_allowed) == (0, 11)
        assert (rows[D].wins, rows[D].losses) == (0, 2)

    def test_pct(self):
        rows = {row.key: row for row in self.make_state().standings}
        assert rows[A].pct == pytest.approx(0.75)
        assert rows[C].pct == pytest.approx(0.0)

    def test_games_behind(self):
        rows = {row.key: row for row in self.make_state().standings}
        assert rows[A].games_behind == 0.0
        assert rows[B].games_behind == 0.0  # identical 3-1 record
        assert rows[C].games_behind == 2.0
        assert rows[D].games_behind == 2.0

    def test_sort_order_pct_then_run_diff_then_key(self):
        order = [row.key for row in self.make_state().standings]
        # A and B tied at .750; A has the better run differential (+20 vs +2).
        # C and D tied at .000 and same run diff; key breaks the tie (C < D).
        assert order == [A, B, C, D]

    def test_no_games_all_zero(self):
        season = make_season(n=4, g=2)
        rows = season.standings
        assert len(rows) == 4
        assert all(row.wins == 0 and row.losses == 0 for row in rows)
        assert all(row.pct == 0.0 and row.games_behind == 0.0 for row in rows)


# --- Champion tiebreaks ------------------------------------------------------


class TestChampionTiebreaks:
    def test_empty_league_has_no_champion(self):
        season = SeasonState(teams=[], games_per_opponent=2, schedule=[])
        assert season.champion is None

    def test_level1_winning_pct(self):
        """A has the strictly best winning pct."""
        season = make_season(n=4, g=2)
        season.results = [
            rec(A, B, 1, 0, game_id=0),  # A 1-0
            rec(A, C, 1, 0, game_id=1),  # A 2-0
            rec(B, C, 1, 0, game_id=2),  # B 1-1, C 0-2
            rec(B, D, 0, 1, game_id=3),  # D 1-0, B 1-2
        ]
        assert season.champion == A

    def test_level2_head_to_head(self):
        """A and B tied on pct; A won head-to-head though B has better run diff."""
        season = make_season(n=4, g=2)
        season.results = [
            rec(A, B, 1, 0, game_id=0),    # A beats B (H2H edge to A)
            rec(A, C, 1, 0, game_id=1),    # A beats C
            rec(D, A, 20, 0, game_id=2),   # D beats A (A's loss)
            rec(B, C, 20, 0, game_id=3),   # B beats C (fat run diff)
            rec(B, D, 5, 0, game_id=4),    # B beats D
            rec(C, D, 5, 0, game_id=5),    # keep C, D off the top
        ]
        rows = {row.key: row for row in season.standings}
        assert rows[A].pct == pytest.approx(rows[B].pct)  # both 2-1
        assert rows[B].run_differential > rows[A].run_differential
        assert season.champion == A  # head-to-head beats run differential

    def test_level3_run_differential(self):
        """A and B tied on pct with a split head-to-head; A wins on run diff."""
        season = make_season(n=4, g=2)
        season.results = [
            rec(A, B, 1, 0, game_id=0),    # A beats B
            rec(B, A, 1, 0, game_id=1),    # B beats A (H2H even, 1-1)
            rec(A, C, 10, 0, game_id=2),   # A crushes C
            rec(A, D, 10, 0, game_id=3),   # A crushes D
            rec(B, C, 1, 0, game_id=4),    # B edges C
            rec(B, D, 1, 0, game_id=5),    # B edges D
        ]
        rows = {row.key: row for row in season.standings}
        assert rows[A].pct == pytest.approx(rows[B].pct)      # both 3-1
        assert season._head_to_head_wins([A, B]) == {A: 1, B: 1}  # split
        assert rows[A].run_differential > rows[B].run_differential
        assert season.champion == A  # run differential decides


# --- Grouped standings + pennants (FRE-118) ---------------------------------


def league_team(team_id, league, division=None):
    """A league-tagged synthetic team; key is ``"{team_id}-2000"``."""
    return LeagueTeam(
        team_id=team_id, year=2000, display_name=team_id,
        league=league, division=division,
    )


def grouped_state(teams, pairs) -> SeasonState:
    """A season over ``teams`` whose results are one game per ``(winner, loser)``
    key pair (winner home, 5-2). Schedule is irrelevant to standings math, so
    an empty schedule keeps the fixture to just teams + results."""
    state = SeasonState(teams=teams, games_per_opponent=None, schedule=[])
    state.results = [
        rec(winner, loser, 5, 2, game_id=i)
        for i, (winner, loser) in enumerate(pairs)
    ]
    return state


# 1969-style: two leagues, two divisions each (8 teams).
_AE1, _AE2 = "AE1-2000", "AE2-2000"
_AW1, _AW2 = "AW1-2000", "AW2-2000"
_NE1, _NE2 = "NE1-2000", "NE2-2000"
_NW1, _NW2 = "NW1-2000", "NW2-2000"

_DIVISION_TEAMS = [
    league_team("AE1", "AL", "E"), league_team("AE2", "AL", "E"),
    league_team("AW1", "AL", "W"), league_team("AW2", "AL", "W"),
    league_team("NE1", "NL", "E"), league_team("NE2", "NL", "E"),
    league_team("NW1", "NL", "W"), league_team("NW2", "NL", "W"),
]
# Records: AW1 3-0, AE1 2-1, AW2 1-2, AE2 0-3 (AL); NE1 3-0, NW1 2-1,
# NW2 1-2, NE2 0-3 (NL). AW1/NE1 are the pennant winners.
_DIVISION_PAIRS = [
    (_AW1, _AE2), (_AW1, _AW2), (_AW1, _AE1),
    (_AE1, _AE2), (_AE1, _AW2), (_AW2, _AE2),
    (_NE1, _NE2), (_NE1, _NW2), (_NE1, _NW1),
    (_NW1, _NE2), (_NW1, _NW2), (_NW2, _NE2),
]

# Pre-division: two leagues, three teams each, no divisions.
_PA1, _PA2, _PA3 = "PA1-2000", "PA2-2000", "PA3-2000"
_PN1, _PN2, _PN3 = "PN1-2000", "PN2-2000", "PN3-2000"
_FLAT_LEAGUE_TEAMS = [
    league_team("PA1", "AL"), league_team("PA2", "AL"), league_team("PA3", "AL"),
    league_team("PN1", "NL"), league_team("PN2", "NL"), league_team("PN3", "NL"),
]
# PA1 2-0, PA2 1-1, PA3 0-2; likewise PN1/PN2/PN3.
_FLAT_LEAGUE_PAIRS = [
    (_PA1, _PA2), (_PA1, _PA3), (_PA2, _PA3),
    (_PN1, _PN2), (_PN1, _PN3), (_PN2, _PN3),
]


class TestIsGrouped:
    def test_round_robin_is_not_grouped(self):
        assert make_season(n=4, g=2).is_grouped is False

    def test_any_league_set_is_grouped(self):
        assert grouped_state(_DIVISION_TEAMS, _DIVISION_PAIRS).is_grouped is True

    def test_flat_standings_unchanged_for_grouped_season(self):
        # The league-wide table still ranks all 8 teams together.
        state = grouped_state(_DIVISION_TEAMS, _DIVISION_PAIRS)
        assert len(state.standings) == len(_DIVISION_TEAMS)


class TestStandingsByGroup:
    def test_division_league_groups_and_order(self):
        groups = grouped_state(_DIVISION_TEAMS, _DIVISION_PAIRS).standings_by_group()
        # Four groups, ordered by (league, division): AL E, AL W, NL E, NL W.
        assert [(g.league, g.division) for g in groups] == [
            ("AL", "E"), ("AL", "W"), ("NL", "E"), ("NL", "W"),
        ]

    def test_rows_partitioned_by_group(self):
        groups = grouped_state(_DIVISION_TEAMS, _DIVISION_PAIRS).standings_by_group()
        by_gd = {(g.league, g.division): g for g in groups}
        assert {r.key for r in by_gd[("AL", "E")].rows} == {_AE1, _AE2}
        assert {r.key for r in by_gd[("AL", "W")].rows} == {_AW1, _AW2}
        # Each group is internally ordered best-first.
        assert by_gd[("AL", "E")].rows[0].key == _AE1  # 2-1 over 0-3
        assert by_gd[("AL", "W")].rows[0].key == _AW1  # 3-0 over 1-2

    def test_gb_is_within_group_not_league_wide(self):
        state = grouped_state(_DIVISION_TEAMS, _DIVISION_PAIRS)
        groups = {(g.league, g.division): g for g in state.standings_by_group()}
        ae = {r.key: r for r in groups[("AL", "E")].rows}
        # AE1 (2-1) leads AL East -> group GB 0.0, though it trails the
        # league-wide leader AW1 (3-0) by 1.0 game in the flat table.
        assert ae[_AE1].games_behind == 0.0
        flat = {r.key: r for r in state.standings}
        assert flat[_AE1].games_behind == 1.0
        # The division cellar sits 2.0 back within its own group.
        assert ae[_AE2].games_behind == 2.0

    def test_predivision_groups_by_league_only(self):
        groups = grouped_state(
            _FLAT_LEAGUE_TEAMS, _FLAT_LEAGUE_PAIRS
        ).standings_by_group()
        assert [(g.league, g.division) for g in groups] == [
            ("AL", None), ("NL", None),
        ]
        by_league = {g.league: g for g in groups}
        assert {r.key for r in by_league["AL"].rows} == {_PA1, _PA2, _PA3}
        # GB within the (undivided) league: 0.0 / 1.0 / 2.0.
        al = {r.key: r for r in by_league["AL"].rows}
        assert al[_PA1].games_behind == 0.0
        assert al[_PA2].games_behind == 1.0
        assert al[_PA3].games_behind == 2.0


class TestPennantWinners:
    def test_best_record_per_league_with_divisions(self):
        winners = grouped_state(_DIVISION_TEAMS, _DIVISION_PAIRS).pennant_winners()
        assert winners == {"AL": _AW1, "NL": _NE1}

    def test_best_record_per_league_predivision(self):
        winners = grouped_state(
            _FLAT_LEAGUE_TEAMS, _FLAT_LEAGUE_PAIRS
        ).pennant_winners()
        assert winners == {"AL": _PA1, "NL": _PN1}

    def test_champion_is_best_overall_not_a_pennant_choice(self):
        # champion stays the single best overall record (headline), drawn from
        # across both leagues' pennant winners (AW1 vs NE1, both 3-0 +9 diff;
        # key breaks the tie -> AW1).
        state = grouped_state(_DIVISION_TEAMS, _DIVISION_PAIRS)
        assert state.champion == _AW1
        assert state.champion in state.pennant_winners().values()

    def test_ungrouped_season_has_no_pennants(self):
        assert make_season(n=4, g=2).pennant_winners() == {}


# --- current_day / is_complete ----------------------------------------------


class TestDayProgression:
    def play_day(self, season: SeasonState, day_index: int, skip_last=False):
        """Append home-win results for every game on a day (optionally skip one)."""
        games = season.schedule[day_index]
        if skip_last:
            games = games[:-1]
        for game in games:
            season.results.append(
                rec(game.home_key, game.away_key, 1, 0,
                    game_id=game.game_id, day=game.day)
            )

    def test_current_day_starts_at_zero(self):
        assert make_season().current_day == 0

    def test_day_advances_only_when_all_games_played(self):
        season = make_season(n=4, g=2)
        self.play_day(season, 0)
        assert season.current_day == 1
        # Play all but one game of day 1: still day 1.
        self.play_day(season, 1, skip_last=True)
        assert season.current_day == 1
        assert not season.is_complete
        # Finish day 1.
        last = season.schedule[1][-1]
        season.results.append(
            rec(last.home_key, last.away_key, 1, 0,
                game_id=last.game_id, day=last.day)
        )
        assert season.current_day == 2

    def test_fully_played_season_is_complete(self):
        season = make_season(n=4, g=2)
        for day_index in range(len(season.schedule)):
            self.play_day(season, day_index)
        assert season.is_complete
        assert season.current_day == len(season.schedule)
        assert season.champion is not None

    def test_empty_schedule_not_complete(self):
        season = SeasonState(teams=[], games_per_opponent=2, schedule=[])
        assert not season.is_complete


# --- Serialization round-trip ------------------------------------------------


class TestSerialization:
    def test_game_record_round_trip(self):
        record = rec("NYA-1927", "CHN-1906", 7, 3, game_id=4, day=2, innings=10)
        assert SeasonGameRecord.from_dict(record.to_dict()) == record

    def test_season_round_trip_empty_results(self):
        season = make_season(n=6, g=4, user_team_key="T2-2000")
        restored = SeasonState.from_dict(json.loads(json.dumps(season.to_dict())))
        assert restored == season

    def test_season_round_trip_with_results(self):
        season = make_season(n=4, g=2, user_team_key=A)
        season.results = [
            rec(A, B, 5, 2, game_id=0, day=0),
            rec(C, D, 1, 3, game_id=1, day=0),
        ]
        restored = SeasonState.from_dict(json.loads(json.dumps(season.to_dict())))
        assert restored == season
        assert restored.user_team_key == A
        assert restored.results == season.results

    def test_derived_state_not_stored(self):
        season = make_season(n=4, g=2)
        data = season.to_dict()
        assert set(data) == {
            "teams", "games_per_opponent", "user_team_key",
            "schedule", "results",
        }
