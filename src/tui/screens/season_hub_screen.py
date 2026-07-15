"""Season hub: the home base between games (season-scale ``SeriesStatusScreen``).

Part 5 of season mode is **rendering + action dispatch only**. The hub surfaces
a :class:`~src.season.controller.SeasonController`'s state — the standings, the
day's slate, and recent results — or, once the season is complete, the season
summary (champion, final standings, league leaders). Every user choice is
emitted to an owner callback via a distinct :class:`HubChoice` constant; the
app-side handlers that actually play/sim/save arrive in Parts 7-8, so until then
those choices no-op behind the callback seam (mirroring how
``app._on_series_status_choice`` owns a ``SeriesStatusScreen``'s result).

The one action the hub owns outright is **l**eaders: the leaderboards are pure
rendering that this part delivers in full, so ``action_leaders`` pushes a
:class:`LeagueLeadersScreen` directly rather than routing through the owner.

Player ids are never shown raw. Both screens resolve them to ``"F. Last"``
through the loaded :class:`~src.game.team.Team` rosters the controller holds
(the in-game name format, e.g. ``game_screen.py``'s cards).
"""

from typing import TYPE_CHECKING, Callable, List, Optional, Tuple

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Static

if TYPE_CHECKING:  # Import for typing only; keeps the module import-light.
    from src.season.controller import SeasonController
    from src.season.state import StandingsRow


class HubChoice:
    """The choice values the hub emits to its owner callback.

    Deliberately plain strings (house style — ``SeriesStatusScreen`` returns
    ``"next"`` / ``"new"`` / ``"quit"``) so the owner can dispatch on them and
    tests can assert them without importing an enum. ``LEADERS`` is not here:
    the hub shows the leaders subscreen itself.
    """

    PLAY = "play"
    SIM_MY_GAME = "sim_my_game"
    SIM_DAY = "sim_day"
    SIM_AHEAD = "sim_ahead"
    SAVE = "save"
    QUIT = "quit"
    NEW_SEASON = "new_season"
    MAIN_MENU = "main_menu"


# How many finished games the recent-results panel shows (newest first).
_RECENT_LIMIT = 6
# How many rows each leaderboard shows.
_LEADER_LIMIT = 5
# Fixed display width of the standings team-name column. Long franchise
# display names (e.g. "1998 Los Angeles Dodgers") are truncated to fit so
# every downstream column (W L Pct GB RS RA) stays aligned under its header.
_TEAM_COL_WIDTH = 24


# --- Formatting helpers (pure) ---------------------------------------------


def _fit(text: str, width: int) -> str:
    """Truncate ``text`` to ``width`` display columns (trailing ``…`` if clipped),
    then left-pad to exactly ``width``. Guarantees a fixed-width cell so the
    standings columns align under their header regardless of name length."""
    if len(text) > width:
        return text[: width - 1] + "…"
    return text.ljust(width)


def _format_pct(pct: float) -> str:
    """Baseball winning percentage: three decimals, no leading zero (``.750``)."""
    text = f"{pct:.3f}"
    return text[1:] if text.startswith("0.") else text


def _format_gb(games_behind: float) -> str:
    """Games-behind: an em dash for the leader, else one decimal (``2.0``)."""
    return "—" if games_behind == 0 else f"{games_behind:.1f}"


def _format_avg(value: float) -> str:
    """Batting average: three decimals, no leading zero (``.333``)."""
    text = f"{value:.3f}"
    return text[1:] if text.startswith("0.") else text


def _format_era(value: float) -> str:
    """Earned run average: two decimals (``2.75``)."""
    return f"{value:.2f}"


def _format_ip(value: float) -> str:
    """Innings pitched from a true-innings float, in thirds (``12.1``).

    The leader query returns ``outs / 3``; recover outs to render the standard
    ``.0/.1/.2`` thirds notation the box score uses.
    """
    outs = round(value * 3)
    return f"{outs // 3}.{outs % 3}"


def _format_int(value: float) -> str:
    """A counting stat (HR/RBI/H/SO): a plain integer."""
    return str(int(value))


