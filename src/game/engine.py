"""Game engine for orchestrating baseball game simulation.

This module provides the GameEngine class that composes the at-bat-level
SimulationEngine from Phase 1 to simulate half-innings and full games.

GameEngine manages:
- Half-inning simulation (plate appearances until 3 outs)
- Score tracking for both teams
- Batting order advancement
- GIDP handling (counts as 2 outs)
"""

from dataclasses import dataclass, replace as dataclass_replace
from typing import TYPE_CHECKING, List, Optional, Tuple

from src.data.lahman import LahmanRepository
from src.data.models import PitchingStats
from src.simulation.engine import AtBatResult, SimulationEngine
from src.simulation.game_state import BaseState
from src.simulation.outcomes import AtBatOutcome
from src.game.fatigue import FatigueState, calculate_fatigue, update_fatigue_state, FatigueConfig
from src.game.substitutions import SubstitutionManager

from .state import GameState, InningHalf
from .team import Lineup

if TYPE_CHECKING:
    from .team import Team
    from .positions import Position


def apply_fatigue_modifier(
    pitching_stats: PitchingStats,
    fatigue: float,
) -> PitchingStats:
    """Create modified pitching stats accounting for fatigue.

    Fatigue increases opponent offensive outcomes proportionally:
    - hits_allowed = base_hits * (1 + fatigue * 0.5)  # Up to 50% more hits at max fatigue
    - walks = base_walks * (1 + fatigue * 0.3)  # Up to 30% more walks
    - home_runs = base_hrs * (1 + fatigue * 0.4)  # Up to 40% more HRs

    Args:
        pitching_stats: Original pitching stats
        fatigue: Fatigue value 0.0-1.0

    Returns:
        New PitchingStats with fatigue adjustments applied
    """
    # Use dataclasses.replace to create modified copy
    from dataclasses import replace
    return replace(
        pitching_stats,
        hits_allowed=int(pitching_stats.hits_allowed * (1 + fatigue * 0.5)),
        walks_allowed=int(pitching_stats.walks_allowed * (1 + fatigue * 0.3)),
        home_runs_allowed=int(pitching_stats.home_runs_allowed * (1 + fatigue * 0.4)),
    )


