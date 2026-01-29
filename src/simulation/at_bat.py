"""At-bat outcome resolution using chained binomial decision tree.

This module implements the core at-bat resolution algorithm that converts
matchup probabilities into specific game outcomes.

The chained binomial approach:
1. Takes marginal probabilities from the odds-ratio method
2. Converts them to conditional probabilities for a decision tree
3. Walks through the tree using RNG to determine the specific outcome

This ensures all probabilities properly sum to 1 while preserving the
relative likelihoods from the matchup calculation.
"""

from typing import Dict, Optional
from src.simulation.rng import SimulationRNG
from src.simulation.outcomes import AtBatOutcome


# League average out type distribution (modern era)
# Source: General MLB data, can be refined with actual splits
OUT_TYPE_PROBS = {
    'groundout': 0.44,   # ~44% of batted ball outs
    'flyout': 0.28,      # ~28% of batted ball outs
    'lineout': 0.21,     # ~21% of batted ball outs
    'popup': 0.07,       # ~7% of batted ball outs (infield fly)
}

# Strikeout type split (swinging vs looking)
STRIKEOUT_SWINGING_RATE = 0.70  # ~70% swinging, 30% looking

# Infield single rate (as fraction of all singles)
INFIELD_SINGLE_RATE = 0.15  # ~15% of singles are infield singles

# GIDP rate when runner on first with less than 2 outs
# (as fraction of groundouts in that situation)
GIDP_RATE = 0.15

# Sacrifice fly rate when runner on third with less than 2 outs
# (as fraction of flyouts in that situation)
SAC_FLY_RATE = 0.20

# Error rate on batted ball outs (ball in play becomes error)
ERROR_RATE = 0.02


def calculate_conditional_probabilities(
    matchup_probs: Dict[str, float],
    game_situation: Optional[Dict] = None
) -> Dict[str, float]:
    """Convert matchup probabilities to conditional probabilities for decision tree.

    The odds-ratio method gives us marginal probabilities for each event type.
    This function converts them to conditional probabilities that can be used
    in a chained binary decision tree.

    Args:
        matchup_probs: Dictionary with probabilities from odds-ratio calculation:
            - strikeout: P(strikeout)
            - walk: P(walk)
            - hbp: P(hit by pitch)
            - single: P(single)
            - double: P(double)
            - triple: P(triple)
            - home_run: P(home run)
        game_situation: Optional dict with game context:
            - outs: Number of outs (0, 1, or 2)
            - runners: Dict with 'first', 'second', 'third' booleans

    Returns:
        Dictionary with conditional probabilities for each decision point:
            - hbp: P(hit by pitch) [first check]
            - walk: P(walk | not HBP)
            - strikeout: P(strikeout | not HBP, not walk)
            - home_run_given_contact: P(HR | contact made)
            - hit_given_non_hr_contact: P(hit | contact, not HR)
            - extra_base_given_hit: P(XBH | hit, not HR)
            - triple_given_extra_base: P(triple | XBH)

    Example:
        >>> probs = {'strikeout': 0.20, 'walk': 0.08, 'hbp': 0.01,
        ...          'single': 0.15, 'double': 0.04, 'triple': 0.005,
        ...          'home_run': 0.03}
        >>> cond = calculate_conditional_probabilities(probs)
        >>> 0 <= cond['strikeout'] <= 1
        True
    """
    # Extract input probabilities with defaults
    p_hbp = matchup_probs.get('hbp', 0.01)
    p_walk = matchup_probs.get('walk', 0.08)
    p_strikeout = matchup_probs.get('strikeout', 0.20)
    p_single = matchup_probs.get('single', 0.15)
    p_double = matchup_probs.get('double', 0.04)
    p_triple = matchup_probs.get('triple', 0.005)
    p_home_run = matchup_probs.get('home_run', 0.03)

    # Calculate conditional probabilities for decision tree

    # After HBP check fails, what's the probability of walk?
    p_not_hbp = 1.0 - p_hbp
    p_walk_given_not_hbp = p_walk / p_not_hbp if p_not_hbp > 0 else 0

    # After walk check fails, what's the probability of strikeout?
    p_not_hbp_not_walk = p_not_hbp - p_walk
    p_strikeout_given_not_hbp_walk = (
        p_strikeout / p_not_hbp_not_walk if p_not_hbp_not_walk > 0 else 0
    )

    # Contact was made - calculate probabilities for hits
    # P(contact) = 1 - P(hbp) - P(walk) - P(strikeout)
    p_contact = 1.0 - p_hbp - p_walk - p_strikeout

    # All hits
    p_hits = p_single + p_double + p_triple + p_home_run

    # Home run given contact
    p_hr_given_contact = p_home_run / p_contact if p_contact > 0 else 0

    # Non-HR contact
    p_non_hr_contact = p_contact - p_home_run

    # Hit (single, double, triple) given non-HR contact
    p_non_hr_hits = p_single + p_double + p_triple
    p_hit_given_non_hr_contact = (
        p_non_hr_hits / p_non_hr_contact if p_non_hr_contact > 0 else 0
    )

    # Extra base hit (double or triple) given hit (not HR)
    p_extra_base = p_double + p_triple
    p_extra_base_given_hit = (
        p_extra_base / p_non_hr_hits if p_non_hr_hits > 0 else 0
    )

    # Triple given extra base hit
    p_triple_given_extra_base = (
        p_triple / p_extra_base if p_extra_base > 0 else 0
    )

    # Clamp all probabilities to [0, 1] to handle floating point issues
    def clamp(x):
        return max(0.0, min(1.0, x))

    return {
        'hbp': clamp(p_hbp),
        'walk': clamp(p_walk_given_not_hbp),
        'strikeout': clamp(p_strikeout_given_not_hbp_walk),
        'home_run_given_contact': clamp(p_hr_given_contact),
        'hit_given_non_hr_contact': clamp(p_hit_given_non_hr_contact),
        'extra_base_given_hit': clamp(p_extra_base_given_hit),
        'triple_given_extra_base': clamp(p_triple_given_extra_base),
    }


