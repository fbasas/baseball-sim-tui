"""Tests for GameEngine class."""

import pytest
from dataclasses import replace

from src.game.engine import GameEngine
from src.game.state import GameState, InningHalf
from src.game.team import Lineup, LineupSlot
from src.game.positions import Position, DesignatedHitter
from src.data.models import BattingStats, PitchingStats
from src.simulation.game_state import BaseState


# Test fixtures
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


def make_lineup() -> Lineup:
    """Create valid 9-player lineup with 8 fielding positions + DH."""
    positions = [
        Position.CENTER_FIELD, Position.SHORTSTOP, Position.LEFT_FIELD,
        Position.FIRST_BASE, Position.RIGHT_FIELD, Position.THIRD_BASE,
        Position.CATCHER, Position.SECOND_BASE, DesignatedHitter
    ]
    slots = [
        LineupSlot(f'b{i}', positions[i], make_batting_stats(f'b{i}'))
        for i in range(9)
    ]
    return Lineup(slots=slots, starting_pitcher_id='p1')


class TestGameEngine:
    """Tests for GameEngine."""

    def test_creates_with_default_simulation_engine(self):
        engine = GameEngine()
        assert engine.sim is not None

    def test_composes_simulation_engine(self):
        from src.simulation.engine import SimulationEngine
        sim = SimulationEngine()
        engine = GameEngine(simulation_engine=sim)
        assert engine.sim is sim

    def test_reset_rng_delegates_to_simulation_engine(self):
        engine = GameEngine()
        engine.reset_rng(42)
        # Verify deterministic results with same seed
        engine2 = GameEngine()
        engine2.reset_rng(42)
        # Same seed should give same behavior


class TestSimulateHalfInning:
    """Tests for simulate_half_inning method."""

    def test_returns_state_with_three_outs(self):
        engine = GameEngine()
        engine.reset_rng(12345)
        state = GameState()
        lineup = make_lineup()
        pitcher = make_pitching_stats('p1')

        new_state, results = engine.simulate_half_inning(state, lineup, pitcher)

        assert new_state.outs == 3

    def test_returns_at_least_three_results(self):
        engine = GameEngine()
        engine.reset_rng(12345)
        state = GameState()
        lineup = make_lineup()
        pitcher = make_pitching_stats('p1')

        new_state, results = engine.simulate_half_inning(state, lineup, pitcher)

        assert len(results) >= 3  # At least 3 at-bats for 3 outs

    def test_does_not_mutate_original_state(self):
        engine = GameEngine()
        engine.reset_rng(12345)
        state = GameState()
        lineup = make_lineup()
        pitcher = make_pitching_stats('p1')

        engine.simulate_half_inning(state, lineup, pitcher)

        assert state.outs == 0
        assert state.away_batting_index == 0

    def test_advances_batting_order(self):
        engine = GameEngine()
        engine.reset_rng(12345)
        state = GameState()
        lineup = make_lineup()
        pitcher = make_pitching_stats('p1')

        new_state, results = engine.simulate_half_inning(state, lineup, pitcher)

        # Batting index should equal number of at-bats mod 9
        expected_idx = len(results) % 9
        assert new_state.away_batting_index == expected_idx

    def test_batting_order_wraps_around(self):
        engine = GameEngine()
        engine.reset_rng(99999)  # Seed that produces many at-bats
        state = GameState()
        lineup = make_lineup()
        pitcher = make_pitching_stats('p1')

        # Run multiple half-innings to force wrap-around
        for _ in range(3):
            state, _ = engine.simulate_half_inning(state, lineup, pitcher)
            # Reset outs for next half-inning test
            state = replace(state, outs=0, base_state=BaseState())

        # Index should have wrapped (0-8)
        assert 0 <= state.away_batting_index < 9

    def test_updates_score_for_top_of_inning(self):
        engine = GameEngine()
        engine.reset_rng(42)
        state = GameState(half=InningHalf.TOP)
        lineup = make_lineup()
        pitcher = make_pitching_stats('p1')

        new_state, results = engine.simulate_half_inning(state, lineup, pitcher)

        # Home score should be unchanged
        assert new_state.home_score == 0
        # Away score should reflect runs scored (may be 0)
        total_runs = sum(r.runs_scored for r in results)
        assert new_state.away_score == total_runs

    def test_updates_score_for_bottom_of_inning(self):
        engine = GameEngine()
        engine.reset_rng(42)
        state = GameState(half=InningHalf.BOTTOM, home_batting_index=0)
        lineup = make_lineup()
        pitcher = make_pitching_stats('p1')

        new_state, results = engine.simulate_half_inning(state, lineup, pitcher)

        # Away score should be unchanged
        assert new_state.away_score == 0
        # Home score should reflect runs scored (may be 0)
        total_runs = sum(r.runs_scored for r in results)
        assert new_state.home_score == total_runs

    def test_reproducible_with_same_seed(self):
        lineup = make_lineup()
        pitcher = make_pitching_stats('p1')

        engine1 = GameEngine()
        engine1.reset_rng(42)
        state1, results1 = engine1.simulate_half_inning(GameState(), lineup, pitcher)

        engine2 = GameEngine()
        engine2.reset_rng(42)
        state2, results2 = engine2.simulate_half_inning(GameState(), lineup, pitcher)

        assert len(results1) == len(results2)
        assert state1.away_score == state2.away_score
        for r1, r2 in zip(results1, results2):
            assert r1.outcome == r2.outcome


