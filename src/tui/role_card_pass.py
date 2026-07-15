"""Shared role-card build pass for the season setup flows.

Both :class:`~src.tui.season_setup_flow.SeasonSetupFlow` (round-robin) and
:class:`~src.tui.historical_setup_flow.HistoricalSeasonSetupFlow` must make every
league team AI-playable before the season starts: a team's games can be simmed
and ``play_ai_game`` needs a manager context for *both* dugouts, so every league
team — the user's included — needs a ``data/roles/<TEAMID>-<YEAR>.json`` role
card. Any that are missing are built in-process (``build_role_card`` +
``save_role_card``, the importable core of ``scripts/build_roles.py``).

This is the one place the sqlite thread-affinity fix lives. The
``LahmanRepository`` wraps a single thread-affine ``sqlite3`` connection, so its
inputs must be gathered on the main thread; only the pure, CPU-bound
``build_role_card`` + ``save_role_card`` runs on the background Textual worker,
keeping the UI responsive. Per-team progress is surfaced via ``notify``; a team
whose card can't be built (inference ``ValueError``) is reported by name and
**blocks the season** — season mode has no silent manual-control fallback
(unlike ``app._build_context``). Any *other* error escaping the worker (e.g. a
save I/O error) is surfaced too, so the flow never hangs on the progress toast.

Extracted from ``SeasonSetupFlow`` (FRE-119) so both flows share one code path
and the thread-affinity fix isn't duplicated.
"""

from pathlib import Path
from typing import Callable, List, Optional, Tuple

from src.game.manager_adapter import DEFAULT_ROLES_DIR
from src.manager.inference import build_role_card
from src.manager.roles import role_card_path, save_role_card
from src.season.state import LeagueTeam


