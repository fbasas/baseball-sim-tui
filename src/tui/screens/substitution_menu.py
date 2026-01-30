"""Substitution menu modal for making pitching changes and pinch hitters.

Provides a unified interface for all substitution types:
- Tab 1: Pitching Change (shows bullpen with ERA)
- Tab 2: Pinch Hitter (shows bench with AVG/OBP/SLG)
"""

from typing import List, Optional, Tuple

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static, TabbedContent, TabPane


class PlayerListItem(Static):
    """Single player in the substitution list.

    Shows player name and stats, grayed out if already used.
    """

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


class SubstitutionMenu(ModalScreen[Optional[Tuple[str, str, str]]]):
    """Modal for making substitutions.

    Returns tuple of (sub_type, player_out_id, player_in_id) on selection,
    or None if cancelled.

    sub_type is 'pitching_change' or 'pinch_hitter'.
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
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
            yield Label("[bold]Substitutions[/bold]", id="sub-title")

            with TabbedContent():
                with TabPane("Pitching Change", id="pitching-tab"):
                    yield Label("Select relief pitcher:")
                    with Vertical(id="pitcher-list"):
                        for pid, name, era, avail in self._pitchers:
                            stats = f"ERA {era:.2f}"
                            yield PlayerListItem(pid, name, stats, avail, id=f"p-{pid}")

                with TabPane("Pinch Hitter", id="batter-tab"):
                    yield Label("Select pinch hitter:")
                    with Vertical(id="batter-list"):
                        for bid, name, slash, avail in self._batters:
                            yield PlayerListItem(bid, name, slash, avail, id=f"b-{bid}")

            with Horizontal(id="sub-buttons"):
                yield Button("Confirm", id="confirm", variant="primary")
                yield Button("Cancel", id="cancel", variant="default")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
        elif event.button.id == "confirm":
            # Return selected substitution
            # For now, basic implementation - full selection logic in next plan
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)
