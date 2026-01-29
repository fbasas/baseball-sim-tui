"""Tests for the odds-ratio probability calculation module.

These tests validate the mathematical correctness of the simulation core.
The odds-ratio method is critical - getting it wrong invalidates all results.
"""

import pytest
import math

from src.simulation.odds_ratio import (
    probability_to_odds,
    odds_to_probability,
    calculate_odds_ratio,
    calculate_matchup_probabilities,
    normalize_probabilities,
)
from src.simulation.league_averages import get_league_averages


class TestProbabilityToOdds:
    """Tests for probability_to_odds conversion."""

    def test_fifty_percent_is_one(self):
        """50% probability = 1:1 odds."""
        assert probability_to_odds(0.5) == 1.0

    def test_twenty_five_percent(self):
        """25% probability = 1:3 odds."""
        result = probability_to_odds(0.25)
        expected = 1/3
        assert result == pytest.approx(expected, rel=1e-9)

    def test_seventy_five_percent(self):
        """75% probability = 3:1 odds."""
        assert probability_to_odds(0.75) == 3.0

    def test_zero_probability(self):
        """0% probability = 0 odds."""
        assert probability_to_odds(0.0) == 0.0

    def test_one_probability(self):
        """100% probability = infinite odds."""
        assert probability_to_odds(1.0) == float('inf')

    def test_invalid_negative(self):
        """Negative probability raises ValueError."""
        with pytest.raises(ValueError, match="between 0 and 1"):
            probability_to_odds(-0.1)

    def test_invalid_greater_than_one(self):
        """Probability > 1 raises ValueError."""
        with pytest.raises(ValueError, match="between 0 and 1"):
            probability_to_odds(1.1)


class TestOddsToProbability:
    """Tests for odds_to_probability conversion."""

    def test_one_odds_is_fifty_percent(self):
        """1:1 odds = 50% probability."""
        assert odds_to_probability(1.0) == 0.5

    def test_zero_odds(self):
        """0 odds = 0% probability."""
        assert odds_to_probability(0.0) == 0.0

    def test_infinity_odds(self):
        """Infinite odds = 100% probability."""
        assert odds_to_probability(float('inf')) == 1.0

    def test_three_odds(self):
        """3:1 odds = 75% probability."""
        assert odds_to_probability(3.0) == 0.75

    def test_negative_odds_raises(self):
        """Negative odds raises ValueError."""
        with pytest.raises(ValueError, match="non-negative"):
            odds_to_probability(-1.0)


class TestCalculateOddsRatio:
    """Tests for the core odds-ratio formula."""

    def test_both_average_returns_league(self):
        """When batter and pitcher match league, result equals league."""
        result = calculate_odds_ratio(0.21, 0.21, 0.21)
        assert result == pytest.approx(0.21, rel=1e-9)

    def test_elite_pitcher_dominates_weak_hitter(self):
        """Elite K pitcher (0.30) vs weak contact hitter (0.25) with league K=0.21.

        This is the CRITICAL test - it proves we're not naive averaging.
        Naive average would be (0.30 + 0.25) / 2 = 0.275
        Odds-ratio should produce a HIGHER value because both are above league avg.
        """
        result = calculate_odds_ratio(0.25, 0.30, 0.21)
        naive_average = 0.275

        # Result should be HIGHER than naive average
        assert result > naive_average, (
            f"Odds-ratio {result:.4f} should be > naive average {naive_average}"
        )

        # Verify it's in a reasonable range (above both inputs combined effect)
        assert result > 0.30, "Elite matchup should exceed individual rates"
        assert result < 0.50, "But shouldn't be unreasonably high"

    def test_weak_pitcher_dominated_by_elite_hitter(self):
        """Weak K pitcher (0.15) vs elite contact hitter (0.10) with league K=0.21.

        Both are below league average for strikeouts, so result should be
        LOWER than naive average of 0.125.
        """
        result = calculate_odds_ratio(0.10, 0.15, 0.21)
        naive_average = (0.10 + 0.15) / 2

        # Result should be LOWER than naive average
        assert result < naive_average, (
            f"Odds-ratio {result:.4f} should be < naive average {naive_average}"
        )

    def test_above_average_batter_below_average_pitcher(self):
        """High-K batter (0.25) vs low-K pitcher (0.15) with league K=0.21."""
        result = calculate_odds_ratio(0.25, 0.15, 0.21)

        # Should be close to league average since effects somewhat cancel
        assert 0.15 < result < 0.25, (
            f"Mixed matchup {result:.4f} should be between input rates"
        )

    def test_zero_batter_returns_zero(self):
        """If batter never strikes out, matchup K rate is 0."""
        result = calculate_odds_ratio(0.0, 0.25, 0.21)
        assert result == 0.0

    def test_one_pitcher_returns_one(self):
        """If pitcher always strikes out batters, result is 1."""
        result = calculate_odds_ratio(0.25, 1.0, 0.21)
        assert result == 1.0

    def test_invalid_league_zero(self):
        """League probability of 0 raises ValueError."""
        with pytest.raises(ValueError, match="strictly between 0 and 1"):
            calculate_odds_ratio(0.20, 0.25, 0.0)

    def test_invalid_league_one(self):
        """League probability of 1 raises ValueError."""
        with pytest.raises(ValueError, match="strictly between 0 and 1"):
            calculate_odds_ratio(0.20, 0.25, 1.0)

    def test_symmetry(self):
        """Order of batter/pitcher doesn't matter mathematically."""
        result1 = calculate_odds_ratio(0.20, 0.25, 0.21)
        result2 = calculate_odds_ratio(0.25, 0.20, 0.21)
        assert result1 == pytest.approx(result2, rel=1e-9)


