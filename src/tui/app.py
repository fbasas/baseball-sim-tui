"""Main TUI application for baseball simulation."""

from pathlib import Path
from typing import Callable, Optional

from textual.app import App, ComposeResult
from textual.widgets import Header

from src.data.lahman import LahmanRepository
from src.game.lineup_builder import get_default_starter
from src.game.lineup_edit import LineupPlan
from src.game.persistence import SaveError, load_game
from src.game.team import Team
from src.series.controller import GameWorkloads, SeriesController

from .game_config import GameConfig
from src.game.manager_adapter import (
    TeamManagerContext,
    build_roles_hint,
    load_manager_for_team,
)
from .screens import GameScreen
from .screens.pitcher_select_screen import PitcherSelectScreen
from .screens.season_hub_screen import HubChoice, SeasonHubScreen
from .screens.series_status_screen import SeriesStatusScreen
from .season_setup_flow import SeasonSetupFlow
from .setup_flow import SetupFlow, pitcher_rows

# Database path relative to this file (src/tui/ -> project root -> data/)
_DB_PATH = Path(__file__).parent.parent.parent / "data" / "lahman.sqlite"


class BaseballSimApp(App):
    """Main TUI application for baseball simulation.

    This app provides a terminal-based interface for running baseball
    simulations using historical player data. On startup it runs the
    mode/control/team/pitcher selection flow over its own base screen, then
    pushes the GameScreen for the chosen matchup. In series mode the app
    also owns the SeriesController (wins, rest ledgers) and drives the
    between-games flow; the manager AI runs any side the user handed to it.
    """

    CSS_PATH = "styles/game.tcss"

    TITLE = "⚾ Baseball Time Machine"
    SUB_TITLE = "any team · any era · Lahman database"

    def compose(self) -> ComposeResult:
        """Compose the base screen layout (shown behind setup modals).

        Only a Header — the selection modals carry their own shortcut hints,
        so a base Footer here would just duplicate them at the screen bottom.
        """
        yield Header()

    def on_mount(self) -> None:
        """Open the repository and start team selection."""
        self.repo = LahmanRepository(str(_DB_PATH))
        self.series: Optional[SeriesController] = None
        self.config: Optional[GameConfig] = None
        self._away_team: Optional[Team] = None
        self._home_team: Optional[Team] = None
        self._away_ctx: Optional[TeamManagerContext] = None
        self._home_ctx: Optional[TeamManagerContext] = None
        self._away_plan: Optional[LineupPlan] = None
        self._home_plan: Optional[LineupPlan] = None
        self.start_setup()

    def start_setup(self) -> None:
        """Run the full pregame selection flow, then launch the game."""
        self.series = None
        SetupFlow(
            self,
            self.repo,
            on_complete=self._on_setup_complete,
            on_cancel=self.exit,
            on_load=self._resume_saved_game,
            on_season=self._start_season_setup,
        ).begin()

    # --- Season flow ------------------------------------------------------

    def _start_season_setup(self) -> None:
        """Run the season league builder, then push the season hub.

        Picked from the mode menu's "Season" entry. ``SeasonSetupFlow`` owns the
        league-size / games / team-picker / your-team chain and the in-process
        role-card pass, then hands back a fully built ``SeasonController``.
        Backing out of its first step (or a failed role-card pass) returns to
        the mode menu via ``start_setup``.
        """
        SeasonSetupFlow(
            self,
            self.repo,
            on_complete=self._on_season_ready,
            on_cancel=self.start_setup,
        ).begin()

    def _on_season_ready(self, controller) -> None:
        """Push the season hub for a freshly built ``SeasonController``."""
        self.push_screen(SeasonHubScreen(controller, self._on_hub_choice))

    def _on_hub_choice(self, choice: str) -> None:
        """Handle a season hub action.

        The play/sim/save actions arrive in later season parts (FRE-96/FRE-97);
        until then they surface a notice behind the same callback seam. The
        menu-navigation choices work now: a new season or returning to the main
        menu restarts setup; quit exits the app (mirroring the series
        scoreboard's ``new`` / exit handling).
        """
        if choice in (HubChoice.NEW_SEASON, HubChoice.MAIN_MENU):
            self.pop_screen()  # tear down the hub
            self.start_setup()
        elif choice == HubChoice.QUIT:
            self.exit()
        else:
            self.notify(
                "Playing and simming season games lands in a follow-up "
                "(FRE-96).",
                title="Coming soon",
                timeout=6,
            )

    def _resume_saved_game(self, path: Path) -> None:
        """Load a save from ``path`` and push the restored GameScreen.

        Called from the setup flow's "Load saved game" branch with the file the
        user picked. Loads the ``SaveFile`` and, per its ``kind``, reconstructs a
        single game or an in-progress series via the replay-safe restore path,
        then pushes the resumed screen. Any load/restore failure —
        corrupt/unparseable JSON, a wrong ``schema_version``, or a
        ``(team_id, year)`` absent from the local Lahman database — is surfaced
        via ``notify`` and returns to the setup menu rather than crashing (all
        are ``SaveError`` subclasses).

        App-level matchup state (``config``, teams, ``series``, manager-AI
        contexts) is synced from the save so a subsequent Ctrl+S re-save and, in
        series mode, the next games continue correctly.
        """
        try:
            save = load_game(path)
            if getattr(save, "kind", "single") == "series":
                screen = self._restore_series_game(save)
            else:
                screen = GameScreen.restore_from(save, self.repo)
                self.config = save.game.config
                self._away_team = screen.away_team
                self._home_team = screen.home_team
                self._away_ctx = None
                self._home_ctx = None
                self._away_plan = None
                self._home_plan = None
                self.series = None
        except SaveError as exc:
            self.notify(
                str(exc),
                title="Couldn't load save",
                severity="error",
                timeout=10,
            )
            self.start_setup()
            return

        self.push_screen(screen)

    def _restore_series_game(self, save) -> "GameScreen":
        """Resume an in-progress best-of-N series from a ``kind == "series"`` save.

        Rebuilds the app-level ``SeriesController`` (standings + both rest
        ledgers) from the ``SeriesSnapshot``, restores the in-progress game via
        the FRE-47 replay-safe path, and — critically — re-establishes the
        series ``_on_game_complete`` wiring so finishing the resumed game records
        the result and advances the series exactly as an unsaved one would.

        The AI dugout contexts are rebuilt from the saved ``GameConfig`` (which
        records which sides are AI) and synced to the restored ledgers + current
        day, so both the resumed game's in-game manager calls and games 2+ stay
        rest-aware. Returns the restored ``GameScreen`` (state is injected on
        mount); raises ``SaveError`` on a missing team, handled by the caller.
        """
        controller = save.series.to_controller()
        screen = GameScreen.restore_from(
            save,
            self.repo,
            on_game_complete=self._on_series_game_complete,
        )

        self.config = save.game.config
        self.series = controller
        self._away_team = screen.away_team
        self._home_team = screen.home_team
        self._away_plan = None
        self._home_plan = None

        # Rebuild AI contexts and sync each to the restored series' rest ledger
        # and current day (the in-progress game's day == current_day, since it
        # is not yet recorded), mirroring _push_game's series sync.
        self._away_ctx = self._build_context(self._away_team, self.config.away_ai)
        self._home_ctx = self._build_context(self._home_team, self.config.home_ai)
        day = controller.current_day
        if self._away_ctx:
            self._away_ctx.ledger = controller.away_ledger
            self._away_ctx.day = day
        if self._home_ctx:
            self._home_ctx.ledger = controller.home_ledger
            self._home_ctx.day = day
        screen._away_ctx = self._away_ctx
        screen._home_ctx = self._home_ctx
        return screen

    def _on_setup_complete(
        self,
        away_team: Team,
        home_team: Team,
        away_pitcher_id: Optional[str],
        home_pitcher_id: Optional[str],
        away_plan: Optional[LineupPlan],
        home_plan: Optional[LineupPlan],
        config: GameConfig,
    ) -> None:
        """Store the matchup, build AI contexts, and launch game 1.

        ``away_plan``/``home_plan`` are the manager's edited lineups (None for
        AI sides and for accept-the-auto-lineup). They are stored and passed
        only into game 1; series games 2+ rebuild the auto lineup (see
        ``_start_next_series_game``), so the editor is initial-setup-only.
        """
        self.config = config
        self._away_team = away_team
        self._home_team = home_team
        self._away_ctx = self._build_context(away_team, config.away_ai)
        self._home_ctx = self._build_context(home_team, config.home_ai)
        self._away_plan = away_plan
        self._home_plan = home_plan
        if config.is_series:
            self.series = SeriesController(best_of=config.best_of)
        self._push_game(
            away_pitcher_id, home_pitcher_id, away_plan, home_plan
        )

    def _build_context(
        self, team: Team, want_ai: bool
    ) -> Optional[TeamManagerContext]:
        """Load a role card for an AI-managed side.

        The role artifact is built by an explicit offline pass; if it's
        missing, tell the user how to create it and fall back to manual
        control for that side rather than blocking the game.
        """
        if not want_ai:
            return None
        try:
            manager = load_manager_for_team(team)
        except FileNotFoundError:
            self.notify(
                f"No role card for {team.info.year} {team.info.team_name} — "
                f"run: {build_roles_hint(team)}\n"
                "That side falls back to manual control for now.",
                title="Manager AI unavailable",
                severity="warning",
                timeout=12,
            )
            return None
        return TeamManagerContext(manager=manager)

    def _push_game(
        self,
        away_pitcher_id: Optional[str],
        home_pitcher_id: Optional[str],
        away_plan: Optional[LineupPlan] = None,
        home_plan: Optional[LineupPlan] = None,
    ) -> None:
        """Push a fresh GameScreen; in series mode, sync rest state first.

        ``away_plan``/``home_plan`` default to None so between-series games
        (``_start_next_series_game``) rebuild the auto lineup; only the initial
        game (``_on_setup_complete``) passes the manager's edited plans.
        """
        if self.series is not None:
            day = self.series.current_day
            if self._away_ctx:
                self._away_ctx.ledger = self.series.away_ledger
                self._away_ctx.day = day
            if self._home_ctx:
                self._home_ctx.ledger = self.series.home_ledger
                self._home_ctx.day = day

        self.push_screen(
            GameScreen(
                self.repo,
                self._away_team,
                self._home_team,
                away_pitcher_id,
                home_pitcher_id,
                away_ctx=self._away_ctx,
                home_ctx=self._home_ctx,
                away_plan=away_plan,
                home_plan=home_plan,
                on_game_complete=(
                    self._on_series_game_complete if self.series else None
                ),
            )
        )

    # --- Series flow ------------------------------------------------------

    def _on_series_game_complete(self, result: dict) -> None:
        """Record a finished series game and show the series scoreboard."""
        self.series.record_game(
            result["away_score"],
            result["home_score"],
            GameWorkloads(away=result["away_workloads"], home=result["home_workloads"]),
        )
        self.pop_screen()  # tear down the finished GameScreen
        self._show_series_status()

    def _show_series_status(self) -> None:
        series = self.series
        away_name = f"{self._away_team.info.year} {self._away_team.info.team_name}"
        home_name = f"{self._home_team.info.year} {self._home_team.info.team_name}"

        game_lines = []
        for record in series.state.results:
            winner = home_name if record.home_won else away_name
            game_lines.append(
                f"Game {record.game_number}:  {away_name} {record.away_score}, "
                f"{home_name} {record.home_score}  —  {winner}"
            )

        if series.is_complete:
            title = f"BEST-OF-{series.state.best_of} · SERIES FINAL"
            next_line = ""
        else:
            title = (
                f"BEST-OF-{series.state.best_of} · "
                f"GAME {series.current_game_number} UP NEXT"
            )
            next_line = f"Day {series.current_day + 1} — rest carries over between games"

        self.push_screen(
            SeriesStatusScreen(
                title_line=title,
                standing_line=series.standings_line(away_name, home_name),
                game_lines=game_lines,
                next_line=next_line,
                is_complete=series.is_complete,
            ),
            self._on_series_status_choice,
        )

    def _on_series_status_choice(self, choice: Optional[str]) -> None:
        if choice == "next":
            self._start_next_series_game()
        elif choice == "new":
            self.start_setup()
        else:
            self.exit()

    def _start_next_series_game(self) -> None:
        """Collect starters for human-managed sides, then push the next game."""

        def after_home(home_pid: Optional[str]) -> None:
            self._push_game(self._pending_away_pid, home_pid)

        def after_away(away_pid: Optional[str]) -> None:
            self._pending_away_pid = away_pid
            self._pick_series_starter(self._home_team, self._home_ctx, "Home", after_home)

        self._pick_series_starter(self._away_team, self._away_ctx, "Away", after_away)

    def _pick_series_starter(
        self,
        team: Team,
        ctx: Optional[TeamManagerContext],
        role: str,
        cont: Callable[[Optional[str]], None],
    ) -> None:
        """Human sides re-pick a starter each game; AI sides pick their own."""
        if ctx is not None:
            cont(None)
            return
        default_pid = get_default_starter(team, self.repo)
        self.push_screen(
            PitcherSelectScreen(
                team_name=f"{team.info.year} {team.info.team_name}",
                pitchers=pitcher_rows(team),
                default_pitcher_id=default_pid,
                role=role,
            ),
            lambda pid: cont(pid or default_pid),
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
