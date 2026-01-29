"""Simulation package for baseball game simulation.

This package provides the core simulation algorithms including:
- odds_ratio: Probability calculation using the odds-ratio method
- league_averages: Era-specific baseline statistics
- rng: Reproducible random number generation with audit trail
- outcomes: At-bat outcome types
- at_bat: At-bat resolution using chained binomial
- game_state: Base state and advancement result tracking
- advancement: Runner advancement logic with probability matrices
"""

from src.simulation.odds_ratio import (
    calculate_odds_ratio,
    calculate_matchup_probabilities,
    normalize_probabilities,
    probability_to_odds,
    odds_to_probability,
)
from src.simulation.league_averages import (
    get_era,
    get_league_averages,
    calculate_out_rate,
    LEAGUE_AVERAGES,
)
from src.simulation.rng import SimulationRNG
from src.simulation.outcomes import AtBatOutcome
from src.simulation.at_bat import (
    calculate_conditional_probabilities,
    resolve_at_bat,
    determine_out_type,
    simulate_at_bat,
)
from src.simulation.game_state import (
    BaseState,
    AdvancementResult,
)
from src.simulation.advancement import (
    advance_runners,
    SINGLE_ADVANCEMENT,
    DOUBLE_ADVANCEMENT,
    TRIPLE_ADVANCEMENT,
    WALK_ADVANCEMENT,
)

__all__ = [
    # odds_ratio
    "calculate_odds_ratio",
    "calculate_matchup_probabilities",
    "normalize_probabilities",
    "probability_to_odds",
    "odds_to_probability",
    # league_averages
    "get_era",
    "get_league_averages",
    "calculate_out_rate",
    "LEAGUE_AVERAGES",
    # rng
    "SimulationRNG",
    # outcomes
    "AtBatOutcome",
    # at_bat
    "calculate_conditional_probabilities",
    "resolve_at_bat",
    "determine_out_type",
    "simulate_at_bat",
    # game_state
    "BaseState",
    "AdvancementResult",
    # advancement
    "advance_runners",
    "SINGLE_ADVANCEMENT",
    "DOUBLE_ADVANCEMENT",
    "TRIPLE_ADVANCEMENT",
    "WALK_ADVANCEMENT",
]