class RoleCardPass:
    """Build any missing role cards for a set of league teams, then continue.

    Args:
        app: the Textual App used to ``notify`` and ``run_worker`` the build.
        repo: open ``LahmanRepository`` for reading each missing team's
            roster/batting/pitching/appearances (touched only on the main
            thread — see the module docstring).
        roles_dir: directory holding/receiving role cards (defaults to the
            repo's ``data/roles``; overridable so tests use a tmp dir).
    """

    def __init__(self, app, repo, roles_dir: Path = DEFAULT_ROLES_DIR) -> None:
        self._app = app
        self._repo = repo
        self._roles_dir = Path(roles_dir)
        self._on_success: Callable[[], None] = lambda: None
        self._on_failure: Callable[[], None] = lambda: None

    def run(
        self,
        teams: List[LeagueTeam],
        on_success: Callable[[], None],
        on_failure: Callable[[], None],
    ) -> None:
        """Ensure every team has a role card, then dispatch to a continuation.

        With every card already present the season launches immediately via
        ``on_success`` (no build attempted, no worker). Otherwise every missing
        team's Lahman inputs are gathered **here on the main thread** — the
        ``LahmanRepository``'s ``sqlite3`` connection is thread-affine, so
        touching it from the worker would raise ``sqlite3.ProgrammingError``
        (not a ``ValueError``, so it would escape the per-team guard and
        silently kill the worker). Only the pure, CPU-bound build runs on the
        background Textual worker; the continuation runs back on the main
        thread. ``on_success`` starts the season; ``on_failure`` is called (after
        a named notify) when any card can't be built or the worker errors.
        """
        self._on_success = on_success
        self._on_failure = on_failure

        missing = self._missing_teams(teams)
        if not missing:
            on_success()
            return

        # Read the DB on the owning (main) thread; the worker gets plain data.
        prepared = [(team, self._gather_inputs(team)) for team in missing]

        self._app.notify(
            f"Building manager role cards for {len(missing)} team(s)…",
            title="Season setup",
            timeout=6,
        )

        def work() -> None:
            try:
                failures = self._build_cards(
                    prepared, progress=self._notify_progress
                )
            except Exception as exc:  # noqa: BLE001 - unexpected: surface, never hang
                self._app.call_from_thread(self._fail, str(exc))
                return
            self._app.call_from_thread(self._finish, failures)

        self._app.run_worker(
            work, thread=True, exclusive=True, group="season_role_cards"
        )

    # --- Missing-card discovery --------------------------------------------

    def _missing_teams(self, teams: List[LeagueTeam]) -> List[LeagueTeam]:
        """League teams with no role card on disk (need building)."""
        return [
            team
            for team in teams
            if not role_card_path(team.team_id, team.year, self._roles_dir).exists()
        ]

    # --- Gather (main thread) ----------------------------------------------

    def _gather_inputs(self, team: LeagueTeam) -> Tuple:
        """Read one team-season's Lahman inputs (the ``build_roles`` gather).

        **Runs on the main thread** — every call here hits the thread-affine
        ``sqlite3`` connection, so it must never run on the worker. Returns the
        plain ``(team_season, roster, batting, pitching, appearances)`` tuple the
        pure build consumes, mirroring ``scripts/build_roles.py``'s gather.
        """
        repo = self._repo
        team_id, year = team.team_id, team.year
        team_season = repo.get_team_season(team_id, year)
        roster = repo.get_team_roster(team_id, year)
        batting = {}
        pitching = {}
        for player in roster:
            b = repo.get_batting_stats(player.player_id, year)
            if b:
                batting[player.player_id] = b
            p = repo.get_pitching_stats(player.player_id, year)
            if p:
                pitching[player.player_id] = p
        appearances = repo.get_appearances(team_id, year)
        return (team_season, roster, batting, pitching, appearances)

    # --- Build (worker thread) ---------------------------------------------

    def _build_cards(
        self,
        prepared: List[Tuple[LeagueTeam, Tuple]],
        progress: Optional[Callable[[int, int, LeagueTeam], None]] = None,
    ) -> List[str]:
        """Build+save each prepared role card; return the names that failed.

        ``prepared`` is a list of ``(team, gathered_inputs)`` produced on the
        main thread by :meth:`_gather_inputs`; this method is pure (no DB
        access) so it is safe to run on the worker. A team whose inference raises
        ``ValueError`` is skipped and its display name collected — the caller
        reports the collected names and blocks the season. ``progress`` (if
        given) is called before each build with ``(index, total, team)``.
        """
        failures: List[str] = []
        total = len(prepared)
        for index, (team, inputs) in enumerate(prepared, start=1):
            if progress is not None:
                progress(index, total, team)
            try:
                self._build_one(inputs)
            except ValueError:
                failures.append(team.display_name)
        return failures

    def _build_one(self, inputs: Tuple) -> None:
        """Infer and persist one team-season's role card (the build_roles core).

        Pure and DB-free: takes the ``(team_season, roster, batting, pitching,
        appearances)`` gathered on the main thread, calls ``build_role_card``
        (raises ``ValueError`` when inference can't proceed), and writes the
        artifact into ``roles_dir``. Safe to run on the worker thread.
        """
        team_season, roster, batting, pitching, appearances = inputs
        card = build_role_card(team_season, roster, batting, pitching, appearances)
        save_role_card(card, self._roles_dir)

    def _notify_progress(self, index: int, total: int, team: LeagueTeam) -> None:
        """Report role-card build progress from the worker thread."""
        self._app.call_from_thread(
            self._app.notify,
            f"Building role card {index}/{total}: {team.display_name}",
            title="Season setup",
        )

    # --- Continuations (main thread) ---------------------------------------

    def _finish(self, failures: List[str]) -> None:
        """Continue to season start, or report unbuildable teams and abort.

        Runs on the main thread. Any failures name the offending team(s) and
        block the season (via ``on_failure``) — season mode never silently
        degrades a dugout to manual control.
        """
        if failures:
            names = ", ".join(failures)
            self._app.notify(
                f"Couldn't build a manager role card for: {names}. "
                "Every team needs one to start a season — season not started.",
                title="Season setup failed",
                severity="error",
                timeout=12,
            )
            self._on_failure()
            return
        self._on_success()

    def _fail(self, message: str) -> None:
        """Report an unexpected worker failure and abort (runs on main thread).

        The per-team ``ValueError`` path (an unbuildable team) is handled by
        :meth:`_finish`; this is the safety net for any *other* error escaping
        the worker (e.g. a save I/O error) so the flow reports it and aborts via
        ``on_failure`` instead of hanging on the progress toast.
        """
        self._app.notify(
            f"Season setup failed while building role cards: {message}. "
            "Season not started.",
            title="Season setup failed",
            severity="error",
            timeout=12,
        )
        self._on_failure()
