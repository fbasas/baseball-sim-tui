"""Per-team season stat page: one club's batting + pitching lines.

The league leaderboards (``LeagueLeadersScreen``) answer "who is best in the
league?"; this screen answers "how is *this* team hitting and pitching?" — the
season-to-date batting and pitching stat lines for every player on one club,
resolved to names and laid out in aligned columns. It is pure rendering over
the controller's :class:`~src.season.stats.SeasonStats`, exactly the data the
hub already accumulates and the leaderboards already read; it collects no new
stats and touches neither accumulation nor persistence.

The hub pushes it for the **t** action (initial team = the user's club, else the
standings leader). One team shows at a time; ``←``/``→`` step through all league
teams in standings order (wrapping) and ``esc``/``q`` pop back — mirroring
``LeagueLeadersScreen``'s ``escape``/``q`` = Back idiom.

Player ids are never shown raw: the shared ``_resolve_name`` /column-formatting
helpers are imported from :mod:`season_hub_screen` (do not re-implement) so this
screen renders ``"F. Last"`` and aligned columns identically to the hub.
"""

from typing import TYPE_CHECKING, List, Optional

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Static

from src.tui.screens.season_hub_screen import (
    _fit,
    _format_avg,
    _format_era,
    _format_int,
    _format_ip,
    _format_pct,
    _resolve_name,
)

if TYPE_CHECKING:  # Import for typing only; keeps the module import-light.
    from src.season.controller import SeasonController
    from src.season.state import StandingsRow


# Fixed display width of the leading name column (``F. Last`` fits comfortably;
# an overlong name is truncated by ``_fit`` so every numeric column stays put).
_NAME_COL_WIDTH = 18
# Every numeric column is this wide, right-aligned, so headers and values line
# up under one another (mirrors ``_build_standings_table``'s alignment).
_NUM_COL_WIDTH = 5

# Column headers, left-to-right, for each table (the name column is separate).
_BATTING_COLS = ("AVG", "AB", "R", "H", "2B", "3B", "HR", "RBI", "BB", "K")
_PITCHING_COLS = ("ERA", "IP", "H", "R", "ER", "BB", "K")

# The dim style the hub uses for placeholders ("No games played yet", etc.).
_DIM = "#6b7d6b"


def _header_line(label: str, cols: tuple) -> str:
    """A dim column-header row: ``label`` in the name cell, ``cols`` right-aligned."""
    cells = "".join(f"{col:>{_NUM_COL_WIDTH}}" for col in cols)
    return f"[{_DIM}]{label.ljust(_NAME_COL_WIDTH)}{cells}[/]"


def _stat_line(name: str, cells: List[str], *, bold: bool = False) -> str:
    """One data row: fixed-width name cell + right-aligned numeric cells."""
    body = _fit(name, _NAME_COL_WIDTH) + "".join(
        f"{cell:>{_NUM_COL_WIDTH}}" for cell in cells
    )
    return f"[bold]{body}[/]" if bold else body


