"""Situation widget displaying current game state.

This module provides the SituationWidget for showing the current inning,
out count, and base runner positions in the game dashboard.
"""

from typing import Dict, Optional

from textual.widgets import Static

from src.game.state import GameState, InningHalf


class SituationWidget(Static):
    """Widget showing current inning, outs, and baserunners.

    Displays the game situation: which half of which inning, how many
    outs, and which bases are occupied with optional player names.

    Example:
        >>> widget = SituationWidget()
        >>> widget.update_from_state(state, {'first': 'Ruth', 'third': 'Gehrig'})
        # Displays:
        # Top 3rd
        # Outs: 1
        # Runners: 1B: Ruth, 3B: Gehrig
    """

    def __init__(self, **kwargs) -> None:
        """Initialize the situation widget.

        Args:
            **kwargs: Passed to parent Static widget.
        """
        super().__init__(**kwargs)
        self.id = "situation"

    def _ordinal(self, n: int) -> str:
        """Convert number to ordinal string (1st, 2nd, 3rd, etc.).

        Args:
            n: Number to convert.

        Returns:
            Ordinal string representation.

        Example:
            >>> self._ordinal(1)
            '1st'
            >>> self._ordinal(11)
            '11th'
            >>> self._ordinal(23)
            '23rd'
        """
        if 11 <= n <= 13:
            return f"{n}th"
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
        return f"{n}{suffix}"

    def update_from_state(
        self,
        state: GameState,
        runner_names: Optional[Dict[str, str]] = None,
    ) -> None:
        """Update display from game state.

        Args:
            state: Current GameState with inning, outs, and base_state.
            runner_names: Optional dict mapping base ('first', 'second', 'third')
                         to player name for display. If None, shows generic "Runner".
        """
        # Inning display
        half = "Top" if state.half == InningHalf.TOP else "Bot"
        inning_str = f"{half} {self._ordinal(state.inning)}"

        # Outs display
        outs_str = f"Outs: {state.outs}"

        # Runners display
        runners = []
        bases = state.base_state
        names = runner_names or {}

        if bases.first:
            name = names.get("first", "Runner")
            runners.append(f"1B: {name}")
        if bases.second:
            name = names.get("second", "Runner")
            runners.append(f"2B: {name}")
        if bases.third:
            name = names.get("third", "Runner")
            runners.append(f"3B: {name}")

        runners_str = "Runners: " + ", ".join(runners) if runners else "Bases empty"

        self.update(f"{inning_str}\n{outs_str}\n{runners_str}")
