"""Tests for pitcher fatigue model."""

import pytest

from src.game.fatigue import (
    FatigueConfig,
    FatigueState,
    calculate_fatigue,
    update_fatigue_state,
)


class TestFatigueConfig:
    """Tests for FatigueConfig dataclass."""

    def test_default_batters_faced_weight(self):
        """Default batters faced weight is 2% per batter."""
        config = FatigueConfig()
        assert config.batters_faced_weight == 0.02

    def test_default_times_through_order_penalty(self):
        """Default TTO penalty matches research-based values."""
        config = FatigueConfig()
        expected = [0.0, 0.0, 0.05, 0.12, 0.20]
        assert config.times_through_order_penalty == expected

    def test_default_stress_weights(self):
        """Default stress weights are configured."""
        config = FatigueConfig()
        assert config.stress_runners_on_weight == 0.005
        assert config.stress_close_game_weight == 0.01

    def test_default_max_fatigue(self):
        """Default max fatigue is 1.0."""
        config = FatigueConfig()
        assert config.max_fatigue == 1.0

    def test_custom_config_overrides_defaults(self):
        """Custom config values override defaults."""
        config = FatigueConfig(
            batters_faced_weight=0.03,
            times_through_order_penalty=[0.0, 0.1, 0.2, 0.3, 0.4],
            stress_runners_on_weight=0.01,
            stress_close_game_weight=0.02,
            max_fatigue=0.8,
        )
        assert config.batters_faced_weight == 0.03
        assert config.times_through_order_penalty == [0.0, 0.1, 0.2, 0.3, 0.4]
        assert config.stress_runners_on_weight == 0.01
        assert config.stress_close_game_weight == 0.02
        assert config.max_fatigue == 0.8


class TestFatigueState:
    """Tests for FatigueState dataclass."""

    def test_default_state_is_fresh_pitcher(self):
        """Default FatigueState represents a fresh pitcher."""
        state = FatigueState()
        assert state.batters_faced == 0
        assert state.times_through_order == 1
        assert state.stress_events == 0
        assert state.current_fatigue == 0.0

    def test_custom_state_values(self):
        """FatigueState accepts custom values."""
        state = FatigueState(
            batters_faced=15,
            times_through_order=2,
            stress_events=5,
            current_fatigue=0.35,
        )
        assert state.batters_faced == 15
        assert state.times_through_order == 2
        assert state.stress_events == 5
        assert state.current_fatigue == 0.35

    def test_state_is_frozen(self):
        """FatigueState is immutable (frozen)."""
        state = FatigueState()
        with pytest.raises(AttributeError):
            state.batters_faced = 10  # type: ignore


