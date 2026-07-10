"""Re-hydrate a saved season's ``Team``s and manager contexts from their keys.

A :class:`~src.game.persistence.SeasonSnapshot` stores only team *keys*
(``"{team_id}-{year}"``) — never rosters, role cards, or managers. On load the
app rebuilds those from the local database and the on-disk role cards, exactly
as season setup does: each team is loaded via ``Team.load_from_repository`` and
wrapped in a :class:`~src.game.manager_adapter.TeamManagerContext`, rebuilding a
missing role card in-process (``build_role_card`` + ``save_role_card``, the
importable core of ``scripts/build_roles.py`` that ``SeasonSetupFlow`` also
uses). A ``(team_id, year)`` absent from the database is a loud
:class:`~src.game.persistence.MissingTeamError` naming the team — never a silent
load of different stats.

This is the season analogue of ``SaveFile.rehydrate_teams`` for single/series
saves; it is kept out of ``SeasonController`` (which stays headless and DB-free)
and out of ``persistence`` (which stays free of the manager/inference layer).
"""

from pathlib import Path
from typing import Dict, Tuple

from src.game.manager_adapter import (
    DEFAULT_ROLES_DIR,
    TeamManagerContext,
    load_manager_for_team,
)
from src.game.persistence import MissingTeamError
from src.game.team import Team
from src.manager.inference import build_role_card
from src.manager.roles import save_role_card
from src.season.state import SeasonState


def _rehydrate_team(repo, team_id: str, year: int) -> Team:
    """Load one team-season, mapping an absent one to ``MissingTeamError``."""
    try:
        return Team.load_from_repository(repo, team_id, year)
    except ValueError as exc:
        raise MissingTeamError(
            f"This season save references {team_id} {year}, which isn't in your "
            f"local database (data/lahman.sqlite). Rebuild it with "
            f"scripts/build_lahman_db.py or load a season whose teams you have."
        ) from exc


def _gather_role_card_inputs(repo, team_id: str, year: int) -> Tuple:
    """Read one team-season's Lahman inputs for ``build_role_card``.

    Mirrors ``scripts/build_roles.py`` / ``SeasonSetupFlow._gather_role_card_inputs``.
    Runs on the caller's thread against the (thread-affine) repository.
    """
    team_season = repo.get_team_season(team_id, year)
    roster = repo.get_team_roster(team_id, year)
    batting: Dict[str, object] = {}
    pitching: Dict[str, object] = {}
    for player in roster:
        b = repo.get_batting_stats(player.player_id, year)
        if b:
            batting[player.player_id] = b
        p = repo.get_pitching_stats(player.player_id, year)
        if p:
            pitching[player.player_id] = p
    appearances = repo.get_appearances(team_id, year)
    return team_season, roster, batting, pitching, appearances


def _ensure_manager(repo, team: Team, roles_dir: Path):
    """Load a team's manager, rebuilding its role card in-process if missing.

    In the normal flow every league team's card was written to ``roles_dir`` at
    season setup and persists on disk, so this loads it directly; a card that
    has since gone missing is rebuilt from the team's Lahman inputs (the setup
    behaviour) rather than degrading the dugout to manual control.
    """
    try:
        return load_manager_for_team(team, roles_dir)
    except FileNotFoundError:
        inputs = _gather_role_card_inputs(repo, team.info.team_id, team.info.year)
        card = build_role_card(*inputs)
        save_role_card(card, roles_dir)
        return load_manager_for_team(team, roles_dir)


def rehydrate_season_teams(
    state: SeasonState, repo, roles_dir: Path = DEFAULT_ROLES_DIR
) -> Tuple[Dict[str, Team], Dict[str, TeamManagerContext]]:
    """Re-hydrate every league team and its manager context, keyed by team key.

    Returns ``(teams, contexts)`` for :meth:`SeasonSnapshot.to_controller`. A
    missing team raises :class:`MissingTeamError` naming it; a missing role card
    is rebuilt in-process (see :func:`_ensure_manager`).
    """
    teams: Dict[str, Team] = {}
    contexts: Dict[str, TeamManagerContext] = {}
    for league_team in state.teams:
        team = _rehydrate_team(repo, league_team.team_id, league_team.year)
        teams[league_team.key] = team
        contexts[league_team.key] = TeamManagerContext(
            manager=_ensure_manager(repo, team, roles_dir)
        )
    return teams, contexts
