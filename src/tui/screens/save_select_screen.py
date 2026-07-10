"""Load/Resume: the saved-game picker screen (FRE-48).

Lists the JSON saves under ``data/saves/`` newest-first and returns the chosen
file's ``Path``, so the setup flow can hand it to ``GameScreen.restore_from``.
Built on the same ``OptionList``-in-a-bordered-panel pattern as ``ChoiceScreen``
(arrows + Enter, Esc backs out).

Reading a save's ``label``/``created_at`` for the list is a deliberately
lightweight parse (:func:`list_save_entries`): enough to render a row without
fully validating the snapshot. A file that isn't valid JSON or lacks those
metadata fields is skipped from the list; a wrong-``schema_version`` /
unknown-team file is still listed but only rejected loudly when actually
selected (``load_game`` + restore, done by the caller). An empty directory shows
a "no saved games" message and Esc returns ``None``.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList
from textual.widgets.option_list import Option


@dataclass(frozen=True)
class SaveEntry:
    """One row in the load list: the save file plus its display metadata."""

    path: Path
    label: str
    created_at: str
    kind: str = "single"

    def _short_time(self) -> str:
        """A compact ``YYYY-MM-DD HH:MM`` from the ISO ``created_at`` (best-effort)."""
        return self.created_at[:16].replace("T", " ")

    def display(self) -> str:
        """The one-line option text: label, timestamp, and a mode marker."""
        tag = ""
        if self.kind == "season":
            tag = "  [dim](season)[/dim]"
        elif self.kind == "series":
            tag = "  [dim](series)[/dim]"
        return f"{self.label}   [dim]{self._short_time()}[/dim]{tag}"


def list_save_entries(directory: Path) -> List[SaveEntry]:
    """Return the saves in ``directory`` as display rows, newest first.

    Reads each ``*.json`` file's top-level ``label``/``created_at``/``kind`` with
    a lightweight parse — enough to render the list without fully validating the
    snapshot (that happens on selection, via ``persistence.load_game``). A file
    that isn't valid JSON, isn't a JSON object, or is missing ``label`` /
    ``created_at`` is skipped rather than breaking the whole list. Sorted by
    ``created_at`` descending (newest first); the filename is a tiebreaker so the
    order is always deterministic. A missing directory yields an empty list.
    """
    entries: List[SaveEntry] = []
    if not directory.exists():
        return entries
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text())
            label = data["label"]
            created_at = data["created_at"]
        except (OSError, ValueError, KeyError, TypeError):
            # Unreadable / not-JSON / not-an-object / missing metadata -> skip.
            continue
        kind = data.get("kind", "single")
        entries.append(
            SaveEntry(
                path=path,
                label=str(label),
                created_at=str(created_at),
                kind=str(kind),
            )
        )
    entries.sort(key=lambda e: (e.created_at, e.path.name), reverse=True)
    return entries


class SaveSelectScreen(ModalScreen[Optional[Path]]):
    """Modal listing saved games; dismisses with the chosen save's ``Path``.

    Given the pre-listed ``entries`` (newest-first, from :func:`list_save_entries`),
    presents them in an ``OptionList`` and returns the selected file's ``Path`` on
    Enter, or ``None`` on Esc / when there are no saves. The caller performs the
    actual ``load_game`` + restore, so wrong-version / missing-team failures are
    surfaced there — this screen only picks a file.

    Args:
        entries: The saves to offer, already ordered for display.
    """

    CSS = """
    SaveSelectScreen {
        align: center middle;
        background: #0d160d 40%;
    }

    #save-container {
        width: 64;
        height: auto;
        max-height: 80%;
        background: #121f12;
        border: round #d4a843;
        border-title-color: #d4a843;
        border-title-style: bold;
        padding: 1 2;
    }

    #save-prompt {
        text-align: center;
        width: 100%;
        height: 1;
        color: #d4a843;
    }

    #save-option-list {
        height: auto;
        max-height: 14;
        width: 100%;
        margin: 1 0 0 0;
        background: #121f12;
        border: none;
    }

    #save-empty {
        text-align: center;
        width: 100%;
        height: auto;
        margin: 1 0 0 0;
        color: #6b7d6b;
    }

    #save-hint {
        text-align: center;
        width: 100%;
        height: 1;
        margin: 1 0 0 0;
        color: #6b7d6b;
    }
    """

    _TITLE = "⚾ LOAD SAVED GAME"
    _PROMPT = "Pick a save to resume"
    _EMPTY_MESSAGE = "No saved games found in data/saves/."
    _HINT = (
        "[#d4a843]↑/↓[/] navigate   [#d4a843]Enter[/] resume   "
        "[#d4a843]Esc[/] back"
    )

    BINDINGS = [
        Binding("enter", "confirm", "Resume", priority=True),
        Binding("escape", "cancel", "Back"),
    ]

    def __init__(self, entries: List[SaveEntry], **kwargs) -> None:
        super().__init__(**kwargs)
        self._entries = entries

    def compose(self) -> ComposeResult:
        with Container(id="save-container"):
            yield Label(f"[bold]{self._PROMPT}[/bold]", id="save-prompt")
            if self._entries:
                option_list = OptionList(id="save-option-list")
                for i, entry in enumerate(self._entries):
                    option_list.add_option(Option(entry.display(), id=str(i)))
                yield option_list
            else:
                yield Label(self._EMPTY_MESSAGE, id="save-empty")
            yield Label(self._HINT, id="save-hint")

    def on_mount(self) -> None:
        container = self.query_one("#save-container", Container)
        container.border_title = self._TITLE
        if self._entries:
            option_list = self.query_one("#save-option-list", OptionList)
            option_list.highlighted = 0
            option_list.focus()

    def on_option_list_option_selected(
        self, event: OptionList.OptionSelected
    ) -> None:
        if event.option.id is not None:
            self._select_index(int(event.option.id))

    def action_confirm(self) -> None:
        if not self._entries:
            self.dismiss(None)
            return
        option_list = self.query_one("#save-option-list", OptionList)
        self._select_index(option_list.highlighted)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _select_index(self, index: Optional[int]) -> None:
        """Dismiss with the ``Path`` at ``index``, or ``None`` if out of range."""
        if index is None or not (0 <= index < len(self._entries)):
            self.dismiss(None)
            return
        self.dismiss(self._entries[index].path)
