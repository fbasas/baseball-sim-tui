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
from .screens.choice_screen import ChoiceScreen
from .screens.pitcher_select_screen import PitcherSelectScreen
from .screens.season_hub_screen import HubChoice, SeasonHubScreen
from .screens.series_status_screen import SeriesStatusScreen
from .season_setup_flow import SeasonSetupFlow
from .setup_flow import SetupFlow, pitcher_rows

# Database path relative to this file (src/tui/ -> project root -> data/)
_DB_PATH = Path(__file__).parent.parent.parent / "data" / "lahman.sqlite"

# Sim-ahead "7 days" spans the current day plus this many following days.
_SIM_AHEAD_WEEK_DAYS = 7
# Toast a sim-ahead progress line no more often than every N simmed games so a
# long (end-of-season) worker shows life without flooding the notification tray.
_SIM_AHEAD_PROGRESS_EVERY = 10


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
        self.season = None  # Optional[SeasonController]; set once a season starts
        self._season_saved_count = 0  # results count at the last save (warn-only)
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
        self.season = None
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
        """Push the season hub for a freshly built ``SeasonController``.

        Records the controller as the app's live season and snapshots its
        result count as the "last saved" baseline (a fresh season starts with
        zero recorded games, so any game played this session is unsaved until
        the Part 8 save lands).
        """
        self.season = controller
        self._season_saved_count = len(controller.state.results)
        self.push_screen(SeasonHubScreen(controller, self._on_hub_choice))

    def _on_hub_choice(self, choice: str) -> None:
        """Dispatch a season hub action to its handler.

        The play/sim actions run against the live ``SeasonController``; the
        end-of-season navigation (new season / main menu) restarts setup; quit
        returns to the mode menu (warning first if unsaved games were played).
        """
        if choice == HubChoice.PLAY:
            self._play_user_game()
        elif choice in (HubChoice.SIM_MY_GAME, HubChoice.SIM_DAY):
            self._sim_current_day()
        elif choice == HubChoice.SIM_AHEAD:
            self._prompt_sim_ahead()
        elif choice == HubChoice.SAVE:
            self._save_season()
        elif choice in (HubChoice.NEW_SEASON, HubChoice.MAIN_MENU):
            self.pop_screen()  # tear down the hub
            self.start_setup()
        elif choice == HubChoice.QUIT:
            self._quit_season_to_menu()

    # --- Season hub refresh -------------------------------------------------

    def _refresh_hub(self) -> None:
        """Replace the (now-stale) top hub with a fresh one over the same season.

        Every play/sim action mutates the controller's state in place; the hub
        renders from a snapshot taken at ``compose`` time, so it must be rebuilt
        to reflect new results. Mirrors how the series flow pushes a fresh
        ``SeriesStatusScreen`` after each game rather than mutating one in
        place. Called only when the hub is the top screen (after a game screen
        or a sim-ahead worker has finished), so popping removes exactly it. When
        the season is now complete the fresh hub composes its summary state
        automatically.
        """
        self.pop_screen()
        self.push_screen(SeasonHubScreen(self.season, self._on_hub_choice))

    def _season_has_unsaved_games(self) -> bool:
        """Whether games were recorded since the last save (warn-only for now)."""
        return len(self.season.state.results) > self._season_saved_count

    # --- Play my game -------------------------------------------------------

    def _play_user_game(self) -> None:
        """Play the user's next game interactively on a ``GameScreen``.

        Picks a starter for the user's side (the AI opponent picks its own via
        ``ai_pregame``), syncs the AI side's manager context to its rest ledger
        and the game's day (exactly as ``_push_game`` does in series mode), and
        pushes a ``GameScreen`` whose ``on_game_complete`` records the result
        into the season and sims the rest of the day. A no-op with a notice if
        there is somehow no user game to play (the action is hidden in that
        state, but guard anyway).
        """
        game = self.season.next_user_game()
        if game is None:
            self.notify("No game to play right now.", title="Season")
            return

        user_key = self.season.state.user_team_key
        away_team = self.season.teams[game.away_key]
        home_team = self.season.teams[game.home_key]
        user_is_home = game.home_key == user_key

        # The user's dugout is human-controlled (ctx=None → they pick + manage);
        # the opponent runs on its manager context, synced to its ledger + day.
        away_ctx = None if game.away_key == user_key else self.season.contexts[game.away_key]
        home_ctx = None if game.home_key == user_key else self.season.contexts[game.home_key]
        if away_ctx is not None:
            away_ctx.ledger = self.season.ledgers[game.away_key]
            away_ctx.day = game.day
        if home_ctx is not None:
            home_ctx.ledger = self.season.ledgers[game.home_key]
            home_ctx.day = game.day

        user_team = home_team if user_is_home else away_team
        role = "Home" if user_is_home else "Away"

        def after_pick(user_pid: Optional[str]) -> None:
            away_pid = None if user_is_home else user_pid
            home_pid = user_pid if user_is_home else None
            self.push_screen(
                GameScreen(
                    self.repo,
                    away_team,
                    home_team,
                    away_pid,
                    home_pid,
                    away_ctx=away_ctx,
                    home_ctx=home_ctx,
                    on_game_complete=lambda payload: self._on_season_game_complete(
                        game, payload
                    ),
                )
            )

        # ctx=None forces the pitcher-select modal for the user's side.
        self._pick_series_starter(user_team, None, role, after_pick)

    def _on_season_game_complete(self, scheduled_game, payload: dict) -> None:
        """Record a finished interactive season game, then sim the rest of the day.

        Records the payload (scores, workloads, and the game's ``BoxScore``)
        into the controller through the shared bookkeeping path, tears down the
        finished ``GameScreen``, auto-sims the day's remaining AI games, and
        rebuilds the hub. A PA-cap failure while simming the rest of the day is
        surfaced but leaves the user's game (and any AI games already simmed)
        recorded.
        """
        self.season.record_user_game(scheduled_game, payload)
        self.pop_screen()  # tear down the finished GameScreen → back to the hub
        self._sim_day_guarded(scheduled_game.day)
        self._refresh_hub()

    # --- Sim my game / sim this day -----------------------------------------

    def _sim_current_day(self) -> None:
        """Sim every unplayed game on the current day headlessly, then refresh.

        Backs both **s** (sim my game, then the rest of the day) and **d** (sim
        this day) — both resolve to "finish the current day headlessly", which
        includes the user's game when it is still unplayed.
        """
        self._sim_day_guarded(self.season.current_day)
        self._refresh_hub()

    def _sim_day_guarded(self, day: int) -> None:
        """Sim ``day``'s remaining games, surfacing a PA-cap stop via ``notify``.

        ``SeasonController.sim_day`` records each game as it finishes, so a
        PA-cap ``RuntimeError`` partway through leaves the earlier games
        standing; the failed/remaining games stay unplayed and re-simmable.
        """
        try:
            self.season.sim_day(day)
        except RuntimeError as exc:
            self._notify_pa_cap(exc)

    def _notify_pa_cap(self, exc: Exception) -> None:
        """Surface a ``play_ai_game`` plate-appearance-cap failure to the user."""
        self.notify(
            f"{exc} — the day was left partly played; the failed game is "
            "re-simmable.",
            title="Sim stopped (PA cap)",
            severity="warning",
            timeout=10,
        )

    # --- Sim ahead (worker) -------------------------------------------------

    def _prompt_sim_ahead(self) -> None:
        """Ask how far to sim, then run the sim-ahead worker for that target."""
        watch_only = self.season.state.user_team_key is None
        choices = [
            ("user", "To my next game"),
            ("week", f"{_SIM_AHEAD_WEEK_DAYS} days"),
            ("end", "To end of season"),
        ]
        # A watch-only season has no "my next game"; default to the week hop.
        default_id = "week" if watch_only else "user"
        self.push_screen(
            ChoiceScreen(
                title="⚾ SIM AHEAD",
                prompt="How far ahead should the league sim?",
                choices=choices,
                default_id=default_id,
            ),
            self._on_sim_ahead_choice,
        )

    def _on_sim_ahead_choice(self, mode: Optional[str]) -> None:
        """Launch the sim-ahead worker for the chosen span (``None`` = no-op)."""
        if mode is None:
            return
        kwargs = self._sim_ahead_kwargs(mode)
        self.notify("Simming ahead…", title="Sim ahead", timeout=4)
        self.run_worker(
            lambda: self._sim_ahead_worker(kwargs),
            thread=True,
            exclusive=True,
            group="season_sim_ahead",
        )

    def _sim_ahead_kwargs(self, mode: str) -> dict:
        """Translate a sim-ahead choice id into ``simulate_ahead`` kwargs.

        ``"user"`` stops before the user's next game (or, in a watch-only
        season, sims to the end); ``"week"`` sims the current day through the
        next ``_SIM_AHEAD_WEEK_DAYS - 1`` days; ``"end"`` sims the whole season.
        """
        if mode == "user":
            return {"stop_before_user_game": True}
        if mode == "week":
            return {"through_day": self.season.current_day + _SIM_AHEAD_WEEK_DAYS - 1}
        return {}

    def _sim_ahead_worker(self, kwargs: dict) -> None:
        """Drive ``simulate_ahead`` on a background thread with progress toasts.

        Runs on a Textual worker thread (``play_ai_game`` is CPU-bound); each
        yielded record advances a counter, and every ``_SIM_AHEAD_PROGRESS_EVERY``
        games a progress line is posted back on the main thread. A PA-cap
        ``RuntimeError`` stops the generator with all prior games recorded — it
        is surfaced and the hub still refreshes. All UI work marshals back via
        ``call_from_thread``.
        """
        count = 0
        try:
            for _record in self.season.simulate_ahead(**kwargs):
                count += 1
                if count % _SIM_AHEAD_PROGRESS_EVERY == 0:
                    self.call_from_thread(self._sim_ahead_progress, count)
        except RuntimeError as exc:
            self.call_from_thread(self._sim_ahead_stopped, str(exc), count)
            return
        self.call_from_thread(self._sim_ahead_finished, count)

    def _sim_ahead_progress(self, count: int) -> None:
        """Post a running sim-ahead progress toast (from the worker thread)."""
        self.notify(f"Simmed {count} games…", title="Sim ahead", timeout=3)

    def _sim_ahead_finished(self, count: int) -> None:
        """Refresh the hub and report how many games the sim-ahead ran."""
        self._refresh_hub()
        self.notify(
            f"Simmed {count} game(s).", title="Sim ahead", timeout=4
        )

    def _sim_ahead_stopped(self, message: str, count: int) -> None:
        """Report a PA-cap stop mid-sim-ahead; recorded games stand, hub refreshes."""
        self._refresh_hub()
        self.notify(
            f"Sim stopped after {count} game(s): {message} — the failed game "
            "is re-simmable.",
            title="Sim ahead — PA cap",
            severity="warning",
            timeout=10,
        )

    # --- Save / quit --------------------------------------------------------

    def _save_season(self) -> None:
        """Season save is warn-only until Part 8 (FRE-97) lands the snapshot."""
        self.notify(
            "Saving a season lands in a follow-up (FRE-97). Your progress this "
            "session is not yet persistable.",
            title="Save unavailable",
            severity="warning",
            timeout=6,
        )

    def _quit_season_to_menu(self) -> None:
        """Quit to the mode menu, warning first if unsaved games were played.

        Season saving is not available yet (Part 8), so the prompt can only
        warn: proceeding to the menu discards the games played this session.
        With no unsaved games (or once the user confirms) control returns to the
        mode menu via ``start_setup``.
        """
        if not self._season_has_unsaved_games():
            self.pop_screen()  # tear down the hub
            self.start_setup()
            return

        def on_choice(choice: Optional[str]) -> None:
            if choice == "menu":
                self.pop_screen()  # tear down the hub
                self.start_setup()
            # "stay" (or Esc → default) leaves the hub in place.

        self.push_screen(
            ChoiceScreen(
                title="⚾ QUIT SEASON",
                prompt="Unsaved games this session will be lost — saving isn't available yet.",
                choices=[
                    ("stay", "Stay in the season"),
                    ("menu", "Quit to menu (lose progress)"),
                ],
                default_id="stay",
            ),
            on_choice,
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
