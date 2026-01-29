"""Tests for runner advancement logic.

This module tests the advancement matrices and advance_runners function
to ensure correct runner movement based on at-bat outcomes.
"""

import pytest

from src.simulation.advancement import (
    DOUBLE_ADVANCEMENT,
    SINGLE_ADVANCEMENT,
    TRIPLE_ADVANCEMENT,
    WALK_ADVANCEMENT,
    advance_runners,
)
from src.simulation.game_state import AdvancementResult, BaseState
from src.simulation.outcomes import AtBatOutcome
from src.simulation.rng import SimulationRNG


class TestHomeRun:
    """Tests for home run advancement."""

    def test_home_run_clears_bases(self):
        """Home run with bases loaded scores 4 runs and clears bases."""
        rng = SimulationRNG(seed=42)
        bases = BaseState(first="r1", second="r2", third="r3")

        result = advance_runners(bases, AtBatOutcome.HOME_RUN, rng, "batter")

        assert result.runs_scored == 4
        assert result.new_base_state.is_empty
        assert len(result.runners_scored) == 4
        assert "batter" in result.runners_scored

    def test_home_run_solo(self):
        """Solo home run scores 1 run."""
        rng = SimulationRNG(seed=42)
        bases = BaseState()  # Empty bases

        result = advance_runners(bases, AtBatOutcome.HOME_RUN, rng, "batter")

        assert result.runs_scored == 1
        assert result.new_base_state.is_empty
        assert result.runners_scored == ["batter"]

    def test_home_run_two_on(self):
        """Home run with runners on first and third scores 3."""
        rng = SimulationRNG(seed=42)
        bases = BaseState(first="r1", third="r3")

        result = advance_runners(bases, AtBatOutcome.HOME_RUN, rng, "batter")

        assert result.runs_scored == 3
        assert result.new_base_state.is_empty


class TestWalk:
    """Tests for walk advancement."""

    def test_walk_forces_runners(self):
        """Bases loaded walk forces in a run."""
        rng = SimulationRNG(seed=42)
        bases = BaseState(first="r1", second="r2", third="r3")

        result = advance_runners(bases, AtBatOutcome.WALK, rng, "batter")

        assert result.runs_scored == 1
        # Bases remain loaded
        assert result.new_base_state.first is not None
        assert result.new_base_state.second is not None
        assert result.new_base_state.third is not None

    def test_walk_no_force_no_advance(self):
        """Walk with runner on second only - no force, 0 runs."""
        rng = SimulationRNG(seed=42)
        bases = BaseState(second="r2")

        result = advance_runners(bases, AtBatOutcome.WALK, rng, "batter")

        assert result.runs_scored == 0
        # Runners on first and second
        assert result.new_base_state.first is not None
        assert result.new_base_state.second is not None
        assert result.new_base_state.third is None

    def test_walk_runner_on_first_only(self):
        """Walk with runner on first advances to second."""
        rng = SimulationRNG(seed=42)
        bases = BaseState(first="r1")

        result = advance_runners(bases, AtBatOutcome.WALK, rng, "batter")

        assert result.runs_scored == 0
        assert result.new_base_state.first is not None
        assert result.new_base_state.second is not None

    def test_hit_by_pitch_same_as_walk(self):
        """HBP uses same advancement as walk."""
        rng1 = SimulationRNG(seed=42)
        rng2 = SimulationRNG(seed=42)
        bases = BaseState(first="r1", second="r2", third="r3")

        walk_result = advance_runners(bases, AtBatOutcome.WALK, rng1, "batter")
        hbp_result = advance_runners(bases, AtBatOutcome.HIT_BY_PITCH, rng2, "batter")

        assert walk_result.runs_scored == hbp_result.runs_scored
        assert walk_result.new_base_state.as_tuple() == hbp_result.new_base_state.as_tuple()


class TestSingle:
    """Tests for single advancement."""

    def test_single_runner_on_second_sometimes_scores(self):
        """Single with runner on second produces mix of outcomes."""
        bases = BaseState(second="r2")
        scored_count = 0
        held_count = 0

        # Run 100 trials
        for seed in range(100):
            rng = SimulationRNG(seed=seed)
            result = advance_runners(bases, AtBatOutcome.SINGLE, rng, "batter")

            if result.runs_scored == 1:
                scored_count += 1
            else:
                held_count += 1

        # Should have mix of outcomes (60% score, 40% hold based on matrix)
        # With 100 trials, expect roughly 60 scores and 40 holds (with variance)
        assert scored_count > 30, f"Expected more scores, got {scored_count}"
        assert held_count > 20, f"Expected more holds, got {held_count}"
        assert scored_count + held_count == 100

    def test_single_empty_bases(self):
        """Single with empty bases puts batter on first."""
        rng = SimulationRNG(seed=42)
        bases = BaseState()

        result = advance_runners(bases, AtBatOutcome.SINGLE, rng, "batter")

        assert result.runs_scored == 0
        assert result.new_base_state.first is not None
        assert result.new_base_state.second is None
        assert result.new_base_state.third is None

    def test_single_runner_on_third_always_scores(self):
        """Single with runner on third always scores the run."""
        bases = BaseState(third="r3")

        for seed in range(20):
            rng = SimulationRNG(seed=seed)
            result = advance_runners(bases, AtBatOutcome.SINGLE, rng, "batter")
            assert result.runs_scored == 1, f"Runner on third should always score on single (seed={seed})"


