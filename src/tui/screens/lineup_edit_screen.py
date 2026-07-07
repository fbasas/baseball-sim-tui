"""Pregame lineup review/edit modal.

``LineupEditScreen`` lets a human manager review the auto-generated lineup and,
before the game starts, reorder the batting order, reassign defensive positions,
and swap in a bench player. It is a keyboard-first modal styled to match
``PitcherSelectScreen`` / ``SubstitutionMenu`` (gold/green theme, in-dialog hint
line, no buttons).

The screen edits a **scratch copy** of the auto lineup via the pure operations in
``src/game/lineup_edit.py`` — it never mutates the passed-in ``team.lineup``. On
confirm it dismisses with a :class:`~src.game.lineup_edit.LineupPlan` snapshot of
the edited lineup; on cancel it dismisses with ``None`` (meaning "use the auto
lineup unchanged"). Applying the plan to a team is the caller's job (FRE-42), so a
cancel truly discards every edit.

Testability: as with ``tests/test_game_screen_substitutions.py``, the edit logic
lives in plain methods that mutate the scratch ``Lineup`` and can be called on a
screen instance without a running Textual ``App`` (no pilot). The Textual action
handlers are thin wrappers that call an edit method and then refresh the display.
"""

from typing import List, Optional, Tuple, Union

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList, Static
from textual.widgets.option_list import Option

from src.data.models import BattingStats
from src.game.lineup_edit import (
    LineupPlan,
    lineup_to_plan,
    substitute_slot,
    swap_batting_slots,
    swap_positions,
)
from src.game.positions import Position
from src.game.team import Lineup, LineupSlot, Team

# Column widths for the batting-order rows / header, kept in one place so the
# header label and the data rows stay aligned.
_ORDER_W = 2
_NAME_W = 20
_POS_W = 4
_SLASH_W = 17


def _clone_lineup(lineup: Lineup) -> Lineup:
    """Return a deep-enough copy of ``lineup`` for scratch editing.

    Fresh ``LineupSlot`` objects and a fresh slot list are created so the edit
    operations (which mutate ``slots`` in place) never touch the original.
    ``batting_stats`` and ``position`` are immutable/shared safely — positions
    are ``Position`` enum members or the ``DesignatedHitter`` sentinel class, and
    batting stats are never mutated.
    """
    return Lineup(
        slots=[
            LineupSlot(
                player_id=slot.player_id,
                position=slot.position,
                batting_stats=slot.batting_stats,
            )
            for slot in lineup.slots
        ],
        starting_pitcher_id=lineup.starting_pitcher_id,
    )


def _slash_line(stats: BattingStats) -> str:
    """Format a season slash line ``AVG/OBP/SLG`` (matches the game screen)."""
    if stats.at_bats <= 0:
        return ".---/.---/.---"
    avg = stats.hits / stats.at_bats
    denom_obp = stats.at_bats + stats.walks
    obp = (stats.hits + stats.walks) / denom_obp if denom_obp > 0 else 0.0
    slg = (
        stats.singles
        + 2 * stats.doubles
        + 3 * stats.triples
        + 4 * stats.home_runs
    ) / stats.at_bats
    return f"{avg:.3f}/{obp:.3f}/{slg:.3f}"


