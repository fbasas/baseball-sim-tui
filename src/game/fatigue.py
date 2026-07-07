"""Pitcher fatigue model for realistic substitution mechanics.

This module calculates pitcher fatigue based on:
- Batters faced (linear accumulation)
- Times through the batting order (research-based penalty)
- Stress events (runners on base, close game situations)

Fatigue drives the substitution mechanic by creating realistic incentives
to replace tired pitchers before performance degrades significantly.

Times-through-order penalty coefficients are based on The Book (Tango, Lichtman, Dolphin)
showing ~5% wOBA increase on 3rd time through, ~12% on 4th time.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class FatigueConfig:
    """Configuration for fatigue calculation with tunable coefficients.

    Attributes:
        batters_faced_weight: Fatigue increase per batter faced (2% default)
        times_through_order_penalty: Fatigue penalty for each trip through order
            Index 0 = 1st time through, Index 1 = 2nd time, etc.
            Based on sabermetric research showing degradation after 2nd time
        stress_runners_on_weight: Fatigue increase per runner on base (0.5% default)
        stress_close_game_weight: Fatigue increase in close game situations (1% default)
        max_fatigue: Maximum fatigue value (1.0 = completely exhausted)
    """

    batters_faced_weight: float = 0.02
    times_through_order_penalty: list[float] = field(
        default_factory=lambda: [0.0, 0.0, 0.05, 0.12, 0.20]
    )
    stress_runners_on_weight: float = 0.005
    stress_close_game_weight: float = 0.01
    max_fatigue: float = 1.0


@dataclass(frozen=True)
class FatigueState:
    """Current fatigue state for a pitcher.

    Attributes:
        batters_faced: Total batters faced by this pitcher
        times_through_order: Which trip through the batting order (1-indexed)
        stress_events: Cumulative count of stress situations
        current_fatigue: Cached fatigue value (0.0-1.0)
    """

    batters_faced: int = 0
    times_through_order: int = 1
    stress_events: int = 0
    current_fatigue: float = 0.0

    def to_dict(self) -> dict:
        """Serialize to a plain JSON-friendly dict."""
        return {
            "batters_faced": self.batters_faced,
            "times_through_order": self.times_through_order,
            "stress_events": self.stress_events,
            "current_fatigue": self.current_fatigue,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "FatigueState":
        """Reconstruct a FatigueState from :meth:`to_dict` output."""
        return cls(
            batters_faced=data["batters_faced"],
            times_through_order=data["times_through_order"],
            stress_events=data["stress_events"],
            current_fatigue=data["current_fatigue"],
        )


def calculate_fatigue(
    state: FatigueState,
    config: FatigueConfig | None = None,
) -> float:
    """Calculate current fatigue level from pitcher state.

    Fatigue formula:
      base = batters_faced * batters_faced_weight
      tto_penalty = times_through_order_penalty[min(times_through_order, 5) - 1]
      stress = stress_events * stress_weight
      fatigue = min(base + tto_penalty + stress, max_fatigue)

    Args:
        state: Current FatigueState for pitcher
        config: Optional FatigueConfig (uses defaults if None)

    Returns:
        Fatigue value between 0.0 and 1.0
    """
    if config is None:
        config = FatigueConfig()

    # Base fatigue from batters faced
    base = state.batters_faced * config.batters_faced_weight

    # Times-through-order penalty (cap at 5th time through)
    tto_index = min(state.times_through_order, 5) - 1
    tto_penalty = config.times_through_order_penalty[tto_index]

    # Stress accumulation
    stress = state.stress_events * config.stress_runners_on_weight

    # Total fatigue, capped at maximum
    fatigue = min(base + tto_penalty + stress, config.max_fatigue)

    return fatigue


def update_fatigue_state(
    state: FatigueState,
    batters_in_order: int,
    runners_on: int,
    close_game: bool,
    config: FatigueConfig | None = None,
) -> FatigueState:
    """Update fatigue state after an at-bat.

    Args:
        state: Current FatigueState
        batters_in_order: Which batter in order (1-9), used to detect new trip through order
        runners_on: Number of runners on base (0-3)
        close_game: True if game within 2 runs
        config: Optional FatigueConfig

    Returns:
        New FatigueState with updated values
    """
    if config is None:
        config = FatigueConfig()

    # Increment batters faced
    new_batters_faced = state.batters_faced + 1

    # Check if we've started a new trip through the order (batter #1 appears)
    new_times_through = state.times_through_order
    if batters_in_order == 1 and state.batters_faced > 0:
        new_times_through += 1

    # Accumulate stress events
    new_stress_events = state.stress_events
    if runners_on > 0:
        new_stress_events += 1
    if close_game:
        new_stress_events += 1

    # Create new state with updated values
    new_state = FatigueState(
        batters_faced=new_batters_faced,
        times_through_order=new_times_through,
        stress_events=new_stress_events,
        current_fatigue=0.0,  # Will be recalculated
    )

    # Calculate and update current fatigue
    new_fatigue = calculate_fatigue(new_state, config)

    return FatigueState(
        batters_faced=new_batters_faced,
        times_through_order=new_times_through,
        stress_events=new_stress_events,
        current_fatigue=new_fatigue,
    )