class TestNormalizeProbabilities:
    """Tests for probability normalization."""

    def test_sums_to_one(self):
        """Normalized probabilities sum to 1.0."""
        input_probs = {'a': 0.3, 'b': 0.4, 'c': 0.5}  # sum = 1.2
        result = normalize_probabilities(input_probs)
        assert sum(result.values()) == pytest.approx(1.0, rel=1e-9)

    def test_preserves_ratios(self):
        """Relative ratios are preserved after normalization."""
        input_probs = {'a': 0.3, 'b': 0.4, 'c': 0.5}
        result = normalize_probabilities(input_probs)

        # a/b ratio should be same before and after
        original_ratio = input_probs['a'] / input_probs['b']
        normalized_ratio = result['a'] / result['b']
        assert normalized_ratio == pytest.approx(original_ratio, rel=1e-9)

    def test_already_normalized(self):
        """Already normalized input stays normalized."""
        input_probs = {'a': 0.25, 'b': 0.35, 'c': 0.40}
        result = normalize_probabilities(input_probs)
        assert sum(result.values()) == pytest.approx(1.0, rel=1e-9)

    def test_single_key(self):
        """Single key normalizes to 1.0."""
        result = normalize_probabilities({'only': 0.5})
        assert result['only'] == 1.0

    def test_all_zeros_raises(self):
        """All-zero probabilities raise ValueError."""
        with pytest.raises(ValueError, match="all probabilities are zero"):
            normalize_probabilities({'a': 0.0, 'b': 0.0})

    def test_returns_new_dict(self):
        """Normalization returns a new dict, not modifying input."""
        input_probs = {'a': 0.3, 'b': 0.7}
        result = normalize_probabilities(input_probs)
        assert result is not input_probs
        assert input_probs['a'] == 0.3  # Original unchanged


