"""Scoreboard widget displaying a live inning-by-inning linescore.

This module provides the BoxscoreWidget for the game dashboard header,
showing a ballpark-style linescore: runs per inning for both teams plus
R/H/E totals, with the side currently batting marked and the in-progress
inning highlighted.
"""

from typing import List, Optional

from textual.widgets import Static

# Widest the team-name column may grow; longer names are truncated with an
# ellipsis so the inning grid keeps a predictable width.
_MAX_NAME_W = 24
_MIN_NAME_W = 12
# Innings shown at once; older innings scroll off the left like a real
# out-of-town scoreboard when a game runs long.
_MAX_INNINGS_SHOWN = 12


class BoxscoreWidget(Static):
    """Header widget showing a live linescore.

    Displays both teams' runs per inning, R/H/E totals, and a marker on the
    side currently at bat. Provides visual flash feedback when runs score.

    Example:
        >>> widget = BoxscoreWidget()
        >>> widget.update_from_state("1927 Yankees", "2016 Cubs", 3, 2)
        # Displays:
        #                 1  2  3  4  5  6  7  8  9    R  H  E
        # ▶ 1927 Yankees  0  1  2                      3  5  0
        #   2016 Cubs     2  0                         2  4  1
    """

    def __init__(self, **kwargs) -> None:
        """Initialize the scoreboard widget.

        Args:
            **kwargs: Passed to parent Static widget.
        """
        super().__init__(**kwargs)
        self.id = "boxscore"
        self.away_name = "Away"
        self.home_name = "Home"
        self.away_runs = 0
        self.home_runs = 0
        self._away_cells: List[Optional[int]] = []
        self._home_cells: List[Optional[int]] = []
        self._away_hits = 0
        self._home_hits = 0
        self._away_errors = 0
        self._home_errors = 0
        self._inning = 1
        self._half_top = True
        self._game_over = False

    @staticmethod
    def _fit_name(name: str, width: int) -> str:
        """Truncate a team name to the column width with an ellipsis."""
        if len(name) <= width:
            return f"{name:<{width}}"
        return name[: width - 1] + "…"

    def render(self) -> str:
        """Render the three-line linescore with Rich markup."""
        n_innings = max(9, len(self._away_cells), len(self._home_cells), self._inning)
        start = max(0, n_innings - _MAX_INNINGS_SHOWN)

        name_w = min(_MAX_NAME_W, max(_MIN_NAME_W, len(self.away_name), len(self.home_name)))

        def _cell(value: Optional[int], is_current: bool) -> str:
            text = " ·" if value is None else f"{value:>2}"
            if is_current:
                return f"[bold #ffd75f]{text}[/]"
            if value is None:
                return f"[dim]{text}[/]"
            return text

        # Header row of inning numbers plus R/H/E.
        header = "  " + " " * name_w
        for i in range(start, n_innings):
            header += f"{i + 1:>3}"
        header += f"   {'R':>2} {'H':>2} {'E':>2}"
        lines = [f"[dim]{header}[/]"]

        current_idx = self._inning - 1

        for is_away, name, cells, runs, hits, errs in (
            (True, self.away_name, self._away_cells, self.away_runs, self._away_hits, self._away_errors),
            (False, self.home_name, self._home_cells, self.home_runs, self._home_hits, self._home_errors),
        ):
            batting = (not self._game_over) and (self._half_top == is_away)
            marker = "[bold #ffd75f]▶[/]" if batting else " "
            styled_name = f"[bold]{self._fit_name(name, name_w)}[/]"
            row = f"{marker} {styled_name}"
            for i in range(start, n_innings):
                value = cells[i] if i < len(cells) else None
                row += " " + _cell(value, batting and i == current_idx)
            row += f"   [bold]{runs:>2}[/] {hits:>2} {errs:>2}"
            lines.append(row)

        return "\n".join(lines)

    def update_from_state(
        self,
        away_name: str,
        home_name: str,
        away_runs: int,
        home_runs: int,
        away_cells: Optional[List[Optional[int]]] = None,
        home_cells: Optional[List[Optional[int]]] = None,
        away_hits: int = 0,
        home_hits: int = 0,
        away_errors: int = 0,
        home_errors: int = 0,
        inning: int = 1,
        half_top: bool = True,
        game_over: bool = False,
    ) -> None:
        """Update display from game state values.

        Triggers a brief visual flash if the score changed.

        Args:
            away_name: Away team display name (e.g., "1927 Yankees").
            home_name: Home team display name.
            away_runs: Away team run total.
            home_runs: Home team run total.
            away_cells: Runs per inning for the away side; None entries are
                innings not yet played ("X" marks a skipped bottom half).
            home_cells: Runs per inning for the home side.
            away_hits: Away hit total.
            home_hits: Home hit total.
            away_errors: Errors charged to the away side.
            home_errors: Errors charged to the home side.
            inning: Current inning number (1-indexed).
            half_top: True if the top half is in progress.
            game_over: True once the game is final (clears the ▶ marker).
        """
        score_changed = self.away_runs != away_runs or self.home_runs != home_runs

        self.away_name = away_name
        self.home_name = home_name
        self.away_runs = away_runs
        self.home_runs = home_runs
        self._away_cells = away_cells if away_cells is not None else []
        self._home_cells = home_cells if home_cells is not None else []
        self._away_hits = away_hits
        self._home_hits = home_hits
        self._away_errors = away_errors
        self._home_errors = home_errors
        self._inning = inning
        self._half_top = half_top
        self._game_over = game_over
        self.refresh()

        if score_changed:
            self._flash_score()

    def _flash_score(self) -> None:
        """Brief visual highlight when score changes.

        Adds a CSS class for 500ms to enable styling hooks.
        """
        self.add_class("score-changed")
        self.set_timer(0.5, lambda: self.remove_class("score-changed"))
