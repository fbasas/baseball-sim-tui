"""Game state representations for baseball simulation.

This module provides data structures for tracking game state,
starting with base runners. It will be expanded in Phase 2 for
full game state including score, inning, outs, etc.
"""

from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass
class BaseState:
    """Represents runners on base.

    Uses Optional[str] for player IDs on each base.
    None means base is empty.

    Attributes:
        first: Player ID on first base, or None if empty
        second: Player ID on second base, or None if empty
        third: Player ID on third base, or None if empty

    Example:
        >>> bs = BaseState(first='ruth01', second='gehrig01')
        >>> bs.count
        2
        >>> bs.runners_on
        (True, True, False)
    """

    first: Optional[str] = None
    second: Optional[str] = None
    third: Optional[str] = None

    @property
    def is_empty(self) -> bool:
        """Check if all bases are empty.

        Returns:
            True if no runners are on base.
        """
        return self.first is None and self.second is None and self.third is None

    @property
    def runners_on(self) -> Tuple[bool, bool, bool]:
        """Return (on_first, on_second, on_third) booleans.

        Returns:
            Tuple of three booleans indicating runner presence.
        """
        return (
            self.first is not None,
            self.second is not None,
            self.third is not None,
        )

    @property
    def count(self) -> int:
        """Number of runners on base.

        Returns:
            Count of runners (0-3).
        """
        return sum(1 for r in [self.first, self.second, self.third] if r is not None)

    def as_tuple(self) -> Tuple[bool, bool, bool]:
        """Return base state as boolean tuple for lookup in advancement matrices.

        Returns:
            Same as runners_on property.
        """
        return self.runners_on

    @classmethod
    def from_tuple(
        cls,
        runners: Tuple[bool, bool, bool],
        player_ids: Tuple[str, str, str] = ("R1", "R2", "R3"),
    ) -> "BaseState":
        """Create BaseState from boolean tuple.

        Args:
            runners: Tuple of (first, second, third) booleans.
            player_ids: Tuple of player IDs to use for occupied bases.
                       Defaults to generic IDs ('R1', 'R2', 'R3').

        Returns:
            BaseState with specified configuration.
        """
        return cls(
            first=player_ids[0] if runners[0] else None,
            second=player_ids[1] if runners[1] else None,
            third=player_ids[2] if runners[2] else None,
        )

    def clear(self) -> "BaseState":
        """Return new empty base state.

        Returns:
            New BaseState with all bases empty.
        """
        return BaseState()

    def get_runner_ids(self) -> List[str]:
        """Get list of runner IDs currently on base.

        Returns:
            List of player IDs for runners on base (in base order).
        """
        runners = []
        if self.first:
            runners.append(self.first)
        if self.second:
            runners.append(self.second)
        if self.third:
            runners.append(self.third)
        return runners

    def __repr__(self) -> str:
        """Return human-readable string representation."""
        bases = []
        if self.first:
            bases.append("1B")
        if self.second:
            bases.append("2B")
        if self.third:
            bases.append("3B")
        return f"BaseState({', '.join(bases) if bases else 'empty'})"


@dataclass
class AdvancementResult:
    """Result of runner advancement after an at-bat.

    Attributes:
        new_base_state: The resulting base state after advancement
        runs_scored: Number of runs scored on the play
        runners_scored: List of player IDs who scored

    Example:
        >>> result = AdvancementResult(BaseState(), 4, ['runner1', 'runner2', 'runner3', 'batter'])
        >>> result.runs_scored
        4
    """

    new_base_state: BaseState
    runs_scored: int
    runners_scored: List[str]

    @property
    def batter_safe(self) -> bool:
        """Did the batter reach base (or score)?

        Returns:
            True if batter is on base or scored.
            This is simplified - batter always reaches on positive outcomes.
        """
        # For now, this is simplified - actual implementation would check
        # if batter is in new_base_state or runners_scored
        return True
