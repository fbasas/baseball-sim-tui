"""Tests for game loop logic: transitions, game-end detection, and full simulation."""

import pytest
from dataclasses import replace
from src.game.engine import (
    GameEngine,
    transition_half_inning,
    check_game_complete,
    simulate_game,
    GameResult,
)
from src.game.state import GameState, InningHalf
from src.game.team import Team, Lineup, LineupSlot, create_lineup
from src.game.positions import Position, DesignatedHitter
from src.data.models import TeamSeason, PlayerInfo, BattingStats, PitchingStats
from src.simulation.game_state import BaseState


# ============ Test Fixtures ============

def make_batting_stats(player_id: str) -> BattingStats:
    """Create batting stats for testing."""
    return BattingStats(
        player_id=player_id, year=2020, team_id='TST',
        games=100, at_bats=400, runs=60, hits=100,
        doubles=20, triples=2, home_runs=15, rbi=55,
        stolen_bases=5, caught_stealing=2, walks=40,
        strikeouts=80, hit_by_pitch=3, sacrifice_flies=3,
        sacrifice_hits=0, gidp=8
    )


def make_pitching_stats(player_id: str) -> PitchingStats:
    """Create pitching stats for testing."""
    return PitchingStats(
        player_id=player_id, year=2020, team_id='TST',
        games=30, games_started=30, wins=15, losses=8,
        ip_outs=600, hits_allowed=180, runs_allowed=70,
        earned_runs=60, home_runs_allowed=15, walks_allowed=50,
        strikeouts=200, hit_batters=5, batters_faced=800,
        wild_pitches=3
    )


def make_team(team_id: str) -> Team:
    """Create a complete team for testing."""
    info = TeamSeason(team_id, 2020, 'AL', f'{team_id} Team')
    roster = [PlayerInfo(f'{team_id}_p{i}', f'Player{i}', team_id, 'R', 'R') for i in range(10)]
    roster.append(PlayerInfo(f'{team_id}_pitcher', 'Ace', team_id, 'R', 'R'))
    batting = {f'{team_id}_p{i}': make_batting_stats(f'{team_id}_p{i}') for i in range(10)}
    pitching = {f'{team_id}_pitcher': make_pitching_stats(f'{team_id}_pitcher')}
    return Team(info=info, roster=roster, batting_stats=batting, pitching_stats=pitching)


def make_lineup(team: Team) -> Lineup:
    """Create a valid lineup for a team."""
    team_id = team.info.team_id
    batting_order = [f'{team_id}_p{i}' for i in range(9)]
    positions = {
        f'{team_id}_p0': Position.CENTER_FIELD,
        f'{team_id}_p1': Position.SHORTSTOP,
        f'{team_id}_p2': Position.LEFT_FIELD,
        f'{team_id}_p3': Position.FIRST_BASE,
        f'{team_id}_p4': Position.RIGHT_FIELD,
        f'{team_id}_p5': Position.THIRD_BASE,
        f'{team_id}_p6': Position.CATCHER,
        f'{team_id}_p7': Position.SECOND_BASE,
        f'{team_id}_p8': DesignatedHitter,
    }
    return create_lineup(team, batting_order, positions, f'{team_id}_pitcher')


# ============ transition_half_inning Tests ============

class TestTransitionHalfInning:
    """Tests for half-inning transition logic."""

    def test_top_to_bottom_same_inning(self):
        state = GameState(inning=1, half=InningHalf.TOP, outs=3)
        new_state = transition_half_inning(state)

        assert new_state.half == InningHalf.BOTTOM
        assert new_state.inning == 1
        assert new_state.outs == 0

    def test_bottom_to_top_next_inning(self):
        state = GameState(inning=1, half=InningHalf.BOTTOM, outs=3)
        new_state = transition_half_inning(state)

        assert new_state.half == InningHalf.TOP
        assert new_state.inning == 2
        assert new_state.outs == 0

    def test_clears_base_state(self):
        """Bases must be cleared between half-innings."""
        runners = BaseState(first='runner1', second='runner2', third='runner3')
        state = GameState(inning=1, half=InningHalf.TOP, outs=3, base_state=runners)
        new_state = transition_half_inning(state)

        assert new_state.base_state == BaseState()
        assert new_state.base_state.first is None
        assert new_state.base_state.second is None
        assert new_state.base_state.third is None

    def test_preserves_batting_order_index(self):
        """Batting order should NOT reset on transition."""
        state = GameState(
            inning=1, half=InningHalf.TOP, outs=3,
            away_batting_index=5, home_batting_index=3
        )
        new_state = transition_half_inning(state)

        # Indices should be preserved
        assert new_state.away_batting_index == 5
        assert new_state.home_batting_index == 3

    def test_preserves_scores(self):
        state = GameState(
            inning=3, half=InningHalf.TOP, outs=3,
            away_score=5, home_score=3
        )
        new_state = transition_half_inning(state)

        assert new_state.away_score == 5
        assert new_state.home_score == 3


# ============ check_game_complete Tests ============

