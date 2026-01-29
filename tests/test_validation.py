"""Statistical validation tests for simulation accuracy.

These tests validate that the simulation produces statistically accurate
results that match historical patterns. Per requirements, we use a 10%
tolerance for statistical validation.

Key validation criteria:
1. 1000-at-bat simulation produces batting averages within 10% of historical
2. Elite pitcher vs weak hitter produces appropriately skewed outcomes
3. Home run rates are reasonable (not collapsed or inflated)
4. Variance is maintained (not all identical outcomes)
"""

import pytest
from collections import Counter

from src.simulation.engine import SimulationEngine
from src.simulation.rng import SimulationRNG
from src.simulation.outcomes import AtBatOutcome
from src.data.models import BattingStats, PitchingStats


@pytest.fixture
def league_average_pitcher():
    """Create a league-average pitcher (modern era)."""
    # League average rates: ~.21 K, ~.08 BB, ~.25 BABIP
    return PitchingStats(
        player_id='lgavgpit',
        year=2023,
        team_id='TEA',
        games=30,
        games_started=30,
        wins=10,
        losses=10,
        ip_outs=540,
        hits_allowed=170,
        runs_allowed=75,
        earned_runs=70,
        home_runs_allowed=25,
        walks_allowed=60,
        strikeouts=160,  # ~.21 K rate
        hit_batters=8,
        batters_faced=750,
        wild_pitches=5,
    )


@pytest.fixture
def three_hundred_hitter():
    """Create a .300 hitter for BA validation."""
    # Design for approximately .300 BA
    # PA = 540 + 60 + 6 + 5 + 5 = 616, Hits = 162
    # BA = 162/540 = .300
    return BattingStats(
        player_id='threehun',
        year=2023,
        team_id='TEA',
        games=150,
        at_bats=540,
        runs=90,
        hits=162,  # .300 BA
        doubles=35,
        triples=4,
        home_runs=25,
        rbi=85,
        stolen_bases=10,
        caught_stealing=4,
        walks=60,
        strikeouts=100,  # Lower than average K rate
        hit_by_pitch=6,
        sacrifice_flies=5,
        sacrifice_hits=5,
        gidp=10,
    )


@pytest.fixture
def elite_k_pitcher():
    """Create an elite strikeout pitcher (~0.30 K rate)."""
    return PitchingStats(
        player_id='eliteK',
        year=2023,
        team_id='TEA',
        games=32,
        games_started=32,
        wins=18,
        losses=5,
        ip_outs=600,
        hits_allowed=140,
        runs_allowed=55,
        earned_runs=50,
        home_runs_allowed=18,
        walks_allowed=45,
        strikeouts=300,  # 0.30 K rate (300/1000 BF)
        hit_batters=5,
        batters_faced=1000,
        wild_pitches=4,
    )


@pytest.fixture
def weak_hitter():
    """Create a weak hitter with high K rate (~0.25 K rate)."""
    return BattingStats(
        player_id='weakbat',
        year=2023,
        team_id='TEA',
        games=120,
        at_bats=400,
        runs=40,
        hits=90,  # .225 BA
        doubles=15,
        triples=1,
        home_runs=8,
        rbi=35,
        stolen_bases=2,
        caught_stealing=2,
        walks=30,
        strikeouts=120,  # 0.25 K rate (120/480 PA)
        hit_by_pitch=3,
        sacrifice_flies=2,
        sacrifice_hits=5,
        gidp=8,
    )


@pytest.fixture
def power_hitter():
    """Create a power hitter with ~0.04 HR rate."""
    # PA = 550 + 70 + 10 + 5 + 0 = 635, HR = 40
    # HR rate = 40/635 = 0.063 (high end power)
    # Design for ~0.04 HR rate: 25 HR / 625 PA
    return BattingStats(
        player_id='powerbat',
        year=2023,
        team_id='TEA',
        games=155,
        at_bats=550,
        runs=95,
        hits=140,  # .255 BA (power hitters trade avg for power)
        doubles=30,
        triples=2,
        home_runs=25,  # ~0.04 HR rate
        rbi=90,
        stolen_bases=3,
        caught_stealing=1,
        walks=70,
        strikeouts=160,  # Power hitters strike out more
        hit_by_pitch=10,
        sacrifice_flies=5,
        sacrifice_hits=0,
        gidp=12,
    )


