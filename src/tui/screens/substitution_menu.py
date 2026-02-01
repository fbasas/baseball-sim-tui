"""Substitution menu modal for making pitching changes and pinch hitters.

Provides a unified interface for all substitution types:
- Tab 1: Pitching Change (shows bullpen with ERA)
- Tab 2: Pinch Hitter (shows bench with AVG/OBP/SLG)
"""

from typing import List, Optional, Tuple

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static


class PlayerSelected(Message):
    """Message sent when a player is clicked."""

    def __init__(self, player_id: str, widget_id: str) -> None:
        super().__init__()
        self.player_id = player_id
        self.widget_id = widget_id


class PlayerListItem(Static):
    """Single player in the substitution list.

    Shows player name and stats, grayed out if already used.
    Focusable and clickable for selection.
    """

    BINDINGS = [
        ("enter", "select", "Select"),
    ]

    def __init__(
        self,
        player_id: str,
        name: str,
        stats_str: str,
        is_available: bool,
        **kwargs
    ) -> None:
        super().__init__(**kwargs)
        self.player_id = player_id
        self._name = name
        self._stats = stats_str
        self._available = is_available

    def render(self) -> str:
        if self._available:
            return f"{self._name:<15} {self._stats}"
        else:
            return f"[dim]{self._name:<15} {self._stats} (Used)[/dim]"

    def on_mount(self) -> None:
        """Make item focusable for keyboard navigation."""
        if self._available:
            self.can_focus = True

    def on_click(self) -> None:
        """Handle click to select this player."""
        if self._available:
            # Notify parent screen of selection
            self.post_message(PlayerSelected(self.player_id, self.id or ""))

    def action_select(self) -> None:
        """Handle Enter key to select this player."""
        if self._available:
            self.post_message(PlayerSelected(self.player_id, self.id or ""))


class SubstitutionMenu(ModalScreen[Optional[Tuple[str, str, str]]]):
    """Modal for making substitutions.

    Returns tuple of (sub_type, player_out_id, player_in_id) on selection,
    or None if cancelled.

    sub_type is 'pitching_change' or 'pinch_hitter'.
    """

    CSS = """
    SubstitutionMenu {
        align: center middle;
        layout: horizontal;
    }

    #sub-menu-container {
        width: 50vw;
        min-width: 50;
        height: 20;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }

    #sub-title {
        text-align: center;
        width: 100%;
        height: 1;
    }

    #pitcher-list {
        height: 10;
        width: 100%;
        border: solid $primary-darken-2;
        margin: 1 0;
    }

    #button-row {
        width: 100%;
        height: 3;
        align: center middle;
    }

    #button-row Button {
        width: auto;
        min-width: 12;
        margin: 0 2;
    }

    PlayerListItem {
        width: 100%;
        padding: 0 1;
    }

    PlayerListItem:hover {
        background: $primary-darken-2;
    }

    PlayerListItem:focus {
        background: $accent;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("c", "confirm", "Confirm"),
    ]

    def __init__(
        self,
        pitchers: List[Tuple[str, str, float, bool]],  # (id, name, ERA, available)
        batters: List[Tuple[str, str, str, bool]],  # (id, name, "AVG/OBP/SLG", available)
        current_pitcher_id: str,
        current_batter_id: str,
        **kwargs
    ) -> None:
        """Initialize substitution menu.

        Args:
            pitchers: List of (player_id, name, ERA, is_available) for bullpen
            batters: List of (player_id, name, slash_line, is_available) for bench
            current_pitcher_id: ID of pitcher to be replaced
            current_batter_id: ID of batter to be replaced (for pinch hit)
        """
        super().__init__(**kwargs)
        self._pitchers = pitchers
        self._batters = batters
        self._current_pitcher = current_pitcher_id
        self._current_batter = current_batter_id
        self._selected_pitcher: Optional[str] = None
        self._selected_batter: Optional[str] = None

    def compose(self) -> ComposeResult:
        with Container(id="sub-menu-container"):
            yield Label("[bold]═══ SUBSTITUTIONS ═══[/bold]", id="sub-title")
            yield Label("[bold]Available Relievers:[/bold]")
            with VerticalScroll(id="pitcher-list"):
                for pid, name, era, avail in self._pitchers:
                    stats = f"ERA {era:.2f}"
                    yield PlayerListItem(pid, name, stats, avail, id=f"p-{pid}")
            with Horizontal(id="button-row"):
                yield Button("Confirm", id="confirm", variant="success")
                yield Button("Cancel", id="cancel", variant="error")


    def on_player_selected(self, message: PlayerSelected) -> None:
        """Handle player selection click.

        Args:
            message: PlayerSelected message with player_id and widget_id
        """
        # Determine if this is a pitcher or batter based on widget ID prefix
        if message.widget_id.startswith("p-"):
            self._selected_pitcher = message.player_id
        elif message.widget_id.startswith("b-"):
            self._selected_batter = message.player_id

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
        elif event.button.id == "confirm":
            # For now, only support pitching changes
            # If no pitcher selected, auto-select first available
            selected = self._selected_pitcher
            if not selected:
                for pid, name, era, avail in self._pitchers:
                    if avail:
                        selected = pid
                        break
            if selected:
                self.dismiss(("pitching_change", self._current_pitcher, selected))
            else:
                self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_confirm(self) -> None:
        """Confirm substitution with C key."""
        selected = self._selected_pitcher
        if not selected:
            for pid, name, era, avail in self._pitchers:
                if avail:
                    selected = pid
                    break
        if selected:
            self.dismiss(("pitching_change", self._current_pitcher, selected))
        else:
            self.dismiss(None)
