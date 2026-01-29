"""Integration tests for SimulationEngine.

Tests verify that the engine correctly orchestrates all components
and produces valid, reproducible results.
"""

import pytest

from src.simulation.engine import SimulationEngine, AtBatResult
from src.simulation.rng import SimulationRNG
from src.simulation.game_state import BaseState
from src.simulation.outcomes import AtBatOutcome
from src.data.models import BattingStats, PitchingStats


# Test fixtures for reusable player stats


@pytest.fixture
def average_batter():
    """Create an average batter (league average rates)."""
    # ~.270 BA, ~20 HR, modern era
    return BattingStats(
        player_id='avgbat01',
        year=2023,
        team_id='TEA',
        games=150,
        at_bats=550,
        runs=75,
        hits=150,
        doubles=30,
        triples=3,
        home_runs=20,
        rbi=75,
        stolen_bases=5,
        caught_stealing=2,
        walks=55,
        strikeouts=120,
        hit_by_pitch=5,
        sacrifice_flies=5,
        sacrifice_hits=0,
        gidp=12,
    )


@pytest.fixture
def average_pitcher():
    """Create an average pitcher (league average rates)."""
    return PitchingStats(
        player_id='avgpit01',
        year=2023,
        team_id='TEA',
        games=30,
        games_started=30,
        wins=12,
        losses=10,
        ip_outs=540,  # 180 IP
        hits_allowed=170,
        runs_allowed=80,
        earned_runs=70,
        home_runs_allowed=25,
        walks_allowed=55,
        strikeouts=170,
        hit_batters=5,
        batters_faced=720,
        wild_pitches=5,
    )


@pytest.fixture
def elite_pitcher():
    """Create an elite pitcher with high K rate."""
    return PitchingStats(
        player_id='elitepit01',
        year=2023,
        team_id='TEA',
        games=30,
        games_started=30,
        wins=18,
        losses=5,
        ip_outs=600,  # 200 IP
        hits_allowed=140,
        runs_allowed=50,
        earned_runs=45,
        home_runs_allowed=15,
        walks_allowed=40,
        strikeouts=270,  # Elite K rate (~0.30)
        hit_batters=3,
        batters_faced=850,
        wild_pitches=3,
    )


class TestSimulateAtBat:
    """Tests for simulate_at_bat method."""

    def test_returns_at_bat_result(self, average_batter, average_pitcher):
        """Simulation returns AtBatResult with valid outcome."""
        engine = SimulationEngine()
        result = engine.simulate_at_bat(average_batter, average_pitcher)

        assert isinstance(result, AtBatResult)
        assert isinstance(result.outcome, AtBatOutcome)

    def test_reproducible_with_seed(self, average_batter, average_pitcher):
        """Same seed produces identical results."""
        rng1 = SimulationRNG(seed=42)
        engine1 = SimulationEngine(rng=rng1)

        # Simulate 10 at-bats
        results1 = [
            engine1.simulate_at_bat(average_batter, average_pitcher)
            for _ in range(10)
        ]

        # Reset and simulate again
        rng2 = SimulationRNG(seed=42)
        engine2 = SimulationEngine(rng=rng2)

        results2 = [
            engine2.simulate_at_bat(average_batter, average_pitcher)
            for _ in range(10)
        ]

        # Outcomes should match exactly
        for r1, r2 in zip(results1, results2):
            assert r1.outcome == r2.outcome

    def test_with_runners_on_base(self, average_batter, average_pitcher):
        """Simulation handles runners on base."""
        engine = SimulationEngine()
        base_state = BaseState(first='runner1', second='runner2', third='runner3')

        result = engine.simulate_at_bat(
            average_batter, average_pitcher, base_state=base_state
        )

        assert isinstance(result, AtBatResult)
        # If home run, should score 4 runs (3 runners + batter)
        if result.outcome == AtBatOutcome.HOME_RUN:
            assert result.runs_scored == 4