def determine_out_type(
    rng: SimulationRNG,
    game_situation: Optional[Dict] = None
) -> AtBatOutcome:
    """Determine the type of batted ball out.

    Uses league average distributions for out types (groundout, flyout, etc.)
    and considers game situation for special outcomes like GIDP and sac fly.

    Args:
        rng: Random number generator for the decision
        game_situation: Optional dict with:
            - outs: Number of outs (0, 1, or 2)
            - runners: Dict with 'first', 'second', 'third' booleans

    Returns:
        AtBatOutcome for the type of out
    """
    # Check for error first (rare)
    if rng.random() < ERROR_RATE:
        return AtBatOutcome.REACHED_ON_ERROR

    # Determine base out type
    roll = rng.random()

    cumulative = 0.0
    out_type = AtBatOutcome.GROUNDOUT  # default

    for outcome_name, prob in OUT_TYPE_PROBS.items():
        cumulative += prob
        if roll < cumulative:
            if outcome_name == 'groundout':
                out_type = AtBatOutcome.GROUNDOUT
            elif outcome_name == 'flyout':
                out_type = AtBatOutcome.FLYOUT
            elif outcome_name == 'lineout':
                out_type = AtBatOutcome.LINEOUT
            elif outcome_name == 'popup':
                out_type = AtBatOutcome.POPUP
            break

    # Check for situational outcomes
    if game_situation:
        outs = game_situation.get('outs', 0)
        runners = game_situation.get('runners', {})

        # GIDP: groundout with runner on first, less than 2 outs
        if (out_type == AtBatOutcome.GROUNDOUT and
            outs < 2 and
            runners.get('first', False)):
            if rng.random() < GIDP_RATE:
                return AtBatOutcome.GIDP

        # Sacrifice fly: flyout with runner on third, less than 2 outs
        if (out_type == AtBatOutcome.FLYOUT and
            outs < 2 and
            runners.get('third', False)):
            if rng.random() < SAC_FLY_RATE:
                return AtBatOutcome.SACRIFICE_FLY

    return out_type


