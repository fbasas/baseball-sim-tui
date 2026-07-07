"""Pre-game setup flow: mode, control, teams, and starting pitchers.

Drives the modal chain — game mode, manager control, away team, home team,
then a starting-pitcher pick for each human-managed side — over the app's
base screen (rather than over a half-built GameScreen), so the game
dashboard isn't visible behind the selection modals. When the user has made
every choice, ``on_complete`` is called with the loaded teams, the chosen
pitcher ids (None for AI-managed sides — the manager AI picks its own
starter), and the GameConfig; backing out of the away team returns to the
control question, and backing out of the mode question calls ``on_cancel``.
"""

from typing import Callable, Optional, Tuple

from src.data.lahman import LahmanRepository
from src.game.lineup_builder import build_lineup, get_default_starter
from src.game.lineup_edit import LineupPlan
from src.game.team import Team

from .game_config import GameConfig
from .screens.choice_screen import ChoiceScreen
from .screens.lineup_edit_screen import LineupEditScreen
from .screens.pitcher_select_screen import PitcherSelectScreen
from .screens.team_select_screen import TeamSelectScreen

_MODE_CHOICES = [
    ("single", "Single game — one exhibition matchup"),
    ("series3", "Best-of-3 series"),
    ("series5", "Best-of-5 series"),
    ("series7", "Best-of-7 series"),
]

def pitcher_rows(team: Team):
    """Build (player_id, name, W, L, ERA, IPouts) rows for PitcherSelectScreen.

    Sorted by games started descending. Shared by the pregame setup flow and
    the between-games starter pick in series mode.
    """
    rows = []
    for p in team.get_available_pitchers():
        ps = team.pitching_stats.get(p.player_id)
        gs = ps.games_started if ps else 0
        wins = ps.wins if ps else 0
        losses = ps.losses if ps else 0
        era = (
            ps.earned_runs / ps.innings_pitched * 9
            if ps and ps.innings_pitched > 0
            else 0.0
        )
        ip_outs = ps.ip_outs if ps else 0
        name = f"{p.name_last}, {p.name_first}"
        # gs kept as the trailing sort key; stripped before returning
        rows.append((p.player_id, name, wins, losses, era, ip_outs, gs))
    rows.sort(key=lambda x: x[6], reverse=True)  # most games started first
    return [row[:6] for row in rows]


_CONTROL_CHOICES = [
    ("home_ai", "You manage the AWAY team (AI runs the home dugout)"),
    ("away_ai", "You manage the HOME team (AI runs the away dugout)"),
    ("none", "You manage BOTH teams"),
    ("both_ai", "AI manages BOTH teams (watch the game)"),
]


