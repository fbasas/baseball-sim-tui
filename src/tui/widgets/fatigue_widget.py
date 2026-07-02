"""Fatigue meter widget displaying pitcher tiredness.

Shows the current pitcher with a visual fatigue bar, percentage, and
batters-faced count.
"""

from textual.widgets import Static

from src.game.fatigue import FatigueState, calculate_fatigue


class FatigueWidget(Static):
    """Display the current pitcher and a fatigue meter.

    Color thresholds:
    - 0-30%: green (fresh)
    - 30-60%: yellow (tiring)
    - 60%+: red (exhausted)

    Example:
        >>> widget = FatigueWidget()
        >>> widget.update_fatigue("W. Hoyt", FatigueState(batters_faced=15))
        # Displays: W. Hoyt  ███░░░░░░░░░  32%   BF 15
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.id = "fatigue"
        self._pitcher_name = "Pitcher"
        self._fatigue_value = 0.0
        self._batters_faced = 0

    def update_fatigue(self, pitcher_name: str, fatigue_state: FatigueState) -> None:
        """Update display with new fatigue data.

        Args:
            pitcher_name: Name of current pitcher
            fatigue_state: Current FatigueState
        """
        self._pitcher_name = pitcher_name
        self._fatigue_value = calculate_fatigue(fatigue_state)
        self._batters_faced = fatigue_state.batters_faced
        self.refresh()

    def render(self) -> str:
        """Render the pitcher name and a colored fatigue bar.

        Falls back to a shorter bar without the batters-faced count when
        the panel is too narrow for the full line.
        """
        pct = int(self._fatigue_value * 100)

        if pct < 30:
            color = "#5fb85f"
        elif pct < 60:
            color = "#d4a843"
        else:
            color = "#d75f5f"

        compact = 0 < self.content_size.width < 42
        name_w, bar_w = (10, 8) if compact else (16, 12)

        filled = int(self._fatigue_value * bar_w)
        bar = f"[{color}]" + "█" * filled + "[dim]" + "░" * (bar_w - filled) + "[/dim][/]"

        line = f"[bold]{self._pitcher_name[:name_w]:<{name_w}}[/] {bar} [{color}]{pct:>3}%[/]"
        if not compact:
            line += f"   [dim]BF {self._batters_faced}[/]"
        return line
