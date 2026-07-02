"""Situation widget displaying current game state.

This module provides the SituationWidget for showing the current inning,
out count, base runners, and the at-bat/on-deck hitters in the game
dashboard.
"""

from typing import Dict, Optional

from textual.widgets import Static

from src.game.state import GameState, InningHalf

_GOLD = "#d4a843"


class SituationWidget(Static):
    """Widget showing inning, outs, baserunners, and the current matchup.

    Displays the game situation: which half of which inning, how many outs,
    which bases are occupied (as a diamond), who is on base, and who is at
    bat and on deck.

    Example:
        >>> widget = SituationWidget()
        >>> widget.update_from_state(state, {'first': 'Ruth'}, 'L. Gehrig')
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
        """
        if 11 <= n <= 13:
            return f"{n}th"
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
        return f"{n}{suffix}"

    def _base_diamond(self, first: bool, second: bool, third: bool) -> list:
        """Render a base diamond as three lines with Rich markup.

        Occupied bases are solid gold diamonds; empty bases are dim outlines.

        Args:
            first: True if runner on first base.
            second: True if runner on second base.
            third: True if runner on third base.

        Returns:
            List of three markup strings.
        """

        def _base(occupied: bool) -> str:
            return f"[bold {_GOLD}]◆[/]" if occupied else "[dim]◇[/]"

        return [
            f"   {_base(second)}   ",
            f" {_base(third)}   {_base(first)} ",
            "   [dim]⌂[/]   ",
        ]

    def _runner_legend(self, runner_names: Dict[str, str]) -> str:
        """Render legend line listing runners on occupied bases."""
        parts = []
        for base, label in (("first", "1B"), ("second", "2B"), ("third", "3B")):
            name = runner_names.get(base)
            if name:
                parts.append(f"[bold {_GOLD}]{label}[/] {name}")
        if not parts:
            return "[dim]bases empty[/]"
        return "  ".join(parts)

    def update_from_state(
        self,
        state: GameState,
        runner_names: Optional[Dict[str, str]] = None,
        batter_name: Optional[str] = None,
        batter_detail: str = "",
        on_deck_name: str = "",
        on_deck_detail: str = "",
    ) -> None:
        """Update display from game state.

        Args:
            state: Current GameState with inning, outs, and base_state.
            runner_names: Optional dict mapping base ('first', 'second',
                'third') to player name for display.
            batter_name: Display name of the current batter.
            batter_detail: Short stat line for the batter (e.g. "CF · .356").
            on_deck_name: Display name of the next batter.
            on_deck_detail: Short stat line for the on-deck batter.
        """
        runner_names = runner_names or {}

        # Inning + outs header, e.g. "▲ Top 3rd        ● ● ○ OUT"
        if state.half == InningHalf.TOP:
            half_marker, half_word = "▲", "Top"
        else:
            half_marker, half_word = "▼", "Bot"
        inning_str = (
            f"[bold {_GOLD}]{half_marker}[/] "
            f"[bold]{half_word} {self._ordinal(state.inning)}[/]"
        )
        outs = max(0, min(3, state.outs))
        dots = " ".join(["[bold]●[/]"] * outs + ["[dim]○[/]"] * (3 - outs))
        header = f"{inning_str}      {dots} [dim]OUT[/]"

        # Base occupancy diamond + runner legend
        bases = state.base_state
        diamond = self._base_diamond(
            bases.first is not None,
            bases.second is not None,
            bases.third is not None,
        )
        legend = self._runner_legend(runner_names)

        sections = [header, ""]
        sections.extend(f"    {line}" for line in diamond)
        sections.append(f"    {legend}")
        sections.append("")

        if batter_name:
            detail = f"  [dim]{batter_detail}[/]" if batter_detail else ""
            sections.append(
                f"[dim]AT BAT [/] [bold]{batter_name}[/]{detail}"
            )
        if on_deck_name:
            detail = f"  [dim]{on_deck_detail}[/]" if on_deck_detail else ""
            sections.append(f"[dim]ON DECK[/] {on_deck_name}{detail}")

        self.update("\n".join(sections))