def resolve_pitcher_stats(
    state: GameState,
    pitching_team: 'Team',
) -> Tuple[str, PitchingStats]:
    """Return (pitcher_id, fatigue_modified_pitching_stats) for the current AB.

    Reads the active pitcher from GameState (not from lineup.starting_pitcher_id),
    looks up the team's PitchingStats, and applies the fatigue modifier from
    state.current_pitcher_fatigue. Falls back to lineup.starting_pitcher_id only if
    GameState has no pitcher set (pre-finalize edge case).

    This is the single source of truth for the TUI hot path's pitcher-stats
    lookup. GameScreen.advance_game calls this BEFORE each call to
    engine.sim.simulate_at_bat so that (a) pitching changes recorded in
    GameState are honored and (b) fatigue modifies hits/walks/HRs allowed.

    NOTE: simulate_half_inning duplicates the fatigue application
    (apply_fatigue_modifier per AB) because its signature accepts a
    caller-supplied pitching_stats rather than a team. If the fatigue formula
    changes (currently hits *= 1+f*0.5, walks *= 1+f*0.3, HRs *= 1+f*0.4),
    BOTH this function AND simulate_half_inning's per-AB loop must be updated.

    Args:
        state: Current GameState
        pitching_team: Team currently in the field (provides pitching_stats dict)

    Returns:
        Tuple of (pitcher_id, fatigue_modified PitchingStats)
    """
    pitcher_id = state.current_pitcher_id
    if pitcher_id is None:
        # Pre-finalize edge case: GameState not yet seeded with pitcher IDs
        pitcher_id = pitching_team.lineup.starting_pitcher_id

    base_stats = pitching_team.pitching_stats[pitcher_id]

    fatigue_state = state.current_pitcher_fatigue
    fatigue_value = fatigue_state.current_fatigue if fatigue_state else 0.0

    modified_stats = apply_fatigue_modifier(base_stats, fatigue_value)
    return pitcher_id, modified_stats


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
        substitution_manager: Optional[SubstitutionManager] = None,
    ):
        """Initialize GameEngine.

        Args:
            simulation_engine: SimulationEngine instance. If None, creates new one.
            repository: Optional repository for ID-based lookups.
            substitution_manager: Optional SubstitutionManager for tracking subs.
        """
        self.sim = simulation_engine or SimulationEngine(repository=repository)
        self.repository = repository
        self.sub_manager = substitution_manager

    def reset_rng(self, seed: Optional[int] = None):
        """Reset RNG for reproducible games."""
        self.sim.reset_rng(seed)

    def make_substitution(
        self,
        state: GameState,
        team: 'Team',
        is_away_team: bool,
        player_out_id: str,
        player_in_id: str,
        new_position: Optional['Position'] = None,
        is_pitching_change: bool = False,
    ) -> Tuple[GameState, 'Team']:
        """Execute a substitution and return updated state/team.

        For pitching changes:
        - Updates current pitcher in GameState
        - Resets pitcher fatigue to fresh state
        - Records substitution in manager

        For position players:
        - Updates lineup slot with new player
        - Records substitution in manager

        Args:
            state: Current GameState
            team: Team making substitution
            is_away_team: True if away team making sub
            player_out_id: Player being removed
            player_in_id: Player entering
            new_position: Position for entering player (None keeps same)
            is_pitching_change: True if this is a pitching change

        Returns:
            (new_state, modified_team) tuple

        Raises:
            ValueError: If substitution is illegal (re-entry, invalid player)
        """
        from src.game.positions import Position
        from src.game.substitutions import SubstitutionRecord, SubstitutionType

        # Validate substitution if manager exists
        if self.sub_manager is not None:
            if is_pitching_change:
                valid, error = self.sub_manager.validate_pitching_change(
                    player_out_id, player_in_id
                )
            else:
                valid, error = self.sub_manager.validate_pinch_hitter(
                    player_out_id, player_in_id
                )
            if not valid:
                raise ValueError(error)

        if is_pitching_change:
            # Update pitcher in state
            new_state = state.with_pitcher(player_in_id, FatigueState())

            # Record substitution if manager exists
            if self.sub_manager is not None:
                record = SubstitutionRecord(
                    inning=state.inning,
                    half=state.half,
                    sub_type=SubstitutionType.PITCHING_CHANGE,
                    player_out_id=player_out_id,
                    player_in_id=player_in_id,
                    old_position=Position.PITCHER if isinstance(new_position, type(Position)) else None,
                    new_position=Position.PITCHER if isinstance(new_position, type(Position)) else None,
                    batting_order_slot=0,  # Pitchers typically don't have batting slot in lineup
                    dh_forfeited=False,
                )
                self.sub_manager.record_substitution(record)

            return new_state, team
        else:
            # Position player substitution
            if team.lineup is None:
                raise ValueError("Team lineup not set")

            # Find which slot the player_out is in
            slot_index = None
            for i, slot in enumerate(team.lineup.slots):
                if slot.player_id == player_out_id:
                    slot_index = i
                    break

            if slot_index is None:
                raise ValueError(f"Player {player_out_id} not found in lineup")

            # Update the lineup
            team.update_lineup_slot(slot_index, player_in_id, new_position)

            # Record substitution if manager exists
            if self.sub_manager is not None:
                record = SubstitutionRecord(
                    inning=state.inning,
                    half=state.half,
                    sub_type=SubstitutionType.PINCH_HITTER,
                    player_out_id=player_out_id,
                    player_in_id=player_in_id,
                    old_position=team.lineup.slots[slot_index].position if isinstance(team.lineup.slots[slot_index].position, Position) else None,
                    new_position=new_position,
                    batting_order_slot=slot_index,
                    dh_forfeited=False,
                )
                self.sub_manager.record_substitution(record)

            return state, team

    def _apply_result(
        self,
        state: GameState,
        result: AtBatResult,
    ) -> GameState:
        """Create new state from at-bat result.

        Updates outs, score, base state, batting order, and pitcher fatigue.

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

        # Update pitcher fatigue
        current_fatigue = state.current_pitcher_fatigue
        # Determine batter's position in order for TTO tracking
        batting_idx = (state.current_batting_index % 9) + 1  # 1-9
        runners_on = (1 if state.base_state.first else 0) + \
                     (1 if state.base_state.second else 0) + \
                     (1 if state.base_state.third else 0)
        close_game = abs(state.away_score - state.home_score) <= 2

        new_fatigue = update_fatigue_state(
            current_fatigue,
            batters_in_order=batting_idx,
            runners_on=runners_on,
            close_game=close_game,
        )

        # Determine which pitcher fatigue to update
        if state.half == InningHalf.TOP:
            # Home team is fielding
            new_away_fatigue = state.away_pitcher_fatigue
            new_home_fatigue = new_fatigue
        else:
            # Away team is fielding
            new_away_fatigue = new_fatigue
            new_home_fatigue = state.home_pitcher_fatigue

        return dataclass_replace(
            state,
            outs=new_outs,
            base_state=result.advancement.new_base_state,
            away_score=new_away,
            home_score=new_home,
            away_batting_index=new_away_idx,
            home_batting_index=new_home_idx,
            away_pitcher_fatigue=new_away_fatigue,
            home_pitcher_fatigue=new_home_fatigue,
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

            # NOTE: This duplicates the fatigue application in resolve_pitcher_stats
            # (used by the TUI hot path). simulate_half_inning intentionally keeps
            # its pitching_stats signature; if the fatigue formula changes, update
            # BOTH this call site AND resolve_pitcher_stats.
            current_fatigue = (
                current_state.current_pitcher_fatigue.current_fatigue
                if current_state.current_pitcher_fatigue
                else 0.0
            )
            ab_pitching_stats = apply_fatigue_modifier(pitching_stats, current_fatigue)

            # Simulate at-bat using Phase 1 engine
            result = self.sim.simulate_at_bat(
                batter_slot.batting_stats,
                ab_pitching_stats,
                current_state.base_state,
                year=batter_slot.batting_stats.year,
                park_factor=park_factor,
            )
            results.append(result)

            # Update state
            current_state = self._apply_result(current_state, result)

        return current_state, results


@dataclass
class GameResult:
    """Complete game result with final state and play history."""

    final_state: GameState
    play_log: List[List[AtBatResult]]  # List of half-innings, each containing at-bat results

    @property
    def winner(self) -> str:
        """Return 'away', 'home', or 'tie' (should not happen in completed game)."""
        if self.final_state.away_score > self.final_state.home_score:
            return 'away'
        elif self.final_state.home_score > self.final_state.away_score:
            return 'home'
        return 'tie'

    @property
    def total_innings(self) -> int:
        """Number of innings played (may be > 9 for extra innings)."""
        return self.final_state.inning


def simulate_game(
    away_team: 'Team',
    home_team: 'Team',
    game_engine: Optional[GameEngine] = None,
    initial_state: Optional[GameState] = None,
    park_factor: int = 100,
) -> GameResult:
    """Simulate a complete 9+ inning baseball game.

    Runs the game loop until completion according to baseball rules:
    - 9 innings minimum (unless home leads after top of 9)
    - Extra innings if tied after 9
    - Walk-off ends game immediately when home takes lead in bottom of 9+

    Args:
        away_team: Team object with lineup set (batting order and pitcher)
        home_team: Team object with lineup set (batting order and pitcher)
        game_engine: Optional GameEngine instance (creates new one if not provided)
        initial_state: Optional starting state (default: fresh GameState)
        park_factor: Park factor for simulation (100 = neutral)

    Returns:
        GameResult with final state and complete play log

    Raises:
        ValueError: If team lineups are not set
    """
    # Validate lineups are set
    if away_team.lineup is None:
        raise ValueError("Away team lineup not set. Call create_lineup() first.")
    if home_team.lineup is None:
        raise ValueError("Home team lineup not set. Call create_lineup() first.")

    # Initialize engine and state
    engine = game_engine or GameEngine()
    state = initial_state or GameState()
    play_log: List[List[AtBatResult]] = []

    while not check_game_complete(state):
        # Determine batting team and pitching stats
        if state.half == InningHalf.TOP:
            batting_lineup = away_team.lineup
            pitcher_id = home_team.lineup.starting_pitcher_id
            pitching_stats = home_team.pitching_stats[pitcher_id]
        else:
            batting_lineup = home_team.lineup
            pitcher_id = away_team.lineup.starting_pitcher_id
            pitching_stats = away_team.pitching_stats[pitcher_id]

        # Simulate half-inning
        state, results = engine.simulate_half_inning(
            state,
            batting_lineup,
            pitching_stats,
            park_factor=park_factor,
        )
        play_log.append(results)

        # Check for walk-off (game can end mid-inning in bottom of 9+)
        if check_game_complete(state):
            break

        # Transition to next half-inning if 3 outs reached
        if state.outs >= 3:
            state = transition_half_inning(state)

    # Mark game as complete
    final_state = dataclass_replace(state, is_complete=True)

    return GameResult(final_state=final_state, play_log=play_log)
