"""Team and lineup data structures for baseball simulation.

This module provides dataclasses for managing batting lineups with
position validation and circular batting order traversal.
"""

from dataclasses import dataclass
from typing import List, Union

from src.data.models import BattingStats
from src.game.positions import DesignatedHitter, Position


@dataclass
class LineupSlot:
    """Single slot in a batting order.

    Represents one batter in the lineup with their defensive position
    and batting statistics.

    Attributes:
        player_id: Unique identifier for the player.
        position: Defensive position (Position enum) or DesignatedHitter.
        batting_stats: Player's batting statistics for simulation.

    Example:
        >>> slot = LineupSlot('ruth01', Position.RIGHT_FIELD, batting_stats)
        >>> slot.position.abbreviation
        'RF'
    """

    player_id: str
    position: Union[Position, type]  # Position or DesignatedHitter class
    batting_stats: BattingStats


@dataclass
class Lineup:
    """9-player batting order with defensive position validation.

    Represents a complete batting lineup with exactly 9 slots.
    Validates that all required defensive positions are covered
    (either 8 fielding positions + DH, or 8 positions with pitcher
    batting separately in NL-style games).

    Attributes:
        slots: List of 9 LineupSlot instances, index 0 = leadoff batter.
        starting_pitcher_id: Player ID of the starting pitcher.

    Example:
        >>> lineup = Lineup(slots=slots, starting_pitcher_id='spahn01')
        >>> lineup.get_batter(0).player_id  # Leadoff
        'p1'
        >>> lineup.get_batter(9).player_id  # Wraps to leadoff
        'p1'
    """

    slots: List[LineupSlot]
    starting_pitcher_id: str

    def __post_init__(self) -> None:
        """Validate lineup after initialization."""
        if len(self.slots) != 9:
            raise ValueError(f"Lineup must have exactly 9 slots, got {len(self.slots)}")
        self._validate_positions()

    def _validate_positions(self) -> None:
        """Validate that defensive positions are properly covered.

        Rules:
        - Pitcher (Position.PITCHER) should NOT appear in batting lineup
          (pitcher is tracked separately via starting_pitcher_id)
        - With DH: exactly 8 Position values covering all non-pitcher positions
        - Without DH: exactly 8 Position values (NL-style, pitcher bats separately)

        Raises:
            ValueError: If positions are invalid or incomplete.
        """
        # Extract Position instances (not DH)
        positions = [s.position for s in self.slots
                     if isinstance(s.position, Position)]

        # Check if DH is used
        has_dh = any(s.position is DesignatedHitter for s in self.slots)

        # Pitcher should never be in the batting lineup
        if Position.PITCHER in positions:
            raise ValueError(
                "Pitcher position should not appear in batting lineup. "
                "The starting pitcher is tracked separately via starting_pitcher_id."
            )

        # Required fielding positions (all except pitcher)
        required_positions = {
            Position.CATCHER, Position.FIRST_BASE, Position.SECOND_BASE,
            Position.THIRD_BASE, Position.SHORTSTOP, Position.LEFT_FIELD,
            Position.CENTER_FIELD, Position.RIGHT_FIELD
        }

        # Check position coverage
        position_set = set(positions)

        if has_dh:
            # With DH: need exactly 8 fielding positions
            if len(positions) != 8:
                raise ValueError(
                    f"With DH, lineup must have exactly 8 fielding positions, "
                    f"got {len(positions)}"
                )
            if position_set != required_positions:
                missing = required_positions - position_set
                extra = position_set - required_positions
                msg = "Position coverage error with DH lineup."
                if missing:
                    msg += f" Missing: {[p.abbreviation for p in missing]}."
                if extra:
                    msg += f" Unexpected: {[p.abbreviation for p in extra]}."
                raise ValueError(msg)
        else:
            # Without DH: still need 8 positions (pitcher bats but isn't in lineup as fielder)
            # This handles NL-style where pitcher occupies a batting slot
            if len(positions) != 8:
                raise ValueError(
                    f"Lineup must have exactly 8 fielding positions, got {len(positions)}"
                )
            if position_set != required_positions:
                missing = required_positions - position_set
                extra = position_set - required_positions
                msg = "Position coverage error in lineup."
                if missing:
                    msg += f" Missing: {[p.abbreviation for p in missing]}."
                if extra:
                    msg += f" Unexpected: {[p.abbreviation for p in extra]}."
                raise ValueError(msg)

    def get_batter(self, index: int) -> LineupSlot:
        """Get batter at the specified lineup position.

        Uses modulo 9 to wrap around the batting order, allowing
        continuous traversal through multiple trips through the order.

        Args:
            index: Batting order index (can be >= 9, will wrap).

        Returns:
            LineupSlot at the wrapped position.

        Example:
            >>> lineup.get_batter(0)   # Leadoff
            >>> lineup.get_batter(8)   # 9th batter
            >>> lineup.get_batter(9)   # Wraps to leadoff
            >>> lineup.get_batter(10)  # Wraps to 2nd batter
        """
        return self.slots[index % 9]

    def next_batter_index(self, current: int) -> int:
        """Advance to the next batter in the order.

        Args:
            current: Current batting index.

        Returns:
            Next batting index (wraps at 9).

        Example:
            >>> lineup.next_batter_index(7)
            8
            >>> lineup.next_batter_index(8)
            0
        """
        return (current + 1) % 9