def _resolve_name(controller: "SeasonController", team_key: str, pid: str) -> str:
    """Resolve a player id to ``"F. Last"`` through the team's loaded roster.

    Falls back to the last name alone, then the raw id, only if the roster
    lookup can't do better — in normal play every league team is loaded, so a
    name always resolves.
    """
    team = controller.teams.get(team_key)
    if team is not None:
        player = team.get_player(pid)
        if player is not None:
            if player.name_first and player.name_last:
                return f"{player.name_first[0]}. {player.name_last}"
            if player.name_last:
                return player.name_last
    return pid


# Each leaderboard: (column title, SeasonStats method name, value formatter).
_BATTING_LEADERS: List[Tuple[str, str, Callable[[float], str]]] = [
    ("AVG", "batting_average_leaders", _format_avg),
    ("HR", "home_run_leaders", _format_int),
    ("RBI", "rbi_leaders", _format_int),
    ("H", "hit_leaders", _format_int),
]
_PITCHING_LEADERS: List[Tuple[str, str, Callable[[float], str]]] = [
    ("ERA", "era_leaders", _format_era),
    ("SO", "strikeout_leaders", _format_int),
    ("IP", "innings_pitched_leaders", _format_ip),
]


def _build_leader_table(
    controller: "SeasonController",
    title: str,
    method_name: str,
    value_fmt: Callable[[float], str],
) -> str:
    """Render one leaderboard as ``title`` + up to ``_LEADER_LIMIT`` name rows.

    Reads the leaders from the season stats (a ``(team_key, pid, value)`` list),
    resolves each id to a name, and tags it with its team key so a leader's club
    is legible. An empty board (no qualifiers yet) renders a dim placeholder.
    """
    rows = getattr(controller.stats, method_name)(limit=_LEADER_LIMIT)
    lines = [f"[bold #d4a843]{title}[/]"]
    if not rows:
        lines.append("[#6b7d6b]  —[/]")
        return "\n".join(lines)
    for rank, (team_key, pid, value) in enumerate(rows, start=1):
        name = _resolve_name(controller, team_key, pid)
        lines.append(
            f"{rank}. {name:<18} [#6b7d6b]{team_key:<9}[/] {value_fmt(value):>6}"
        )
    return "\n".join(lines)


class LeagueLeadersScreen(Screen):
    """League leaderboards: batting AVG/HR/RBI/H and pitching ERA/SO/IP.

    Pure rendering over the controller's :class:`~src.season.stats.SeasonStats`
    and loaded rosters — the hub pushes it for the **l** action and it pops back
    on Esc / **q**. Ids are resolved to names here; nothing raw is shown.
    """

    BINDINGS = [
        Binding("escape", "close", "Back", priority=True),
        Binding("q", "close", "Back", show=False),
    ]

    def __init__(self, controller: "SeasonController", **kwargs) -> None:
        super().__init__(**kwargs)
        self._controller = controller

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="leaders-container"):
            yield Static("⚾ LEAGUE LEADERS", id="leaders-title")
            yield Static("BATTING", classes="hub-header")
            yield Static(self._build_batting_leaders(), classes="hub-section")
            yield Static("PITCHING", classes="hub-header")
            yield Static(self._build_pitching_leaders(), classes="hub-section")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#leaders-container", VerticalScroll).focus()

    def _build_batting_leaders(self) -> str:
        return "\n\n".join(
            _build_leader_table(self._controller, title, method, fmt)
            for title, method, fmt in _BATTING_LEADERS
        )

    def _build_pitching_leaders(self) -> str:
        return "\n\n".join(
            _build_leader_table(self._controller, title, method, fmt)
            for title, method, fmt in _PITCHING_LEADERS
        )

    def action_close(self) -> None:
        self.app.pop_screen()


