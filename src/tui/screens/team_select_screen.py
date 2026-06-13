"""Team selection modal for choosing a team-season before the game.

Three-phase, keyboard-driven flow for a single team (away or home):

  1. Decade phase — pick a decade (1870s … 2020s) to keep the year list short.
  2. Year phase   — pick a season within that decade.
  3. Team phase   — pick a club from the teams that played that season.

Navigation is arrow-key driven: ↑/↓ move the highlight, Enter selects the
highlighted row (and advances to the next phase), and Esc steps back one phase
(decade-phase Esc cancels selection). The footer lists these shortcuts.

The screen returns ``(team_id, year)`` when a team is chosen, or ``None`` if
the user backs out of the decade phase.
"""

from typing import List, Optional, Tuple

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList
from textual.widgets.option_list import Option

from src.data.lahman import LahmanRepository


class TeamSelectScreen(ModalScreen[Optional[Tuple[str, int]]]):
    """Modal for selecting one team-season (decade, then year, then club).

    Args:
        role: "Away" or "Home" — shown in the header so the user knows which
            side they are choosing.
        repo: Open LahmanRepository used to list years and teams.
    """

    CSS = """
    TeamSelectScreen {
        align: center middle;
    }

    #team-select-container {
        width: 62;
        height: auto;
        max-height: 90%;
        background: #2a1a0a;
        border: thick #8b6914;
        padding: 1 2;
    }

    #team-select-title {
        text-align: center;
        width: 100%;
        height: 1;
        color: #d4a843;
    }

    #team-option-list {
        height: auto;
        max-height: 16;
        width: 100%;
        margin: 1 0 0 0;
    }

    #team-select-hint {
        text-align: center;
        width: 100%;
        height: 1;
        margin: 1 0 0 0;
        color: #8b6914;
    }
    """

    _HINT = "[#d4a843]↑/↓[/] Navigate   [#d4a843]Enter[/] Select   [#d4a843]Esc[/] Back"

    BINDINGS = [
        # priority so they fire (and show in the footer) at the screen level
        # rather than being shadowed by the focused OptionList's own bindings.
        Binding("up", "cursor_up", "Up", priority=True),
        Binding("down", "cursor_down", "Down", priority=True),
        Binding("enter", "confirm", "Select", priority=True),
        Binding("escape", "back", "Back"),
    ]

    def __init__(self, role: str, repo: LahmanRepository, **kwargs) -> None:
        super().__init__(**kwargs)
        self._role = role
        self._repo = repo
        self._years: List[int] = repo.get_available_years()  # descending
        self._decades: List[int] = sorted(
            {y // 10 * 10 for y in self._years}, reverse=True
        )
        self._phase = "decade"  # "decade" | "year" | "team"
        self._chosen_decade: Optional[int] = None
        self._chosen_year: Optional[int] = None
        self._teams: List[Tuple[str, str]] = []

    def compose(self) -> ComposeResult:
        with Container(id="team-select-container"):
            yield Label("", id="team-select-title")
            yield OptionList(id="team-option-list")
            # Shortcut hint lives inside the dialog box (rather than only in a
            # screen-bottom Footer, which sits far below the centered modal and
            # is easy to miss) so the controls read as part of this screen.
            yield Label(self._HINT, id="team-select-hint")

    def on_mount(self) -> None:
        self._enter_decade_phase()

    # --- Phase setup ----------------------------------------------------

    def _enter_decade_phase(self) -> None:
        self._phase = "decade"
        self._set_title(f"Select {self._role} Team — Decade")
        option_list = self._option_list()
        option_list.clear_options()
        for decade in self._decades:
            option_list.add_option(Option(f"{decade}s", id=f"decade:{decade}"))
        self._focus_list()

    def _enter_year_phase(self, decade: int) -> None:
        self._phase = "year"
        self._chosen_decade = decade
        self._set_title(f"Select {self._role} Team — {decade}s")
        option_list = self._option_list()
        option_list.clear_options()
        for year in self._years:  # already descending
            if year // 10 * 10 == decade:
                option_list.add_option(Option(str(year), id=f"year:{year}"))
        self._focus_list()

    def _enter_team_phase(self, year: int) -> None:
        self._phase = "team"
        self._chosen_year = year
        self._teams = self._repo.get_teams_for_year(year)
        self._set_title(f"Select {self._role} Team — {year}")
        option_list = self._option_list()
        option_list.clear_options()
        for team_id, name in self._teams:
            option_list.add_option(
                Option(f"{name}  [dim]({team_id})[/dim]", id=f"team:{team_id}")
            )
        self._focus_list()

    # --- Helpers --------------------------------------------------------

    def _option_list(self) -> OptionList:
        return self.query_one("#team-option-list", OptionList)

    def _set_title(self, text: str) -> None:
        self.query_one("#team-select-title", Label).update(f"[bold]{text}[/bold]")

    def _focus_list(self) -> None:
        option_list = self._option_list()
        if option_list.option_count:
            option_list.highlighted = 0
        option_list.focus()

    # --- Navigation actions ---------------------------------------------

    def action_cursor_up(self) -> None:
        option_list = self._option_list()
        if option_list.option_count:
            current = option_list.highlighted if option_list.highlighted is not None else 0
            option_list.highlighted = (current - 1) % option_list.option_count

    def action_cursor_down(self) -> None:
        option_list = self._option_list()
        if option_list.option_count:
            current = option_list.highlighted if option_list.highlighted is not None else 0
            option_list.highlighted = (current + 1) % option_list.option_count

    def action_confirm(self) -> None:
        option_list = self._option_list()
        idx = option_list.highlighted
        if idx is None:
            return
        option = option_list.get_option_at_index(idx)
        if option.id:
            self._select(option.id)

    def action_back(self) -> None:
        """Esc: step back one phase, or cancel from the decade phase."""
        if self._phase == "team":
            self._enter_year_phase(self._chosen_decade)
        elif self._phase == "year":
            self._enter_decade_phase()
        else:
            self.dismiss(None)

    # --- Selection routing ----------------------------------------------

    def on_option_list_option_selected(
        self, event: OptionList.OptionSelected
    ) -> None:
        """Mouse double-click / enter on an option."""
        if event.option.id:
            self._select(str(event.option.id))

    def _select(self, option_id: str) -> None:
        kind, _, value = option_id.partition(":")
        if kind == "decade":
            self._enter_year_phase(int(value))
        elif kind == "year":
            self._enter_team_phase(int(value))
        elif kind == "team":
            self.dismiss((value, self._chosen_year))
