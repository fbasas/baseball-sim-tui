"""Main TUI application for baseball simulation."""

from textual.app import App, ComposeResult
from textual.widgets import Header, Footer

from .screens import GameScreen


class BaseballSimApp(App):
    """Main TUI application for baseball simulation.

    This app provides a terminal-based interface for running baseball
    simulations using historical player data. The game controls (advance,
    fast forward, substitutions, quit) live on GameScreen so that each
    screen's footer shows only the commands relevant to it.
    """

    CSS_PATH = "styles/game.tcss"

    def compose(self) -> ComposeResult:
        """Compose the application layout.

        Yields header and footer. GameScreen is pushed on mount.
        """
        yield Header()
        yield Footer()

    def on_mount(self) -> None:
        """Push game screen when app starts."""
        self.push_screen(GameScreen())


if __name__ == "__main__":
    app = BaseballSimApp()
    app.run()
