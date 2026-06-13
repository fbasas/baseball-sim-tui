"""Pre-game setup flow: pick both teams and their starting pitchers.

Drives the modal chain — away team, home team, away pitcher, home pitcher —
over the app's base screen (rather than over a half-built GameScreen), so the
game dashboard isn't visible behind the selection modals. When the user has
made every choice, ``on_complete`` is called with the two loaded teams and the
chosen pitcher ids; backing out of the first team calls ``on_cancel``.
"""

from typing import Callable, Optional, Tuple

from src.data.lahman import LahmanRepository
from src.game.lineup_builder import get_default_starter
from src.game.team import Team

from .screens.pitcher_select_screen import PitcherSelectScreen
from .screens.team_select_screen import TeamSelectScreen


class SetupFlow:
    """Coordinates team and pitcher selection before a game starts.

    Args:
        app: The Textual App used to push the selection modals.
        repo: Open LahmanRepository for loading teams and pitcher data.
        on_complete: Called as ``on_complete(away_team, home_team,
            away_pitcher_id, home_pitcher_id)`` once everything is chosen.
        on_cancel: Called if the user backs out of the away-team selection.
    """

    def __init__(
        self,
        app,
        repo: LahmanRepository,
        on_complete: Callable[[Team, Team, str, str], None],
        on_cancel: Callable[[], None],
    ) -> None:
        self._app = app
        self._repo = repo
        self._on_complete = on_complete
        self._on_cancel = on_cancel
        self.away_team: Optional[Team] = None
        self.home_team: Optional[Team] = None
        self._away_pitcher_id: Optional[str] = None

    def begin(self) -> None:
        """Start the flow at away-team selection."""
        self._select_team(is_away=True)

    # --- Team selection -------------------------------------------------

    def _select_team(self, is_away: bool) -> None:
        role = "Away" if is_away else "Home"

        def on_team_chosen(result: Optional[Tuple[str, int]]) -> None:
            if result is None:
                # Backing out of the away pick cancels setup entirely; backing
                # out of the home pick returns to the away pick.
                if is_away:
                    self._on_cancel()
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
                self._select_pitcher(self.away_team, is_away=True)

        self._app.push_screen(TeamSelectScreen(role, self._repo), on_team_chosen)

    # --- Pitcher selection ----------------------------------------------

    def _select_pitcher(self, team: Team, is_away: bool) -> None:
        default_pid = get_default_starter(team, self._repo)

        pitchers = []
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
            # gs kept as the trailing sort key; stripped before passing on
            pitchers.append((p.player_id, name, wins, losses, era, ip_outs, gs))
        pitchers.sort(key=lambda x: x[6], reverse=True)  # most games started first
        pitchers = [row[:6] for row in pitchers]

        def on_pitcher_chosen(chosen_id: Optional[str]) -> None:
            pid = chosen_id or default_pid
            if is_away:
                self._away_pitcher_id = pid
                self._select_pitcher(self.home_team, is_away=False)
            else:
                self._on_complete(
                    self.away_team, self.home_team, self._away_pitcher_id, pid
                )

        self._app.push_screen(
            PitcherSelectScreen(
                team_name=f"{team.info.year} {team.info.team_name}",
                pitchers=pitchers,
                default_pitcher_id=default_pid,
            ),
            on_pitcher_chosen,
        )
