"""Historical-season setup flow: year picker, league build, and role-card pass.

The historical-mode analogue of :class:`~src.tui.season_setup_flow.SeasonSetupFlow`.
Reached from the ``"historical"`` entry in ``SetupFlow``'s mode menu, it drives a
year-based modal chain — pick a year, choose the actual or a generated schedule,
build that year's full league, pick the team to manage (or watch as commissioner)
— then makes every league team AI-playable and hands a fully constructed
:class:`~src.season.controller.SeasonController` back to its owner (the app pushes
the season hub through the *existing* ``_on_season_ready`` path, exactly as the
round-robin season flow does).

Everything downstream of the ``SeasonState`` is unchanged season machinery — the
controller, ``SeasonHubScreen``, sim/play, and ``kind == "season"`` save/resume.
The new work here is only the setup chain:

1. **Year picker** — a ``ChoiceScreen`` over years the local database can build a
   season for: ``get_available_years()`` intersected with ``has_schedule(year)``.
   Backing out returns to the mode menu.
2. **Schedule type** — a ``ChoiceScreen`` toggle: **Actual schedule** (the year's
   real Retrosheet calendar) vs **Generated schedule** (the same league and
   matchup multiset re-ordered into a fresh day sequence). Backing out returns to
   the year picker. The choice only selects the builder — everything after is
   shared between the two.
3. **League build** — the chosen builder
   (:func:`~src.season.historical.build_historical_season` or
   :func:`~src.season.historical.build_generated_historical_season`, drop-in same
   signature) resolves the year's teams (Retrosheet → Lahman) and its day-by-day
   schedule. A build failure (unresolved/unloadable teams) or a team-object load
   failure is reported by name and returns to the year picker — a faithful league
   loads cleanly for supported years (season mode's blocking precedent).
4. **Your team** — a ``ChoiceScreen`` over every league team (labelled
   ``"{year} {team_name}"``) plus **"Watch-only (commissioner)"``
   (``user_team_key=None``). Backing out returns to the year picker.
5. **Role-card pass** — the shared :class:`~src.tui.role_card_pass.RoleCardPass`
   builds any missing ``data/roles/<TEAMID>-<YEAR>.json`` for all league teams
   (up to 30). A team whose card can't be built blocks the season, named.
6. **Launch** — build each team's manager context (cards now all present) and
   hand the ``SeasonController`` to ``on_complete``.

Team objects and the built ``SeasonState`` are loaded once at the build step and
reused for the controller, so the league is validated end-to-end before the user
picks a team (no late failure after the your-team choice).
"""

from pathlib import Path
from typing import Callable, Dict, List, Optional

from src.game.manager_adapter import (
    DEFAULT_ROLES_DIR,
    TeamManagerContext,
    load_manager_for_team,
)
from src.game.team import Team
from src.season.controller import SeasonController
from src.season.historical import (
    HistoricalSeasonError,
    build_generated_historical_season,
    build_historical_season,
)
from src.season.state import SeasonState

from .role_card_pass import RoleCardPass
from .screens.choice_screen import ChoiceScreen

# Sentinel id for the "watch-only (commissioner)" your-team choice. Cannot
# collide with a team key ("{team_id}-{year}"), which never contains a space.
_WATCH_ONLY = "watch only"


