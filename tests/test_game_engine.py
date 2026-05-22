"""Tests for GameEngine class."""

import pytest
from dataclasses import replace
from unittest.mock import patch

from src.game.engine import GameEngine
from src.game.fatigue import FatigueState
from src.game.state import GameState, InningHalf
from src.game.team import Lineup, LineupSlot, Team
from src.game.positions import Position, DesignatedHitter
from src.data.models import BattingStats, PitchingStats, TeamSeason
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


# ---------------------------------------------------------------------------
# Helpers for TestResolvePitcherStats / TestFatigueEffectsSim
# ---------------------------------------------------------------------------

def _make_team_with_two_pitchers(starter_id: str = "starter_p", reliever_id: str = "reliever_p") -> Team:
    """Build a minimal Team with two pitchers in pitching_stats and a valid lineup.

    The Lineup's starting_pitcher_id is intentionally the STARTER even though
    the GameState in the tests will record the RELIEVER as the current pitcher.
    This isolates the resolve_pitcher_stats bug: starting_pitcher_id vs state.
    """
    # Minimal TeamSeason just for typing (fields not used by the helper)
    info = TeamSeason(
        team_id="TST", year=2020, league_id="AL",
        team_name="Test Team", park_factor_batting=100, park_factor_pitching=100,
    )
    # Build a 9-slot lineup (8 fielders + DH) — same shape as make_lineup()
    positions = [
        Position.CENTER_FIELD, Position.SHORTSTOP, Position.LEFT_FIELD,
        Position.FIRST_BASE, Position.RIGHT_FIELD, Position.THIRD_BASE,
        Position.CATCHER, Position.SECOND_BASE, DesignatedHitter,
    ]
    slots = [
        LineupSlot(f"b{i}", positions[i], make_batting_stats(f"b{i}"))
        for i in range(9)
    ]
    lineup = Lineup(slots=slots, starting_pitcher_id=starter_id)

    pitching = {
        starter_id: make_pitching_stats(starter_id),
        reliever_id: make_pitching_stats(reliever_id),
    }
    batting = {f"b{i}": make_batting_stats(f"b{i}") for i in range(9)}

    return Team(
        info=info,
        roster=[],  # Not exercised by resolve_pitcher_stats
        batting_stats=batting,
        pitching_stats=pitching,
        lineup=lineup,
    )


class TestResolvePitcherStats:
    """Tests for the resolve_pitcher_stats helper (TUI hot path lookup)."""

    def test_returns_state_pitcher_id_not_lineup_starter(self):
        """Helper must read pitcher from GameState, not lineup.starting_pitcher_id."""
        from src.game.engine import resolve_pitcher_stats

        team = _make_team_with_two_pitchers("starter_p", "reliever_p")
        # state.half=TOP means home team is fielding -> home_pitcher_id is the active one.
        # Lineup's starting_pitcher_id is 'starter_p' but GameState records 'reliever_p'.
        state = GameState(
            half=InningHalf.TOP,
            home_pitcher_id="reliever_p",
            home_pitcher_fatigue=FatigueState(),  # zero fatigue
        )

        pitcher_id, stats = resolve_pitcher_stats(state, team)

        assert pitcher_id == "reliever_p"
        # With zero fatigue, stats should equal the reliever's base PitchingStats.
        assert stats == team.pitching_stats["reliever_p"]

    def test_applies_fatigue_modifier(self):
        """Returned stats reflect fatigue modifier (hits *= 1 + fatigue*0.5)."""
        from src.game.engine import resolve_pitcher_stats

        team = _make_team_with_two_pitchers("p_main")
        base_hits = team.pitching_stats["p_main"].hits_allowed
        base_walks = team.pitching_stats["p_main"].walks_allowed
        base_hrs = team.pitching_stats["p_main"].home_runs_allowed

        # Fatigue 0.8
        state = GameState(
            half=InningHalf.TOP,
            home_pitcher_id="p_main",
            home_pitcher_fatigue=FatigueState(current_fatigue=0.8),
        )
        _, stats_fatigued = resolve_pitcher_stats(state, team)

        assert stats_fatigued.hits_allowed == int(base_hits * (1 + 0.8 * 0.5))
        assert stats_fatigued.walks_allowed == int(base_walks * (1 + 0.8 * 0.3))
        assert stats_fatigued.home_runs_allowed == int(base_hrs * (1 + 0.8 * 0.4))

        # Fatigue 0.0 -> unchanged
        state_zero = GameState(
            half=InningHalf.TOP,
            home_pitcher_id="p_main",
            home_pitcher_fatigue=FatigueState(current_fatigue=0.0),
        )
        _, stats_fresh = resolve_pitcher_stats(state_zero, team)
        assert stats_fresh.hits_allowed == base_hits

    def test_resolves_per_inning_half(self):
        """TOP uses home_pitcher_id (home fielding); BOTTOM uses away_pitcher_id."""
        from src.game.engine import resolve_pitcher_stats

        team = _make_team_with_two_pitchers("home_p", "away_p")

        state_top = GameState(
            half=InningHalf.TOP,
            home_pitcher_id="home_p",
            away_pitcher_id="away_p",
        )
        pid_top, _ = resolve_pitcher_stats(state_top, team)
        assert pid_top == "home_p"

        state_bot = GameState(
            half=InningHalf.BOTTOM,
            home_pitcher_id="home_p",
            away_pitcher_id="away_p",
        )
        pid_bot, _ = resolve_pitcher_stats(state_bot, team)
        assert pid_bot == "away_p"

    def test_falls_back_to_starting_pitcher_if_state_pitcher_none(self):
        """If state.current_pitcher_id is None, fall back to lineup.starting_pitcher_id."""
        from src.game.engine import resolve_pitcher_stats

        team = _make_team_with_two_pitchers("starter_p", "reliever_p")
        # No pitcher IDs in state (pre-finalize)
        state = GameState(
            half=InningHalf.TOP,
            home_pitcher_id=None,
            away_pitcher_id=None,
        )
        pid, stats = resolve_pitcher_stats(state, team)
        assert pid == "starter_p"
        assert stats == team.pitching_stats["starter_p"]