class TeamStatsScreen(Screen):
    """One league team's season batting + pitching lines, cyclable by ``←``/``→``.

    Full-screen and pure-rendering, like :class:`LeagueLeadersScreen`. Holds the
    standings-order key list and an index (initialized to ``initial_key``); every
    render reads the *current* key, so stepping the index re-renders in place.

    Args:
        controller: the season being viewed — source of stats, rosters, standings.
        initial_key: the team to show first (its standings position seeds the
            index; a key not in the standings falls back to the first team).
    """

    BINDINGS = [
        Binding("left", "prev_team", "Prev team"),
        Binding("right", "next_team", "Next team"),
        Binding("[", "prev_team", "Prev team", show=False),
        Binding("]", "next_team", "Next team", show=False),
        Binding("escape", "close", "Back", priority=True),
        Binding("q", "close", "Back", show=False),
    ]

    def __init__(
        self, controller: "SeasonController", initial_key: str, **kwargs
    ) -> None:
        super().__init__(**kwargs)
        self._controller = controller
        self._keys: List[str] = [row.key for row in controller.state.standings]
        try:
            self._index = self._keys.index(initial_key)
        except ValueError:
            self._index = 0

    # --- Compose ------------------------------------------------------------

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="team-stats-container"):
            yield Static("⚾ TEAM STATS", id="team-stats-title")
            yield Static("", id="team-stats-team")
            yield Static("BATTING", id="team-stats-batting-header", classes="hub-header")
            yield Static("", id="team-stats-batting", classes="hub-section")
            yield Static("PITCHING", id="team-stats-pitching-header", classes="hub-header")
            yield Static("", id="team-stats-pitching", classes="hub-section")
            yield Static(f"[{_DIM}]No stats yet[/]", id="team-stats-empty", classes="hub-section")
        yield Footer()

    def on_mount(self) -> None:
        self._render_current()
        self.query_one("#team-stats-container", VerticalScroll).focus()

    def _render_current(self) -> None:
        """Push the current team's header + tables into the mounted widgets.

        Empty teams (no games yet) show a single ``No stats yet`` placeholder in
        place of the tables — the two paths are toggled with ``display`` rather
        than by re-mounting, so cycling teams is a plain content update.
        """
        self.query_one("#team-stats-team", Static).update(self._team_header())
        empty = self._is_empty()
        for wid in (
            "#team-stats-batting-header",
            "#team-stats-batting",
            "#team-stats-pitching-header",
            "#team-stats-pitching",
        ):
            self.query_one(wid, Static).display = not empty
        self.query_one("#team-stats-empty", Static).display = empty
        if not empty:
            self.query_one("#team-stats-batting", Static).update(
                self._build_batting_table()
            )
            self.query_one("#team-stats-pitching", Static).update(
                self._build_pitching_table()
            )

    # --- Current-team lookups (pure over the controller) --------------------

    def _current_key(self) -> str:
        return self._keys[self._index]

    def _team_name(self, key: str) -> str:
        """Display name for a team key, falling back to the key itself."""
        for team in self._controller.state.teams:
            if team.key == key:
                return team.display_name
        return key

    def _standings_row(self, key: str) -> Optional["StandingsRow"]:
        """This team's standings row, or ``None`` before it has one."""
        for row in self._controller.state.standings:
            if row.key == key:
                return row
        return None

    def _is_empty(self) -> bool:
        """True when the current team has no accumulated batting or pitching."""
        key = self._current_key()
        return not self._controller.stats.team_batting(key) and not (
            self._controller.stats.team_pitching(key)
        )

    # --- Rendering ----------------------------------------------------------

    def _team_header(self) -> str:
        """``1927 Yankees   (12-3, .800)`` — name + record from the standings."""
        key = self._current_key()
        name = self._team_name(key)
        row = self._standings_row(key)
        if row is None:
            return f"[bold #d4a843]{name}[/]"
        record = f"({row.wins}-{row.losses}, {_format_pct(row.pct)})"
        return f"[bold #d4a843]{name}   {record}[/]"

    def _build_batting_table(self) -> str:
        """Batting lines, one row per player, sorted AB-desc then AVG-desc then name.

        AVG is ``H/AB`` (``—`` at 0 AB); the rest are counting integers. A bold
        ``TEAM`` totals row (Σ each column, AVG = ΣH/ΣAB) closes the table.
        """
        key = self._current_key()
        lines = self._controller.stats.team_batting(key)
        entries = []
        for pid, line in lines.items():
            ab = line.get("AB", 0)
            avg = line.get("H", 0) / ab if ab else 0.0
            name = _resolve_name(self._controller, key, pid)
            entries.append((pid, name, line, ab, avg))
        # AB desc, then AVG desc, then name, then pid — fully deterministic.
        entries.sort(key=lambda e: (-e[3], -e[4], e[1], e[0]))

        rows = [_header_line("Player", _BATTING_COLS)]
        totals = {k: 0 for k in ("AB", "R", "H", "2B", "3B", "HR", "RBI", "BB", "K")}
        for _pid, name, line, ab, avg in entries:
            rows.append(_stat_line(name, self._batting_cells(line, ab, avg)))
            for k in totals:
                totals[k] += line.get(k, 0)
        team_avg = totals["H"] / totals["AB"] if totals["AB"] else 0.0
        rows.append(
            _stat_line("TEAM", self._batting_cells(totals, totals["AB"], team_avg), bold=True)
        )
        return "\n".join(rows)

    @staticmethod
    def _batting_cells(line: dict, ab: int, avg: float) -> List[str]:
        """The ten batting cells (AVG + counting stats) for one line."""
        return [
            _format_avg(avg) if ab else "—",
            _format_int(line.get("AB", 0)),
            _format_int(line.get("R", 0)),
            _format_int(line.get("H", 0)),
            _format_int(line.get("2B", 0)),
            _format_int(line.get("3B", 0)),
            _format_int(line.get("HR", 0)),
            _format_int(line.get("RBI", 0)),
            _format_int(line.get("BB", 0)),
            _format_int(line.get("K", 0)),
        ]

    def _build_pitching_table(self) -> str:
        """Pitching lines, one per pitcher, sorted IP-desc then ERA-asc then name.

        ERA is ``ER/(outs/3)*9`` and IP the standard ``.0/.1/.2`` thirds (both
        ``—`` at 0 outs); the rest are integers. A bold ``TEAM`` totals row closes
        the table.
        """
        key = self._current_key()
        lines = self._controller.stats.team_pitching(key)
        entries = []
        for pid, line in lines.items():
            outs = line.get("outs", 0)
            era = line.get("ER", 0) / (outs / 3) * 9 if outs else float("inf")
            name = _resolve_name(self._controller, key, pid)
            entries.append((pid, name, line, outs, era))
        # outs (IP) desc, then ERA asc, then name, then pid — deterministic.
        entries.sort(key=lambda e: (-e[3], e[4], e[1], e[0]))

        rows = [_header_line("Pitcher", _PITCHING_COLS)]
        totals = {k: 0 for k in ("outs", "H", "R", "ER", "BB", "K")}
        for _pid, name, line, outs, _era in entries:
            rows.append(_stat_line(name, self._pitching_cells(line, outs)))
            for k in totals:
                totals[k] += line.get(k, 0)
        rows.append(
            _stat_line("TEAM", self._pitching_cells(totals, totals["outs"]), bold=True)
        )
        return "\n".join(rows)

    @staticmethod
    def _pitching_cells(line: dict, outs: int) -> List[str]:
        """The seven pitching cells (ERA, IP + counting stats) for one line."""
        era = line.get("ER", 0) / (outs / 3) * 9 if outs else 0.0
        return [
            _format_era(era) if outs else "—",
            _format_ip(outs / 3) if outs else "—",
            _format_int(line.get("H", 0)),
            _format_int(line.get("R", 0)),
            _format_int(line.get("ER", 0)),
            _format_int(line.get("BB", 0)),
            _format_int(line.get("K", 0)),
        ]

    # --- Actions ------------------------------------------------------------

    def _step(self, delta: int) -> None:
        """Advance the team index by ``delta`` (wrapping) and re-render."""
        if not self._keys:
            return
        self._index = (self._index + delta) % len(self._keys)
        self._render_current()

    def action_prev_team(self) -> None:
        self._step(-1)

    def action_next_team(self) -> None:
        self._step(1)

    def action_close(self) -> None:
        self.app.pop_screen()
