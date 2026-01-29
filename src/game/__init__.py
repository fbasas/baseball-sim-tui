"""Game layer for baseball simulation orchestration.

This module provides game-level data structures and orchestration:
- Position: IntEnum for defensive positions (1-9)
- DesignatedHitter: Sentinel for DH position
- LineupSlot, Lineup: Batting order management
- GameState, InningHalf: Immutable game state tracking
"""

from src.game.positions import DesignatedHitter, Position
from src.game.state import GameState, InningHalf
from src.game.team import Lineup, LineupSlot, Team

__all__ = [
    'Position',
    'DesignatedHitter',
    'LineupSlot',
    'Lineup',
    'Team',
    'InningHalf',
    'GameState',
]
