"""Simulation package for baseball game simulation.

This package provides the core simulation algorithms including:
- odds_ratio: Probability calculation using the odds-ratio method
- league_averages: Era-specific baseline statistics
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

__all__ = [
    "calculate_odds_ratio",
    "calculate_matchup_probabilities",
    "normalize_probabilities",
    "probability_to_odds",
    "odds_to_probability",
    "get_era",
    "get_league_averages",
    "calculate_out_rate",
    "LEAGUE_AVERAGES",
]