class TestCheckGameComplete:
    """Tests for game-end detection logic."""

    def test_not_complete_before_9_innings(self):
        for inning in range(1, 9):
            state = GameState(inning=inning, half=InningHalf.TOP, outs=3,
                              home_score=10, away_score=0)
            assert not check_game_complete(state)

    def test_home_wins_without_batting(self):
        """Home team doesn't bat if winning after top of 9."""
        state = GameState(inning=9, half=InningHalf.TOP, outs=3,
                          home_score=5, away_score=2)
        assert check_game_complete(state)

    def test_home_must_bat_if_trailing(self):
        """Home team bats if trailing after top of 9."""
        state = GameState(inning=9, half=InningHalf.TOP, outs=3,
                          home_score=2, away_score=5)
        assert not check_game_complete(state)

    def test_home_must_bat_if_tied(self):
        """Home team bats if tied after top of 9."""
        state = GameState(inning=9, half=InningHalf.TOP, outs=3,
                          home_score=3, away_score=3)
        assert not check_game_complete(state)

    def test_regulation_home_win_after_bottom_9(self):
        state = GameState(inning=9, half=InningHalf.BOTTOM, outs=3,
                          home_score=5, away_score=3)
        assert check_game_complete(state)

    def test_regulation_away_win_after_bottom_9(self):
        state = GameState(inning=9, half=InningHalf.BOTTOM, outs=3,
                          home_score=3, away_score=5)
        assert check_game_complete(state)

    def test_extra_innings_if_tied_after_9(self):
        """Game continues if tied after 9 complete innings."""
        state = GameState(inning=9, half=InningHalf.BOTTOM, outs=3,
                          home_score=3, away_score=3)
        assert not check_game_complete(state)

    def test_walk_off_bottom_9_no_outs(self):
        """Walk-off with 0 outs in bottom of 9."""
        state = GameState(inning=9, half=InningHalf.BOTTOM, outs=0,
                          home_score=4, away_score=3)
        assert check_game_complete(state)

    def test_walk_off_bottom_9_one_out(self):
        """Walk-off with 1 out in bottom of 9."""
        state = GameState(inning=9, half=InningHalf.BOTTOM, outs=1,
                          home_score=4, away_score=3)
        assert check_game_complete(state)

    def test_walk_off_bottom_9_two_outs(self):
        """Walk-off with 2 outs in bottom of 9."""
        state = GameState(inning=9, half=InningHalf.BOTTOM, outs=2,
                          home_score=4, away_score=3)
        assert check_game_complete(state)

    def test_walk_off_extra_innings(self):
        """Walk-off in extra innings (11th inning)."""
        state = GameState(inning=11, half=InningHalf.BOTTOM, outs=1,
                          home_score=5, away_score=4)
        assert check_game_complete(state)

    def test_no_walk_off_if_tied(self):
        """Game continues if tied in bottom of 9+."""
        state = GameState(inning=9, half=InningHalf.BOTTOM, outs=1,
                          home_score=3, away_score=3)
        assert not check_game_complete(state)

    def test_no_walk_off_in_top_of_inning(self):
        """Walk-off only applies to home team (bottom half)."""
        state = GameState(inning=9, half=InningHalf.TOP, outs=1,
                          home_score=3, away_score=4)
        assert not check_game_complete(state)


# ============ simulate_game Tests ============

class TestSimulateGame:
    """Tests for full game simulation."""

    @pytest.fixture
    def teams(self):
        """Create away and home teams with lineups."""
        away = make_team('AWY')
        home = make_team('HME')
        away.lineup = make_lineup(away)
        home.lineup = make_lineup(home)
        return away, home

    def test_returns_game_result(self, teams):
        away, home = teams
        engine = GameEngine()
        engine.reset_rng(42)

        result = simulate_game(away, home, game_engine=engine)

        assert isinstance(result, GameResult)

    def test_game_is_complete(self, teams):
        away, home = teams
        engine = GameEngine()
        engine.reset_rng(42)

        result = simulate_game(away, home, game_engine=engine)

        assert result.final_state.is_complete

    def test_minimum_9_innings(self, teams):
        away, home = teams
        engine = GameEngine()
        engine.reset_rng(42)

        result = simulate_game(away, home, game_engine=engine)

        assert result.final_state.inning >= 9

    def test_has_winner(self, teams):
        away, home = teams
        engine = GameEngine()
        engine.reset_rng(42)

        result = simulate_game(away, home, game_engine=engine)

        assert result.winner in ('away', 'home')

    def test_play_log_minimum_half_innings(self, teams):
        """Should have at least 17 half-innings (9 full innings minus possible bottom 9)."""
        away, home = teams
        engine = GameEngine()
        engine.reset_rng(42)

        result = simulate_game(away, home, game_engine=engine)

        # At minimum: 9 top halves + 8 bottom halves (if home wins after top of 9)
        assert len(result.play_log) >= 17

    def test_reproducible_with_seed(self, teams):
        away, home = teams

        engine1 = GameEngine()
        engine1.reset_rng(12345)
        result1 = simulate_game(away, home, game_engine=engine1)

        engine2 = GameEngine()
        engine2.reset_rng(12345)
        result2 = simulate_game(away, home, game_engine=engine2)

        assert result1.final_state.away_score == result2.final_state.away_score
        assert result1.final_state.home_score == result2.final_state.home_score
        assert result1.final_state.inning == result2.final_state.inning

    def test_raises_if_away_lineup_not_set(self, teams):
        away, home = teams
        away.lineup = None

        with pytest.raises(ValueError, match="Away team lineup not set"):
            simulate_game(away, home)

    def test_raises_if_home_lineup_not_set(self, teams):
        away, home = teams
        home.lineup = None

        with pytest.raises(ValueError, match="Home team lineup not set"):
            simulate_game(away, home)


class TestGameResult:
    """Tests for GameResult dataclass."""

    def test_winner_away(self):
        state = GameState(away_score=5, home_score=3, is_complete=True)
        result = GameResult(final_state=state, play_log=[])
        assert result.winner == 'away'

    def test_winner_home(self):
        state = GameState(away_score=3, home_score=5, is_complete=True)
        result = GameResult(final_state=state, play_log=[])
        assert result.winner == 'home'

    def test_total_innings(self):
        state = GameState(inning=11, is_complete=True)
        result = GameResult(final_state=state, play_log=[])
        assert result.total_innings == 11
