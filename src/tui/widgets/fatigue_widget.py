"""Fatigue meter widget displaying pitcher tiredness.

Shows a visual bar and percentage indicating current pitcher fatigue level.
"""

from textual.widgets import Static

from src.game.fatigue import FatigueState, calculate_fatigue


class FatigueWidget(Static):
    """Display pitcher fatigue as visual meter.

    Shows:
    - Pitcher name
    - Visual bar (green/yellow/red based on level)
    - Percentage value

    Color thresholds:
    - 0-30%: green (fresh)
    - 30-60%: yellow (tiring)
    - 60%+: red (exhausted)

    Example:
        >>> widget = FatigueWidget()
        >>> widget.update_fatigue("Smith", FatigueState(batters_faced=15))
        # Displays: Smith [████████░░] 32%
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.id = "fatigue"
        self._pitcher_name = "Pitcher"
        self._fatigue_value = 0.0

    def update_fatigue(self, pitcher_name: str, fatigue_state: FatigueState) -> None:
        """Update display with new fatigue data.

        Args:
            pitcher_name: Name of current pitcher
            fatigue_state: Current FatigueState
        """
        self._pitcher_name = pitcher_name
        self._fatigue_value = calculate_fatigue(fatigue_state)
        self.refresh()

    def render(self) -> str:
        """Render fatigue meter with Rich markup.

        Returns bar like: [████████░░] with color based on level.
        """
        pct = int(self._fatigue_value * 100)

        # Color based on fatigue level
        if pct < 30:
            color = "green"
        elif pct < 60:
            color = "yellow"
        else:
            color = "red"

        # Bar visualization (10 chars wide)
        filled = int(self._fatigue_value * 10)
        bar = "█" * filled + "░" * (10 - filled)

        return f"[bold]Pitcher[/bold]\n{self._pitcher_name}: [{color}]{bar}[/{color}] {pct}%"
