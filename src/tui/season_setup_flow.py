"""Season setup flow: league builder, role-card pass, and team choice.

The season-mode analogue of :class:`~src.tui.setup_flow.SetupFlow`. Reached
from the ``"season"`` entry in ``SetupFlow``'s mode menu, it drives its own
modal chain — league size, games per opponent, an N-long team-picker loop, and
the user's team — then makes every league team AI-playable and hands a fully
constructed :class:`~src.season.controller.SeasonController` back to its owner
(the app pushes the hub, exactly as ``SetupFlow`` hands a matchup to
``_on_setup_complete``).

Two things set this flow apart from the two-team ``SetupFlow`` chain:

- **The team-picker loop.** ``TeamSelectScreen`` is shown ``N`` times with a
  context line listing the picks so far; a duplicate ``(team_id, year)`` or a
  sparse-roster load failure re-prompts that same slot (the ``SetupFlow``
  ``_select_team`` pattern, generalized to a loop). Backing out of a slot pops
  the previous pick and re-prompts it; backing out of the first slot returns to
  the games question, and so on back to the mode menu.
- **The in-process role-card pass.** Every league team — the user's included,
  since its games can be simmed and ``play_ai_game`` needs a context for both
  dugouts — needs a ``data/roles/<TEAMID>-<YEAR>.json`` role card. The shared
  :class:`~src.tui.role_card_pass.RoleCardPass` builds any that are missing on a
  Textual worker (gathering DB inputs on the main thread first), reporting a team
  whose card can't be built by name and **blocking season start** — season mode
  has no silent manual-control fallback (unlike ``app._build_context``). The same
  pass backs the historical flow, so the sqlite-thread-affinity fix lives in one
  place.
"""

from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from src.game.manager_adapter import (
    DEFAULT_ROLES_DIR,
    TeamManagerContext,
    load_manager_for_team,
)
from src.game.team import Team
from src.season.controller import SeasonController
from src.season.state import LeagueTeam, SeasonState

from .role_card_pass import RoleCardPass
from .screens.choice_screen import ChoiceScreen
from .screens.team_select_screen import TeamSelectScreen

# League-size and games-per-opponent options (mirror the model-layer's
# VALID_LEAGUE_SIZES / VALID_GAMES_PER_OPPONENT; ids are the numbers as strings).
_SIZE_CHOICES = [
    ("4", "4 teams"),
    ("6", "6 teams"),
    ("8", "8 teams"),
]
_GAMES_CHOICES = [
    ("2", "2 games vs each opponent"),
    ("4", "4 games vs each opponent"),
    ("6", "6 games vs each opponent"),
    ("10", "10 games vs each opponent"),
]

# Sentinel id for the "watch-only (commissioner)" your-team choice. Cannot
# collide with a team key ("{team_id}-{year}"), which never contains a space.
_WATCH_ONLY = "watch only"


