"""Full-screen end-of-game box score with newspaper-format display.

Shows linescore (inning-by-inning R/H/E), batting stats (AB/R/H/RBI/BB/K),
and pitching stats (IP/H/R/ER/BB/K) with Replay/New Game/Quit navigation.
"""

from typing import Dict, List, Optional, Tuple

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Static


def _format_ip(outs: int) -> str:
    """Format outs as innings pitched (e.g., 19 outs -> '6.1')."""
    return f"{outs // 3}.{outs % 3}"


class BoxScoreScreen(Screen):
    """Full-screen box score displayed at game's end.

    Shows newspaper-format linescore, batting tables for both teams,
    and pitching summary. Dismisses with "replay", "new", or "quit".
    """

    CSS = """
    BoxScoreScreen {
        layout: vertical;
        background: #0d1f0d;
        color: #fffdd0;
    }

    #box-score-container {
        width: 100%;
        /* 1fr (not auto) gives the scroll container a bounded viewport so it
           can actually scroll its overflowing content with the keyboard. */
        height: 1fr;
        padding: 1 2;
    }

    .box-header {
        text-align: center;
        width: 100%;
        color: #ffd700;
        text-style: bold;
        margin: 1 0;
    }

    .box-section {
        width: 100%;
        margin: 0 0 1 0;
        padding: 0 1;
    }

    #box-score-container:focus {
        /* No focus border — the screen reads as a document, not a control. */
        border: none;
    }
    """

    BINDINGS = [
        # priority so these fire (and the hint shows in the footer) instead of
        # being shadowed by the focused scroll container's own hidden bindings.
        Binding("up", "scroll_up", "Scroll", show=True, priority=True),
        Binding("down", "scroll_down", "Scroll", show=False, priority=True),
        Binding("pageup", "page_up", "Page Up", show=False, priority=True),
        Binding("pagedown", "page_down", "Page Down", show=False, priority=True),
        Binding("home", "scroll_top", "Top", show=False, priority=True),
        Binding("end", "scroll_bottom", "Bottom", show=False, priority=True),
        Binding("r", "replay", "Replay"),
        Binding("n", "new_game", "New Game"),
        Binding("q", "quit_game", "Quit"),
    ]

    def __init__(
        self,
        away_team_name: str,
        home_team_name: str,
        away_score: int,
        home_score: int,
        away_hits: int,
        home_hits: int,
        away_errors: int,
        home_errors: int,
        inning_scores: List[Tuple[int, int]],
        away_batting: List[Tuple[str, Dict[str, int]]],
        home_batting: List[Tuple[str, Dict[str, int]]],
        away_pitching: list,
        home_pitching: list,
        winner: str,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._away_name = away_team_name
        self._home_name = home_team_name
        self._away_score = away_score
        self._home_score = home_score
        self._away_hits = away_hits
        self._home_hits = home_hits
        self._away_errors = away_errors
        self._home_errors = home_errors
        self._inning_scores = inning_scores
        self._away_batting = away_batting
        self._home_batting = home_batting
        self._away_pitching = away_pitching
        self._home_pitching = home_pitching
        self._winner = winner

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="box-score-container"):
            yield Static("[bold]═══════════════ FINAL ═══════════════[/bold]", classes="box-header")
            yield Static(self._build_linescore(), classes="box-section")
            yield Static(f"[bold]── {self._away_name} Batting ──[/bold]", classes="box-header")
            yield Static(self._build_batting_table(self._away_batting), classes="box-section")
            yield Static(f"[bold]── {self._home_name} Batting ──[/bold]", classes="box-header")
            yield Static(self._build_batting_table(self._home_batting), classes="box-section")
            yield Static("[bold]── Pitching ──[/bold]", classes="box-header")
            yield Static(self._build_pitching_table(), classes="box-section")
        yield Footer()

    def on_mount(self) -> None:
        """Focus the scroll container so arrow/page keys scroll the box score."""
        self.query_one("#box-score-container", VerticalScroll).focus()

    def _build_linescore(self) -> str:
        """Build newspaper-format linescore."""
        num_innings = max(len(self._inning_scores), 9)

        # Pad the team-name column to the longest name (floor 13) so the inning
        # columns line up under the header for any name length — a fixed width
        # let long names like "New York Yankees" overflow and skew the columns.
        name_w = max(len(self._away_name), len(self._home_name), 13)

        def _row(name: str, side: int, runs: int, hits: int, errs: int) -> str:
            row = f"{name:<{name_w}}"
            for i in range(num_innings):
                if i < len(self._inning_scores):
                    row += f"{self._inning_scores[i][side]:>4}"
                else:
                    row += "   -"
            row += f"    {runs:>2}  {hits:>2}  {errs:>2}"
            return row

        header = " " * name_w
        for i in range(1, num_innings + 1):
            header += f"{i:>4}"
        header += "     R   H   E"

        away_row = _row(self._away_name, 0, self._away_score, self._away_hits, self._away_errors)
        home_row = _row(self._home_name, 1, self._home_score, self._home_hits, self._home_errors)

        return f"{header}\n{away_row}\n{home_row}"

    def _build_batting_table(self, batting: List[Tuple[str, Dict[str, int]]]) -> str:
        """Build batting stats table."""
        header = f"{'Player':<18} {'AB':>3} {'R':>3} {'H':>3} {'RBI':>4} {'BB':>3} {'K':>3}"
        lines = [header]

        totals = {"AB": 0, "R": 0, "H": 0, "RBI": 0, "BB": 0, "K": 0}
        for name, stats in batting:
            line = f"{name:<18} {stats['AB']:>3} {stats['R']:>3} {stats['H']:>3} {stats['RBI']:>4} {stats['BB']:>3} {stats['K']:>3}"
            lines.append(line)
            for k in totals:
                totals[k] += stats[k]

        lines.append(f"{'TOTALS':<18} {totals['AB']:>3} {totals['R']:>3} {totals['H']:>3} {totals['RBI']:>4} {totals['BB']:>3} {totals['K']:>3}")
        return "\n".join(lines)

    def _build_pitching_table(self) -> str:
        """Build pitching stats table for both teams with team headers."""
        header = f"{'Pitcher':<18} {'IP':>5} {'H':>3} {'R':>3} {'ER':>3} {'BB':>3} {'K':>3}"
        lines = []

        for pitching_list, team_name in [(self._away_pitching, self._away_name), (self._home_pitching, self._home_name)]:
            lines.append(f"  {team_name}")
            lines.append(header)
            for entry in pitching_list:
                name, stats, is_winner = entry
                marker = " (W)" if is_winner else " (L)"
                ip = _format_ip(stats["outs"])
                line = f"{name + marker:<18} {ip:>5} {stats['H']:>3} {stats['R']:>3} {stats['ER']:>3} {stats['BB']:>3} {stats['K']:>3}"
                lines.append(line)
            lines.append("")

        return "\n".join(lines)

    def _container(self) -> VerticalScroll:
        return self.query_one("#box-score-container", VerticalScroll)

    def action_scroll_up(self) -> None:
        self._container().scroll_up()

    def action_scroll_down(self) -> None:
        self._container().scroll_down()

    def action_page_up(self) -> None:
        self._container().scroll_page_up()

    def action_page_down(self) -> None:
        self._container().scroll_page_down()

    def action_scroll_top(self) -> None:
        self._container().scroll_home()

    def action_scroll_bottom(self) -> None:
        self._container().scroll_end()

    def action_replay(self) -> None:
        self.dismiss("replay")

    def action_new_game(self) -> None:
        self.dismiss("new")

    def action_quit_game(self) -> None:
        self.dismiss("quit")
