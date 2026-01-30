"""Main TUI application for baseball simulation."""

from textual.app import App, ComposeResult
from textual.widgets import Header, Footer

from .screens import GameScreen


class BaseballSimApp(App):
    """Main TUI application for baseball simulation.

    This app provides a terminal-based interface for running baseball
    simulations using historical player data. Pressing Space or Enter
    advances the game by one at-bat.

    Bindings:
        Space/Enter: Advance one at-bat
        f: Fast forward (simulate rest of game)
        q: Quit
    """

    CSS_PATH = "styles/game.tcss"

    BINDINGS = [
        ("space", "advance", "Next Play"),
        ("enter", "advance", "Next Play"),
        ("f", "fast_forward", "Fast Forward"),
        ("s", "substitute", "Substitutions"),
        ("q", "quit", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        """Compose the application layout.

        Yields header and footer. GameScreen is pushed on mount.
        """
        yield Header()
        yield Footer()

    def on_mount(self) -> None:
        """Push game screen when app starts."""
        self.push_screen(GameScreen())

    def action_advance(self) -> None:
        """Advance game by one at-bat.

        Delegates to GameScreen.advance_game() if available.
        """
        screen = self.screen
        if hasattr(screen, 'advance_game'):
            screen.advance_game()

    def action_fast_forward(self) -> None:
        """Simulate rest of game.

        Delegates to GameScreen.fast_forward() if available.
        """
        screen = self.screen
        if hasattr(screen, 'fast_forward'):
            screen.fast_forward()

    def action_substitute(self) -> None:
        """Open substitution menu.

        Delegates to GameScreen.show_substitution_menu() if available.
        """
        screen = self.screen
        if hasattr(screen, 'show_substitution_menu'):
            screen.show_substitution_menu()


if __name__ == "__main__":
    app = BaseballSimApp()
    app.run()
