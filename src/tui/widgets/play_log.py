"""Play-by-play log widget for game events.

This module provides the PlayByPlayLog widget that wraps Textual's RichLog
for displaying scrolling play-by-play descriptions with Rich markup and
inning dividers.
"""

from textual.widgets import RichLog


class PlayByPlayLog(RichLog):
    """Scrolling play-by-play log with auto-scroll and Rich markup.

    Displays game events as they happen, with automatic scrolling to
    keep the latest play visible. Supports Rich markup for colored
    text (e.g., bold yellow for home runs, bold red for errors).

    Example:
        >>> log = PlayByPlayLog()
        >>> log.add_inning_divider(1, True)  # "--- Top 1st ---"
        >>> log.add_play("[bold yellow]Ruth crushes one! Home run![/bold yellow]")
    """

    def __init__(self, **kwargs) -> None:
        """Initialize the play-by-play log.

        Args:
            **kwargs: Passed to parent RichLog widget.
        """
        super().__init__(auto_scroll=True, markup=True, **kwargs)
        self.id = "play-log"

    def add_play(self, description: str) -> None:
        """Add a play description to the log.

        Args:
            description: Text describing the play outcome. Supports Rich markup.

        Example:
            >>> log.add_play("[bold yellow]Ruth: Home Run![/bold yellow]")
        """
        self.write(description)

    def add_inning_divider(self, inning: int, is_top: bool) -> None:
        """Add visual divider for inning transitions.

        Displays a centered divider line showing the inning and half.

        Args:
            inning: Inning number (1-indexed).
            is_top: True for top of inning (away batting), False for bottom.

        Example:
            >>> log.add_inning_divider(3, True)
            # Displays: "--- Top 3rd ---"
        """
        half = "Top" if is_top else "Bot"
        ordinal = self._ordinal(inning)
        self.write(f"\n--- {half} {ordinal} ---\n")

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