class SeasonSetupFlow:
    """Coordinates league configuration, team selection, and the role-card pass.

    Args:
        app: the Textual App used to push the selection modals and run the
            role-card worker.
        repo: open ``LahmanRepository`` for loading teams and, when building a
            missing role card, that team's roster/batting/pitching/appearances.
        on_complete: called as ``on_complete(controller)`` with the constructed
            :class:`SeasonController` once every league team is loaded and
            AI-ready; the app pushes the season hub from here.
        on_cancel: called when the user backs out of the first step (league
            size) or when the role-card pass fails — i.e. the season does not
            start and control returns to the mode menu.
        roles_dir: directory holding/receiving role cards (defaults to the
            repo's ``data/roles``; overridable so tests use a tmp dir).
    """

    def __init__(
        self,
        app,
        repo,
        on_complete: Callable[[SeasonController], None],
        on_cancel: Callable[[], None],
        roles_dir: Path = DEFAULT_ROLES_DIR,
    ) -> None:
        self._app = app
        self._repo = repo
        self._on_complete = on_complete
        self._on_cancel = on_cancel
        self._roles_dir = Path(roles_dir)
        self._league_size: Optional[int] = None
        self._games_per_opponent: Optional[int] = None
        # Picks in selection order; the loaded Team objects are kept keyed so
        # they are reused for the contexts and the controller (never reloaded).
        self._league_teams: List[LeagueTeam] = []
        self._loaded_teams: Dict[str, Team] = {}
        self._user_team_key: Optional[str] = None

    def begin(self) -> None:
        """Start the flow at league-size selection."""
        self._select_league_size()

    # --- League configuration ----------------------------------------------

    def _select_league_size(self) -> None:
        def on_chosen(choice_id: Optional[str]) -> None:
            if choice_id is None:
                # Backing out of the first step returns to the mode menu.
                self._on_cancel()
                return
            self._league_size = int(choice_id)
            self._select_games_per_opponent()

        self._app.push_screen(
            ChoiceScreen(
                title="⚾ LEAGUE SIZE",
                prompt="How many teams in the league?",
                choices=_SIZE_CHOICES,
                default_id="4",
            ),
            on_chosen,
        )

    def _select_games_per_opponent(self) -> None:
        def on_chosen(choice_id: Optional[str]) -> None:
            if choice_id is None:
                self._select_league_size()  # back
                return
            self._games_per_opponent = int(choice_id)
            self._select_team(index=0)

        self._app.push_screen(
            ChoiceScreen(
                title="⚾ SEASON LENGTH",
                prompt="How many games against each opponent?",
                choices=_GAMES_CHOICES,
                default_id="4",
            ),
            on_chosen,
        )

    # --- Team-picker loop ---------------------------------------------------

    def _picks_context(self) -> str:
        """The dim context line listing the teams picked so far."""
        if not self._league_teams:
            return ""
        names = ", ".join(team.display_name for team in self._league_teams)
        return f"picked: {names}"

    def _add_pick(self, team: Team) -> None:
        info = team.info
        key = f"{info.team_id}-{info.year}"
        self._league_teams.append(
            LeagueTeam(
                team_id=info.team_id,
                year=info.year,
                display_name=f"{info.year} {info.team_name}",
            )
        )
        self._loaded_teams[key] = team

    def _pop_pick(self) -> None:
        """Undo the most recent pick (used when backing out of a later step)."""
        if not self._league_teams:
            return
        removed = self._league_teams.pop()
        self._loaded_teams.pop(removed.key, None)

    def _select_team(self, index: int) -> None:
        """Pick the ``index``-th league team (0-based), then advance.

        A duplicate ``(team_id, year)`` or a sparse-roster load failure
        re-prompts the same slot; backing out (``None``) pops the previous pick
        and re-prompts it, or — at the first slot — returns to the games
        question.
        """
        role = f"Team {index + 1} of {self._league_size}"

        def on_team_chosen(result: Optional[Tuple[str, int]]) -> None:
            if result is None:
                if index == 0:
                    self._select_games_per_opponent()
                else:
                    self._pop_pick()
                    self._select_team(index - 1)
                return

            team_id, year = result
            key = f"{team_id}-{year}"
            if key in self._loaded_teams:
                # Duplicate team-season — re-prompt this same slot.
                self._select_team(index)
                return
            try:
                team = Team.load_from_repository(self._repo, team_id, year)
            except Exception:
                # Sparse roster / missing data — re-prompt this same slot.
                self._select_team(index)
                return

            self._add_pick(team)
            if index + 1 < self._league_size:
                self._select_team(index + 1)
            else:
                self._select_user_team()

        self._app.push_screen(
            TeamSelectScreen(role, self._repo, context=self._picks_context()),
            on_team_chosen,
        )

    # --- Your team ----------------------------------------------------------

    def _select_user_team(self) -> None:
        """Choose which league team the user manages (or watch-only)."""
        choices = [(team.key, team.display_name) for team in self._league_teams]
        choices.append((_WATCH_ONLY, "Watch-only (commissioner)"))

        def on_chosen(choice_id: Optional[str]) -> None:
            if choice_id is None:
                # Back: undo the last team pick and re-prompt that slot.
                self._pop_pick()
                self._select_team(self._league_size - 1)
                return
            self._user_team_key = None if choice_id == _WATCH_ONLY else choice_id
            self._start_role_card_pass()

        self._app.push_screen(
            ChoiceScreen(
                title="⚾ YOUR TEAM",
                prompt="Which team do you manage?",
                choices=choices,
                default_id=self._league_teams[0].key,
            ),
            on_chosen,
        )

    # --- Role-card pass -----------------------------------------------------

    def _start_role_card_pass(self) -> None:
        """Build any missing role cards, then launch the season.

        Delegates to the shared :class:`~src.tui.role_card_pass.RoleCardPass`
        (gather-on-main-thread + worker-build + progress + blocking), which the
        historical flow also uses. Every card present ⇒ the season launches
        immediately; an unbuildable team ⇒ the pass names it and returns to the
        mode menu via ``on_cancel`` (season mode never silently degrades a dugout
        to manual control).
        """
        RoleCardPass(self._app, self._repo, self._roles_dir).run(
            self._league_teams,
            on_success=self._launch_season,
            on_failure=self._on_cancel,
        )

    # --- Launch -------------------------------------------------------------

    def _launch_season(self) -> None:
        """Build every team's context and hand a controller to the owner.

        Every league team (the user's included) gets a ``TeamManagerContext``
        from its now-present role card, and the loaded ``Team`` objects are
        reused for the controller. The ``SeasonState`` generates the schedule
        from the picks and chosen game count; the owner pushes the hub.
        """
        contexts: Dict[str, TeamManagerContext] = {}
        for team in self._league_teams:
            loaded = self._loaded_teams[team.key]
            manager = load_manager_for_team(loaded, self._roles_dir)
            contexts[team.key] = TeamManagerContext(manager=manager)

        state = SeasonState.create(
            teams=list(self._league_teams),
            games_per_opponent=self._games_per_opponent,
            user_team_key=self._user_team_key,
        )
        controller = SeasonController(
            state=state,
            teams={team.key: self._loaded_teams[team.key] for team in self._league_teams},
            contexts=contexts,
        )
        self._on_complete(controller)
