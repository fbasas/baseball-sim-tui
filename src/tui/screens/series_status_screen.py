"""Between-games (and end-of-series) status screen for best-of-N series.

Shows the series standing, per-game results, and what's next. Dismisses
with "next" (play the next game), "new" (new matchup after a finished
series), or "quit".
"""

from typing import List, Optional, Tuple

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Label, Static


class SeriesStatusScreen(ModalScreen[Optional[str]]):
    """Series scoreboard between games.

    Args:
        title_line: e.g. "BEST-OF-7 · GAME 3 UP NEXT" or "SERIES FINAL".
        standing_line: e.g. "1927 Yankees lead 2-1".
        game_lines: one display line per completed game.
        next_line: probable starters / next-game info ("" when complete).
        is_complete: True when the series is decided.
    """

    CSS = """
    SeriesStatusScreen {
        align: center middle;
        background: #0d160d 40%;
    }

    #series-container {
        width: 64;
        height: auto;
        max-height: 85%;
        background: #121f12;
        border: round #d4a843;
        border-title-color: #d4a843;
        border-title-style: bold;
        padding: 1 2;
    }

    #series-standing {
        text-align: center;
        width: 100%;
        color: #d4a843;
        text-style: bold;
        margin: 0 0 1 0;
    }

    #series-games {
        width: 100%;
        margin: 0 0 1 0;
        padding: 0 1;
        border: round #3e5c40;
    }

    #series-next {
        text-align: center;
        width: 100%;
        color: #f2ecd8;
    }

    #series-hint {
        text-align: center;
        width: 100%;
        height: 1;
        margin: 1 0 0 0;
        color: #6b7d6b;
    }
    """

    BINDINGS = [
        Binding("enter", "proceed", "Continue", priority=True),
        Binding("space", "proceed", "Continue", show=False),
        Binding("q", "quit_series", "Quit"),
    ]

    def __init__(
        self,
        title_line: str,
        standing_line: str,
        game_lines: List[str],
        next_line: str = "",
        is_complete: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._title_line = title_line
        self._standing_line = standing_line
        self._game_lines = game_lines
        self._next_line = next_line
        self._is_complete = is_complete

    def compose(self) -> ComposeResult:
        proceed_label = "New Matchup" if self._is_complete else "Next Game"
        hint = (
            f"[#d4a843]Enter[/] {proceed_label.lower()}   [#d4a843]Q[/] quit"
        )
        with Container(id="series-container"):
            yield Label(self._standing_line, id="series-standing")
            yield Static("\n".join(self._game_lines) or "No games yet", id="series-games")
            if self._next_line:
                yield Static(self._next_line, id="series-next")
            yield Label(hint, id="series-hint")

    def on_mount(self) -> None:
        container = self.query_one("#series-container", Container)
        container.border_title = f"⚾ {self._title_line}"

    def action_proceed(self) -> None:
        self.dismiss("new" if self._is_complete else "next")

    def action_quit_series(self) -> None:
        self.dismiss("quit")
