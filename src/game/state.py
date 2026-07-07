"""Game state data structures for baseball simulation.

This module provides immutable game state tracking using frozen dataclasses.
GameState captures all game information needed to simulate the next play.
"""

from dataclasses import dataclass, field, replace
from enum import Enum, auto
from typing import Optional

from src.simulation.game_state import BaseState
from src.game.fatigue import FatigueState


class InningHalf(Enum):
    """Identifies which half of an inning is being played.

    TOP: Away team is batting
    BOTTOM: Home team is batting
    """

    TOP = auto()     # Away team batting
    BOTTOM = auto()  # Home team batting


@dataclass(frozen=True)
class GameState:
    """Immutable snapshot of complete game state.

    This dataclass captures all information needed to determine the next
    play and continue simulation. It is frozen (immutable) to prevent
    accidental state corruption and enable safe state history tracking.

    Use the `with_*` methods to create modified copies of the state.

    Attributes:
        inning: Current inning number (1-indexed, 1+ for extra innings).
        half: Which half of the inning (TOP for away batting, BOTTOM for home).
        outs: Current number of outs in the half-inning (0-2, or 3 when complete).
        base_state: Current base runner configuration.
        away_score: Away team's total runs.
        home_score: Home team's total runs.
        away_batting_index: Away team's current position in batting order (0-8).
        home_batting_index: Home team's current position in batting order (0-8).
        is_complete: Whether the game has ended.
        away_pitcher_id: Player ID of current away team pitcher.
        home_pitcher_id: Player ID of current home team pitcher.
        away_pitcher_fatigue: Fatigue state for away team pitcher.
        home_pitcher_fatigue: Fatigue state for home team pitcher.

    Example:
        >>> state = GameState()
        >>> state.inning
        1
        >>> state.half
        InningHalf.TOP
        >>> new_state = state.with_outs(2)
        >>> state.outs  # Original unchanged
        0
        >>> new_state.outs
        2
    """

    inning: int = 1
    half: InningHalf = InningHalf.TOP
    outs: int = 0
    base_state: BaseState = field(default_factory=BaseState)
    away_score: int = 0
    home_score: int = 0
    away_batting_index: int = 0  # 0-8 position in batting order
    home_batting_index: int = 0
    is_complete: bool = False

    # Pitcher tracking (player IDs)
    away_pitcher_id: Optional[str] = None
    home_pitcher_id: Optional[str] = None

    # Fatigue state for each pitcher
    away_pitcher_fatigue: FatigueState = field(default_factory=FatigueState)
    home_pitcher_fatigue: FatigueState = field(default_factory=FatigueState)

    def to_dict(self) -> dict:
        """Serialize to a plain JSON-friendly dict.

        The ``InningHalf`` enum is encoded by name; nested ``BaseState`` and both
        ``FatigueState`` pieces delegate to their own ``to_dict``.
        """
        return {
            "inning": self.inning,
            "half": self.half.name,
            "outs": self.outs,
            "base_state": self.base_state.to_dict(),
            "away_score": self.away_score,
            "home_score": self.home_score,
            "away_batting_index": self.away_batting_index,
            "home_batting_index": self.home_batting_index,
            "is_complete": self.is_complete,
            "away_pitcher_id": self.away_pitcher_id,
            "home_pitcher_id": self.home_pitcher_id,
            "away_pitcher_fatigue": self.away_pitcher_fatigue.to_dict(),
            "home_pitcher_fatigue": self.home_pitcher_fatigue.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "GameState":
        """Reconstruct a GameState from :meth:`to_dict` output."""
        return cls(
            inning=data["inning"],
            half=InningHalf[data["half"]],
            outs=data["outs"],
            base_state=BaseState.from_dict(data["base_state"]),
            away_score=data["away_score"],
            home_score=data["home_score"],
            away_batting_index=data["away_batting_index"],
            home_batting_index=data["home_batting_index"],
            is_complete=data["is_complete"],
            away_pitcher_id=data["away_pitcher_id"],
            home_pitcher_id=data["home_pitcher_id"],
            away_pitcher_fatigue=FatigueState.from_dict(data["away_pitcher_fatigue"]),
            home_pitcher_fatigue=FatigueState.from_dict(data["home_pitcher_fatigue"]),
        )

    @property
    def batting_team_score(self) -> int:
        """Get the score of the team currently batting.

        Returns:
            Away score if top of inning, home score if bottom.
        """
        return self.away_score if self.half == InningHalf.TOP else self.home_score

    @property
    def fielding_team_score(self) -> int:
        """Get the score of the team currently fielding.

        Returns:
            Home score if top of inning, away score if bottom.
        """
        return self.home_score if self.half == InningHalf.TOP else self.away_score

    @property
    def current_batting_index(self) -> int:
        """Get the batting order index for the team currently batting.

        Returns:
            Away batting index if top, home batting index if bottom.
        """
        return self.away_batting_index if self.half == InningHalf.TOP else self.home_batting_index

    @property
    def current_pitcher_id(self) -> Optional[str]:
        """Get the pitcher ID for the team currently fielding.

        Returns:
            Home pitcher if top of inning, away pitcher if bottom.
        """
        return self.home_pitcher_id if self.half == InningHalf.TOP else self.away_pitcher_id

    @property
    def current_pitcher_fatigue(self) -> FatigueState:
        """Get fatigue state for the team currently fielding.

        Returns:
            Home pitcher fatigue if top of inning, away pitcher fatigue if bottom.
        """
        return self.home_pitcher_fatigue if self.half == InningHalf.TOP else self.away_pitcher_fatigue

    def with_outs(self, outs: int) -> 'GameState':
        """Return new state with updated out count.

        Args:
            outs: New number of outs.

        Returns:
            New GameState with updated outs.
        """
        return replace(self, outs=outs)

    def with_score(self, away: int, home: int) -> 'GameState':
        """Return new state with updated scores.

        Args:
            away: New away team score.
            home: New home team score.

        Returns:
            New GameState with updated scores.
        """
        return replace(self, away_score=away, home_score=home)

    def with_base_state(self, base_state: BaseState) -> 'GameState':
        """Return new state with updated base runner configuration.

        Args:
            base_state: New base state.

        Returns:
            New GameState with updated base state.
        """
        return replace(self, base_state=base_state)

    def with_batting_index(self, index: int) -> 'GameState':
        """Return new state with updated batting index for current team.

        Updates away_batting_index if top of inning, home_batting_index
        if bottom of inning.

        Args:
            index: New batting order index (0-8).

        Returns:
            New GameState with updated batting index.
        """
        if self.half == InningHalf.TOP:
            return replace(self, away_batting_index=index)
        else:
            return replace(self, home_batting_index=index)

    def with_pitcher(self, pitcher_id: str, fatigue: Optional[FatigueState] = None) -> 'GameState':
        """Return new state with updated pitcher for fielding team.

        Args:
            pitcher_id: New pitcher's player ID
            fatigue: Optional fatigue state (fresh FatigueState if None)

        Returns:
            New GameState with updated pitcher for fielding team.
        """
        if fatigue is None:
            fatigue = FatigueState()

        if self.half == InningHalf.TOP:
            # Top of inning: home team is fielding
            return replace(self, home_pitcher_id=pitcher_id, home_pitcher_fatigue=fatigue)
        else:
            # Bottom of inning: away team is fielding
            return replace(self, away_pitcher_id=pitcher_id, away_pitcher_fatigue=fatigue)

    def with_pitcher_fatigue(self, fatigue: FatigueState) -> 'GameState':
        """Return new state with updated fatigue for current pitcher.

        Args:
            fatigue: New fatigue state for fielding team's pitcher.

        Returns:
            New GameState with updated pitcher fatigue.
        """
        if self.half == InningHalf.TOP:
            # Top of inning: home team is fielding
            return replace(self, home_pitcher_fatigue=fatigue)
        else:
            # Bottom of inning: away team is fielding
            return replace(self, away_pitcher_fatigue=fatigue)