class TestMatchupProbabilities:
    """Tests for calculate_matchup_probabilities."""

    def test_returns_all_expected_keys(self):
        """Result contains all standard event types."""
        league = get_league_averages(2023)  # Modern era
        batter = league.copy()
        pitcher = league.copy()

        result = calculate_matchup_probabilities(batter, pitcher, league)

        expected_keys = ['strikeout', 'walk', 'hbp', 'single', 'double', 'triple', 'home_run']
        for key in expected_keys:
            assert key in result, f"Missing key: {key}"

    def test_all_values_are_floats(self):
        """All values are floats between 0 and 1."""
        league = get_league_averages(2023)
        batter = league.copy()
        pitcher = league.copy()

        result = calculate_matchup_probabilities(batter, pitcher, league)

        for key, value in result.items():
            assert isinstance(value, float), f"{key} is not a float"
            assert 0 <= value <= 1, f"{key}={value} not in [0, 1]"

    def test_average_inputs_return_league(self):
        """When both batter and pitcher are league average, result equals league."""
        league = get_league_averages(2023)
        batter = league.copy()
        pitcher = league.copy()

        result = calculate_matchup_probabilities(batter, pitcher, league)

        for key in result:
            assert result[key] == pytest.approx(league[key], rel=1e-9), (
                f"{key}: {result[key]} != {league[key]}"
            )

    def test_elite_pitcher_increases_strikeouts(self):
        """Elite strikeout pitcher should increase K rate vs average batter."""
        league = get_league_averages(2023)
        batter = league.copy()
        pitcher = league.copy()
        pitcher['strikeout'] = 0.30  # Elite K pitcher

        result = calculate_matchup_probabilities(batter, pitcher, league)

        assert result['strikeout'] > league['strikeout'], (
            f"Elite pitcher K rate {result['strikeout']:.3f} should exceed "
            f"league average {league['strikeout']}"
        )

    def test_power_hitter_increases_home_runs(self):
        """Power hitter should increase HR rate vs average pitcher."""
        league = get_league_averages(2023)
        batter = league.copy()
        batter['home_run'] = 0.06  # Power hitter
        pitcher = league.copy()

        result = calculate_matchup_probabilities(batter, pitcher, league)

        assert result['home_run'] > league['home_run'], (
            f"Power hitter HR rate {result['home_run']:.3f} should exceed "
            f"league average {league['home_run']}"
        )


class TestEdgeCases:
    """Tests for edge case handling."""

    def test_very_small_probability(self):
        """Very small probabilities don't cause numerical issues."""
        result = calculate_odds_ratio(0.001, 0.002, 0.005)
        assert 0 < result < 0.01
        assert not math.isnan(result)
        assert not math.isinf(result)

    def test_very_high_probability(self):
        """Very high probabilities don't cause numerical issues."""
        result = calculate_odds_ratio(0.99, 0.98, 0.50)
        assert 0.9 < result < 1.0
        assert not math.isnan(result)

    def test_mixed_extreme_values(self):
        """Extreme values on both sides work correctly."""
        result = calculate_odds_ratio(0.001, 0.999, 0.50)
        # Should be somewhere in between
        assert 0 < result < 1
        assert not math.isnan(result)


class TestRealWorldScenarios:
    """Tests using realistic baseball scenarios."""

    def test_research_md_example(self):
        """Test the example from RESEARCH.md.

        - Batter K rate: 0.20 (below average)
        - Pitcher K rate: 0.25 (above average)
        - League K rate: 0.21
        - Expected odds-ratio: ~0.238
        """
        result = calculate_odds_ratio(0.20, 0.25, 0.21)
        assert result == pytest.approx(0.238, rel=0.01)

    def test_deadball_era_context(self):
        """Deadball era matchup should work with era-specific averages."""
        league = get_league_averages(1915)  # Deadball

        # Ty Cobb-like batter (elite contact)
        batter = {
            'strikeout': 0.05,  # Very low K rate
            'walk': 0.10,
            'hbp': 0.008,
            'single': 0.25,    # Lots of singles
            'double': 0.06,
            'triple': 0.04,    # Many triples (speed + big parks)
            'home_run': 0.01,
        }

        # Average deadball pitcher
        pitcher = league.copy()

        result = calculate_matchup_probabilities(batter, pitcher, league)

        # Elite contact hitter should have very low K rate
        assert result['strikeout'] < league['strikeout']
        # And higher hit rates
        assert result['single'] > league['single']

    def test_modern_power_matchup(self):
        """Modern era power matchup should produce high K and HR rates."""
        league = get_league_averages(2023)

        # Power hitter (high K, high HR)
        batter = {
            'strikeout': 0.28,
            'walk': 0.10,
            'hbp': 0.01,
            'single': 0.12,
            'double': 0.04,
            'triple': 0.003,
            'home_run': 0.06,  # Power
        }

        # Strikeout pitcher
        pitcher = {
            'strikeout': 0.30,
            'walk': 0.06,
            'hbp': 0.008,
            'single': 0.13,
            'double': 0.04,
            'triple': 0.004,
            'home_run': 0.025,
        }

        result = calculate_matchup_probabilities(batter, pitcher, league)

        # Should produce elevated K and HR rates
        assert result['strikeout'] > 0.30, "Both above avg K -> high K matchup"
        assert result['home_run'] > league['home_run'], "Power hitter elevates HR"