class SeasonHubScreen(Screen):
    """The season's home base between games (season-scale ``SeriesStatusScreen``).

    Renders the standings (user's team marked), the day header, today's slate
    (user's game marked), and recent results — or, once the season is complete,
    the season summary (champion, final standings, leaders). Actions emit a
    :class:`HubChoice` to ``on_choice``; **l**eaders is handled locally.

    Args:
        controller: the season being played; the source of all rendered state.
        on_choice: owner callback invoked with a :class:`HubChoice` value when
            the user picks an action (the seam Parts 7-8 fill).
    """

    BINDINGS = [
        Binding("p", "play_my_game", "Play"),
        Binding("s", "sim_my_game", "Sim game"),
        Binding("d", "sim_day", "Sim day"),
        Binding("a", "sim_ahead", "Sim ahead"),
        Binding("l", "leaders", "Leaders"),
        Binding("t", "team_stats", "Team stats"),
        Binding("ctrl+s", "save", "Save"),
        Binding("n", "new_season", "New season"),
        Binding("m", "main_menu", "Main menu"),
        Binding("q", "quit_to_menu", "Quit"),
    ]

    def __init__(
        self,
        controller: "SeasonController",
        on_choice: Callable[[str], None],
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._controller = controller
        self._on_choice = on_choice

    # --- Action gating ------------------------------------------------------

    def check_action(
        self, action: str, parameters: tuple
    ) -> Optional[bool]:
        """Hide actions that don't apply to the current season state.

        Play / sim-my-game vanish in a watch-only (no user team) season and
        once the season is over; the day-sim / sim-ahead / save actions vanish
        at season end; new-season / main-menu appear only at season end. Leaders
        and quit are always available. Returning ``None`` hides *and* disables
        the binding (Textual convention), so the footer stays truthful.
        """
        complete = self._controller.is_complete
        watch_only = self._controller.state.user_team_key is None
        if action in ("play_my_game", "sim_my_game"):
            return None if (watch_only or complete) else True
        if action in ("sim_day", "sim_ahead", "save"):
            return None if complete else True
        if action in ("new_season", "main_menu"):
            return True if complete else None
        return True

    # --- Compose ------------------------------------------------------------

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="hub-container"):
            if self._controller.is_complete:
                yield from self._compose_summary()
            else:
                yield from self._compose_active()
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#hub-container", VerticalScroll).focus()

    def _compose_active(self) -> ComposeResult:
        yield Static(self._day_header(), id="hub-day-header")
        yield Static("STANDINGS", classes="hub-header")
        yield Static(self._build_standings_table(), classes="hub-section")
        yield Static("TODAY", classes="hub-header")
        yield Static(self._build_matchups(), classes="hub-section")
        yield Static("RECENT", classes="hub-header")
        yield Static(self._build_recent_results(), classes="hub-section")

    def _compose_summary(self) -> ComposeResult:
        yield Static("═══════════  ⚾ SEASON COMPLETE  ═══════════", id="hub-day-header")
        yield Static(self._champion_line(), id="hub-champion")
        yield Static("FINAL STANDINGS", classes="hub-header")
        yield Static(self._build_standings_table(), classes="hub-section")
        yield Static("LEADERS", classes="hub-header")
        yield Static(self._build_summary_leaders(), classes="hub-section")

    # --- Rendering helpers (pure over the controller) -----------------------

    def _team_name(self, key: str) -> str:
        """The display name for a team key, falling back to the key itself."""
        for team in self._controller.state.teams:
            if team.key == key:
                return team.display_name
        return key

    def _day_header(self) -> str:
        """``Day 12 of 42`` — the current day (1-indexed) of the season."""
        total_days = len(self._controller.state.schedule)
        return f"Day {self._controller.current_day + 1} of {total_days}"

    def _champion_line(self) -> str:
        """The champion banner for the summary (``None`` guard for empty leagues)."""
        champion = self._controller.champion
        if champion is None:
            return "No champion"
        return f"[bold #d4a843]🏆 {self._team_name(champion)} — League Champions[/]"

    def _build_standings_table(self) -> str:
        """Standings in order, user's team marked with a caret + bold row."""
        user_key = self._controller.state.user_team_key
        header = (
            f"   {_fit('Team', _TEAM_COL_WIDTH)} {'W':>3} {'L':>3} {'Pct':>5} "
            f"{'GB':>5} {'RS':>4} {'RA':>4}"
        )
        lines = [f"[#6b7d6b]{header}[/]"]
        rows: List["StandingsRow"] = self._controller.state.standings
        for row in rows:
            is_user = row.key == user_key
            marker = "►" if is_user else " "
            body = (
                f" {marker} {_fit(self._team_name(row.key), _TEAM_COL_WIDTH)} "
                f"{row.wins:>3} {row.losses:>3} {_format_pct(row.pct):>5} "
                f"{_format_gb(row.games_behind):>5} "
                f"{row.runs_scored:>4} {row.runs_allowed:>4}"
            )
            lines.append(f"[bold]{body}[/]" if is_user else body)
        return "\n".join(lines)

    def _build_matchups(self) -> str:
        """Today's slate, ``away @ home``, the user's game marked."""
        user_key = self._controller.state.user_team_key
        games = self._controller.games_for_day(self._controller.current_day)
        if not games:
            return "[#6b7d6b]No games scheduled[/]"
        lines = []
        for game in games:
            line = f"{self._team_name(game.away_key)} @ {self._team_name(game.home_key)}"
            if user_key is not None and user_key in (game.home_key, game.away_key):
                line = f"[bold]{line}[/]  [#d4a843]← your game[/]"
            lines.append(line)
        return "\n".join(lines)

    def _build_recent_results(self) -> str:
        """The last few finished games, newest first, with the final score."""
        results = self._controller.state.results
        if not results:
            return "[#6b7d6b]No games played yet[/]"
        lines = []
        for record in reversed(results[-_RECENT_LIMIT:]):
            lines.append(
                f"{self._team_name(record.away_key)} {record.away_score}, "
                f"{self._team_name(record.home_key)} {record.home_score}"
            )
        return "\n".join(lines)

    def _build_summary_leaders(self) -> str:
        """A compact leaders block for the season summary (all seven boards)."""
        tables = [
            _build_leader_table(self._controller, title, method, fmt)
            for title, method, fmt in (*_BATTING_LEADERS, *_PITCHING_LEADERS)
        ]
        return "\n\n".join(tables)

    # --- Actions ------------------------------------------------------------

    def _emit(self, choice: str) -> None:
        """Surface a chosen action to the owner callback."""
        self._on_choice(choice)

    def action_play_my_game(self) -> None:
        self._emit(HubChoice.PLAY)

    def action_sim_my_game(self) -> None:
        self._emit(HubChoice.SIM_MY_GAME)

    def action_sim_day(self) -> None:
        self._emit(HubChoice.SIM_DAY)

    def action_sim_ahead(self) -> None:
        self._emit(HubChoice.SIM_AHEAD)

    def action_save(self) -> None:
        self._emit(HubChoice.SAVE)

    def action_new_season(self) -> None:
        self._emit(HubChoice.NEW_SEASON)

    def action_main_menu(self) -> None:
        self._emit(HubChoice.MAIN_MENU)

    def action_quit_to_menu(self) -> None:
        self._emit(HubChoice.QUIT)

    def action_leaders(self) -> None:
        """Show the league leaders subscreen (owned by the hub, not the app)."""
        self.app.push_screen(LeagueLeadersScreen(self._controller))

    def action_team_stats(self) -> None:
        """Show the per-team stat page (owned by the hub, like leaders).

        Opens on the user's team when there is one, else the standings leader
        (a watch-only season has no user team), falling back to the first league
        team. Imported lazily to avoid a module-load cycle: ``TeamStatsScreen``
        imports the shared render helpers from this module.
        """
        from src.tui.screens.team_stats_screen import TeamStatsScreen

        state = self._controller.state
        if state.user_team_key is not None:
            initial_key = state.user_team_key
        elif state.standings:
            initial_key = state.standings[0].key
        else:
            initial_key = state.teams[0].key
        self.app.push_screen(TeamStatsScreen(self._controller, initial_key))