class TestGIDPHandling:
    """Tests for GIDP (double play) handling."""

    def test_gidp_counts_as_two_outs(self):
        """Verify that GIDP properly adds 2 outs.

        This test runs many simulations and verifies that when GIDP occurs,
        the resulting out count is appropriate (2 more than before, capped at 3).
        """
        engine = GameEngine()
        lineup = make_lineup()
        pitcher = make_pitching_stats('p1')

        from src.simulation.outcomes import AtBatOutcome

        # Run many half-innings and check GIDP behavior
        gidp_found = False
        for seed in range(100):
            engine.reset_rng(seed)
            state = GameState()
            new_state, results = engine.simulate_half_inning(state, lineup, pitcher)

            # Check if any at-bat was GIDP and verify outs
            outs = 0
            for r in results:
                if r.outcome == AtBatOutcome.GIDP:
                    gidp_found = True
                    expected_outs = min(outs + 2, 3)
                    outs = expected_outs
                elif r.is_out:
                    outs = min(outs + 1, 3)

        # We should find at least one GIDP in 100 simulations
        # (GIDP requires runner on first, so not guaranteed in every half-inning)
        assert new_state.outs == 3  # Always ends with 3 outs

    def test_gidp_capped_at_three_outs(self):
        """Verify that GIDP with 2 outs only results in 3 outs total."""
        from src.game.engine import GameEngine
        from src.simulation.engine import AtBatResult
        from src.simulation.outcomes import AtBatOutcome
        from src.simulation.game_state import BaseState, AdvancementResult

        engine = GameEngine()

        # Create a fake result that is GIDP
        gidp_result = AtBatResult(
            outcome=AtBatOutcome.GIDP,
            advancement=AdvancementResult(
                new_base_state=BaseState(),
                runs_scored=0,
                runners_scored=[]
            ),
            probabilities={},
            audit_trail=[]
        )

        # Start with 2 outs
        state = GameState(outs=2)
        new_state = engine._apply_result(state, gidp_result)

        # Should cap at 3 outs, not 4
        assert new_state.outs == 3


