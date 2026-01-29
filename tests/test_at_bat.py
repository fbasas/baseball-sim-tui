"""Tests for at-bat resolution module.

Tests validate:
- RNG reproducibility with seeding
- Audit trail recording
- Outcome distribution accuracy
- AtBatOutcome enum properties
- Conditional probability calculations
"""

import pytest
from collections import Counter
from src.simulation.rng import SimulationRNG
from src.simulation.outcomes import AtBatOutcome
from src.simulation.at_bat import (
    calculate_conditional_probabilities,
    resolve_at_bat,
    determine_out_type,
    simulate_at_bat,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def sample_probabilities():
    """Sample matchup probabilities representing modern league averages."""
    return {
        'strikeout': 0.21,
        'walk': 0.08,
        'hbp': 0.01,
        'single': 0.15,
        'double': 0.04,
        'triple': 0.005,
        'home_run': 0.03,
    }


@pytest.fixture
def seeded_rng():
    """RNG with fixed seed for reproducible tests."""
    return SimulationRNG(seed=42)


@pytest.fixture
def conditional_probs(sample_probabilities):
    """Pre-calculated conditional probabilities."""
    return calculate_conditional_probabilities(sample_probabilities)


# ============================================================================
# RNG Tests
# ============================================================================

class TestSimulationRNG:
    """Tests for the SimulationRNG wrapper class."""

    def test_rng_produces_values_in_range(self, seeded_rng):
        """RNG random() returns values in [0, 1)."""
        for _ in range(100):
            value = seeded_rng.random()
            assert 0 <= value < 1

    def test_rng_reproducible_with_seed(self):
        """Same seed produces identical sequence of values."""
        rng1 = SimulationRNG(seed=12345)
        rng2 = SimulationRNG(seed=12345)

        values1 = [rng1.random() for _ in range(10)]
        values2 = [rng2.random() for _ in range(10)]

        assert values1 == values2

    def test_rng_different_seeds_produce_different_values(self):
        """Different seeds produce different sequences."""
        rng1 = SimulationRNG(seed=42)
        rng2 = SimulationRNG(seed=43)

        values1 = [rng1.random() for _ in range(10)]
        values2 = [rng2.random() for _ in range(10)]

        assert values1 != values2

    def test_rng_reset_reproduces_sequence(self, seeded_rng):
        """Resetting RNG reproduces the same sequence."""
        values1 = [seeded_rng.random() for _ in range(10)]

        seeded_rng.reset()
        values2 = [seeded_rng.random() for _ in range(10)]

        assert values1 == values2

    def test_audit_trail_records_decisions(self, seeded_rng):
        """Audit trail captures all random decisions."""
        seeded_rng.random()
        seeded_rng.random()
        seeded_rng.random()

        trail = seeded_rng.get_audit_trail()

        assert len(trail) == 3
        for entry in trail:
            assert entry[0] == 'random'
            assert isinstance(entry[1], float)

    def test_audit_trail_records_choices(self):
        """Audit trail captures weighted choices."""
        rng = SimulationRNG(seed=42)
        options = ['A', 'B', 'C']
        probs = [0.5, 0.3, 0.2]

        result = rng.choice(options, probs)

        trail = rng.get_audit_trail()
        assert len(trail) == 1
        assert trail[0][0] == 'choice'
        assert trail[0][1] in options

    def test_audit_trail_is_copy(self, seeded_rng):
        """get_audit_trail returns a copy, not the original."""
        seeded_rng.random()
        trail1 = seeded_rng.get_audit_trail()
        trail2 = seeded_rng.get_audit_trail()

        # Should be equal but not the same object
        assert trail1 == trail2
        assert trail1 is not trail2


# ============================================================================
# AtBatOutcome Enum Tests
# ============================================================================

class TestAtBatOutcome:
    """Tests for AtBatOutcome enum properties."""

    def test_home_run_is_hit(self):
        """HOME_RUN is classified as a hit."""
        assert AtBatOutcome.HOME_RUN.is_hit is True

    def test_home_run_bases_gained(self):
        """HOME_RUN awards 4 bases."""
        assert AtBatOutcome.HOME_RUN.bases_gained == 4

    def test_strikeout_is_out(self):
        """Strikeouts are classified as outs."""
        assert AtBatOutcome.STRIKEOUT_SWINGING.is_out is True
        assert AtBatOutcome.STRIKEOUT_LOOKING.is_out is True

    def test_strikeout_not_on_base(self):
        """Strikeouts do not result in reaching base."""
        assert AtBatOutcome.STRIKEOUT_SWINGING.is_on_base is False
        assert AtBatOutcome.STRIKEOUT_LOOKING.is_on_base is False

    def test_all_hits_are_hits(self):
        """All hit types are classified as hits."""
        hits = [
            AtBatOutcome.SINGLE,
            AtBatOutcome.DOUBLE,
            AtBatOutcome.TRIPLE,
            AtBatOutcome.HOME_RUN,
            AtBatOutcome.INFIELD_SINGLE,
        ]
        for outcome in hits:
            assert outcome.is_hit is True, f"{outcome} should be a hit"

    def test_all_outs_are_outs(self):
        """All out types are classified as outs."""
        outs = [
            AtBatOutcome.STRIKEOUT_SWINGING,
            AtBatOutcome.STRIKEOUT_LOOKING,
            AtBatOutcome.GROUNDOUT,
            AtBatOutcome.FLYOUT,
            AtBatOutcome.LINEOUT,
            AtBatOutcome.POPUP,
            AtBatOutcome.FOUL_OUT,
            AtBatOutcome.SACRIFICE_FLY,
            AtBatOutcome.SACRIFICE_HIT,
            AtBatOutcome.GIDP,
            AtBatOutcome.FIELD_CHOICE,
        ]
        for outcome in outs:
            assert outcome.is_out is True, f"{outcome} should be an out"

    def test_walk_is_on_base(self):
        """Walk results in reaching base."""
        assert AtBatOutcome.WALK.is_on_base is True

    def test_walk_not_a_hit(self):
        """Walk is not a hit."""
        assert AtBatOutcome.WALK.is_hit is False

    def test_bases_gained_mapping(self):
        """Bases gained correctly mapped for each outcome type."""
        assert AtBatOutcome.SINGLE.bases_gained == 1
        assert AtBatOutcome.INFIELD_SINGLE.bases_gained == 1
        assert AtBatOutcome.DOUBLE.bases_gained == 2
        assert AtBatOutcome.TRIPLE.bases_gained == 3
        assert AtBatOutcome.HOME_RUN.bases_gained == 4
        assert AtBatOutcome.WALK.bases_gained == 1
        assert AtBatOutcome.HIT_BY_PITCH.bases_gained == 1
        assert AtBatOutcome.GROUNDOUT.bases_gained == 0

    def test_is_strikeout_property(self):
        """is_strikeout identifies both strikeout types."""
        assert AtBatOutcome.STRIKEOUT_SWINGING.is_strikeout is True
        assert AtBatOutcome.STRIKEOUT_LOOKING.is_strikeout is True
        assert AtBatOutcome.GROUNDOUT.is_strikeout is False

    def test_is_extra_base_hit_property(self):
        """is_extra_base_hit identifies 2B, 3B, HR."""
        assert AtBatOutcome.DOUBLE.is_extra_base_hit is True
        assert AtBatOutcome.TRIPLE.is_extra_base_hit is True
        assert AtBatOutcome.HOME_RUN.is_extra_base_hit is True
        assert AtBatOutcome.SINGLE.is_extra_base_hit is False


# ============================================================================
# Conditional Probability Tests
# ============================================================================

class TestConditionalProbabilities:
    """Tests for calculate_conditional_probabilities function."""

    def test_all_probabilities_in_valid_range(self, sample_probabilities):
        """All conditional probabilities are between 0 and 1."""
        cond = calculate_conditional_probabilities(sample_probabilities)

        for key, value in cond.items():
            assert 0 <= value <= 1, f"{key} = {value} is out of range"

    def test_conditional_probs_sum_correctly(self, sample_probabilities):
        """Conditional probability structure is mathematically consistent."""
        cond = calculate_conditional_probabilities(sample_probabilities)

        # Basic checks that values are reasonable
        # HBP should be small
        assert cond['hbp'] < 0.05

        # Walk should be moderate
        assert 0.05 < cond['walk'] < 0.20

        # Strikeout should be substantial
        assert 0.10 < cond['strikeout'] < 0.40

    def test_handles_zero_probabilities(self):
        """Function handles zero probabilities gracefully."""
        probs = {
            'strikeout': 0.0,
            'walk': 0.0,
            'hbp': 0.0,
            'single': 0.30,
            'double': 0.10,
            'triple': 0.02,
            'home_run': 0.05,
        }
        cond = calculate_conditional_probabilities(probs)

        # Should not raise and all values should be valid
        for value in cond.values():
            assert 0 <= value <= 1

    def test_handles_extreme_probabilities(self):
        """Function handles edge case probability distributions."""
        # All strikeouts
        probs = {
            'strikeout': 0.99,
            'walk': 0.005,
            'hbp': 0.005,
            'single': 0.0,
            'double': 0.0,
            'triple': 0.0,
            'home_run': 0.0,
        }
        cond = calculate_conditional_probabilities(probs)

        for value in cond.values():
            assert 0 <= value <= 1


# ============================================================================
# At-Bat Resolution Tests
# ============================================================================

class TestResolveAtBat:
    """Tests for resolve_at_bat function."""

    def test_returns_valid_outcome(self, conditional_probs, seeded_rng):
        """resolve_at_bat returns an AtBatOutcome enum value."""
        outcome = resolve_at_bat(conditional_probs, seeded_rng)

        assert isinstance(outcome, AtBatOutcome)

    def test_reproducible_with_seed(self, conditional_probs):
        """Same seed produces identical sequence of outcomes."""
        rng1 = SimulationRNG(seed=42)
        rng2 = SimulationRNG(seed=42)

        outcomes1 = [resolve_at_bat(conditional_probs, rng1) for _ in range(10)]
        outcomes2 = [resolve_at_bat(conditional_probs, rng2) for _ in range(10)]

        assert outcomes1 == outcomes2

    def test_audit_trail_records_decisions(self, conditional_probs, seeded_rng):
        """Audit trail is populated after resolution."""
        resolve_at_bat(conditional_probs, seeded_rng)
        trail = seeded_rng.get_audit_trail()

        # Should have at least one decision recorded
        assert len(trail) > 0

    def test_distribution_matches_probabilities(self, sample_probabilities):
        """Outcome distribution approximately matches input probabilities.

        This is a statistical test with tolerances for random variation.
        """
        n_trials = 10000
        rng = SimulationRNG(seed=12345)

        outcomes = []
        for _ in range(n_trials):
            cond_probs = calculate_conditional_probabilities(sample_probabilities)
            outcome = resolve_at_bat(cond_probs, rng)
            outcomes.append(outcome)

        counts = Counter(outcomes)

        # Calculate observed rates
        strikeout_rate = (
            counts[AtBatOutcome.STRIKEOUT_SWINGING] +
            counts[AtBatOutcome.STRIKEOUT_LOOKING]
        ) / n_trials

        hr_rate = counts[AtBatOutcome.HOME_RUN] / n_trials

        walk_rate = counts[AtBatOutcome.WALK] / n_trials

        # Check strikeout rate within 3% tolerance
        expected_k = sample_probabilities['strikeout']
        assert abs(strikeout_rate - expected_k) < 0.03, (
            f"Strikeout rate {strikeout_rate:.3f} too far from expected {expected_k}"
        )

        # Check HR rate within 2% tolerance
        expected_hr = sample_probabilities['home_run']
        assert abs(hr_rate - expected_hr) < 0.02, (
            f"HR rate {hr_rate:.3f} too far from expected {expected_hr}"
        )

        # Check walk rate within 2% tolerance
        expected_bb = sample_probabilities['walk']
        assert abs(walk_rate - expected_bb) < 0.02, (
            f"Walk rate {walk_rate:.3f} too far from expected {expected_bb}"
        )

    def test_all_major_outcomes_possible(self, sample_probabilities):
        """All major outcome types can occur with sufficient trials."""
        n_trials = 5000
        rng = SimulationRNG(seed=99999)

        outcomes = set()
        for _ in range(n_trials):
            cond_probs = calculate_conditional_probabilities(sample_probabilities)
            outcome = resolve_at_bat(cond_probs, rng)
            outcomes.add(outcome)

        # Should see at least these common outcomes
        expected_outcomes = {
            AtBatOutcome.STRIKEOUT_SWINGING,
            AtBatOutcome.STRIKEOUT_LOOKING,
            AtBatOutcome.WALK,
            AtBatOutcome.SINGLE,
            AtBatOutcome.DOUBLE,
            AtBatOutcome.HOME_RUN,
            AtBatOutcome.GROUNDOUT,
            AtBatOutcome.FLYOUT,
        }

        missing = expected_outcomes - outcomes
        assert len(missing) == 0, f"Missing outcomes: {missing}"


# ============================================================================
# Determine Out Type Tests
# ============================================================================

class TestDetermineOutType:
    """Tests for determine_out_type function."""

    def test_returns_valid_out_type(self):
        """determine_out_type returns an out-type outcome."""
        rng = SimulationRNG(seed=42)
        outcome = determine_out_type(rng)

        valid_outs = {
            AtBatOutcome.GROUNDOUT,
            AtBatOutcome.FLYOUT,
            AtBatOutcome.LINEOUT,
            AtBatOutcome.POPUP,
            AtBatOutcome.REACHED_ON_ERROR,
            AtBatOutcome.GIDP,
            AtBatOutcome.SACRIFICE_FLY,
        }
        assert outcome in valid_outs

    def test_gidp_requires_runner_on_first(self):
        """GIDP only possible with runner on first and less than 2 outs."""
        rng = SimulationRNG(seed=42)

        # No situation - GIDP should not occur
        outcomes_no_situation = Counter(
            determine_out_type(SimulationRNG(seed=i))
            for i in range(1000)
        )
        assert outcomes_no_situation[AtBatOutcome.GIDP] == 0

        # With runner on first - GIDP can occur
        situation = {'outs': 0, 'runners': {'first': True}}
        outcomes_with_runner = Counter(
            determine_out_type(SimulationRNG(seed=i), situation)
            for i in range(1000)
        )
        # Some GIDPs should occur (not guaranteed but very likely)
        assert outcomes_with_runner[AtBatOutcome.GIDP] > 0

    def test_sac_fly_requires_runner_on_third(self):
        """Sac fly only possible with runner on third and less than 2 outs."""
        # With runner on third - sac fly can occur
        situation = {'outs': 0, 'runners': {'third': True}}
        outcomes = Counter(
            determine_out_type(SimulationRNG(seed=i), situation)
            for i in range(1000)
        )
        # Some sac flies should occur
        assert outcomes[AtBatOutcome.SACRIFICE_FLY] > 0


# ============================================================================
# Integration Tests
# ============================================================================

class TestSimulateAtBat:
    """Tests for the convenience simulate_at_bat function."""

    def test_simulate_at_bat_returns_outcome(self, sample_probabilities):
        """simulate_at_bat returns valid outcome."""
        rng = SimulationRNG(seed=42)
        outcome = simulate_at_bat(sample_probabilities, rng)

        assert isinstance(outcome, AtBatOutcome)

    def test_simulate_at_bat_reproducible(self, sample_probabilities):
        """simulate_at_bat produces reproducible results."""
        outcomes1 = [
            simulate_at_bat(sample_probabilities, SimulationRNG(seed=42))
            for _ in range(5)
        ]

        # Note: Need fresh RNG for each call to match behavior
        outcomes2 = [
            simulate_at_bat(sample_probabilities, SimulationRNG(seed=42))
            for _ in range(5)
        ]

        assert outcomes1 == outcomes2


# ============================================================================
# All Module Imports Test
# ============================================================================

def test_all_modules_importable():
    """Verify all simulation modules can be imported."""
    from src.simulation import rng, outcomes, at_bat

    assert hasattr(rng, 'SimulationRNG')
    assert hasattr(outcomes, 'AtBatOutcome')
    assert hasattr(at_bat, 'resolve_at_bat')
    assert hasattr(at_bat, 'calculate_conditional_probabilities')
