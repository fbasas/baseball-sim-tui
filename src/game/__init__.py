"""Game layer for baseball simulation orchestration.

This module provides game-level data structures and orchestration:
- Position: IntEnum for defensive positions (1-9)
- DesignatedHitter: Sentinel for DH position
- LineupSlot, Lineup: Batting order management
- GameState, InningHalf: Immutable game state tracking
- GameEngine: Orchestrates half-inning and game simulation
"""

from src.game.engine import (
    GameEngine,
    GameResult,
    check_game_complete,
    simulate_game,
    transition_half_inning,
)
from src.game.positions import DesignatedHitter, Position
from src.game.state import GameState, InningHalf
from src.game.team import Lineup, LineupSlot, Team, create_lineup

__all__ = [
    'Position',
    'DesignatedHitter',
    'LineupSlot',
    'Lineup',
    'Team',
    'create_lineup',
    'InningHalf',
    'GameState',
    'GameEngine',
    'GameResult',
    'transition_half_inning',
    'check_game_complete',
    'simulate_game',
]
