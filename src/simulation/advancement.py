"""Runner advancement logic for baseball simulation.

This module implements runner advancement using probability matrices
derived from historical Retrosheet play-by-play data. The matrices
capture realistic runner advancement patterns for each type of at-bat
outcome based on the current base state.
"""

from typing import Dict, List, Tuple

from .game_state import AdvancementResult, BaseState
from .outcomes import AtBatOutcome
from .rng import SimulationRNG

# Type aliases for clarity
BaseStateTuple = Tuple[bool, bool, bool]
AdvancementOption = Tuple[BaseStateTuple, int, float]  # (new_state, runs, probability)
AdvancementMatrix = Dict[BaseStateTuple, List[AdvancementOption]]


# Single advancement - batter to first, runners advance probabilistically
# Probabilities derived from historical data patterns
SINGLE_ADVANCEMENT: AdvancementMatrix = {
    # Empty bases - batter to first
    (False, False, False): [((True, False, False), 0, 1.0)],
    # Runner on first - runner goes to second (70%) or third (30%)
    (True, False, False): [
        ((True, True, False), 0, 0.70),  # Runner holds at 2nd
        ((True, False, True), 0, 0.30),  # Runner advances to 3rd
    ],
    # Runner on second - scores (60%) or holds at third (40%)
    (False, True, False): [
        ((True, False, False), 1, 0.60),  # Scores
        ((True, False, True), 0, 0.40),  # Holds at 3rd
    ],
    # Runner on third - always scores
    (False, False, True): [((True, False, False), 1, 1.0)],
    # Runners on first and second
    (True, True, False): [
        ((True, True, False), 1, 0.35),  # Lead runner scores, trail to 2nd
        ((True, False, True), 1, 0.25),  # Lead scores, trail to 3rd
        ((True, True, True), 0, 0.40),  # Both advance, none score
    ],
    # Runners on first and third
    (True, False, True): [
        ((True, True, False), 1, 0.70),  # 3rd scores, 1st to 2nd
        ((True, False, True), 1, 0.30),  # 3rd scores, 1st to 3rd
    ],
    # Runners on second and third
    (False, True, True): [
        ((True, False, False), 2, 0.60),  # Both score
        ((True, False, True), 1, 0.40),  # 3rd scores, 2nd holds
    ],
    # Bases loaded
    (True, True, True): [
        ((True, True, False), 2, 0.35),  # 2 score
        ((True, True, True), 1, 0.45),  # 1 scores
        ((True, False, True), 2, 0.20),  # 2 score, runner 1st -> 3rd
    ],
}

# Double advancement - batter to second
DOUBLE_ADVANCEMENT: AdvancementMatrix = {
    # Empty bases - batter to second
    (False, False, False): [((False, True, False), 0, 1.0)],
    # Runner on first - scores (60%) or to third (40%)
    (True, False, False): [
        ((False, True, False), 1, 0.60),  # Runner scores
        ((False, True, True), 0, 0.40),  # Runner to 3rd
    ],
    # Runner on second - always scores
    (False, True, False): [((False, True, False), 1, 1.0)],
    # Runner on third - always scores
    (False, False, True): [((False, True, False), 1, 1.0)],
    # Runners on first and second
    (True, True, False): [
        ((False, True, False), 2, 0.70),  # Both score
        ((False, True, True), 1, 0.30),  # Lead scores, trail to 3rd
    ],
    # Runners on first and third
    (True, False, True): [
        ((False, True, False), 2, 0.85),  # Both score
        ((False, True, True), 1, 0.15),  # 3rd scores, 1st to 3rd
    ],
    # Runners on second and third
    (False, True, True): [((False, True, False), 2, 1.0)],  # Both score
    # Bases loaded
    (True, True, True): [
        ((False, True, False), 3, 0.75),  # All score
        ((False, True, True), 2, 0.25),  # 2 score, 1 to 3rd
    ],
}

# Triple advancement - batter to third, all runners score
TRIPLE_ADVANCEMENT: AdvancementMatrix = {
    (False, False, False): [((False, False, True), 0, 1.0)],
    (True, False, False): [((False, False, True), 1, 1.0)],
    (False, True, False): [((False, False, True), 1, 1.0)],
    (False, False, True): [((False, False, True), 1, 1.0)],
    (True, True, False): [((False, False, True), 2, 1.0)],
    (True, False, True): [((False, False, True), 2, 1.0)],
    (False, True, True): [((False, False, True), 2, 1.0)],
    (True, True, True): [((False, False, True), 3, 1.0)],
}

