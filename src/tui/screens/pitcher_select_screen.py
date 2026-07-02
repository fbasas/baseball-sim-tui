"""Pitcher selection modal for choosing starting pitcher before game.

Shows available pitchers sorted by games started with W-L / ERA / IP, the
default (most games started) pre-highlighted. Keyboard-driven: arrow keys to
move, Enter to select, Esc to use the default. Shortcuts are shown inside
the dialog, matching the team-select modal.
"""

from typing import List, Optional, Tuple

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList
from textual.widgets.option_list import Option

# Column widths for the pitcher rows / header, kept in one place so the header
# label and the data rows stay aligned.
_NAME_W = 22
_WL_W = 7
_ERA_W = 8
_IP_W = 8


class PitcherSelectScreen(ModalScreen[Optional[str]]):
    """Modal for selecting starting pitcher before game start.

    Shows pitchers sorted by games started with W-L / ERA / IP. Returns the
    chosen pitcher_id on Enter, or the default on Esc.

    Args:
        team_name: Display name for the team header.
        pitchers: List of (player_id, name, wins, losses, era, ip_outs) sorted
            by games started descending.
        default_pitcher_id: Auto-selected pitcher (most games started).
        role: "Away" or "Home" — shown in the panel title for context.
    """

    CSS = """
    PitcherSelectScreen {
        align: center middle;
        background: #0d160d 40%;
    }

    #pitcher-select-container {
        width: 62;
        height: auto;
        max-height: 90%;
        background: #121f12;
        border: round #d4a843;
        border-title-color: #d4a843;
        border-title-style: bold;
        padding: 1 2;
    }

    #pitcher-select-title {
        text-align: center;
        width: 100%;
        height: 1;
        color: #d4a843;
    }

    #pitcher-col-header {
        width: 100%;
        height: 1;
        margin: 1 0 0 0;
        color: #6b7d6b;
    }

    #pitcher-option-list {
        height: auto;
        max-height: 14;
        width: 100%;
        margin: 0 0 0 0;
        background: #121f12;
        border: none;
    }

    #pitcher-select-hint {
        text-align: center;
        width: 100%;
        height: 1;
        margin: 1 0 0 0;
        color: #6b7d6b;
    }
    """

    _HINT = (
        "[#d4a843]↑/↓[/] navigate   [#d4a843]Enter[/] select   "
        "[#d4a843]Esc[/] use default [#d4a843]★[/]"
    )

    BINDINGS = [
        # priority so it fires instead of being shadowed by the focused
        # OptionList's own Enter binding.
        Binding("enter", "confirm", "Select", priority=True),
        Binding("escape", "use_default", "Use Default"),
    ]

    def __init__(
        self,
        team_name: str,
        pitchers: List[Tuple[str, str, int, int, float, int]],
        default_pitcher_id: str,
        role: str = "",
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._team_name = team_name
        self._pitchers = pitchers
        self._default_pitcher_id = default_pitcher_id
        self._role = role

    @staticmethod
    def _format_ip(ip_outs: int) -> str:
        """Format outs as innings pitched (e.g., 19 outs -> '6.1')."""
        return f"{ip_outs // 3}.{ip_outs % 3}"

    def _column_header(self) -> str:
        return (
            f"{'Pitcher':<{_NAME_W}}{'W-L':>{_WL_W}}"
            f"{'ERA':>{_ERA_W}}{'IP':>{_IP_W}}"
        )

    def _format_row(
        self, pid: str, name: str, wins: int, losses: int, era: float, ip_outs: int
    ) -> str:
        wl = f"{wins}-{losses}"
        era_s = f"{era:.2f}" if era > 0 else "-"
        ip_s = self._format_ip(ip_outs)
        marker = "  [#d4a843]★[/]" if pid == self._default_pitcher_id else ""
        return (
            f"{name:<{_NAME_W}}{wl:>{_WL_W}}"
            f"{era_s:>{_ERA_W}}{ip_s:>{_IP_W}}{marker}"
        )

    def compose(self) -> ComposeResult:
        with Container(id="pitcher-select-container"):
            yield Label(
                f"[bold]{self._team_name}[/bold]",
                id="pitcher-select-title",
            )
            yield Label(self._column_header(), id="pitcher-col-header")
            option_list = OptionList(id="pitcher-option-list")
            for pid, name, wins, losses, era, ip_outs in self._pitchers:
                option_list.add_option(
                    Option(self._format_row(pid, name, wins, losses, era, ip_outs), id=pid)
                )
            yield option_list
            yield Label(self._HINT, id="pitcher-select-hint")

    def on_mount(self) -> None:
        """Highlight the default pitcher and focus the list for keyboard nav."""
        container = self.query_one("#pitcher-select-container", Container)
        role = f" · {self._role.upper()}" if self._role else ""
        container.border_title = f"⚾ STARTING PITCHER{role}"
        option_list = self.query_one("#pitcher-option-list", OptionList)
        for i, row in enumerate(self._pitchers):
            if row[0] == self._default_pitcher_id:
                option_list.highlighted = i
                break
        option_list.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Enter or double-click on an option confirms it."""
        if event.option.id:
            self.dismiss(str(event.option.id))

    def action_confirm(self) -> None:
        """Confirm the currently highlighted pitcher (fallback for Enter)."""
        option_list = self.query_one("#pitcher-option-list", OptionList)
        idx = option_list.highlighted
        if idx is not None and 0 <= idx < len(self._pitchers):
            self.dismiss(self._pitchers[idx][0])
        else:
            self.dismiss(self._default_pitcher_id)

    def action_use_default(self) -> None:
        self.dismiss(self._default_pitcher_id)