class TestProbabilities:
    """Tests for probability calculations."""

    def test_probabilities_returned(self, average_batter, average_pitcher):
        """Result includes probability dict with expected keys."""
        engine = SimulationEngine()
        result = engine.simulate_at_bat(average_batter, average_pitcher)

        expected_keys = ['strikeout', 'walk', 'hbp', 'single', 'double', 'triple', 'home_run']
        for key in expected_keys:
            assert key in result.probabilities
            assert 0 <= result.probabilities[key] <= 1

    def test_probabilities_sum_less_than_one(self, average_batter, average_pitcher):
        """Probabilities sum to less than 1.0 (remainder is batted-ball outs)."""
        engine = SimulationEngine()
        result = engine.simulate_at_bat(average_batter, average_pitcher)

        total = sum(result.probabilities.values())
        # Probabilities should sum to ~0.50-0.55 (non-out events)
        # The remainder (~0.45-0.50) represents batted-ball outs
        assert 0.45 < total < 0.60, (
            f"Probabilities sum to {total}, expected ~0.50-0.55 "
            "(remainder is batted-ball out probability)"
        )

    def test_get_expected_probabilities(self, average_batter, average_pitcher):
        """get_expected_probabilities returns valid unnormalized probabilities."""
        engine = SimulationEngine()
        probs = engine.get_expected_probabilities(average_batter, average_pitcher)

        expected_keys = ['strikeout', 'walk', 'hbp', 'single', 'double', 'triple', 'home_run']
        for key in expected_keys:
            assert key in probs
            assert 0 <= probs[key] <= 1

        # Unnormalized: sum should be ~0.50-0.55
        total = sum(probs.values())
        assert 0.45 < total < 0.60, (
            f"Expected probabilities sum to {total}, expected ~0.50-0.55"
        )


class TestAuditTrail:
    """Tests for RNG audit trail."""

    def test_audit_trail_populated(self, average_batter, average_pitcher):
        """Result includes non-empty audit trail."""
        engine = SimulationEngine()
        result = engine.simulate_at_bat(average_batter, average_pitcher)

        # Audit trail should have at least one entry (HBP check)
        assert len(result.audit_trail) > 0

    def test_audit_trail_contains_tuples(self, average_batter, average_pitcher):
        """Audit trail entries are tuples."""
        engine = SimulationEngine()
        result = engine.simulate_at_bat(average_batter, average_pitcher)

        for entry in result.audit_trail:
            assert isinstance(entry, tuple)


class TestOddsRatioEffect:
    """Tests that odds-ratio method properly weights abilities."""

    def test_elite_pitcher_reduces_batting(
        self, average_batter, average_pitcher, elite_pitcher
    ):
        """Elite pitcher increases expected K rate vs average batter."""
        engine = SimulationEngine()

        # Get expected K rate vs average pitcher
        avg_probs = engine.get_expected_probabilities(average_batter, average_pitcher)

        # Get expected K rate vs elite pitcher
        elite_probs = engine.get_expected_probabilities(average_batter, elite_pitcher)

        # Elite pitcher should have higher K rate
        assert elite_probs['strikeout'] > avg_probs['strikeout'], (
            f"Elite K rate {elite_probs['strikeout']:.3f} should be higher than "
            f"average K rate {avg_probs['strikeout']:.3f}"
        )

        # Elite pitcher should also reduce hit probabilities
        avg_hit_rate = sum(avg_probs[k] for k in ['single', 'double', 'triple', 'home_run'])
        elite_hit_rate = sum(elite_probs[k] for k in ['single', 'double', 'triple', 'home_run'])

        assert elite_hit_rate < avg_hit_rate, (
            f"Elite hit rate {elite_hit_rate:.3f} should be lower than "
            f"average hit rate {avg_hit_rate:.3f}"
        )


class TestEngineReset:
    """Tests for RNG reset functionality."""

    def test_reset_rng_creates_reproducible_sequence(
        self, average_batter, average_pitcher
    ):
        """reset_rng allows replaying simulations."""
        engine = SimulationEngine()

        # First run with seed
        engine.reset_rng(12345)
        results1 = [
            engine.simulate_at_bat(average_batter, average_pitcher).outcome
            for _ in range(5)
        ]

        # Reset to same seed
        engine.reset_rng(12345)
        results2 = [
            engine.simulate_at_bat(average_batter, average_pitcher).outcome
            for _ in range(5)
        ]

        assert results1 == results2
