"""Substitution menu modal for making pitching changes and pinch hitters.

A single scrolling view with two lists:
- Pitching Change (bullpen with ERA)
- Pinch Hitter (bench with AVG/OBP/SLG)

Keyboard-driven: arrow keys move within a list, Tab switches lists, Enter
substitutes the focused player, Esc cancels. A mouse click on a player also
substitutes them. Shortcuts are shown inside the dialog; there are no buttons.
"""

from typing import Dict, List, Optional, Tuple

from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Label, Static


class PlayerListItem(Static):
    """Single player in the substitution list.

    Shows player name and stats, grayed out if already used.
    Focusable and clickable for selection.
    """

    BINDINGS = [
        ("enter", "select", "Substitute"),
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
        """Handle click: commit this player as the substitution immediately."""
        if not self._available:
            return
        self.focus()
        screen = self.screen
        confirm = getattr(screen, "confirm_player", None)
        if confirm:
            confirm(self.player_id, self.id or "")

    def on_focus(self) -> None:
        """Notify the modal so it can remember the last-focused item per list."""
        screen = self.screen
        track = getattr(screen, "_track_focus", None)
        if track:
            track(self)

    def action_select(self) -> None:
        """Handle Enter: confirm this player as the substitution immediately.

        Pressing Enter on a focused, available player is unambiguous — that
        player is the one coming in — so it commits the substitution and
        closes the modal. A mouse click does the same thing.
        """
        if not self._available:
            return
        screen = self.screen
        confirm = getattr(screen, "confirm_player", None)
        if confirm:
            confirm(self.player_id, self.id or "")

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
        background: #0d160d 40%;
    }

    #sub-menu-container {
        width: 50vw;
        min-width: 52;
        height: auto;
        max-height: 90%;
        background: #121f12;
        color: #f2ecd8;
        border: round #d4a843;
        border-title-color: #d4a843;
        border-title-style: bold;
        padding: 1 2;
    }

    .sub-section-label {
        color: #d4a843;
        text-style: bold;
        margin: 1 0 0 0;
    }

    .sub-replacing {
        color: #6b7d6b;
    }

    #pitcher-list, #batter-list {
        height: 8;
        width: 100%;
        border: round #3e5c40;
        margin: 0 0 1 0;
        background: #0d160d;
        scrollbar-color: #3e5c40;
        scrollbar-background: #0d160d;
        scrollbar-size-vertical: 1;
    }

    #sub-menu-hint {
        text-align: center;
        width: 100%;
        height: 1;
        color: #6b7d6b;
    }

    PlayerListItem {
        width: 100%;
        padding: 0 1;
    }

    PlayerListItem:hover {
        background: #1a2b1a;
    }

    PlayerListItem:focus {
        background: #d4a843;
        color: #1a2b1a;
        text-style: bold;
    }
    """

    _HINT = (
        "[#d4a843]↑/↓[/] navigate   [#d4a843]Tab[/] switch list   "
        "[#d4a843]Enter[/] substitute   [#d4a843]Esc[/] cancel"
    )

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
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
        # Remembers the last focused PlayerListItem widget id within each list
        # (keys: "pitcher-list", "batter-list") so Tab can restore focus to
        # where the user left off rather than always jumping to the top.
        self._last_focus_by_list: Dict[str, str] = {}

    def compose(self) -> ComposeResult:
        with Container(id="sub-menu-container"):
            yield Label("PITCHING CHANGE", classes="sub-section-label")
            if self._current_pitcher_label:
                yield Label(
                    f"replacing {self._current_pitcher_label}",
                    classes="sub-replacing",
                )
            with VerticalScroll(id="pitcher-list"):
                for pid, name, era, avail in self._pitchers:
                    stats = f"ERA {era:.2f}"
                    yield PlayerListItem(pid, name, stats, avail, id=f"p-{pid}")
            yield Label("PINCH HITTER", classes="sub-section-label")
            if self._current_batter_label:
                yield Label(
                    f"replacing {self._current_batter_label}",
                    classes="sub-replacing",
                )
            with VerticalScroll(id="batter-list"):
                for pid, name, slash, avail in self._batters:
                    yield PlayerListItem(pid, name, slash, avail, id=f"b-{pid}")
            yield Label(self._HINT, id="sub-menu-hint")

    def on_mount(self) -> None:
        """Title the panel and focus the first available player."""
        container = self.query_one("#sub-menu-container", Container)
        container.border_title = "⚾ SUBSTITUTIONS"
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


    def confirm_player(self, player_id: str, widget_id: str) -> None:
        """Commit a substitution for a single player and close the modal.

        Called when the user presses Enter on (or clicks) a player. The widget
        id prefix disambiguates the list the player came from:
        ``p-`` → pitching change, ``b-`` → pinch hitter.

        Args:
            player_id: The player coming in.
            widget_id: The PlayerListItem id (``p-<id>`` or ``b-<id>``).
        """
        if widget_id.startswith("p-"):
            self.dismiss(("pitching_change", self._current_pitcher, player_id))
        elif widget_id.startswith("b-"):
            self.dismiss(("pinch_hitter", self._current_batter, player_id))

    def action_cancel(self) -> None:
        self.dismiss(None)