class LineupEditScreen(ModalScreen[Optional[LineupPlan]]):
    """Modal for reviewing and editing the pregame lineup.

    Returns a :class:`LineupPlan` reflecting the edits on confirm (``Enter``), or
    ``None`` on cancel (``Esc``) meaning "use the auto lineup unchanged".

    Args:
        team: The team whose lineup is being edited (roster + batting stats).
        lineup: The freshly built auto ``Lineup`` (from ``build_lineup``). It is
            snapshotted; this screen never mutates it.
        repo: The Lahman repository. Accepted for interface parity with the other
            pregame modals / the wiring in FRE-42; bench players and stats are
            read from ``team`` so it is not otherwise required here.
        role: "Away" or "Home" — shown in the panel title for context.
    """

    CSS = """
    LineupEditScreen {
        align: center middle;
        background: #0d160d 40%;
    }

    #lineup-edit-container {
        width: 66;
        height: auto;
        max-height: 90%;
        background: #121f12;
        color: #f2ecd8;
        border: round #d4a843;
        border-title-color: #d4a843;
        border-title-style: bold;
        padding: 1 2;
    }

    #lineup-edit-title {
        text-align: center;
        width: 100%;
        height: 1;
        color: #d4a843;
    }

    #lineup-col-header {
        width: 100%;
        height: 1;
        margin: 1 0 0 0;
        color: #6b7d6b;
    }

    #lineup-rows {
        width: 100%;
        height: auto;
        margin: 0 0 0 0;
    }

    #lineup-edit-status {
        width: 100%;
        height: 1;
        margin: 1 0 0 0;
        color: #d4a843;
    }

    #bench-label {
        color: #d4a843;
        text-style: bold;
        margin: 1 0 0 0;
    }

    #bench-list {
        display: none;
        height: 8;
        width: 100%;
        border: round #3e5c40;
        margin: 0 0 0 0;
        background: #0d160d;
        scrollbar-color: #3e5c40;
        scrollbar-background: #0d160d;
        scrollbar-size-vertical: 1;
    }

    #lineup-edit-hint {
        text-align: center;
        width: 100%;
        height: auto;
        margin: 1 0 0 0;
        color: #6b7d6b;
    }
    """

    _HINT = (
        "[#d4a843]↑/↓[/] select   [#d4a843],/.[/] reorder   "
        "[#d4a843]p[/] swap pos   [#d4a843]s[/] sub\n"
        "[#d4a843]r[/] reset   [#d4a843]Enter[/] confirm   [#d4a843]Esc[/] cancel"
    )

    _BENCH_HINT = (
        "[#d4a843]↑/↓[/] navigate   [#d4a843]Enter[/] substitute   "
        "[#d4a843]Esc[/] cancel sub"
    )

    BINDINGS = [
        Binding("up", "cursor_up", "Up"),
        Binding("down", "cursor_down", "Down"),
        Binding("shift+up", "move_up", "Move Up"),
        Binding("shift+down", "move_down", "Move Down"),
        Binding("comma", "move_up", "Move Up"),
        Binding("full_stop", "move_down", "Move Down"),
        Binding("p", "mark_position", "Swap Position"),
        Binding("s", "open_bench", "Substitute"),
        Binding("r", "reset", "Reset"),
        # priority so Enter confirms the lineup rather than being swallowed by a
        # focused child; when the bench list is open we route it to the sub pick.
        Binding("enter", "confirm", "Confirm", priority=True),
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(
        self,
        team: Team,
        lineup: Lineup,
        repo,
        role: str = "",
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._team = team
        self._repo = repo
        self._role = role
        # Pristine snapshot of the auto lineup for reset-to-auto, plus the
        # working scratch copy every edit operates on. Neither is team.lineup.
        self._auto_lineup = _clone_lineup(lineup)
        self._scratch = _clone_lineup(lineup)
        self._selected = 0
        # Index of a slot marked for a two-step position swap, or None.
        self._pending_pos_mark: Optional[int] = None
        # Whether the bench substitution list is currently open.
        self._bench_open = False

    # ------------------------------------------------------------------
    # Pure edit logic — mutates the scratch Lineup only. Callable without a
    # running Textual App (mirrors tests/test_game_screen_substitutions.py).
    # ------------------------------------------------------------------

    def move_selection(self, delta: int) -> None:
        """Move the selected batting slot by ``delta`` (clamped to 0-8)."""
        self._selected = max(0, min(8, self._selected + delta))

    def move_batter_up(self) -> None:
        """Move the selected batter one slot earlier in the order (reorder).

        The whole slot moves (the batter keeps their position); the selection
        follows the batter. A no-op at the top of the order.
        """
        i = self._selected
        if i > 0:
            swap_batting_slots(self._scratch, i, i - 1)
            self._selected = i - 1

    def move_batter_down(self) -> None:
        """Move the selected batter one slot later in the order (reorder).

        A no-op at the bottom of the order.
        """
        i = self._selected
        if i < len(self._scratch.slots) - 1:
            swap_batting_slots(self._scratch, i, i + 1)
            self._selected = i + 1

    def mark_or_swap_position(self) -> None:
        """Two-step position swap.

        First press marks the selected slot; the second press swaps the marked
        slot's defensive position with the currently selected slot's (always
        legal, including when one is the DH) and clears the mark. Pressing on the
        already-marked slot is a legal no-op swap that just clears the mark.
        """
        if self._pending_pos_mark is None:
            self._pending_pos_mark = self._selected
        else:
            swap_positions(self._scratch, self._pending_pos_mark, self._selected)
            self._pending_pos_mark = None

    def clear_position_mark(self) -> None:
        """Clear any pending position-swap mark."""
        self._pending_pos_mark = None

    def substitute(self, new_player_id: str) -> None:
        """Substitute the selected slot for a bench player (delegates to the
        hardened op, which enforces stats / duplicate / pitcher guards).

        Raises:
            ValueError: If ``new_player_id`` is ineligible (no batting stats,
                already in the lineup, or the starting pitcher). The scratch
                lineup is left unchanged.
        """
        substitute_slot(self._team, self._scratch, self._selected, new_player_id)

    def reset_to_auto(self) -> None:
        """Discard all edits, restoring the auto lineup (``build_lineup``).

        The scratch copy is rebuilt from the pristine snapshot of the auto
        lineup captured at construction, and selection/mark state is reset.
        """
        self._scratch = _clone_lineup(self._auto_lineup)
        self._selected = 0
        self._pending_pos_mark = None

    def bench_candidates(self) -> List[Tuple[str, str, str]]:
        """Return ``(player_id, name, slash_line)`` for eligible bench batters.

        Eligible = has batting stats, not already in the scratch lineup, and not
        the starting pitcher. Sorted by at-bats descending (regulars first).
        """
        in_lineup = {slot.player_id for slot in self._scratch.slots}
        pitcher_id = self._scratch.starting_pitcher_id
        rows: List[Tuple[str, str, str, int]] = []
        for pid, stats in self._team.batting_stats.items():
            if pid in in_lineup or pid == pitcher_id:
                continue
            rows.append((pid, self._player_name(pid), _slash_line(stats), stats.at_bats))
        rows.sort(key=lambda r: r[3], reverse=True)
        return [(pid, name, slash) for pid, name, slash, _ in rows]

    def current_plan(self) -> LineupPlan:
        """Snapshot the edited scratch lineup as a :class:`LineupPlan`."""
        return lineup_to_plan(self._scratch)

    # ------------------------------------------------------------------
    # Display helpers
    # ------------------------------------------------------------------

    def _player_name(self, player_id: str) -> str:
        """Short display name (``F. Last``), falling back to the id."""
        player = self._team.get_player(player_id)
        if player:
            return f"{player.name_first[0]}. {player.name_last}"
        return player_id

    @staticmethod
    def _position_abbrev(position: Union[Position, type]) -> str:
        return position.abbreviation

    def _column_header(self) -> str:
        return (
            f"{'#':<{_ORDER_W}}{'Batter':<{_NAME_W}}"
            f"{'Pos':<{_POS_W}}{'AVG/OBP/SLG':<{_SLASH_W}}"
        )

    def _row_text(self, index: int, slot: LineupSlot) -> str:
        """Rich-markup text for one batting-order row."""
        order = f"{index + 1:<{_ORDER_W}}"
        name = f"{self._player_name(slot.player_id):<{_NAME_W}}"
        pos = f"{self._position_abbrev(slot.position):<{_POS_W}}"
        slash = f"{_slash_line(slot.batting_stats):<{_SLASH_W}}"
        body = f"{order}{name}{pos}{slash}"
        if index == self._pending_pos_mark:
            # Marked for a position swap.
            body = f"[#d4a843]‣ {body}[/]"
        else:
            body = f"  {body}"
        if index == self._selected:
            # Selected row: gold background bar.
            return f"[on #d4a843][#1a2b1a]{body}[/][/]"
        return body

    def _rows_markup(self) -> str:
        return "\n".join(
            self._row_text(i, slot) for i, slot in enumerate(self._scratch.slots)
        )

    def _status_text(self) -> str:
        if self._pending_pos_mark is not None:
            marked = self._scratch.slots[self._pending_pos_mark]
            return (
                f"Position swap: marked #{self._pending_pos_mark + 1} "
                f"{self._player_name(marked.player_id)} — press [b]p[/b] on "
                "another slot ([b]Esc[/b] to clear)"
            )
        return ""

    # ------------------------------------------------------------------
    # Textual composition / lifecycle
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Container(id="lineup-edit-container"):
            yield Label(f"[bold]{self._team.info.team_name}[/bold]", id="lineup-edit-title")
            yield Label(self._column_header(), id="lineup-col-header")
            yield Static(self._rows_markup(), id="lineup-rows")
            yield Static(self._status_text(), id="lineup-edit-status")
            yield Label("BENCH", id="bench-label")
            yield OptionList(id="bench-list")
            yield Label(self._HINT, id="lineup-edit-hint")

    def on_mount(self) -> None:
        container = self.query_one("#lineup-edit-container", Container)
        role = f" · {self._role.upper()}" if self._role else ""
        container.border_title = f"⚾ EDIT LINEUP{role}"
        # Bench label is hidden until substituting.
        self.query_one("#bench-label", Label).display = False

    def _refresh(self) -> None:
        """Re-render the batting rows and status line from scratch state."""
        self.query_one("#lineup-rows", Static).update(self._rows_markup())
        self.query_one("#lineup-edit-status", Static).update(self._status_text())

    # ------------------------------------------------------------------
    # Bench (substitution) UI
    # ------------------------------------------------------------------

    def _open_bench(self) -> None:
        bench = self.query_one("#bench-list", OptionList)
        bench.clear_options()
        candidates = self.bench_candidates()
        for pid, name, slash in candidates:
            bench.add_option(Option(f"{name:<{_NAME_W}}{slash}", id=pid))
        if not candidates:
            self._bench_open = False
            self.query_one("#lineup-edit-status", Static).update(
                "No eligible bench players to substitute."
            )
            return
        self._bench_open = True
        self.query_one("#bench-label", Label).display = True
        bench.display = True
        bench.highlighted = 0
        bench.focus()
        self.query_one("#lineup-edit-hint", Label).update(self._BENCH_HINT)

    def _close_bench(self) -> None:
        self._bench_open = False
        bench = self.query_one("#bench-list", OptionList)
        bench.display = False
        self.query_one("#bench-label", Label).display = False
        self.query_one("#lineup-edit-hint", Label).update(self._HINT)
        self.set_focus(None)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """A bench player was chosen (Enter/click on the bench list)."""
        if not self._bench_open or not event.option.id:
            return
        self._commit_bench_selection(str(event.option.id))

    def _commit_bench_selection(self, player_id: str) -> None:
        try:
            self.substitute(player_id)
        except ValueError as exc:
            self.query_one("#lineup-edit-status", Static).update(f"[red]{exc}[/red]")
            return
        self._close_bench()
        self._refresh()

    # ------------------------------------------------------------------
    # Textual action handlers — thin wrappers over the pure edit methods.
    # ------------------------------------------------------------------

    def action_cursor_up(self) -> None:
        if self._bench_open:
            return
        self.move_selection(-1)
        self._refresh()

    def action_cursor_down(self) -> None:
        if self._bench_open:
            return
        self.move_selection(1)
        self._refresh()

    def action_move_up(self) -> None:
        if self._bench_open:
            return
        self.move_batter_up()
        self._refresh()

    def action_move_down(self) -> None:
        if self._bench_open:
            return
        self.move_batter_down()
        self._refresh()

    def action_mark_position(self) -> None:
        if self._bench_open:
            return
        self.mark_or_swap_position()
        self._refresh()

    def action_open_bench(self) -> None:
        if self._bench_open:
            return
        self._open_bench()

    def action_reset(self) -> None:
        if self._bench_open:
            return
        self.reset_to_auto()
        self._refresh()

    def action_confirm(self) -> None:
        if self._bench_open:
            # Enter inside the bench list commits the highlighted candidate.
            bench = self.query_one("#bench-list", OptionList)
            idx = bench.highlighted
            if idx is not None:
                option = bench.get_option_at_index(idx)
                if option.id:
                    self._commit_bench_selection(str(option.id))
            return
        self.dismiss(self.current_plan())

    def action_cancel(self) -> None:
        if self._pending_pos_mark is not None:
            self.clear_position_mark()
            self._refresh()
            return
        if self._bench_open:
            self._close_bench()
            return
        self.dismiss(None)
