"""Main TUI application for baseball simulation."""

from pathlib import Path

from textual.app import App, ComposeResult
from textual.widgets import Header

from src.data.lahman import LahmanRepository
from src.game.team import Team

from .screens import GameScreen
from .setup_flow import SetupFlow

# Database path relative to this file (src/tui/ -> project root -> data/)
_DB_PATH = Path(__file__).parent.parent.parent / "data" / "lahman.sqlite"


class BaseballSimApp(App):
    """Main TUI application for baseball simulation.

    This app provides a terminal-based interface for running baseball
    simulations using historical player data. On startup it runs the
    team/pitcher selection flow over its own base screen (so the game
    dashboard isn't shown behind the selection modals), then pushes the
    GameScreen for the chosen matchup. The game controls live on GameScreen
    so that each screen's footer shows only the commands relevant to it.
    """

    CSS_PATH = "styles/game.tcss"

    def compose(self) -> ComposeResult:
        """Compose the base screen layout (shown behind setup modals).

        Only a Header — the selection modals carry their own shortcut hints,
        so a base Footer here would just duplicate them at the screen bottom.
        """
        yield Header()

    def on_mount(self) -> None:
        """Open the repository and start team selection."""
        self.repo = LahmanRepository(str(_DB_PATH))
        self.start_setup()

    def start_setup(self) -> None:
        """Run the team/pitcher selection flow, then launch the game."""
        SetupFlow(
            self,
            self.repo,
            on_complete=self._launch_game,
            on_cancel=self.exit,
        ).begin()

    def _launch_game(
        self,
        away_team: Team,
        home_team: Team,
        away_pitcher_id: str,
        home_pitcher_id: str,
    ) -> None:
        """Push a fresh GameScreen for the selected matchup."""
        self.push_screen(
            GameScreen(
                self.repo,
                away_team,
                home_team,
                away_pitcher_id,
                home_pitcher_id,
            )
        )

    def restart_setup(self) -> None:
        """Tear down the current game and start a brand-new matchup.

        Called from GameScreen when the user picks "New Game" at the box
        score. Pops the finished GameScreen back to the base screen so the
        selection modals don't render over the old dashboard.
        """
        self.pop_screen()
        self.start_setup()


if __name__ == "__main__":
    app = BaseballSimApp()
    app.run()
