"""Game engine for orchestrating baseball game simulation.

This module provides the GameEngine class that composes the at-bat-level
SimulationEngine from Phase 1 to simulate half-innings and full games.

GameEngine manages:
- Half-inning simulation (plate appearances until 3 outs)
- Score tracking for both teams
- Batting order advancement
- GIDP handling (counts as 2 outs)
"""

from dataclasses import replace as dataclass_replace
from typing import List, Optional, Tuple

from src.data.lahman import LahmanRepository
from src.data.models import PitchingStats
from src.simulation.engine import AtBatResult, SimulationEngine
from src.simulation.game_state import BaseState
from src.simulation.outcomes import AtBatOutcome

from .state import GameState, InningHalf
from .team import Lineup


def transition_half_inning(state: GameState) -> GameState:
    """Transition from completed half-inning to next.

    After TOP of inning: switch to BOTTOM of same inning.
    After BOTTOM of inning: switch to TOP of next inning.

    IMPORTANT: Always clears base_state and resets outs to 0.
    Batting order indices are NOT reset (they persist across innings).

    Args:
        state: GameState with outs >= 3 (half-inning complete)

    Returns:
        New GameState for the next half-inning
    """
    if state.half == InningHalf.TOP:
        # Top complete -> Bottom of same inning
        return dataclass_replace(
            state,
            half=InningHalf.BOTTOM,
            outs=0,
            base_state=BaseState(),  # Clear bases
        )
    else:
        # Bottom complete -> Top of next inning
        return dataclass_replace(
            state,
            inning=state.inning + 1,
            half=InningHalf.TOP,
            outs=0,
            base_state=BaseState(),  # Clear bases
        )


def check_game_complete(state: GameState) -> bool:
    """Check if game should end.

    Baseball game-end rules:
    1. Before 9 innings complete: never ends early
    2. After top of 9+: if home leads, they don't bat (game over)
    3. After bottom of 9+: game ends if not tied
    4. Walk-off: home takes lead in bottom of 9+ (ends immediately)

    Args:
        state: Current game state

    Returns:
        True if game is complete, False if play should continue
    """
    # Regulation: 9 innings minimum
    if state.inning < 9:
        return False

    # After top of 9+: if home leads, they don't need to bat
    if state.half == InningHalf.TOP and state.outs >= 3:
        if state.home_score > state.away_score:
            return True

    # After bottom of 9+: game ends if not tied
    if state.half == InningHalf.BOTTOM and state.outs >= 3:
        return state.home_score != state.away_score

    # Walk-off: home takes lead in bottom of 9+ (mid-inning)
    # This check happens DURING bottom half before 3 outs
    if (state.half == InningHalf.BOTTOM and
        state.inning >= 9 and
        state.home_score > state.away_score):
        return True

    return False


class GameEngine:
    """Orchestrates game flow using at-bat simulation.

    Composes SimulationEngine (from Phase 1) to simulate individual
    at-bats while managing game-level state: innings, outs, score,
    and batting order.

    Attributes:
        sim: SimulationEngine for at-bat resolution
        repository: Optional LahmanRepository for stats lookup
    """

    def __init__(
        self,
        simulation_engine: Optional[SimulationEngine] = None,
        repository: Optional[LahmanRepository] = None,
    ):
        """Initialize GameEngine.

        Args:
            simulation_engine: SimulationEngine instance. If None, creates new one.
            repository: Optional repository for ID-based lookups.
        """
        self.sim = simulation_engine or SimulationEngine(repository=repository)
        self.repository = repository

    def reset_rng(self, seed: Optional[int] = None):
        """Reset RNG for reproducible games."""
        self.sim.reset_rng(seed)

    def _apply_result(
        self,
        state: GameState,
        result: AtBatResult,
    ) -> GameState:
        """Create new state from at-bat result.

        Updates outs, score, base state, and batting order.

        Args:
            state: Current game state.
            result: At-bat result to apply.

        Returns:
            New GameState with updates applied.
        """
        # Calculate new outs (GIDP = 2 outs, capped at 3)
        if result.outcome == AtBatOutcome.GIDP:
            new_outs = min(state.outs + 2, 3)
        elif result.is_out:
            new_outs = state.outs + 1
        else:
            new_outs = state.outs

        # Update score for batting team
        runs = result.runs_scored
        if state.half == InningHalf.TOP:
            new_away = state.away_score + runs
            new_home = state.home_score
        else:
            new_away = state.away_score
            new_home = state.home_score + runs

        # Advance batting order (always advance, even on outs)
        if state.half == InningHalf.TOP:
            new_away_idx = (state.away_batting_index + 1) % 9
            new_home_idx = state.home_batting_index
        else:
            new_away_idx = state.away_batting_index
            new_home_idx = (state.home_batting_index + 1) % 9

        return dataclass_replace(
            state,
            outs=new_outs,
            base_state=result.advancement.new_base_state,
            away_score=new_away,
            home_score=new_home,
            away_batting_index=new_away_idx,
            home_batting_index=new_home_idx,
        )

    def simulate_half_inning(
        self,
        state: GameState,
        batting_lineup: Lineup,
        pitching_stats: PitchingStats,
        park_factor: int = 100,
    ) -> Tuple[GameState, List[AtBatResult]]:
        """Simulate until 3 outs, return new state and play log.

        Args:
            state: Current game state (outs should typically be 0)
            batting_lineup: Lineup of batting team
            pitching_stats: Stats of current pitcher
            park_factor: Park factor (100 = neutral)

        Returns:
            Tuple of (updated GameState with outs=3, list of AtBatResults)
        """
        results: List[AtBatResult] = []
        current_state = state

        while current_state.outs < 3:
            # Get current batter from correct team's lineup index
            batting_idx = current_state.current_batting_index
            batter_slot = batting_lineup.get_batter(batting_idx)

            # Simulate at-bat using Phase 1 engine
            result = self.sim.simulate_at_bat(
                batter_slot.batting_stats,
                pitching_stats,
                current_state.base_state,
                year=batter_slot.batting_stats.year,
                park_factor=park_factor,
            )
            results.append(result)

            # Update state
            current_state = self._apply_result(current_state, result)

        return current_state, results
