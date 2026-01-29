"""Boxscore widget displaying team names and scores.

This module provides the BoxscoreWidget for the game dashboard header,
showing both teams' runs and hits with visual feedback on score changes.
"""

from textual.widgets import Static
from textual.reactive import reactive


class BoxscoreWidget(Static):
    """Header widget showing team scores in runs-hits format.

    Displays a compact boxscore header with both team names, run totals,
    and hit totals. Provides visual flash feedback when scores change.

    Attributes:
        away_name: Away team name for display.
        home_name: Home team name for display.
        away_runs: Away team's total runs scored.
        home_runs: Home team's total runs scored.
        away_hits: Away team's total hit count.
        home_hits: Home team's total hit count.

    Example:
        >>> widget = BoxscoreWidget()
        >>> widget.update_from_state("Yankees", "Red Sox", 3, 2, 7, 5)
        # Displays: "       Yankees   3 |  7    2 |  5   Red Sox"
    """

    away_name = reactive("Away")
    home_name = reactive("Home")
    away_runs = reactive(0)
    home_runs = reactive(0)
    away_hits = reactive(0)
    home_hits = reactive(0)

    def __init__(self, **kwargs) -> None:
        """Initialize the boxscore widget.

        Args:
            **kwargs: Passed to parent Static widget.
        """
        super().__init__(**kwargs)
        self.id = "boxscore"

    def render(self) -> str:
        """Render the boxscore display.

        Format: "Away Team    R | H    R | H    Home Team"
        Runs and hits displayed compactly with pipe separator.

        Returns:
            Formatted boxscore string.
        """
        return (
            f"{self.away_name:>15}  {self.away_runs:>2} | {self.away_hits:<2}  "
            f"{self.home_runs:>2} | {self.home_hits:<2}  {self.home_name:<15}"
        )

    def update_from_state(
        self,
        away_name: str,
        home_name: str,
        away_runs: int,
        home_runs: int,
        away_hits: int,
        home_hits: int,
    ) -> None:
        """Update display from game state values.

        Triggers a brief visual flash if score has changed.

        Args:
            away_name: Away team name.
            home_name: Home team name.
            away_runs: Away team run total.
            home_runs: Home team run total.
            away_hits: Away team hit total.
            home_hits: Home team hit total.
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
        self.away_hits = away_hits
        self.home_hits = home_hits

        if score_changed:
            self._flash_score()

    def _flash_score(self) -> None:
        """Brief visual highlight when score changes.

        Adds a CSS class for 500ms to enable styling hooks.
        """
        self.add_class("score-changed")
        self.set_timer(0.5, lambda: self.remove_class("score-changed"))