class TestCalculateFatigue:
    """Tests for calculate_fatigue function."""

    def test_fresh_pitcher_has_zero_fatigue(self):
        """Fresh pitcher with no batters faced has 0.0 fatigue."""
        state = FatigueState()
        fatigue = calculate_fatigue(state)
        assert fatigue == 0.0

    @pytest.mark.parametrize(
        "batters,expected_min,expected_max",
        [
            (0, 0.0, 0.0),
            (5, 0.08, 0.12),  # ~0.10 (5 * 0.02)
            (10, 0.18, 0.22),  # ~0.20 (10 * 0.02)
            (15, 0.28, 0.32),  # ~0.30 (15 * 0.02)
            (20, 0.38, 0.42),  # ~0.40 (20 * 0.02)
            (25, 0.48, 0.52),  # ~0.50 (25 * 0.02)
            (30, 0.58, 0.62),  # ~0.60 (30 * 0.02)
        ],
    )
    def test_fatigue_increases_linearly_with_batters_faced(
        self, batters, expected_min, expected_max
    ):
        """Fatigue increases linearly at 2% per batter (1st time through)."""
        state = FatigueState(batters_faced=batters, times_through_order=1)
        fatigue = calculate_fatigue(state)
        assert expected_min <= fatigue <= expected_max

    def test_second_time_through_no_penalty(self):
        """2nd time through order has no additional penalty."""
        state = FatigueState(batters_faced=10, times_through_order=2)
        fatigue = calculate_fatigue(state)
        # Should be ~0.20 (10 * 0.02 + 0.0 TTO penalty)
        assert 0.18 <= fatigue <= 0.22

    def test_third_time_through_adds_penalty(self):
        """3rd time through order adds 5% penalty."""
        state = FatigueState(batters_faced=18, times_through_order=3)
        fatigue = calculate_fatigue(state)
        # Should be ~0.41 (18 * 0.02 + 0.05 TTO penalty)
        assert 0.39 <= fatigue <= 0.43

    def test_fourth_time_through_larger_penalty(self):
        """4th time through order adds 12% penalty."""
        state = FatigueState(batters_faced=27, times_through_order=4)
        fatigue = calculate_fatigue(state)
        # Should be ~0.66 (27 * 0.02 + 0.12 TTO penalty)
        assert 0.64 <= fatigue <= 0.68

    def test_fifth_time_through_max_penalty(self):
        """5th time through order adds 20% penalty."""
        state = FatigueState(batters_faced=36, times_through_order=5)
        fatigue = calculate_fatigue(state)
        # Should be ~0.92 (36 * 0.02 + 0.20 TTO penalty)
        assert 0.90 <= fatigue <= 0.94

    def test_times_through_order_caps_at_fifth(self):
        """Times through order penalty caps at 5th time (20%)."""
        state_5th = FatigueState(batters_faced=36, times_through_order=5)
        state_6th = FatigueState(batters_faced=36, times_through_order=6)
        state_7th = FatigueState(batters_faced=36, times_through_order=7)

        fatigue_5th = calculate_fatigue(state_5th)
        fatigue_6th = calculate_fatigue(state_6th)
        fatigue_7th = calculate_fatigue(state_7th)

        # All should have same 20% penalty
        assert fatigue_5th == fatigue_6th == fatigue_7th

    def test_stress_events_increase_fatigue(self):
        """Stress events accumulate fatigue."""
        state_no_stress = FatigueState(batters_faced=10, stress_events=0)
        state_stress = FatigueState(batters_faced=10, stress_events=10)

        fatigue_no_stress = calculate_fatigue(state_no_stress)
        fatigue_stress = calculate_fatigue(state_stress)

        # 10 stress events = 10 * 0.005 = 0.05 additional fatigue
        assert fatigue_stress - fatigue_no_stress == pytest.approx(0.05, abs=0.001)

    def test_fatigue_caps_at_max(self):
        """Fatigue never exceeds max_fatigue."""
        # Extreme scenario: 100 batters, 5th time through, 50 stress events
        state = FatigueState(
            batters_faced=100, times_through_order=5, stress_events=50
        )
        fatigue = calculate_fatigue(state)
        assert fatigue == 1.0

    def test_fatigue_caps_at_custom_max(self):
        """Fatigue respects custom max_fatigue config."""
        config = FatigueConfig(max_fatigue=0.8)
        state = FatigueState(batters_faced=100, times_through_order=5)
        fatigue = calculate_fatigue(state, config)
        assert fatigue == 0.8

    def test_uses_default_config_when_none(self):
        """Uses FatigueConfig defaults when config is None."""
        state = FatigueState(batters_faced=10, times_through_order=1)
        fatigue = calculate_fatigue(state, None)
        # Should be ~0.20 with default config
        assert 0.18 <= fatigue <= 0.22

    def test_uses_custom_config_when_provided(self):
        """Uses provided custom config instead of defaults."""
        config = FatigueConfig(batters_faced_weight=0.04)  # 4% per batter
        state = FatigueState(batters_faced=10, times_through_order=1)
        fatigue = calculate_fatigue(state, config)
        # Should be ~0.40 with 4% weight
        assert 0.38 <= fatigue <= 0.42


