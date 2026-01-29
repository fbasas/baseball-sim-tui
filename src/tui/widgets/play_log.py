"""Play-by-play log widget for game events.

This module provides the PlayByPlayLog widget that wraps Textual's Log
for displaying scrolling play-by-play descriptions with inning dividers.
"""

from textual.widgets import Log


class PlayByPlayLog(Log):
    """Scrolling play-by-play log with auto-scroll.

    Displays game events as they happen, with automatic scrolling to
    keep the latest play visible. Includes visual dividers for inning
    transitions.

    Example:
        >>> log = PlayByPlayLog()
        >>> log.add_inning_divider(1, True)  # "--- Top 1st ---"
        >>> log.add_play("Ruth: Single (1 run)")
        >>> log.add_play("Gehrig: Flyout")
    """

    def __init__(self, **kwargs) -> None:
        """Initialize the play-by-play log.

        Args:
            **kwargs: Passed to parent Log widget.
        """
        super().__init__(auto_scroll=True, **kwargs)
        self.id = "play-log"

    def add_play(self, description: str) -> None:
        """Add a play description to the log.

        Args:
            description: Text describing the play outcome.

        Example:
            >>> log.add_play("Ruth: Home Run (2 runs)")
        """
        self.write_line(description)

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
        self.write_line(f"\n--- {half} {ordinal} ---\n")

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
