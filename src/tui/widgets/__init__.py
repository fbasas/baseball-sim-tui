"""TUI widgets for baseball game dashboard.

This package provides reusable Textual widgets for displaying game state
in the terminal user interface.

Widgets:
    BoxscoreWidget: Header showing team names and scores (runs/hits).
    SituationWidget: Panel showing inning, outs, and base runners.
    LineupCard: Batting lineup display with current batter highlighting.
    PlayByPlayLog: Scrolling log of play-by-play descriptions.
"""

from .boxscore import BoxscoreWidget
from .lineup_card import LineupCard
from .play_log import PlayByPlayLog
from .situation import SituationWidget

__all__ = ["BoxscoreWidget", "SituationWidget", "LineupCard", "PlayByPlayLog"]
