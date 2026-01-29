"""Main TUI application for baseball simulation."""

from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Static


class BaseballSimApp(App):
    """Main TUI application for baseball simulation.

    This app provides a terminal-based interface for running baseball
    simulations using historical player data. The layout uses a three-column
    grid with away lineup, center game info, and home lineup.
    """

    CSS_PATH = "styles/game.tcss"

    BINDINGS = [
        ("space", "advance", "Next Play"),
        ("enter", "advance", "Next Play"),
        ("f", "fast_forward", "Fast Forward"),
        ("q", "quit", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        """Compose the application layout.

        Yields a header, placeholder content, and footer.
        The placeholder will be replaced by GameScreen in Plan 03.
        """
        yield Header()
        yield Static("Game dashboard loading...", id="placeholder")
        yield Footer()

    def action_advance(self) -> None:
        """Advance game by one at-bat.

        Placeholder action - will trigger simulation step in GameScreen.
        """
        pass

    def action_fast_forward(self) -> None:
        """Simulate rest of game.

        Placeholder action - will fast-forward to game end in GameScreen.
        """
        pass


if __name__ == "__main__":
    app = BaseballSimApp()
    app.run()
