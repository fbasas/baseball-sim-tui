"""End game menu modal for game completion options.

This module provides the EndGameMenu ModalScreen displayed when a game
completes, offering replay, new game, and quit options.
"""

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class EndGameMenu(ModalScreen[str]):
    """Modal menu shown when game ends.

    Displays final score and offers three options:
    - Replay same matchup
    - New game (currently restarts same matchup)
    - Quit application

    Attributes:
        winner: "away" or "home" indicating winning team.
        away_score: Final away team score.
        home_score: Final home team score.

    Example:
        >>> menu = EndGameMenu(winner="home", away_score=3, home_score=5)
        >>> app.push_screen(menu, callback)
    """

    BINDINGS = [("escape", "dismiss(None)", "Cancel")]

    DEFAULT_CSS = """
    EndGameMenu {
        align: center middle;
    }

    EndGameMenu > Vertical {
        width: 40;
        height: auto;
        padding: 1 2;
        background: $surface;
        border: thick $primary;
    }

    EndGameMenu Static {
        width: 100%;
        text-align: center;
        padding: 0 1;
    }

    EndGameMenu Button {
        width: 100%;
        margin: 1 0 0 0;
    }
    """

    def __init__(
        self, winner: str, away_score: int, home_score: int, **kwargs
    ) -> None:
        """Initialize the end game menu.

        Args:
            winner: "away" or "home" indicating winning team.
            away_score: Final away team score.
            home_score: Final home team score.
            **kwargs: Passed to parent ModalScreen.
        """
        super().__init__(**kwargs)
        self.winner = winner
        self.away_score = away_score
        self.home_score = home_score

    def compose(self) -> ComposeResult:
        """Compose the menu layout.

        Yields:
            Menu container with title, score, and action buttons.
        """
        with Vertical(id="menu"):
            yield Static("[bold]Game Over![/bold]", markup=True)
            yield Static(f"Final Score: {self.away_score} - {self.home_score}")
            yield Static("")
            yield Button("Replay Same Matchup", id="replay", variant="primary")
            yield Button("New Game", id="new", variant="default")
            yield Button("Quit", id="quit", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button selection.

        Dismisses the modal with the button ID as the result.

        Args:
            event: Button pressed event with button reference.
        """
        self.dismiss(event.button.id)
