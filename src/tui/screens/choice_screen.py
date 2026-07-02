"""Generic keyboard-driven choice modal.

Used by the setup flow for game-mode and manager-control selection. Styled
to match the pitcher/team select modals: an OptionList in a bordered panel,
arrows + Enter, Esc picks the default.
"""

from typing import List, Optional, Tuple

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList
from textual.widgets.option_list import Option


class ChoiceScreen(ModalScreen[Optional[str]]):
    """Modal presenting a titled list of options; returns the chosen id.

    Args:
        title: Panel title (e.g. "GAME MODE").
        prompt: One-line prompt above the list.
        choices: (id, label) pairs in display order.
        default_id: Highlighted initially and returned on Esc.
    """

    CSS = """
    ChoiceScreen {
        align: center middle;
        background: #0d160d 40%;
    }

    #choice-container {
        width: 56;
        height: auto;
        max-height: 80%;
        background: #121f12;
        border: round #d4a843;
        border-title-color: #d4a843;
        border-title-style: bold;
        padding: 1 2;
    }

    #choice-prompt {
        text-align: center;
        width: 100%;
        height: 1;
        color: #d4a843;
    }

    #choice-option-list {
        height: auto;
        max-height: 12;
        width: 100%;
        margin: 1 0 0 0;
        background: #121f12;
        border: none;
    }

    #choice-hint {
        text-align: center;
        width: 100%;
        height: 1;
        margin: 1 0 0 0;
        color: #6b7d6b;
    }
    """

    _HINT = (
        "[#d4a843]↑/↓[/] navigate   [#d4a843]Enter[/] select   "
        "[#d4a843]Esc[/] default"
    )

    BINDINGS = [
        Binding("enter", "confirm", "Select", priority=True),
        Binding("escape", "use_default", "Default"),
    ]

    def __init__(
        self,
        title: str,
        prompt: str,
        choices: List[Tuple[str, str]],
        default_id: Optional[str] = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._title = title
        self._prompt = prompt
        self._choices = choices
        self._default_id = default_id or (choices[0][0] if choices else None)

    def compose(self) -> ComposeResult:
        with Container(id="choice-container"):
            yield Label(f"[bold]{self._prompt}[/bold]", id="choice-prompt")
            option_list = OptionList(id="choice-option-list")
            for choice_id, label in self._choices:
                option_list.add_option(Option(label, id=choice_id))
            yield option_list
            yield Label(self._HINT, id="choice-hint")

    def on_mount(self) -> None:
        container = self.query_one("#choice-container", Container)
        container.border_title = self._title
        option_list = self.query_one("#choice-option-list", OptionList)
        for i, (choice_id, _) in enumerate(self._choices):
            if choice_id == self._default_id:
                option_list.highlighted = i
                break
        option_list.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option.id:
            self.dismiss(str(event.option.id))

    def action_confirm(self) -> None:
        option_list = self.query_one("#choice-option-list", OptionList)
        idx = option_list.highlighted
        if idx is not None and 0 <= idx < len(self._choices):
            self.dismiss(self._choices[idx][0])
        else:
            self.dismiss(self._default_id)

    def action_use_default(self) -> None:
        self.dismiss(self._default_id)