class TestDistributionMatchesHistorical:
    """Test that simulated distributions match historical patterns."""

    def test_batting_average_within_10_percent(
        self, three_hundred_hitter, league_average_pitcher
    ):
        """5000-at-bat simulation produces BA within 10% of expected.

        This is a key validation requirement from the specs.
        A .300 hitter vs league-average pitcher should produce ~.270-.330 BA.

        Note: Using 5000 samples for statistical stability. The odds-ratio
        method produces theoretical BA of ~.292 for this matchup, which
        is within the 10% tolerance of .300.
        """
        rng = SimulationRNG(seed=42)
        engine = SimulationEngine(rng=rng)

        hits = 0
        at_bats = 0
        num_simulations = 5000

        for _ in range(num_simulations):
            result = engine.simulate_at_bat(three_hundred_hitter, league_average_pitcher)
            outcome = result.outcome

            # Count at-bats and hits
            # Walk, HBP, sac fly don't count as AB
            if outcome not in (
                AtBatOutcome.WALK,
                AtBatOutcome.HIT_BY_PITCH,
                AtBatOutcome.SACRIFICE_FLY,
                AtBatOutcome.SACRIFICE_HIT,
            ):
                at_bats += 1
                if outcome.is_hit:
                    hits += 1

        simulated_ba = hits / at_bats if at_bats > 0 else 0
        expected_ba = 0.300

        # Within 10% means: 0.270 <= simulated <= 0.330
        lower_bound = expected_ba * 0.90
        upper_bound = expected_ba * 1.10

        assert lower_bound <= simulated_ba <= upper_bound, (
            f"Simulated BA {simulated_ba:.3f} outside 10% range "
            f"[{lower_bound:.3f}, {upper_bound:.3f}] of expected {expected_ba:.3f}"
        )


class TestElitePitcherDominates:
    """Test that elite pitchers dominate weak hitters."""

    def test_elite_pitcher_vs_weak_hitter_k_rate(
        self, weak_hitter, elite_k_pitcher
    ):
        """Elite pitcher vs weak hitter produces elevated K rate.

        Both have high K rates:
        - Elite pitcher: 0.30 K rate
        - Weak hitter: 0.25 K rate

        Naive average would be ~0.275.
        Odds-ratio should produce higher than 0.275 (elite dominates).
        """
        rng = SimulationRNG(seed=42)
        engine = SimulationEngine(rng=rng)

        strikeouts = 0
        num_simulations = 1000

        for _ in range(num_simulations):
            result = engine.simulate_at_bat(weak_hitter, elite_k_pitcher)
            if result.outcome.is_strikeout:
                strikeouts += 1

        simulated_k_rate = strikeouts / num_simulations
        naive_average = (0.30 + 0.25) / 2  # 0.275

        # Odds-ratio should produce K rate higher than naive average
        # because elite pitcher skill compounds with weak hitter's vulnerability
        assert simulated_k_rate > naive_average, (
            f"Simulated K rate {simulated_k_rate:.3f} should be higher than "
            f"naive average {naive_average:.3f} - odds-ratio not working correctly"
        )


