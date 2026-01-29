"""Era-specific league average statistics.

This module provides baseline probabilities for different baseball eras,
which are essential for the odds-ratio calculation method.

The odds-ratio formula requires a league average as the baseline:
    Matchup_Odds = (Batter_Odds * Pitcher_Odds) / League_Odds

Without proper era-specific league averages, cross-era comparisons
would be meaningless (1908 deadball vs 2020 would be unfair).

Eras defined:
    - Deadball (1901-1919): Low power, few strikeouts, many triples
    - Liveball (1920-1960): More offense after ban on spitball
    - Modern (1961-present): High strikeouts, more home runs, few triples
"""

from typing import Dict


# Era-specific league average probabilities per plate appearance
# Values are approximate based on historical MLB data from RESEARCH.md
LEAGUE_AVERAGES: Dict[str, Dict[str, float]] = {
    'deadball': {  # 1901-1919
        'strikeout': 0.10,   # Low strikeout rate
        'walk': 0.08,
        'hbp': 0.008,
        'single': 0.18,      # More contact hitting
        'double': 0.04,
        'triple': 0.02,      # More triples (large parks, dead ball)
        'home_run': 0.005,   # Very few home runs
    },
    'liveball': {  # 1920-1960
        'strikeout': 0.12,   # Moderate strikeout rate
        'walk': 0.09,
        'hbp': 0.008,
        'single': 0.17,
        'double': 0.04,
        'triple': 0.015,     # Fewer triples as parks shrink
        'home_run': 0.02,    # Babe Ruth era power
    },
    'modern': {  # 1961-present
        'strikeout': 0.21,   # High strikeout rate (2020s: ~0.23)
        'walk': 0.08,
        'hbp': 0.01,
        'single': 0.15,      # Fewer singles (more power focus)
        'double': 0.045,
        'triple': 0.005,     # Rare (smaller parks, slower runners)
        'home_run': 0.03,    # Modern power era
    },
}


def get_era(year: int) -> str:
    """Return era name for a given year.

    Args:
        year: The season year (e.g., 1927, 2023)

    Returns:
        Era name: 'deadball', 'liveball', or 'modern'

    Examples:
        >>> get_era(1915)
        'deadball'
        >>> get_era(1927)
        'liveball'
        >>> get_era(2023)
        'modern'
    """
    if year < 1920:
        return 'deadball'
    elif year < 1961:
        return 'liveball'
    else:
        return 'modern'


def get_league_averages(year: int) -> Dict[str, float]:
    """Return league averages for a given year's era.

    Args:
        year: The season year (e.g., 1927, 2023)

    Returns:
        Dictionary of event probabilities per plate appearance

    Examples:
        >>> avgs = get_league_averages(2023)
        >>> avgs['strikeout']
        0.21
        >>> avgs['home_run']
        0.03
    """
    era = get_era(year)
    return LEAGUE_AVERAGES[era].copy()


def calculate_out_rate(averages: Dict[str, float]) -> float:
    """Calculate implied out rate from event probabilities.

    The out rate is the complement of all positive outcomes.
    This represents batted-ball outs (groundout, flyout, lineout).

    Args:
        averages: Dictionary of event probabilities

    Returns:
        Out rate = 1 - sum(positive outcomes)

    Examples:
        >>> avgs = get_league_averages(2023)
        >>> out_rate = calculate_out_rate(avgs)
        >>> 0.4 < out_rate < 0.6  # Reasonable range
        True
    """
    positive_outcomes = ['strikeout', 'walk', 'hbp', 'single', 'double', 'triple', 'home_run']
    total_positive = sum(averages.get(outcome, 0.0) for outcome in positive_outcomes)
    return 1.0 - total_positive
