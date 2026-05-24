"""Substitution menu modal for making pitching changes and pinch hitters.

Provides a unified interface for all substitution types:
- Tab 1: Pitching Change (shows bullpen with ERA)
- Tab 2: Pinch Hitter (shows bench with AVG/OBP/SLG)
"""

from typing import Dict, List, Optional, Tuple

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Label, Static


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
        ("up", "focus_prev", "Up"),
        ("down", "focus_next", "Down"),
        ("tab", "switch_list", "Switch List"),
        ("shift+tab", "switch_list", "Switch List"),
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
        """Handle click: focus the item and notify parent of selection."""
        if self._available:
            self.focus()
            self.post_message(PlayerSelected(self.player_id, self.id or ""))

    def on_focus(self) -> None:
        """Notify the modal so it can remember the last-focused item per list."""
        screen = self.screen
        track = getattr(screen, "_track_focus", None)
        if track:
            track(self)

    def action_select(self) -> None:
        """Handle Enter key to select this player."""
        if self._available:
            self.post_message(PlayerSelected(self.player_id, self.id or ""))

    def _available_siblings(self) -> List["PlayerListItem"]:
        """Return the available items in the same list, in DOM order."""
        if self.parent is None:
            return [self] if self._available else []
        return [
            w for w in self.parent.query(PlayerListItem)
            if w._available
        ]

    def action_focus_prev(self) -> None:
        """Move focus to the previous available item in the same list.

        Clamps at the top — pressing up on the first item stays put.
        """
        siblings = self._available_siblings()
        if self not in siblings:
            return
        idx = siblings.index(self)
        if idx > 0:
            siblings[idx - 1].focus()

    def action_focus_next(self) -> None:
        """Move focus to the next available item in the same list.

        Clamps at the bottom — pressing down on the last item stays put.
        """
        siblings = self._available_siblings()
        if self not in siblings:
            return
        idx = siblings.index(self)
        if idx < len(siblings) - 1:
            siblings[idx + 1].focus()

    def action_switch_list(self) -> None:
        """Move focus to the other list (pitcher <-> batter).

        Restores the last-focused item in that list, or the first available
        if it hasn't been visited yet.
        """
        screen = self.screen
        switch = getattr(screen, "switch_list", None)
        if switch:
            parent_id = self.parent.id if self.parent else ""
            switch(parent_id)


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
        height: auto;
        max-height: 90%;
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
        height: 8;
        width: 100%;
        border: solid $primary-darken-2;
        margin: 1 0;
    }

    #batter-list {
        height: 8;
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
        current_pitcher_label: str = "",
        current_batter_label: str = "",
        **kwargs
    ) -> None:
        """Initialize substitution menu.

        Args:
            pitchers: List of (player_id, name, ERA, is_available) for bullpen
            batters: List of (player_id, name, slash_line, is_available) for bench
            current_pitcher_id: ID of pitcher to be replaced
            current_batter_id: ID of batter to be replaced (for pinch hit)
            current_pitcher_label: Display string for the pitcher being replaced
                (e.g. "C. Root  ERA 3.62"). Empty hides the line.
            current_batter_label: Display string for the batter being replaced
                (e.g. "E. Combs  .356"). Empty hides the line.
        """
        super().__init__(**kwargs)
        self._pitchers = pitchers
        self._batters = batters
        self._current_pitcher = current_pitcher_id
        self._current_batter = current_batter_id
        self._current_pitcher_label = current_pitcher_label
        self._current_batter_label = current_batter_label
        self._selected_pitcher: Optional[str] = None
        self._selected_batter: Optional[str] = None
        # Tracks which list the most recent selection came from.
        # Values: "pitcher", "batter", or None (nothing selected yet).
        # Used to disambiguate confirm intent when both lists have selections.
        self._last_selection: Optional[str] = None
        # Remembers the last focused PlayerListItem widget id within each list
        # (keys: "pitcher-list", "batter-list") so Tab can restore focus to
        # where the user left off rather than always jumping to the top.
        self._last_focus_by_list: Dict[str, str] = {}

    def compose(self) -> ComposeResult:
        with Container(id="sub-menu-container"):
            yield Label("[bold]═══ SUBSTITUTIONS ═══[/bold]", id="sub-title")
            yield Label("[bold]Pitching Change[/bold]")
            if self._current_pitcher_label:
                yield Label(f"Replacing: [italic]{self._current_pitcher_label}[/italic]")
            yield Label("Available relievers:")
            with VerticalScroll(id="pitcher-list"):
                for pid, name, era, avail in self._pitchers:
                    stats = f"ERA {era:.2f}"
                    yield PlayerListItem(pid, name, stats, avail, id=f"p-{pid}")
            yield Label("[bold]Pinch Hitter[/bold]")
            if self._current_batter_label:
                yield Label(f"Replacing: [italic]{self._current_batter_label}[/italic]")
            yield Label("Available pinch hitters:")
            with VerticalScroll(id="batter-list"):
                for pid, name, slash, avail in self._batters:
                    yield PlayerListItem(pid, name, slash, avail, id=f"b-{pid}")
            with Horizontal(id="button-row"):
                yield Button("Confirm", id="confirm", variant="success")
                yield Button("Cancel", id="cancel", variant="error")
        yield Footer()

    def on_mount(self) -> None:
        """Focus the first available pitcher (or batter) so arrow keys move highlight."""
        for item in self.query(PlayerListItem):
            if item._available:
                item.focus()
                return

    def _track_focus(self, item: PlayerListItem) -> None:
        """Remember which item was last focused in each list."""
        parent_id = item.parent.id if item.parent else ""
        if parent_id in ("pitcher-list", "batter-list") and item.id:
            self._last_focus_by_list[parent_id] = item.id

    def switch_list(self, from_list_id: str) -> None:
        """Move focus to the other list, restoring its last-focused item.

        Args:
            from_list_id: id of the VerticalScroll the user is leaving
                ("pitcher-list" or "batter-list"). Any other value is ignored.
        """
        if from_list_id == "pitcher-list":
            target_id = "batter-list"
        elif from_list_id == "batter-list":
            target_id = "pitcher-list"
        else:
            return

        try:
            container = self.query_one(f"#{target_id}", VerticalScroll)
        except Exception:
            return

        # Prefer the last item focused in the target list.
        last_item_id = self._last_focus_by_list.get(target_id)
        if last_item_id:
            for item in container.query(PlayerListItem):
                if item.id == last_item_id and item._available:
                    item.focus()
                    return

        # Otherwise fall back to the first available item.
        for item in container.query(PlayerListItem):
            if item._available:
                item.focus()
                return


    def on_player_selected(self, message: PlayerSelected) -> None:
        """Handle player selection click.

        Args:
            message: PlayerSelected message with player_id and widget_id
        """
        # Determine if this is a pitcher or batter based on widget ID prefix
        if message.widget_id.startswith("p-"):
            self._selected_pitcher = message.player_id
            self._last_selection = "pitcher"
        elif message.widget_id.startswith("b-"):
            self._selected_batter = message.player_id
            self._last_selection = "batter"

    def _resolve_confirm_choice(self) -> Optional[Tuple[str, str, str]]:
        """Resolve the (sub_type, out_id, in_id) tuple to dismiss with.

        Returns:
            - ("pitching_change", current_pitcher, selected_pitcher) if a pitcher
              is selected and no batter is (or pitcher is most recent).
            - ("pinch_hitter", current_batter, selected_batter) if a batter is
              selected and no pitcher is (or batter is most recent).
            - None if nothing is selected. **No auto-fallback** — confirming
              without a selection dismisses without making a substitution.
        """
        pitcher = self._selected_pitcher
        batter = self._selected_batter

        if pitcher and not batter:
            return ("pitching_change", self._current_pitcher, pitcher)
        if batter and not pitcher:
            return ("pinch_hitter", self._current_batter, batter)
        if pitcher and batter:
            # Both selected — prefer the most recently selected
            if self._last_selection == "batter":
                return ("pinch_hitter", self._current_batter, batter)
            return ("pitching_change", self._current_pitcher, pitcher)
        # Neither selected — no auto-pick fallback (intentional UX change:
        # the previous auto-pick-first-pitcher fallback masked selection
        # failures and produced phantom substitutions).
        return None

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
        elif event.button.id == "confirm":
            self.dismiss(self._resolve_confirm_choice())

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_confirm(self) -> None:
        """Confirm substitution with C key."""
        self.dismiss(self._resolve_confirm_choice())