class TestTriple:
    """Tests for triple advancement."""

    def test_triple_everyone_scores(self):
        """Triple with runners on first and second scores 2."""
        rng = SimulationRNG(seed=42)
        bases = BaseState(first="r1", second="r2")

        result = advance_runners(bases, AtBatOutcome.TRIPLE, rng, "batter")

        assert result.runs_scored == 2
        # Only batter on third
        assert result.new_base_state.first is None
        assert result.new_base_state.second is None
        assert result.new_base_state.third is not None

    def test_triple_bases_loaded_scores_three(self):
        """Triple with bases loaded scores 3."""
        rng = SimulationRNG(seed=42)
        bases = BaseState(first="r1", second="r2", third="r3")

        result = advance_runners(bases, AtBatOutcome.TRIPLE, rng, "batter")

        assert result.runs_scored == 3


class TestDouble:
    """Tests for double advancement."""

    def test_double_runner_on_first(self):
        """Double with runner on first - probabilistic outcome."""
        bases = BaseState(first="r1")
        scored_count = 0
        held_count = 0

        for seed in range(100):
            rng = SimulationRNG(seed=seed)
            result = advance_runners(bases, AtBatOutcome.DOUBLE, rng, "batter")

            if result.runs_scored == 1:
                scored_count += 1
            else:
                held_count += 1

        # 60% score, 40% to third based on matrix
        assert scored_count > 30, f"Expected more scores, got {scored_count}"
        assert held_count > 20, f"Expected more holds, got {held_count}"

    def test_double_empty_bases(self):
        """Double with empty bases puts batter on second."""
        rng = SimulationRNG(seed=42)
        bases = BaseState()

        result = advance_runners(bases, AtBatOutcome.DOUBLE, rng, "batter")

        assert result.runs_scored == 0
        assert result.new_base_state.first is None
        assert result.new_base_state.second is not None
        assert result.new_base_state.third is None


class TestOut:
    """Tests for out advancement (simplified model)."""

    def test_out_no_advancement(self):
        """Groundout does not advance runners (simplified)."""
        rng = SimulationRNG(seed=42)
        bases = BaseState(first="r1")

        result = advance_runners(bases, AtBatOutcome.GROUNDOUT, rng, "batter")

        assert result.runs_scored == 0
        # Runner stays on first (simplified model)
        assert result.new_base_state.first is not None
        assert result.new_base_state.second is None

    def test_strikeout_no_advancement(self):
        """Strikeout does not advance runners."""
        rng = SimulationRNG(seed=42)
        bases = BaseState(first="r1", third="r3")

        result = advance_runners(bases, AtBatOutcome.STRIKEOUT_SWINGING, rng, "batter")

        assert result.runs_scored == 0
        assert result.new_base_state.first is not None
        assert result.new_base_state.third is not None

    def test_flyout_no_advancement(self):
        """Flyout does not advance runners (simplified - no sac fly)."""
        rng = SimulationRNG(seed=42)
        bases = BaseState(third="r3")

        result = advance_runners(bases, AtBatOutcome.FLYOUT, rng, "batter")

        assert result.runs_scored == 0


class TestReproducibility:
    """Tests for reproducible results."""

    def test_reproducible_with_seed(self):
        """Same seed produces identical advancement decisions."""
        bases = BaseState(second="r2")

        # Run same scenario twice with same seed
        rng1 = SimulationRNG(seed=12345)
        result1 = advance_runners(bases, AtBatOutcome.SINGLE, rng1, "batter")

        rng2 = SimulationRNG(seed=12345)
        result2 = advance_runners(bases, AtBatOutcome.SINGLE, rng2, "batter")

        assert result1.runs_scored == result2.runs_scored
        assert result1.new_base_state.as_tuple() == result2.new_base_state.as_tuple()

    def test_different_seeds_can_differ(self):
        """Different seeds can produce different outcomes for probabilistic scenarios."""
        bases = BaseState(second="r2")  # 60/40 split scenario
        outcomes = set()

        # Try many seeds to find different outcomes
        for seed in range(100):
            rng = SimulationRNG(seed=seed)
            result = advance_runners(bases, AtBatOutcome.SINGLE, rng, "batter")
            outcomes.add(result.runs_scored)

        # Should have found both 0 and 1 runs scenarios
        assert len(outcomes) == 2, f"Expected two different outcomes, got {outcomes}"