class HistoricalSeasonSetupFlow:
    """Coordinates year selection, league build, and the role-card pass.

    Args:
        app: the Textual App used to push the selection modals and run the
            role-card worker.
        repo: open ``LahmanRepository`` exposing ``get_available_years``,
            ``has_schedule``, ``get_schedule``, ``retro_to_lahman_team``,
            ``get_team_season`` and ``get_team_roster`` (the builder's inputs)
            plus the role-card gather methods.
        on_complete: called as ``on_complete(controller)`` with the constructed
            :class:`SeasonController` once every league team is loaded and
            AI-ready; the app pushes the season hub from here (the existing
            ``_on_season_ready`` path).
        on_cancel: called when the user backs out of the year picker (the first
            step) or when the role-card pass fails — i.e. the season does not
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
        self._year: Optional[int] = None
        # Built once the league is resolved; reused for the controller so the
        # league is never re-read after the your-team pick.
        self._state: Optional[SeasonState] = None
        self._loaded_teams: Dict[str, Team] = {}
        self._user_team_key: Optional[str] = None

    def begin(self) -> None:
        """Start the flow at year selection."""
        self._select_year()

    # --- Year picker --------------------------------------------------------

    def _available_years(self) -> List[int]:
        """Years the local database can build a historical season for.

        The database's seasons (``get_available_years``, most-recent-first)
        intersected with the years that have ingested schedule data
        (``has_schedule``) — a year needs both a roster (Lahman) and a schedule
        (Retrosheet) to build.
        """
        return [
            year
            for year in self._repo.get_available_years()
            if self._repo.has_schedule(year)
        ]

    def _select_year(self) -> None:
        """Offer the buildable years; backing out returns to the mode menu.

        With no buildable year (schedule data never ingested) the flow reports
        it and returns to the mode menu rather than showing an empty picker.
        """
        years = self._available_years()
        if not years:
            self._app.notify(
                "No historical schedule data is available. Ingest it with "
                "scripts/build_schedule_db.py, then rebuild the database.",
                title="Historical season unavailable",
                severity="warning",
                timeout=12,
            )
            self._on_cancel()
            return

        choices = [(str(year), str(year)) for year in years]

        def on_chosen(choice_id: Optional[str]) -> None:
            if choice_id is None:
                # Backing out of the first step returns to the mode menu.
                self._on_cancel()
                return
            self._select_schedule_type(int(choice_id))

        self._app.push_screen(
            ChoiceScreen(
                title="⚾ HISTORICAL SEASON",
                prompt="Which year's league do you want to play?",
                choices=choices,
                default_id=str(years[0]),
            ),
            on_chosen,
        )

    # --- Schedule type ------------------------------------------------------

    def _select_schedule_type(self, year: int) -> None:
        """Choose the year's actual schedule or a freshly generated one.

        A ``ChoiceScreen`` toggle between the real Retrosheet calendar and a
        generated season (same league, same matchup multiset, re-ordered into a
        fresh day sequence — see
        :func:`~src.season.historical.build_generated_historical_season`). The
        choice only selects the builder; the league build and everything after
        are shared. Backing out returns to the year picker.
        """

        def on_chosen(choice_id: Optional[str]) -> None:
            if choice_id is None:
                self._select_year()  # back
                return
            self._build_league(year, generated=(choice_id == "generated"))

        self._app.push_screen(
            ChoiceScreen(
                title="⚾ SCHEDULE",
                prompt="Play the season's actual schedule, or a generated one?",
                choices=[
                    ("actual", "Actual schedule"),
                    ("generated", "Generated schedule"),
                ],
                default_id="actual",
            ),
            on_chosen,
        )

    # --- League build -------------------------------------------------------

    def _build_league(self, year: int, generated: bool = False) -> None:
        """Resolve the year's full league + schedule, then pick the user's team.

        Builds the ``SeasonState`` (no user team yet) with the schedule variant
        chosen at the toggle — the actual Retrosheet calendar
        (:func:`~src.season.historical.build_historical_season`) or a generated
        re-ordering (:func:`~src.season.historical.build_generated_historical_season`,
        drop-in same signature) — and loads a ``Team`` object for every league
        team, so the whole league is validated before the your-team pick. A build
        failure (unresolved/unloadable teams) or a team-object load failure is
        reported by name and returns to the year picker — a faithful league loads
        cleanly for supported years.
        """
        build = (
            build_generated_historical_season
            if generated
            else build_historical_season
        )
        try:
            state = build(self._repo, year)
        except HistoricalSeasonError as exc:
            self._app.notify(
                f"Couldn't build the {year} season: "
                f"{len(exc.problem_teams)} team(s) could not be loaded — "
                f"{', '.join(exc.problem_teams)}.",
                title="Historical season failed",
                severity="error",
                timeout=12,
            )
            self._select_year()
            return
        except ValueError as exc:
            # No schedule rows / none played — shouldn't happen for an offered
            # year, but report it rather than crashing.
            self._app.notify(
                str(exc),
                title="Historical season failed",
                severity="error",
                timeout=12,
            )
            self._select_year()
            return

        loaded: Dict[str, Team] = {}
        failures: List[str] = []
        for team in state.teams:
            try:
                loaded[team.key] = Team.load_from_repository(
                    self._repo, team.team_id, team.year
                )
            except Exception:  # noqa: BLE001 - a sparse/broken team blocks, named
                failures.append(self._team_label(year, team.display_name))
        if failures:
            self._app.notify(
                f"Couldn't load {len(failures)} team(s) for the {year} season: "
                f"{', '.join(failures)}. Season not started.",
                title="Historical season failed",
                severity="error",
                timeout=12,
            )
            self._select_year()
            return

        self._year = year
        self._state = state
        self._loaded_teams = loaded
        self._select_user_team()

    def _team_label(self, year: int, display_name: str) -> str:
        """``"{year} {team_name}"`` label for a league team."""
        return f"{year} {display_name}"

    # --- Your team ----------------------------------------------------------

    def _select_user_team(self) -> None:
        """Choose which league team the user manages (or watch-only).

        Backing out returns to the year picker (the league is rebuilt when a year
        is re-chosen).
        """
        assert self._state is not None
        choices = [
            (team.key, self._team_label(self._year, team.display_name))
            for team in self._state.teams
        ]
        choices.append((_WATCH_ONLY, "Watch-only (commissioner)"))

        def on_chosen(choice_id: Optional[str]) -> None:
            if choice_id is None:
                self._select_year()  # back
                return
            self._user_team_key = None if choice_id == _WATCH_ONLY else choice_id
            self._start_role_card_pass()

        self._app.push_screen(
            ChoiceScreen(
                title="⚾ YOUR TEAM",
                prompt="Which team do you manage?",
                choices=choices,
                default_id=self._state.teams[0].key,
            ),
            on_chosen,
        )

    # --- Role-card pass -----------------------------------------------------

    def _start_role_card_pass(self) -> None:
        """Build any missing role cards for all league teams, then launch.

        Delegates to the shared :class:`~src.tui.role_card_pass.RoleCardPass`
        (the same pass season mode uses). Every card present ⇒ the season
        launches immediately; an unbuildable team ⇒ the pass names it and returns
        to the mode menu via ``on_cancel``.
        """
        assert self._state is not None
        RoleCardPass(self._app, self._repo, self._roles_dir).run(
            self._state.teams,
            on_success=self._launch_season,
            on_failure=self._on_cancel,
        )

    # --- Launch -------------------------------------------------------------

    def _launch_season(self) -> None:
        """Build every team's context and hand a controller to the owner.

        Every league team (the user's included) gets a ``TeamManagerContext``
        from its now-present role card, and the ``Team`` objects loaded at build
        time are reused for the controller. The ``SeasonState`` is rebuilt from
        the resolved league + schedule with the chosen ``user_team_key`` (a cheap
        re-wrap — no schedule re-read); the owner pushes the hub.
        """
        assert self._state is not None
        contexts: Dict[str, TeamManagerContext] = {}
        for team in self._state.teams:
            loaded = self._loaded_teams[team.key]
            manager = load_manager_for_team(loaded, self._roles_dir)
            contexts[team.key] = TeamManagerContext(manager=manager)

        state = SeasonState.from_schedule(
            self._state.teams,
            self._state.schedule,
            user_team_key=self._user_team_key,
        )
        controller = SeasonController(
            state=state,
            teams=dict(self._loaded_teams),
            contexts=contexts,
        )
        self._on_complete(controller)