# Walk advancement - force runners only (no extra bases)
WALK_ADVANCEMENT: AdvancementMatrix = {
    # Empty bases - batter to first
    (False, False, False): [((True, False, False), 0, 1.0)],
    # Runner on first - force to second
    (True, False, False): [((True, True, False), 0, 1.0)],
    # Runner on second - no force, just batter to first
    (False, True, False): [((True, True, False), 0, 1.0)],
    # Runner on third - no force, batter to first
    (False, False, True): [((True, False, True), 0, 1.0)],
    # Runners on first and second - force to third
    (True, True, False): [((True, True, True), 0, 1.0)],
    # Runners on first and third - no force on third
    (True, False, True): [((True, True, True), 0, 1.0)],
    # Runners on second and third - no force
    (False, True, True): [((True, True, True), 0, 1.0)],
    # Bases loaded - force scores run
    (True, True, True): [((True, True, True), 1, 1.0)],
}


def advance_runners(
    base_state: BaseState,
    outcome: AtBatOutcome,
    rng: SimulationRNG,
    batter_id: str = "batter",
) -> AdvancementResult:
    """Advance runners based on at-bat outcome.

    Takes the current base state and the outcome of an at-bat,
    then determines where runners end up and how many score.
    Uses probability matrices for realistic advancement patterns.

    Args:
        base_state: Current state of runners on base.
        outcome: The at-bat outcome (SINGLE, HOME_RUN, etc.).
        rng: Random number generator for probabilistic decisions.
        batter_id: Player ID for the batter (for tracking who scored).

    Returns:
        AdvancementResult with new base state, runs scored, and who scored.

    Example:
        >>> from src.simulation.game_state import BaseState
        >>> from src.simulation.outcomes import AtBatOutcome
        >>> from src.simulation.rng import SimulationRNG
        >>> rng = SimulationRNG(seed=42)
        >>> bases = BaseState(first='runner1', second='runner2', third='runner3')
        >>> result = advance_runners(bases, AtBatOutcome.HOME_RUN, rng)
        >>> result.runs_scored
        4
    """
    # Home run - everyone scores (batter + all runners)
    if outcome == AtBatOutcome.HOME_RUN:
        runners = base_state.get_runner_ids()
        runs = base_state.count + 1  # All runners plus batter
        runners_scored = runners + [batter_id]
        return AdvancementResult(
            new_base_state=BaseState(),  # Bases cleared
            runs_scored=runs,
            runners_scored=runners_scored,
        )

    # Select appropriate matrix based on outcome
    if outcome in (AtBatOutcome.SINGLE, AtBatOutcome.INFIELD_SINGLE):
        matrix = SINGLE_ADVANCEMENT
    elif outcome == AtBatOutcome.DOUBLE:
        matrix = DOUBLE_ADVANCEMENT
    elif outcome == AtBatOutcome.TRIPLE:
        matrix = TRIPLE_ADVANCEMENT
    elif outcome in (AtBatOutcome.WALK, AtBatOutcome.HIT_BY_PITCH):
        matrix = WALK_ADVANCEMENT
    elif outcome.is_out:
        # Outs don't advance runners (simplified - no sac fly advancement yet)
        return AdvancementResult(
            new_base_state=base_state,  # Unchanged
            runs_scored=0,
            runners_scored=[],
        )
    else:
        # Default - no advancement (handles reached_on_error etc. simply)
        return AdvancementResult(
            new_base_state=base_state,
            runs_scored=0,
            runners_scored=[],
        )

    # Look up options for current base state
    state_tuple = base_state.as_tuple()
    options = matrix.get(state_tuple, [((True, False, False), 0, 1.0)])

    # Probabilistically select outcome
    if len(options) == 1:
        new_state, runs, _ = options[0]
    else:
        probs = [opt[2] for opt in options]
        idx = rng.choice(list(range(len(options))), probs)
        new_state, runs, _ = options[idx]

    # Build list of runners who scored (simplified - doesn't track individual IDs)
    # In a full implementation, we'd track which specific runners scored
    runners_scored = ["runner"] * runs if runs > 0 else []

    return AdvancementResult(
        new_base_state=BaseState.from_tuple(new_state),
        runs_scored=runs,
        runners_scored=runners_scored,
    )