class SetupFlow:
    """Coordinates mode, control, team, and pitcher selection pregame.

    Args:
        app: The Textual App used to push the selection modals.
        repo: Open LahmanRepository for loading teams and pitcher data.
        on_complete: Called as ``on_complete(away_team, home_team,
            away_pitcher_id, home_pitcher_id, away_plan, home_plan, config)``
            once everything is chosen; pitcher ids are None for AI-managed
            sides, and each ``*_plan`` is an ``Optional[LineupPlan]`` — the
            manager's edited lineup, or None for AI sides and when the auto
            lineup was accepted unchanged.
        on_cancel: Called if the user backs out of the mode selection.
    """

    def __init__(
        self,
        app,
        repo: LahmanRepository,
        on_complete: Callable[
            [
                Team,
                Team,
                Optional[str],
                Optional[str],
                Optional[LineupPlan],
                Optional[LineupPlan],
                GameConfig,
            ],
            None,
        ],
        on_cancel: Callable[[], None],
    ) -> None:
        self._app = app
        self._repo = repo
        self._on_complete = on_complete
        self._on_cancel = on_cancel
        self.config: Optional[GameConfig] = None
        self.away_team: Optional[Team] = None
        self.home_team: Optional[Team] = None
        self._away_pitcher_id: Optional[str] = None
        self._away_plan: Optional[LineupPlan] = None

    def begin(self) -> None:
        """Start the flow at game-mode selection."""
        self._select_mode()

    # --- Mode / control selection ----------------------------------------

    def _select_mode(self) -> None:
        def on_mode_chosen(mode_id: Optional[str]) -> None:
            if mode_id is None:
                self._on_cancel()
                return
            self._mode_id = mode_id
            self._select_control()

        self._app.push_screen(
            ChoiceScreen(
                title="⚾ GAME MODE",
                prompt="How do you want to play?",
                choices=_MODE_CHOICES,
                default_id="single",
            ),
            on_mode_chosen,
        )

    def _select_control(self) -> None:
        def on_control_chosen(control_id: Optional[str]) -> None:
            if control_id is None:
                self._select_mode()
                return
            mode = "single" if self._mode_id == "single" else "series"
            best_of = None if mode == "single" else int(self._mode_id[-1])
            self.config = GameConfig(
                mode=mode,
                best_of=best_of,
                away_ai=control_id in ("away_ai", "both_ai"),
                home_ai=control_id in ("home_ai", "both_ai"),
            )
            self._select_team(is_away=True)

        self._app.push_screen(
            ChoiceScreen(
                title="⚾ MANAGER CONTROL",
                prompt="Who manages the dugouts?",
                choices=_CONTROL_CHOICES,
                default_id="home_ai",
            ),
            on_control_chosen,
        )

    # --- Team selection -------------------------------------------------

    def _select_team(self, is_away: bool) -> None:
        role = "Away" if is_away else "Home"
        # When picking the home side, show the away pick for context.
        if not is_away and self.away_team is not None:
            info = self.away_team.info
            context = f"visiting: {info.year} {info.team_name}"
        else:
            context = ""

        def on_team_chosen(result: Optional[Tuple[str, int]]) -> None:
            if result is None:
                # Backing out of the away pick returns to the control
                # question; backing out of the home pick returns to the
                # away pick.
                if is_away:
                    self._select_control()
                else:
                    self._select_team(is_away=True)
                return

            team_id, year = result
            try:
                team = Team.load_from_repository(self._repo, team_id, year)
            except Exception:
                # Sparse roster / missing data — re-prompt the same side.
                self._select_team(is_away=is_away)
                return

            if is_away:
                self.away_team = team
                self._select_team(is_away=False)
            else:
                self.home_team = team
                self._pitcher_phase(is_away=True)

        self._app.push_screen(
            TeamSelectScreen(role, self._repo, context=context), on_team_chosen
        )

    # --- Pitcher selection ----------------------------------------------

    def _pitcher_phase(self, is_away: bool) -> None:
        """Ask for a starter on human-managed sides; AI sides pick their own.

        A ``None`` pitcher id tells the game screen to let that side's
        manager AI choose from its role card's rotation.
        """
        side_is_ai = self.config.away_ai if is_away else self.config.home_ai
        if side_is_ai:
            if is_away:
                self._away_pitcher_id = None
                self._pitcher_phase(is_away=False)
            else:
                self._finish(home_pitcher_id=None)
            return
        team = self.away_team if is_away else self.home_team
        self._select_pitcher(team, is_away=is_away)

    def _finish(
        self,
        home_pitcher_id: Optional[str],
        home_plan: Optional[LineupPlan] = None,
    ) -> None:
        self._on_complete(
            self.away_team,
            self.home_team,
            self._away_pitcher_id,
            home_pitcher_id,
            self._away_plan,
            home_plan,
            self.config,
        )

    def _select_pitcher(self, team: Team, is_away: bool) -> None:
        default_pid = get_default_starter(team, self._repo)
        pitchers = pitcher_rows(team)

        def on_pitcher_chosen(chosen_id: Optional[str]) -> None:
            pid = chosen_id or default_pid
            self._edit_lineup(team, pid, is_away)

        self._app.push_screen(
            PitcherSelectScreen(
                team_name=f"{team.info.year} {team.info.team_name}",
                pitchers=pitchers,
                default_pitcher_id=default_pid,
                role="Away" if is_away else "Home",
            ),
            on_pitcher_chosen,
        )

    # --- Lineup review / edit -------------------------------------------

    def _edit_lineup(self, team: Team, pid: str, is_away: bool) -> None:
        """Build the auto lineup and let a human side review/edit it.

        Builds the auto lineup for ``pid`` (so the editor shows the same
        starting nine the game would otherwise use), then pushes
        ``LineupEditScreen``. Its result is an ``Optional[LineupPlan]``: an
        edited plan on confirm, or None when the auto lineup is accepted
        (Esc/cancel) — in which case the game screen rebuilds the auto lineup
        as before. The plan is stored per side and carried through to
        ``on_complete``; only human sides reach this method.
        """
        build_lineup(team, self._repo, pitcher_id=pid)

        def on_lineup_chosen(plan: Optional[LineupPlan]) -> None:
            if is_away:
                self._away_pitcher_id = pid
                self._away_plan = plan
                self._pitcher_phase(is_away=False)
            else:
                self._finish(home_pitcher_id=pid, home_plan=plan)

        self._app.push_screen(
            LineupEditScreen(
                team,
                team.lineup,
                self._repo,
                role="Away" if is_away else "Home",
            ),
            on_lineup_chosen,
        )