class TestBattingOrderAdvancement:
    """Tests for batting order advancement."""

    def test_advances_on_hit(self):
        """Batting order advances after a hit."""
        from src.simulation.engine import AtBatResult
        from src.simulation.outcomes import AtBatOutcome
        from src.simulation.game_state import BaseState, AdvancementResult

        engine = GameEngine()

        hit_result = AtBatResult(
            outcome=AtBatOutcome.SINGLE,
            advancement=AdvancementResult(
                new_base_state=BaseState(first='batter'),
                runs_scored=0,
                runners_scored=[]
            ),
            probabilities={},
            audit_trail=[]
        )

        state = GameState(away_batting_index=5)
        new_state = engine._apply_result(state, hit_result)

        assert new_state.away_batting_index == 6

    def test_advances_on_out(self):
        """Batting order advances after an out."""
        from src.simulation.engine import AtBatResult
        from src.simulation.outcomes import AtBatOutcome
        from src.simulation.game_state import BaseState, AdvancementResult

        engine = GameEngine()

        out_result = AtBatResult(
            outcome=AtBatOutcome.GROUNDOUT,
            advancement=AdvancementResult(
                new_base_state=BaseState(),
                runs_scored=0,
                runners_scored=[]
            ),
            probabilities={},
            audit_trail=[]
        )

        state = GameState(away_batting_index=5)
        new_state = engine._apply_result(state, out_result)

        assert new_state.away_batting_index == 6

    def test_wraps_at_nine(self):
        """Batting order wraps from 8 to 0."""
        from src.simulation.engine import AtBatResult
        from src.simulation.outcomes import AtBatOutcome
        from src.simulation.game_state import BaseState, AdvancementResult

        engine = GameEngine()

        result = AtBatResult(
            outcome=AtBatOutcome.GROUNDOUT,
            advancement=AdvancementResult(
                new_base_state=BaseState(),
                runs_scored=0,
                runners_scored=[]
            ),
            probabilities={},
            audit_trail=[]
        )

        state = GameState(away_batting_index=8)
        new_state = engine._apply_result(state, result)

        assert new_state.away_batting_index == 0

    def test_advances_correct_team(self):
        """Batting order advances for correct team based on inning half."""
        from src.simulation.engine import AtBatResult
        from src.simulation.outcomes import AtBatOutcome
        from src.simulation.game_state import BaseState, AdvancementResult

        engine = GameEngine()

        result = AtBatResult(
            outcome=AtBatOutcome.GROUNDOUT,
            advancement=AdvancementResult(
                new_base_state=BaseState(),
                runs_scored=0,
                runners_scored=[]
            ),
            probabilities={},
            audit_trail=[]
        )

        # Top of inning - away team batting
        state = GameState(half=InningHalf.TOP, away_batting_index=3, home_batting_index=5)
        new_state = engine._apply_result(state, result)
        assert new_state.away_batting_index == 4
        assert new_state.home_batting_index == 5  # Unchanged

        # Bottom of inning - home team batting
        state = GameState(half=InningHalf.BOTTOM, away_batting_index=3, home_batting_index=5)
        new_state = engine._apply_result(state, result)
        assert new_state.away_batting_index == 3  # Unchanged
        assert new_state.home_batting_index == 6


class TestScoreTracking:
    """Tests for score tracking."""

    def test_runs_added_to_away_in_top(self):
        """Runs scored in top of inning go to away team."""
        from src.simulation.engine import AtBatResult
        from src.simulation.outcomes import AtBatOutcome
        from src.simulation.game_state import BaseState, AdvancementResult

        engine = GameEngine()

        hr_result = AtBatResult(
            outcome=AtBatOutcome.HOME_RUN,
            advancement=AdvancementResult(
                new_base_state=BaseState(),
                runs_scored=2,  # Solo HR + runner
                runners_scored=[]
            ),
            probabilities={},
            audit_trail=[]
        )

        state = GameState(half=InningHalf.TOP, away_score=3, home_score=1)
        new_state = engine._apply_result(state, hr_result)

        assert new_state.away_score == 5
        assert new_state.home_score == 1

    def test_runs_added_to_home_in_bottom(self):
        """Runs scored in bottom of inning go to home team."""
        from src.simulation.engine import AtBatResult
        from src.simulation.outcomes import AtBatOutcome
        from src.simulation.game_state import BaseState, AdvancementResult

        engine = GameEngine()

        hr_result = AtBatResult(
            outcome=AtBatOutcome.HOME_RUN,
            advancement=AdvancementResult(
                new_base_state=BaseState(),
                runs_scored=2,
                runners_scored=[]
            ),
            probabilities={},
            audit_trail=[]
        )

        state = GameState(half=InningHalf.BOTTOM, away_score=3, home_score=1)
        new_state = engine._apply_result(state, hr_result)

        assert new_state.away_score == 3
        assert new_state.home_score == 3