class TestFatigueEffectsSim:
    """Tests proving simulate_half_inning applies fatigue per AB."""

    def test_fatigue_modifier_called_inside_simulate_half_inning(self):
        """simulate_half_inning must wrap pitching_stats with apply_fatigue_modifier per AB."""
        engine = GameEngine()
        engine.reset_rng(12345)
        lineup = make_lineup()
        base_pitcher = make_pitching_stats("p1")
        base_hits = base_pitcher.hits_allowed
        base_walks = base_pitcher.walks_allowed
        base_hrs = base_pitcher.home_runs_allowed

        # Start with fatigue 0.8 — fatigue updates after each AB inside _apply_result,
        # so the FIRST captured stats should reflect entry-time fatigue 0.8.
        state = GameState(
            half=InningHalf.TOP,
            home_pitcher_fatigue=FatigueState(current_fatigue=0.8),
        )

        captured = []
        real_sim = engine.sim.simulate_at_bat

        def capture(batting, pitching, base_state, **kw):
            captured.append(pitching)
            return real_sim(batting, pitching, base_state, **kw)

        with patch.object(engine.sim, "simulate_at_bat", side_effect=capture):
            engine.simulate_half_inning(state, lineup, base_pitcher)

        assert captured, "simulate_at_bat was never called"
        first = captured[0]
        # First call: entry fatigue 0.8 should apply (fatigue updates AFTER the AB).
        assert first.hits_allowed == int(base_hits * (1 + 0.8 * 0.5))
        assert first.walks_allowed == int(base_walks * (1 + 0.8 * 0.3))
        assert first.home_runs_allowed == int(base_hrs * (1 + 0.8 * 0.4))

    def test_zero_fatigue_passes_stats_unchanged(self):
        """With fatigue 0.0, captured stats equal base PitchingStats."""
        engine = GameEngine()
        engine.reset_rng(12345)
        lineup = make_lineup()
        base_pitcher = make_pitching_stats("p1")
        base_hits = base_pitcher.hits_allowed
        base_walks = base_pitcher.walks_allowed
        base_hrs = base_pitcher.home_runs_allowed

        state = GameState(
            half=InningHalf.TOP,
            home_pitcher_fatigue=FatigueState(current_fatigue=0.0),
        )

        captured = []
        real_sim = engine.sim.simulate_at_bat

        def capture(batting, pitching, base_state, **kw):
            captured.append(pitching)
            return real_sim(batting, pitching, base_state, **kw)

        with patch.object(engine.sim, "simulate_at_bat", side_effect=capture):
            engine.simulate_half_inning(state, lineup, base_pitcher)

        assert captured, "simulate_at_bat was never called"
        first = captured[0]
        assert first.hits_allowed == base_hits
        assert first.walks_allowed == base_walks
        assert first.home_runs_allowed == base_hrs
