"""Boxscore widget displaying team names and scores.

This module provides the BoxscoreWidget for the game dashboard header,
showing both teams' runs with visual feedback on score changes.
"""

from textual.widgets import Static
from textual.reactive import reactive


class BoxscoreWidget(Static):
    """Header widget showing team scores.

    Displays a compact boxscore header with both team names and run totals.
    Provides visual flash feedback when scores change.

    Attributes:
        away_name: Away team name for display (includes year).
        home_name: Home team name for display (includes year).
        away_runs: Away team's total runs scored.
        home_runs: Home team's total runs scored.

    Example:
        >>> widget = BoxscoreWidget()
        >>> widget.update_from_state("1927 Yankees", "1927 Cubs", 3, 2)
        # Displays: "    1927 Yankees   3  -  2   1927 Cubs"
    """

    away_name = reactive("Away")
    home_name = reactive("Home")
    away_runs = reactive(0)
    home_runs = reactive(0)

    def __init__(self, **kwargs) -> None:
        """Initialize the boxscore widget.

        Args:
            **kwargs: Passed to parent Static widget.
        """
        super().__init__(**kwargs)
        self.id = "boxscore"

    def render(self) -> str:
        """Render the boxscore display.

        Format: "Away Team    R  -  R    Home Team"
        Simple runs display with dash separator.

        Returns:
            Formatted boxscore string.
        """
        return (
            f"{self.away_name:>18}  {self.away_runs:>2}  -  "
            f"{self.home_runs:<2}  {self.home_name:<18}"
        )

    def update_from_state(
        self,
        away_name: str,
        home_name: str,
        away_runs: int,
        home_runs: int,
    ) -> None:
        """Update display from game state values.

        Triggers a brief visual flash if score has changed.

        Args:
            away_name: Away team name (should include year, e.g., "1927 Yankees").
            home_name: Home team name (should include year, e.g., "1927 Cubs").
            away_runs: Away team run total.
            home_runs: Home team run total.
        """
        # Check for score changes before updating
        score_changed = (
            self.away_runs != away_runs or
            self.home_runs != home_runs
        )

        self.away_name = away_name
        self.home_name = home_name
        self.away_runs = away_runs
        self.home_runs = home_runs

        if score_changed:
            self._flash_score()

    def _flash_score(self) -> None:
        """Brief visual highlight when score changes.

        Adds a CSS class for 500ms to enable styling hooks.
        """
        self.add_class("score-changed")
        self.set_timer(0.5, lambda: self.remove_class("score-changed"))