class TestMatrixCoverage:
    """Tests for matrix completeness."""

    def test_all_base_states_covered_in_single(self):
        """Each of 8 base states has entry in SINGLE_ADVANCEMENT."""
        all_states = [
            (False, False, False),
            (True, False, False),
            (False, True, False),
            (False, False, True),
            (True, True, False),
            (True, False, True),
            (False, True, True),
            (True, True, True),
        ]

        for state in all_states:
            assert state in SINGLE_ADVANCEMENT, f"Missing state {state} in SINGLE_ADVANCEMENT"

    def test_all_base_states_covered_in_double(self):
        """Each of 8 base states has entry in DOUBLE_ADVANCEMENT."""
        all_states = [
            (False, False, False),
            (True, False, False),
            (False, True, False),
            (False, False, True),
            (True, True, False),
            (True, False, True),
            (False, True, True),
            (True, True, True),
        ]

        for state in all_states:
            assert state in DOUBLE_ADVANCEMENT, f"Missing state {state} in DOUBLE_ADVANCEMENT"

    def test_all_base_states_covered_in_triple(self):
        """Each of 8 base states has entry in TRIPLE_ADVANCEMENT."""
        all_states = [
            (False, False, False),
            (True, False, False),
            (False, True, False),
            (False, False, True),
            (True, True, False),
            (True, False, True),
            (False, True, True),
            (True, True, True),
        ]

        for state in all_states:
            assert state in TRIPLE_ADVANCEMENT, f"Missing state {state} in TRIPLE_ADVANCEMENT"

    def test_all_base_states_covered_in_walk(self):
        """Each of 8 base states has entry in WALK_ADVANCEMENT."""
        all_states = [
            (False, False, False),
            (True, False, False),
            (False, True, False),
            (False, False, True),
            (True, True, False),
            (True, False, True),
            (False, True, True),
            (True, True, True),
        ]

        for state in all_states:
            assert state in WALK_ADVANCEMENT, f"Missing state {state} in WALK_ADVANCEMENT"

    def test_probabilities_sum_to_one(self):
        """All probability options in each matrix sum to 1.0."""
        for matrix_name, matrix in [
            ("SINGLE", SINGLE_ADVANCEMENT),
            ("DOUBLE", DOUBLE_ADVANCEMENT),
            ("TRIPLE", TRIPLE_ADVANCEMENT),
            ("WALK", WALK_ADVANCEMENT),
        ]:
            for state, options in matrix.items():
                prob_sum = sum(opt[2] for opt in options)
                assert abs(prob_sum - 1.0) < 0.001, f"{matrix_name}[{state}] probs sum to {prob_sum}"


class TestBaseState:
    """Tests for BaseState helper methods."""

    def test_base_state_count(self):
        """BaseState.count returns correct runner count."""
        assert BaseState().count == 0
        assert BaseState(first="r1").count == 1
        assert BaseState(first="r1", second="r2").count == 2
        assert BaseState(first="r1", second="r2", third="r3").count == 3

    def test_base_state_is_empty(self):
        """BaseState.is_empty returns True only when empty."""
        assert BaseState().is_empty
        assert not BaseState(first="r1").is_empty
        assert not BaseState(second="r2").is_empty
        assert not BaseState(third="r3").is_empty

    def test_base_state_from_tuple(self):
        """BaseState.from_tuple creates correct state."""
        bs = BaseState.from_tuple((True, False, True))
        assert bs.first is not None
        assert bs.second is None
        assert bs.third is not None

    def test_base_state_as_tuple(self):
        """BaseState.as_tuple returns correct boolean tuple."""
        bs = BaseState(first="r1", third="r3")
        assert bs.as_tuple() == (True, False, True)

    def test_base_state_clear(self):
        """BaseState.clear returns empty state."""
        bs = BaseState(first="r1", second="r2", third="r3")
        cleared = bs.clear()
        assert cleared.is_empty


class TestAdvancementResult:
    """Tests for AdvancementResult dataclass."""

    def test_advancement_result_creation(self):
        """AdvancementResult can be created with all fields."""
        result = AdvancementResult(
            new_base_state=BaseState(first="r1"),
            runs_scored=2,
            runners_scored=["r2", "r3"],
        )

        assert result.runs_scored == 2
        assert result.new_base_state.first == "r1"
        assert len(result.runners_scored) == 2

    def test_advancement_result_batter_safe(self):
        """AdvancementResult.batter_safe property works."""
        result = AdvancementResult(
            new_base_state=BaseState(),
            runs_scored=1,
            runners_scored=["batter"],
        )

        assert result.batter_safe
