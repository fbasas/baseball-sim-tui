"""Main simulation engine orchestrating all components.

This is the integration point that combines:
- Data loading (LahmanRepository)
- Probability calculation (odds-ratio)
- Outcome resolution (chained binomial)
- Runner advancement

The engine provides a simple interface for simulating at-bats
while handling all the complexity internally.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional

from ..data.models import BattingStats, PitchingStats
from ..data.lahman import LahmanRepository
from .odds_ratio import calculate_matchup_probabilities, normalize_probabilities
from .league_averages import get_league_averages
from .stats_calculator import (
    calculate_batter_probabilities,
    calculate_pitcher_probabilities,
    apply_park_factor,
)
from .at_bat import calculate_conditional_probabilities, resolve_at_bat
from .outcomes import AtBatOutcome
from .advancement import advance_runners
from .game_state import BaseState, AdvancementResult
from .rng import SimulationRNG


@dataclass
class AtBatResult:
    """Complete result of an at-bat simulation.

    Contains the outcome, runner advancement, probabilities used,
    and a full audit trail of RNG decisions for debugging/replay.

    Attributes:
        outcome: The specific at-bat outcome (SINGLE, STRIKEOUT, etc.)
        advancement: Runner positions and runs scored
        probabilities: Matchup probabilities that were used
        audit_trail: List of RNG decisions for debugging

    Example:
        >>> result = engine.simulate_at_bat(batter, pitcher)
        >>> print(f"{result.outcome}: {result.runs_scored} runs")
        SINGLE: 1 runs
    """

    outcome: AtBatOutcome
    advancement: AdvancementResult
    probabilities: Dict[str, float]
    audit_trail: List[tuple]

    @property
    def runs_scored(self) -> int:
        """Number of runs scored on this play."""
        return self.advancement.runs_scored

    @property
    def is_hit(self) -> bool:
        """Whether the outcome was a hit."""
        return self.outcome.is_hit

    @property
    def is_out(self) -> bool:
        """Whether the outcome resulted in an out."""
        return self.outcome.is_out


class SimulationEngine:
    """Main simulation engine for at-bat resolution.

    Orchestrates:
    - Loading player statistics
    - Calculating matchup probabilities (odds-ratio)
    - Resolving at-bat outcomes (chained binomial)
    - Advancing runners

    The engine maintains its own RNG for reproducibility. Seed the RNG
    to get deterministic results.

    Attributes:
        repository: Optional LahmanRepository for loading stats by ID
        rng: SimulationRNG for random decisions

    Example:
        >>> engine = SimulationEngine()
        >>> engine.reset_rng(42)  # Seed for reproducibility
        >>> result = engine.simulate_at_bat(batter_stats, pitcher_stats)
        >>> print(result.outcome)
        SINGLE
    """

    def __init__(
        self,
        repository: Optional[LahmanRepository] = None,
        rng: Optional[SimulationRNG] = None,
    ):
        """Initialize the simulation engine.

        Args:
            repository: Optional LahmanRepository for ID-based simulation.
                       If None, must pass stats objects directly.
            rng: Optional SimulationRNG. If None, creates unseeded RNG.
        """
        self.repository = repository
        self.rng = rng or SimulationRNG()

    def simulate_at_bat(
        self,
        batter_stats: BattingStats,
        pitcher_stats: PitchingStats,
        base_state: Optional[BaseState] = None,
        year: Optional[int] = None,
        park_factor: int = 100,
    ) -> AtBatResult:
        """Simulate a single at-bat.

        This is the main entry point for simulation. It:
        1. Calculates individual probabilities from stats
        2. Combines them using odds-ratio method
        3. Resolves the outcome using chained binomial
        4. Advances runners based on outcome

        Args:
            batter_stats: Batter's season statistics
            pitcher_stats: Pitcher's season statistics
            base_state: Current runners on base (default: empty)
            year: Year for league averages (default: from batter_stats)
            park_factor: Park factor (100 = neutral)

        Returns:
            AtBatResult with outcome, advancement, probabilities, and audit trail

        Example:
            >>> result = engine.simulate_at_bat(batter, pitcher, BaseState(first='r1'))
            >>> print(f"{result.outcome}: {result.runs_scored} runs")
        """
        # Default values
        if base_state is None:
            base_state = BaseState()
        if year is None:
            year = batter_stats.year

        # Track audit trail start position
        initial_trail_length = len(self.rng.history)

        # Step 1: Calculate probabilities from stats
        batter_probs = calculate_batter_probabilities(batter_stats, year)
        pitcher_probs = calculate_pitcher_probabilities(pitcher_stats, year)
        league_probs = get_league_averages(year)

        # Apply park factor to batter (home player)
        batter_probs = apply_park_factor(batter_probs, park_factor)

        # Step 2: Combine using odds-ratio
        # NOTE: Do NOT normalize - at_bat.py needs unnormalized probabilities
        # to correctly compute out rates (implicit in the remainder)
        matchup_probs = calculate_matchup_probabilities(
            batter_probs, pitcher_probs, league_probs
        )

        # Step 3: Calculate conditional probabilities for decision tree
        game_situation = {
            'outs': 0,  # Simplified - full tracking in Phase 2
            'runners': {
                'first': base_state.first is not None,
                'second': base_state.second is not None,
                'third': base_state.third is not None,
            },
        }
        conditional_probs = calculate_conditional_probabilities(
            matchup_probs, game_situation
        )

        # Step 4: Resolve outcome
        outcome = resolve_at_bat(conditional_probs, self.rng, game_situation)

        # Step 5: Advance runners
        advancement = advance_runners(
            base_state, outcome, self.rng, batter_stats.player_id
        )

        # Extract audit trail for this at-bat only
        audit_trail = self.rng.history[initial_trail_length:]

        return AtBatResult(
            outcome=outcome,
            advancement=advancement,
            probabilities=matchup_probs,
            audit_trail=audit_trail,
        )

    def simulate_at_bat_from_ids(
        self,
        batter_id: str,
        batter_year: int,
        pitcher_id: str,
        pitcher_year: int,
        base_state: Optional[BaseState] = None,
        park_factor: int = 100,
    ) -> Optional[AtBatResult]:
        """Simulate at-bat by loading stats from repository.

        Convenience method that loads player statistics by ID and year,
        then simulates the at-bat.

        Args:
            batter_id: Lahman player ID for batter
            batter_year: Season year for batter stats
            pitcher_id: Lahman player ID for pitcher
            pitcher_year: Season year for pitcher stats
            base_state: Current runners on base (default: empty)
            park_factor: Park factor (100 = neutral)

        Returns:
            AtBatResult if both players found, None if either not found.

        Raises:
            ValueError: If repository was not provided to constructor.

        Example:
            >>> result = engine.simulate_at_bat_from_ids('ruthba01', 1927, 'grover01', 1927)
        """
        if self.repository is None:
            raise ValueError("Repository required for ID-based simulation")

        batter_stats = self.repository.get_batting_stats(batter_id, batter_year)
        pitcher_stats = self.repository.get_pitching_stats(pitcher_id, pitcher_year)

        if batter_stats is None or pitcher_stats is None:
            return None

        return self.simulate_at_bat(
            batter_stats,
            pitcher_stats,
            base_state,
            year=batter_year,
            park_factor=park_factor,
        )

    def get_expected_probabilities(
        self,
        batter_stats: BattingStats,
        pitcher_stats: PitchingStats,
        year: Optional[int] = None,
        park_factor: int = 100,
    ) -> Dict[str, float]:
        """Get matchup probabilities without simulating (no RNG).

        Useful for displaying expected outcomes before an at-bat
        or analyzing matchups without running simulations.

        Note: Probabilities are NOT normalized and will sum to less than 1.0.
        The remainder represents probability of batted-ball outs.
        Use normalize_probabilities() if you need normalized values.

        Args:
            batter_stats: Batter's season statistics
            pitcher_stats: Pitcher's season statistics
            year: Year for league averages (default: from batter_stats)
            park_factor: Park factor (100 = neutral)

        Returns:
            Dictionary of unnormalized matchup probabilities.
            Keys: strikeout, walk, hbp, single, double, triple, home_run
            The sum will be approximately 0.50-0.55 (remainder is out on contact).

        Example:
            >>> probs = engine.get_expected_probabilities(batter, pitcher)
            >>> print(f"K%: {probs['strikeout']:.1%}")
            K%: 16.5%
            >>> print(f"Out on contact: {1 - sum(probs.values()):.1%}")
            Out on contact: 46.8%
        """
        if year is None:
            year = batter_stats.year

        batter_probs = calculate_batter_probabilities(batter_stats, year)
        pitcher_probs = calculate_pitcher_probabilities(pitcher_stats, year)
        league_probs = get_league_averages(year)

        batter_probs = apply_park_factor(batter_probs, park_factor)

        return calculate_matchup_probabilities(
            batter_probs, pitcher_probs, league_probs
        )

    def reset_rng(self, seed: Optional[int] = None):
        """Reset RNG with new seed.

        Call this to make simulations reproducible or to start
        a fresh sequence.

        Args:
            seed: New seed value. If None, reuses original seed.
        """
        self.rng.reset(seed)
