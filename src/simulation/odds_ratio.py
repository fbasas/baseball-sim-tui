"""Odds-ratio method for combining batter, pitcher, and league probabilities.

This is the mathematical core of the simulation. The odds-ratio method
(a variant of Bill James' log5 formula) properly handles the multiplicative
interaction between batter and pitcher abilities.

Key insight: Do NOT simply average batter and pitcher rates.
A 47% K pitcher vs 31% K batter should NOT produce 39% K rate.
The odds-ratio method correctly reflects that elite players dominate.

The formula:
    Odds = probability / (1 - probability)
    Matchup_Odds = (Batter_Odds * Pitcher_Odds) / League_Odds
    Result = Matchup_Odds / (1 + Matchup_Odds)

Sources:
    - SABR: https://sabr.org/journal/article/matchup-probabilities-in-major-league-baseball/
    - Inside the Book: http://www.insidethebook.com/ee/index.php/site/comments/the_odds_ratio_method
"""

from typing import Dict


def probability_to_odds(prob: float) -> float:
    """Convert probability to odds ratio.

    Args:
        prob: Probability value between 0 and 1

    Returns:
        Odds ratio (probability / (1 - probability))

    Raises:
        ValueError: If probability is outside [0, 1] range

    Examples:
        >>> probability_to_odds(0.5)
        1.0
        >>> probability_to_odds(0.25)
        0.3333333333333333
        >>> probability_to_odds(0.75)
        3.0
        >>> probability_to_odds(0.0)
        0.0
    """
    if prob < 0 or prob > 1:
        raise ValueError(f"Probability must be between 0 and 1, got {prob}")

    if prob == 0:
        return 0.0
    if prob == 1:
        return float('inf')

    return prob / (1 - prob)


def odds_to_probability(odds: float) -> float:
    """Convert odds ratio back to probability.

    Args:
        odds: Odds ratio (non-negative)

    Returns:
        Probability value between 0 and 1

    Examples:
        >>> odds_to_probability(1.0)
        0.5
        >>> odds_to_probability(0.0)
        0.0
        >>> odds_to_probability(float('inf'))
        1.0
    """
    if odds == float('inf'):
        return 1.0
    if odds < 0:
        raise ValueError(f"Odds must be non-negative, got {odds}")

    return odds / (1 + odds)


def calculate_odds_ratio(
    batter_prob: float,
    pitcher_prob: float,
    league_prob: float
) -> float:
    """Combine three probabilities using the odds-ratio method.

    This formula properly weights batter and pitcher abilities relative
    to the league average. It prevents the "naive averaging" pitfall.

    Formula:
        matchup_odds = (batter_odds * pitcher_odds) / league_odds
        result = matchup_odds / (1 + matchup_odds)

    Args:
        batter_prob: Batter's probability for this event type
        pitcher_prob: Pitcher's probability for this event type
        league_prob: League average probability for this event type

    Returns:
        Combined matchup probability

    Raises:
        ValueError: If league_prob is not strictly between 0 and 1

    Examples:
        >>> # Both average = league average result
        >>> calculate_odds_ratio(0.21, 0.21, 0.21)
        0.21

        >>> # Elite pitcher vs weak hitter - pitcher dominates
        >>> result = calculate_odds_ratio(0.20, 0.25, 0.21)
        >>> 0.23 < result < 0.24  # Should be ~0.238, NOT naive 0.225
        True

        >>> # Above-average pitcher vs above-average hitter (K context)
        >>> result = calculate_odds_ratio(0.30, 0.25, 0.21)  # Both above avg K
        >>> result > 0.275  # Higher than naive average
        True
    """
    # Validate league probability - must be strictly between 0 and 1
    # (we divide by league_odds, so league_prob can't be 0 or 1)
    if league_prob <= 0 or league_prob >= 1:
        raise ValueError(
            f"League probability must be strictly between 0 and 1, got {league_prob}"
        )

    # Handle edge cases for batter/pitcher
    if batter_prob == 0 or pitcher_prob == 0:
        return 0.0
    if batter_prob == 1 or pitcher_prob == 1:
        return 1.0

    # Convert to odds
    batter_odds = probability_to_odds(batter_prob)
    pitcher_odds = probability_to_odds(pitcher_prob)
    league_odds = probability_to_odds(league_prob)

    # Calculate matchup odds
    matchup_odds = (batter_odds * pitcher_odds) / league_odds

    # Convert back to probability
    return odds_to_probability(matchup_odds)


def calculate_matchup_probabilities(
    batter_probs: Dict[str, float],
    pitcher_probs: Dict[str, float],
    league_probs: Dict[str, float]
) -> Dict[str, float]:
    """Apply odds-ratio to each event type.

    Combines batter, pitcher, and league probabilities for all outcome
    types using the odds-ratio method.

    Args:
        batter_probs: Batter's probabilities by event type
        pitcher_probs: Pitcher's probabilities by event type
        league_probs: League average probabilities by event type

    Returns:
        Dictionary of unnormalized matchup probabilities

    Note:
        The returned probabilities are NOT normalized (may not sum to 1).
        Use normalize_probabilities() if you need normalized values.

    Examples:
        >>> batter = {'strikeout': 0.20, 'walk': 0.10, 'hbp': 0.01,
        ...           'single': 0.17, 'double': 0.05, 'triple': 0.01, 'home_run': 0.04}
        >>> pitcher = {'strikeout': 0.25, 'walk': 0.07, 'hbp': 0.008,
        ...            'single': 0.14, 'double': 0.04, 'triple': 0.004, 'home_run': 0.025}
        >>> league = {'strikeout': 0.21, 'walk': 0.08, 'hbp': 0.01,
        ...           'single': 0.15, 'double': 0.045, 'triple': 0.005, 'home_run': 0.03}
        >>> result = calculate_matchup_probabilities(batter, pitcher, league)
        >>> 'strikeout' in result and 'home_run' in result
        True
    """
    events = ['strikeout', 'walk', 'hbp', 'single', 'double', 'triple', 'home_run']
    matchup = {}

    for event in events:
        # Get probabilities, defaulting to league average if missing
        batter_p = batter_probs.get(event, league_probs[event])
        pitcher_p = pitcher_probs.get(event, league_probs[event])
        league_p = league_probs[event]

        matchup[event] = calculate_odds_ratio(batter_p, pitcher_p, league_p)

    return matchup


def normalize_probabilities(probs: Dict[str, float]) -> Dict[str, float]:
    """Scale probabilities so they sum to 1.0.

    Preserves the relative ratios between probabilities while ensuring
    the total equals 1.0.

    Args:
        probs: Dictionary of unnormalized probabilities

    Returns:
        New dictionary with normalized probabilities (sum = 1.0)

    Raises:
        ValueError: If total is zero (all probabilities are 0)

    Examples:
        >>> result = normalize_probabilities({'a': 0.3, 'b': 0.4, 'c': 0.5})
        >>> abs(sum(result.values()) - 1.0) < 0.0001
        True
        >>> abs(result['a'] / result['b'] - 0.75) < 0.0001  # Ratio preserved
        True
    """
    total = sum(probs.values())

    if total == 0:
        raise ValueError("Cannot normalize: all probabilities are zero")

    return {k: v / total for k, v in probs.items()}
