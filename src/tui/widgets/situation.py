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
    outs, and which bases are occupied with an ASCII base diamond.

    Example:
        >>> widget = SituationWidget()
        >>> widget.update_from_state(state, {'first': 'Ruth', 'third': 'Gehrig'})
        # Displays:
        # Top 3rd | Outs: 1
        #      [2B]
        #     /    \\
        #  [3B]    [1B]
        #     \\    /
        #      [H]
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

    def _base_diamond(self, first: bool, second: bool, third: bool) -> str:
        """Render an ASCII base diamond with occupied/empty indicators.

        Args:
            first: True if runner on first base.
            second: True if runner on second base.
            third: True if runner on third base.

        Returns:
            Multi-line string with Rich markup for the base diamond.
        """
        # Use Rich markup: bold yellow for occupied, dim for empty
        b1 = "[bold yellow]1B[/bold yellow]" if first  else "[dim]1B[/dim]"
        b2 = "[bold yellow]2B[/bold yellow]" if second else "[dim]2B[/dim]"
        b3 = "[bold yellow]3B[/bold yellow]" if third  else "[dim]3B[/dim]"
        home = "[dim] H[/dim]"

        lines = [
            f"       {b2}     ",
            f"      /    \\    ",
            f"  {b3}        {b1}",
            f"      \\    /    ",
            f"       {home}     ",
        ]
        return "\n".join(lines)

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

        # Base occupancy
        bases = state.base_state
        first_occupied = bases.first is not None
        second_occupied = bases.second is not None
        third_occupied = bases.third is not None

        # Build base diamond
        diamond = self._base_diamond(first_occupied, second_occupied, third_occupied)

        # Combine into display
        header = f"{inning_str}  |  {outs_str}"
        self.update(f"{header}\n{diamond}")
