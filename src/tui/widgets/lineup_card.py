"""Lineup card widget displaying batting order.

This module provides the LineupCard widget for showing a team's batting
lineup with position, name, and batting average, highlighting the current batter.
"""

from typing import List, Tuple

from textual.reactive import reactive
from textual.widgets import Static


class LineupCard(Static):
    """Display batting order with current batter highlighted.

    Shows a team's 9-player batting lineup with each player's position
    and batting average. The current batter is visually highlighted.

    Attributes:
        current_batter_index: Index (0-8) of the batter currently at bat.
        team_name: Team name displayed as header.
        lineup_data: List of (name, position, avg) tuples for 9 batters.

    Example:
        >>> data = [('Ruth', 'RF', 0.356), ('Gehrig', '1B', 0.373), ...]
        >>> card = LineupCard('Yankees', data, 'away-lineup')
        >>> card.set_current_batter(2)  # Highlight 3rd batter
    """

    current_batter_index = reactive(0)

    def __init__(
        self,
        team_name: str,
        lineup_data: List[Tuple[str, str, float]],
        widget_id: str,
        **kwargs,
    ) -> None:
        """Initialize lineup card.

        Args:
            team_name: Team name for header display.
            lineup_data: List of 9 tuples (player_name, position_abbrev, batting_avg).
            widget_id: CSS ID for targeting ("away-lineup" or "home-lineup").
            **kwargs: Passed to parent Static widget.
        """
        super().__init__(**kwargs)
        self.id = widget_id
        self.team_name = team_name
        self.lineup_data = lineup_data

    def render(self) -> str:
        """Render lineup as formatted text with Rich markup.

        Format:
        Team Name (bold header)

        > 1. PlayerName   RF .356  (current batter highlighted)
          2. PlayerName   1B .373
          ...

        Returns:
            Formatted lineup string with Rich markup.
        """
        lines = [f"[bold]{self.team_name}[/bold]", ""]

        for i, (name, pos, avg) in enumerate(self.lineup_data):
            # Format batting average: .000 to .999
            avg_str = f".{int(avg * 1000):03d}" if avg > 0 else ".000"
            # Marker for current batter
            marker = ">" if i == self.current_batter_index else " "
            # Truncate name to 12 chars for consistent column width
            line = f"{marker} {i+1}. {name[:12]:<12} {pos:>2} {avg_str}"

            if i == self.current_batter_index:
                line = f"[bold reverse]{line}[/bold reverse]"

            lines.append(line)

        return "\n".join(lines)

    def watch_current_batter_index(self, old: int, new: int) -> None:
        """Re-render when current batter changes.

        Called automatically by Textual's reactive system when
        current_batter_index is modified.

        Args:
            old: Previous batter index.
            new: New batter index.
        """
        self.refresh()

    def set_current_batter(self, index: int) -> None:
        """Update which batter is currently at bat.

        Args:
            index: Batting order position (0-8), wraps with modulo.
        """
        self.current_batter_index = index % 9