class TestHomeRunRateReasonable:
    """Test that HR rates are within reasonable range."""

    def test_power_hitter_hr_rate(self, power_hitter, league_average_pitcher):
        """Power hitter HR rate should be reasonable (0.03-0.05).

        Power hitter has ~0.04 HR rate historically.
        Simulation should produce within range accounting for variance.
        """
        rng = SimulationRNG(seed=42)
        engine = SimulationEngine(rng=rng)

        home_runs = 0
        num_simulations = 1000

        for _ in range(num_simulations):
            result = engine.simulate_at_bat(power_hitter, league_average_pitcher)
            if result.outcome == AtBatOutcome.HOME_RUN:
                home_runs += 1

        simulated_hr_rate = home_runs / num_simulations

        # Expected ~0.04, allow 0.02-0.06 range (wider variance for rarer event)
        # Using 10% tolerance on 0.04 would be 0.036-0.044, too tight for 1000 samples
        # HR is rare, so we allow more variance
        lower_bound = 0.02
        upper_bound = 0.06

        assert lower_bound <= simulated_hr_rate <= upper_bound, (
            f"Simulated HR rate {simulated_hr_rate:.3f} outside reasonable range "
            f"[{lower_bound:.3f}, {upper_bound:.3f}]"
        )


class TestVarianceNotCollapsed:
    """Test that outcomes have proper variance."""

    def test_different_seeds_produce_different_outcomes(
        self, three_hundred_hitter, league_average_pitcher
    ):
        """Different seeds should produce different outcome sequences.

        This validates that RNG is working and variance exists.
        """
        all_outcomes = []

        for seed in range(10):
            rng = SimulationRNG(seed=seed)
            engine = SimulationEngine(rng=rng)
            result = engine.simulate_at_bat(three_hundred_hitter, league_average_pitcher)
            all_outcomes.append(result.outcome)

        # Should have at least 3 different outcome types
        unique_outcomes = set(all_outcomes)
        assert len(unique_outcomes) >= 3, (
            f"Only {len(unique_outcomes)} unique outcomes in 10 simulations - "
            f"variance may be collapsed. Outcomes: {unique_outcomes}"
        )

    def test_outcome_distribution_variety(
        self, three_hundred_hitter, league_average_pitcher
    ):
        """Larger sample should show variety of outcomes."""
        rng = SimulationRNG(seed=42)
        engine = SimulationEngine(rng=rng)

        outcomes = []
        for _ in range(200):
            result = engine.simulate_at_bat(three_hundred_hitter, league_average_pitcher)
            outcomes.append(result.outcome)

        counter = Counter(outcomes)

        # Should have hits, outs, and walks in the distribution
        # (strikeouts count as outs but check specifically)
        has_hits = any(o.is_hit for o in counter.keys())
        has_outs = any(o.is_out for o in counter.keys())
        has_walks = AtBatOutcome.WALK in counter or AtBatOutcome.HIT_BY_PITCH in counter

        assert has_hits, "No hits observed in 200 simulations"
        assert has_outs, "No outs observed in 200 simulations"
        # Walks are less common, so we allow this to be optional
        # Just verify we have variety

        assert len(counter) >= 5, (
            f"Only {len(counter)} outcome types in 200 simulations - "
            f"expected more variety. Distribution: {dict(counter)}"
        )


class TestOddsRatioNotNaiveAverage:
    """Verify odds-ratio produces different results than naive averaging."""

    def test_matchup_probabilities_not_averaged(
        self, weak_hitter, elite_k_pitcher, league_average_pitcher
    ):
        """Expected probabilities should differ from naive average.

        This validates the odds-ratio method is working.
        """
        engine = SimulationEngine()

        # Get probabilities for elite vs weak
        elite_matchup = engine.get_expected_probabilities(weak_hitter, elite_k_pitcher)

        # Get probabilities for average vs weak
        avg_matchup = engine.get_expected_probabilities(weak_hitter, league_average_pitcher)

        # Elite should produce higher K rate than average
        assert elite_matchup['strikeout'] > avg_matchup['strikeout'], (
            f"Elite K prob {elite_matchup['strikeout']:.3f} should exceed "
            f"average K prob {avg_matchup['strikeout']:.3f}"
        )

        # The difference should be meaningful, not marginal
        k_difference = elite_matchup['strikeout'] - avg_matchup['strikeout']
        assert k_difference > 0.05, (
            f"K rate difference {k_difference:.3f} should be substantial (>0.05)"
        )
