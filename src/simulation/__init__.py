"""Simulation package for baseball game simulation.

This package provides the core simulation algorithms including:
- odds_ratio: Probability calculation using the odds-ratio method
- league_averages: Era-specific baseline statistics
"""

from src.simulation.league_averages import (
    get_era,
    get_league_averages,
    calculate_out_rate,
    LEAGUE_AVERAGES,
)

__all__ = [
    "get_era",
    "get_league_averages",
    "calculate_out_rate",
    "LEAGUE_AVERAGES",
]
