"""Convert player statistics to event probabilities.

This module transforms raw batting and pitching statistics from the
Lahman database into event probabilities per plate appearance.

Key insight: Calculate rates per plate appearance, NOT per at-bat,
since walks and HBP don't count as official at-bats.
"""

from typing import Dict

from ..data.models import BattingStats, PitchingStats
from .league_averages import get_league_averages


def calculate_batter_probabilities(stats: BattingStats, year: int) -> Dict[str, float]:
    """Convert batting stats to event probabilities per plate appearance.

    Takes a batter's season statistics and calculates the probability
    of each event type occurring in a plate appearance.

    Args:
        stats: BattingStats object with season totals
        year: Year for league averages (used as fallback)

    Returns:
        Dictionary with keys: strikeout, walk, hbp, single, double,
        triple, home_run. Values are probabilities (0-1).

    Example:
        >>> stats = BattingStats('ruth01', 1927, 'NYA', 151, 540, 158, 192,
        ...                      29, 8, 60, 164, 7, 6, 137, 89, 0, 0, 0, 5)
        >>> probs = calculate_batter_probabilities(stats, 1927)
        >>> 0.08 < probs['home_run'] < 0.10  # ~60 HR / ~690 PA
        True
    """
    pa = stats.plate_appearances
    if pa == 0:
        # No stats - return league average for era
        return get_league_averages(year)

    return {
        'strikeout': stats.strikeouts / pa,
        'walk': stats.walks / pa,
        'hbp': stats.hit_by_pitch / pa if stats.hit_by_pitch else 0,
        'single': stats.singles / pa,
        'double': stats.doubles / pa,
        'triple': stats.triples / pa,
        'home_run': stats.home_runs / pa,
    }


def calculate_pitcher_probabilities(stats: PitchingStats, year: int) -> Dict[str, float]:
    """Convert pitching stats to event probabilities per batter faced.

    Pitching stats track what pitchers ALLOW, so these are opponent rates.
    Since Lahman only has total hits allowed (not breakdown by type),
    we allocate non-HR hits using league ratios.

    Args:
        stats: PitchingStats object with season totals
        year: Year for league averages (used for hit breakdown)

    Returns:
        Dictionary with keys: strikeout, walk, hbp, single, double,
        triple, home_run. Values are probabilities (0-1).

    Example:
        >>> stats = PitchingStats('grove01', 1931, 'PHA', 41, 30, 31, 4,
        ...                       848, 249, 84, 64, 10, 62, 175, 0, 900, 0)
        >>> probs = calculate_pitcher_probabilities(stats, 1931)
        >>> probs['strikeout'] > 0.15  # High K rate
        True
    """
    bf = stats.batters_faced
    if bf == 0:
        return get_league_averages(year)

    # Get league ratios for hit breakdown
    league = get_league_averages(year)

    hits_allowed = stats.hits_allowed
    hr_allowed = stats.home_runs_allowed

    # Non-HR hits allocated by league ratios
    non_hr_hits = hits_allowed - hr_allowed
    non_hr_total = league['single'] + league['double'] + league['triple']

    if non_hr_total > 0:
        single_rate = (league['single'] / non_hr_total) * (non_hr_hits / bf)
        double_rate = (league['double'] / non_hr_total) * (non_hr_hits / bf)
        triple_rate = (league['triple'] / non_hr_total) * (non_hr_hits / bf)
    else:
        single_rate = double_rate = triple_rate = 0

    return {
        'strikeout': stats.strikeouts / bf,
        'walk': stats.walks_allowed / bf,
        'hbp': stats.hit_batters / bf if stats.hit_batters else 0,
        'single': single_rate,
        'double': double_rate,
        'triple': triple_rate,
        'home_run': hr_allowed / bf,
    }


def apply_park_factor(probs: Dict[str, float], park_factor: int) -> Dict[str, float]:
    """Adjust probabilities for park effects.

    Park factor of 100 = neutral.
    110 = 10% more offense (hitter-friendly).
    90 = 10% less offense (pitcher-friendly).

    Apply at 50% effect since players play half games away.

    Args:
        probs: Dictionary of event probabilities
        park_factor: Park factor (100 = neutral)

    Returns:
        New dictionary with adjusted probabilities for hit types.
        Strikeouts, walks, and HBP are unchanged.

    Example:
        >>> probs = {'single': 0.15, 'double': 0.04, 'triple': 0.01,
        ...          'home_run': 0.03, 'strikeout': 0.20, 'walk': 0.08, 'hbp': 0.01}
        >>> adjusted = apply_park_factor(probs, 110)  # Hitter-friendly
        >>> adjusted['home_run'] > probs['home_run']
        True
    """
    if park_factor == 100:
        return probs.copy()

    # Park factor affects hits, especially HR and doubles
    # Apply at 50% since players play half games away
    adjustment = 1 + ((park_factor - 100) / 100) * 0.5

    adjusted = probs.copy()
    for event in ['single', 'double', 'triple', 'home_run']:
        adjusted[event] = probs[event] * adjustment

    return adjusted