def resolve_at_bat(
    conditional_probs: Dict[str, float],
    rng: SimulationRNG,
    game_situation: Optional[Dict] = None
) -> AtBatOutcome:
    """Resolve an at-bat using the chained binomial decision tree.

    This function walks through a binary decision tree, using the RNG
    at each branch point to determine the path. The conditional probabilities
    ensure that the marginal probabilities of outcomes match the input.

    Decision tree structure:
    1. HBP? -> HIT_BY_PITCH
    2. Walk? -> WALK
    3. Strikeout? -> STRIKEOUT_SWINGING or STRIKEOUT_LOOKING
    4. (Contact made)
    5. Home run? -> HOME_RUN
    6. Hit? -> proceed to hit type determination
    7. Extra base? -> DOUBLE or TRIPLE
    8. Otherwise -> SINGLE or INFIELD_SINGLE
    9. (Out on batted ball) -> determine out type

    Args:
        conditional_probs: Dictionary of conditional probabilities from
            calculate_conditional_probabilities()
        rng: SimulationRNG instance for random decisions
        game_situation: Optional dict with game context for situational
            outcomes (GIDP, sac fly)

    Returns:
        AtBatOutcome representing the result of the plate appearance

    Example:
        >>> from src.simulation.rng import SimulationRNG
        >>> probs = {'strikeout': 0.20, 'walk': 0.08, 'hbp': 0.01,
        ...          'single': 0.15, 'double': 0.04, 'triple': 0.005,
        ...          'home_run': 0.03}
        >>> cond = calculate_conditional_probabilities(probs)
        >>> rng = SimulationRNG(seed=42)
        >>> outcome = resolve_at_bat(cond, rng)
        >>> isinstance(outcome, AtBatOutcome)
        True
    """
    # 1. Hit by pitch (checked first - very rare)
    if rng.random() < conditional_probs['hbp']:
        return AtBatOutcome.HIT_BY_PITCH

    # 2. Walk
    if rng.random() < conditional_probs['walk']:
        return AtBatOutcome.WALK

    # 3. Strikeout (no contact made)
    if rng.random() < conditional_probs['strikeout']:
        # Determine swinging vs looking
        if rng.random() < STRIKEOUT_SWINGING_RATE:
            return AtBatOutcome.STRIKEOUT_SWINGING
        return AtBatOutcome.STRIKEOUT_LOOKING

    # Contact was made - now determine outcome

    # 4. Home run (given contact)
    if rng.random() < conditional_probs['home_run_given_contact']:
        return AtBatOutcome.HOME_RUN

    # 5. Hit vs out (given non-HR contact)
    if rng.random() < conditional_probs['hit_given_non_hr_contact']:
        # 6. Extra base hit (given hit)
        if rng.random() < conditional_probs['extra_base_given_hit']:
            # 7. Triple vs double
            if rng.random() < conditional_probs['triple_given_extra_base']:
                return AtBatOutcome.TRIPLE
            return AtBatOutcome.DOUBLE

        # Single - check for infield single
        if rng.random() < INFIELD_SINGLE_RATE:
            return AtBatOutcome.INFIELD_SINGLE
        return AtBatOutcome.SINGLE

    # Out on batted ball - determine type
    return determine_out_type(rng, game_situation)


def simulate_at_bat(
    matchup_probs: Dict[str, float],
    rng: SimulationRNG,
    game_situation: Optional[Dict] = None
) -> AtBatOutcome:
    """Convenience function to simulate an at-bat from raw matchup probabilities.

    This combines calculate_conditional_probabilities and resolve_at_bat
    for simpler usage when you just want to get an outcome.

    Args:
        matchup_probs: Raw probabilities from odds-ratio calculation
        rng: SimulationRNG instance
        game_situation: Optional game context

    Returns:
        AtBatOutcome for the plate appearance
    """
    cond_probs = calculate_conditional_probabilities(matchup_probs, game_situation)
    return resolve_at_bat(cond_probs, rng, game_situation)
