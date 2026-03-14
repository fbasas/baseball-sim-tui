"""Pitcher selection modal for choosing starting pitcher before game.

Shows available pitchers sorted by games started (GS) with the default
(most GS) pre-highlighted. User can confirm or pick a different pitcher.
"""

from typing import List, Optional, Tuple

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Label, OptionList, Static
from textual.widgets.option_list import Option


class PitcherSelectScreen(ModalScreen[Optional[str]]):
    """Modal for selecting starting pitcher before game start.

    Shows pitchers sorted by games started. Returns the chosen pitcher_id
    on confirm, or the default on escape.

    Args:
        team_name: Display name for the team header.
        pitchers: List of (player_id, display_name, games_started) sorted by GS desc.
        default_pitcher_id: Auto-selected pitcher (most GS).
    """

    CSS = """
    PitcherSelectScreen {
        align: center middle;
    }

    #pitcher-select-container {
        width: 50;
        height: auto;
        max-height: 20;
        background: #2a1a0a;
        border: thick #8b6914;
        padding: 1 2;
    }

    #pitcher-select-title {
        text-align: center;
        width: 100%;
        height: 1;
        color: #d4a843;
    }

    #pitcher-option-list {
        height: auto;
        max-height: 12;
        width: 100%;
        margin: 1 0;
    }

    #pitcher-button-row {
        width: 100%;
        height: 3;
        align: center middle;
    }

    #pitcher-button-row Button {
        width: auto;
        min-width: 14;
        margin: 0 1;
    }
    """

    BINDINGS = [
        ("escape", "use_default", "Use Default"),
    ]

    def __init__(
        self,
        team_name: str,
        pitchers: List[Tuple[str, str, int]],
        default_pitcher_id: str,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._team_name = team_name
        self._pitchers = pitchers
        self._default_pitcher_id = default_pitcher_id

    def compose(self) -> ComposeResult:
        with Container(id="pitcher-select-container"):
            yield Label(
                f"[bold]Starting Pitcher - {self._team_name}[/bold]",
                id="pitcher-select-title",
            )
            option_list = OptionList(id="pitcher-option-list")
            for pid, name, gs in self._pitchers:
                marker = " *" if pid == self._default_pitcher_id else ""
                option_list.add_option(Option(f"{name:<25} GS: {gs}{marker}", id=pid))
            yield option_list
            with Horizontal(id="pitcher-button-row"):
                yield Button("Confirm", id="confirm-pitcher", variant="success")
                yield Button("Default", id="default-pitcher", variant="primary")

    def on_mount(self) -> None:
        """Pre-select the default pitcher in the option list."""
        option_list = self.query_one("#pitcher-option-list", OptionList)
        for i, (pid, _, _) in enumerate(self._pitchers):
            if pid == self._default_pitcher_id:
                option_list.highlighted = i
                break

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm-pitcher":
            self._confirm_selection()
        elif event.button.id == "default-pitcher":
            self.dismiss(self._default_pitcher_id)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Double-click or Enter on an option confirms it."""
        if event.option.id:
            self.dismiss(str(event.option.id))

    def _confirm_selection(self) -> None:
        """Confirm the currently highlighted pitcher."""
        option_list = self.query_one("#pitcher-option-list", OptionList)
        idx = option_list.highlighted
        if idx is not None and 0 <= idx < len(self._pitchers):
            self.dismiss(self._pitchers[idx][0])
        else:
            self.dismiss(self._default_pitcher_id)

    def action_use_default(self) -> None:
        self.dismiss(self._default_pitcher_id)