class TestUpdateFatigueState:
    """Tests for update_fatigue_state function."""

    def test_increments_batters_faced(self):
        """Update increments batters faced by 1."""
        state = FatigueState(batters_faced=5)
        new_state = update_fatigue_state(state, batters_in_order=2, runners_on=0, close_game=False)
        assert new_state.batters_faced == 6

    def test_increments_times_through_order_on_first_batter(self):
        """When batter #1 appears, times_through_order increments."""
        state = FatigueState(batters_faced=9, times_through_order=1)
        new_state = update_fatigue_state(state, batters_in_order=1, runners_on=0, close_game=False)
        assert new_state.times_through_order == 2

    def test_does_not_increment_tto_for_first_batter_first_time(self):
        """First batter of first at-bat doesn't increment TTO (starts at 1)."""
        state = FatigueState(batters_faced=0, times_through_order=1)
        new_state = update_fatigue_state(state, batters_in_order=1, runners_on=0, close_game=False)
        assert new_state.times_through_order == 1

    def test_does_not_increment_tto_for_other_batters(self):
        """Non-first batters don't increment times_through_order."""
        state = FatigueState(batters_faced=10, times_through_order=2)
        for batter_num in [2, 3, 4, 5, 6, 7, 8, 9]:
            new_state = update_fatigue_state(
                state, batters_in_order=batter_num, runners_on=0, close_game=False
            )
            assert new_state.times_through_order == 2

    def test_increments_stress_events_with_runners_on(self):
        """Stress events increment when runners are on base."""
        state = FatigueState(stress_events=5)
        new_state = update_fatigue_state(state, batters_in_order=2, runners_on=2, close_game=False)
        assert new_state.stress_events == 6

    def test_increments_stress_events_in_close_game(self):
        """Stress events increment in close game situations."""
        state = FatigueState(stress_events=5)
        new_state = update_fatigue_state(state, batters_in_order=2, runners_on=0, close_game=True)
        assert new_state.stress_events == 6

    def test_increments_stress_events_twice_when_both(self):
        """Stress events increment twice when both conditions apply."""
        state = FatigueState(stress_events=5)
        new_state = update_fatigue_state(state, batters_in_order=2, runners_on=1, close_game=True)
        assert new_state.stress_events == 7

    def test_no_stress_increment_when_neither_condition(self):
        """Stress events unchanged when no runners and not close game."""
        state = FatigueState(stress_events=5)
        new_state = update_fatigue_state(state, batters_in_order=2, runners_on=0, close_game=False)
        assert new_state.stress_events == 5

    def test_recalculates_current_fatigue(self):
        """Updates current_fatigue field after state changes."""
        state = FatigueState(batters_faced=9, times_through_order=1, current_fatigue=0.18)
        new_state = update_fatigue_state(state, batters_in_order=2, runners_on=0, close_game=False)

        # Should recalculate: 10 batters * 0.02 = 0.20
        assert 0.18 <= new_state.current_fatigue <= 0.22

    def test_recalculates_with_tto_penalty(self):
        """Recalculated fatigue includes TTO penalty when transitioning."""
        state = FatigueState(batters_faced=17, times_through_order=2, current_fatigue=0.34)
        # Batter #1 appears, triggering 3rd time through
        new_state = update_fatigue_state(state, batters_in_order=1, runners_on=0, close_game=False)

        # Should recalculate: 18 batters * 0.02 + 0.05 TTO = 0.41
        assert 0.39 <= new_state.current_fatigue <= 0.43

    def test_uses_default_config_when_none(self):
        """Uses default config when None provided."""
        state = FatigueState(batters_faced=9)
        new_state = update_fatigue_state(state, batters_in_order=2, runners_on=0, close_game=False, config=None)
        # Should use default 2% per batter
        assert 0.18 <= new_state.current_fatigue <= 0.22

    def test_uses_custom_config_when_provided(self):
        """Uses provided custom config."""
        config = FatigueConfig(batters_faced_weight=0.04)
        state = FatigueState(batters_faced=9)
        new_state = update_fatigue_state(
            state, batters_in_order=2, runners_on=0, close_game=False, config=config
        )
        # Should use custom 4% per batter: 10 * 0.04 = 0.40
        assert 0.38 <= new_state.current_fatigue <= 0.42

    def test_state_is_immutable(self):
        """Update returns new state, doesn't mutate original."""
        state = FatigueState(batters_faced=10, times_through_order=1, stress_events=5)
        update_fatigue_state(state, batters_in_order=2, runners_on=1, close_game=True)

        # Original state unchanged
        assert state.batters_faced == 10
        assert state.times_through_order == 1
        assert state.stress_events == 5

    def test_realistic_game_progression(self):
        """Test realistic progression through a game."""
        state = FatigueState()

        # First 9 batters (1st time through)
        for i in range(1, 10):
            state = update_fatigue_state(state, batters_in_order=i, runners_on=0, close_game=False)

        assert state.batters_faced == 9
        assert state.times_through_order == 1
        assert 0.16 <= state.current_fatigue <= 0.20

        # Next 9 batters (2nd time through)
        for i in range(1, 10):
            state = update_fatigue_state(state, batters_in_order=i, runners_on=0, close_game=False)

        assert state.batters_faced == 18
        assert state.times_through_order == 2
        assert 0.34 <= state.current_fatigue <= 0.38

        # First batter of 3rd time through (TTO penalty kicks in)
        state = update_fatigue_state(state, batters_in_order=1, runners_on=0, close_game=False)

        assert state.batters_faced == 19
        assert state.times_through_order == 3
        assert 0.41 <= state.current_fatigue <= 0.45  # Includes 5% TTO penalty
