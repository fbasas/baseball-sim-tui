"""Lineup card widget displaying batting order.

This module provides the LineupCard widget for showing a team's batting
lineup with position, season average, and today's game line, highlighting
the current batter.
"""

from typing import List, Sequence, Tuple

from textual.reactive import reactive
from textual.widgets import Static

# Rows are "▶1 Name........... POS .AVG 0-0" = 28 cells, sized to fit the
# 32-cell sidebar (28 content cells after border + padding) — keep in sync
# with the grid-columns sidebar width in game.tcss.
_NAME_W = 12


class LineupCard(Static):
    """Display batting order with current batter highlighted.

    Shows a team's 9-player batting lineup with each player's position,
    season batting average, and today's hits-for-at-bats line. The current
    batter is marked and highlighted; the team name lives in the panel's
    border title (set by the screen), not the body.

    Attributes:
        current_batter_index: Index (0-8) of the batter currently at bat.
        team_name: Team name (used by the screen for the border title).
        lineup_data: List of (name, position, avg[, today]) tuples.

    Example:
        >>> data = [('B. Ruth', 'RF', 0.356, '2-3'), ...]
        >>> card = LineupCard('Yankees', data, 'away-lineup')
        >>> card.set_current_batter(2)  # Highlight 3rd batter
    """

    current_batter_index = reactive(0)

    def __init__(
        self,
        team_name: str,
        lineup_data: List[Sequence],
        widget_id: str,
        **kwargs,
    ) -> None:
        """Initialize lineup card.

        Args:
            team_name: Team name (surfaced via the panel border title).
            lineup_data: List of 9 tuples (player_name, position_abbrev,
                batting_avg) or (..., today_line) with today's H-AB string.
            widget_id: CSS ID for targeting ("away-lineup" or "home-lineup").
            **kwargs: Passed to parent Static widget.
        """
        super().__init__(**kwargs)
        self.id = widget_id
        self.team_name = team_name
        self.lineup_data = lineup_data

    def render(self) -> str:
        """Render lineup as formatted text with Rich markup.

        Full format (current batter marked and highlighted):
        ▶1 E. Combs     POS  AVG TDY
        Compact format (narrow sidebars): drops POS and TDY.

        Returns:
            Formatted lineup string with Rich markup.
        """
        # Compact rows when the sidebar can't fit the full 28-cell row
        # (e.g. the -narrow breakpoint's 22-cell sidebar).
        compact = 0 < self.content_size.width < 28

        if compact:
            name_w = 10
            header = f"{'#':>2} {'PLAYER':<{name_w}} {'AVG':>4}"
        else:
            name_w = _NAME_W
            header = f"{'#':>2} {'PLAYER':<{name_w}} {'POS':>3} {'AVG':>4} {'TDY':>3}"
        lines = [f"[dim]{header}[/]", ""]

        for i, row in enumerate(self.lineup_data):
            name, pos, avg = row[0], row[1], row[2]
            today = row[3] if len(row) > 3 else ""
            avg_str = f".{int(avg * 1000):03d}" if avg > 0 else ".000"
            name_str = name[:name_w]
            is_current = i == self.current_batter_index

            marker = "▶" if is_current else " "
            if compact:
                line = f"{marker}{i + 1} {name_str:<{name_w}} {avg_str}"
            else:
                line = (
                    f"{marker}{i + 1} {name_str:<{name_w}} {pos:>3} {avg_str} {today:>3}"
                )

            if is_current:
                line = f"[bold #1a2b1a on #d4a843]{line}[/]"

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
