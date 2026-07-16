"""Decade ▸ Year picker for the historical-season setup flow.

A two-phase, keyboard-driven year browser that replaces the flat ~149-item
``ChoiceScreen`` the historical flow used to push. It mirrors the single-game
flow's :class:`~src.tui.screens.team_select_screen.TeamSelectScreen` pattern
minus that screen's third "Team" phase:

  1. Decade phase — pick a decade (``{decade}s``, 2020s … 1870s) to keep the
     year list short.
  2. Year phase   — pick a season within that decade.

Navigation is arrow-key driven: ↑/↓ move the highlight, Enter selects the
highlighted row (and advances to the next phase), and Esc steps back one phase
(decade-phase Esc cancels the whole pick). A ``Decade ▸ Year`` breadcrumb in the
dialog title shows where you are in the flow.

The screen is deliberately **DB-free**: it takes the plain ``List[int]`` of
buildable years the flow already computes (descending, as
``HistoricalSeasonSetupFlow._available_years()`` returns) rather than a repo, so
it unit-tests without a database. It returns the chosen ``year`` (an ``int``)
when a year is picked, or ``None`` if the user backs out of the decade phase.
"""

from typing import Dict, List, Optional

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList
from textual.widgets.option_list import Option


class HistoricalYearSelectScreen(ModalScreen[Optional[int]]):
    """Modal for selecting a historical season year (decade, then year).

    Args:
        years: buildable years, descending ints (as
            ``HistoricalSeasonSetupFlow._available_years()`` returns). No repo is
            taken, so the screen is DB-free and unit-testable.
        default_year: year to land the highlight on when its decade is opened
            (and whose decade is highlighted in the decade phase). Optional.
        notice: an optional **persistent** message rendered as an error-styled
            inline line at the bottom of the modal (only when non-empty; it does
            not auto-dismiss). ``HistoricalSeasonSetupFlow._select_year`` passes
            the actionable "rebuild the database" text here for the
            unresolved-Retrosheet-id build failure (FRE-155), so the reason stays
            visible on the picker the user lands back on. ``None`` (the default)
            shows the picker unadorned.
        cached: an optional ``{year: bool}`` map (``repo.has_schedule`` per
            buildable year) marking each year already-cached (schedule in the
            local DB — picks offline-instantly) vs. needs-a-network-fetch on
            pick. The **year-phase** options render a legible marker
            (``● cached`` / ``↓ fetch``); decade-phase rows are unannotated. A
            year absent from the map (or ``None``, the default) renders bare, so
            the picker is unchanged when no annotation is supplied (FRE-161).
    """

    CSS = """
    HistoricalYearSelectScreen {
        align: center middle;
        background: #0d160d 40%;
    }

    #historical-year-container {
        width: 62;
        height: auto;
        max-height: 90%;
        background: #121f12;
        border: round #d4a843;
        border-title-color: #d4a843;
        border-title-style: bold;
        padding: 1 2;
    }

    #historical-year-title {
        text-align: center;
        width: 100%;
        height: 1;
        color: #d4a843;
    }

    #historical-year-option-list {
        height: auto;
        max-height: 16;
        width: 100%;
        margin: 1 0 0 0;
        background: #121f12;
        border: none;
    }

    #historical-year-hint {
        text-align: center;
        width: 100%;
        height: 1;
        margin: 1 0 0 0;
        color: #6b7d6b;
    }

    #historical-year-notice {
        width: 100%;
        height: auto;
        margin: 1 0 0 0;
        padding: 1 1 0 1;
        border-top: solid #5a3030;
        color: #e69a9a;
        text-align: center;
    }
    """

    # No ``q`` quit: the flat ChoiceScreen this replaces had none. The in-box
    # hint and option styling still match TeamSelectScreen so the two read as
    # one system.
    _HINT = (
        "[#d4a843]↑/↓[/] navigate   [#d4a843]Enter[/] select   "
        "[#d4a843]Esc[/] back"
    )

    BINDINGS = [
        # priority so they fire (and show in the footer) at the screen level
        # rather than being shadowed by the focused OptionList's own bindings.
        Binding("up", "cursor_up", "Up", priority=True),
        Binding("down", "cursor_down", "Down", priority=True),
        Binding("enter", "confirm", "Select", priority=True),
        Binding("escape", "back", "Back"),
    ]

    def __init__(
        self,
        years: List[int],
        default_year: Optional[int] = None,
        notice: Optional[str] = None,
        cached: Optional[Dict[int, bool]] = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._years: List[int] = list(years)  # already descending
        self._default_year = default_year
        self._notice = notice
        self._cached: Dict[int, bool] = dict(cached) if cached else {}
        self._decades: List[int] = sorted(
            {y // 10 * 10 for y in self._years}, reverse=True
        )
        self._phase = "decade"  # "decade" | "year"
        self._chosen_decade: Optional[int] = None

    def compose(self) -> ComposeResult:
        with Container(id="historical-year-container"):
            yield Label("", id="historical-year-title")
            yield OptionList(id="historical-year-option-list")
            # Shortcut hint lives inside the dialog box (rather than only in a
            # screen-bottom Footer, which sits far below the centered modal and
            # is easy to miss) so the controls read as part of this screen.
            yield Label(self._HINT, id="historical-year-hint")
            # A persistent, error-styled failure line (e.g. the unresolved-id
            # rebuild message from FRE-155) — composed only when present so the
            # unadorned picker is unchanged. Mirrors ChoiceScreen's #choice-notice.
            if self._notice:
                yield Label(self._notice, id="historical-year-notice")

    def on_mount(self) -> None:
        container = self.query_one("#historical-year-container", Container)
        container.border_title = "⚾ HISTORICAL SEASON"
        self._enter_decade_phase()

    def _breadcrumb(self) -> str:
        """Render the Decade ▸ Year trail with the current phase lit."""
        crumbs = []
        for phase, label in (
            ("decade", f"{self._chosen_decade}s" if self._chosen_decade else "Decade"),
            ("year", "Year"),
        ):
            if phase == self._phase:
                crumbs.append(f"[bold #d4a843]{label}[/]")
            else:
                crumbs.append(f"[#6b7d6b]{label}[/]")
        return " [#3e5c40]▸[/] ".join(crumbs)

    # --- Phase setup ----------------------------------------------------

    def _enter_decade_phase(self) -> None:
        self._phase = "decade"
        self._chosen_decade = None
        self._set_title(self._breadcrumb())
        option_list = self._option_list()
        option_list.clear_options()
        for decade in self._decades:
            option_list.add_option(Option(f"{decade}s", id=f"decade:{decade}"))
        self._focus_list(self._default_decade())

    def _enter_year_phase(self, decade: int) -> None:
        self._phase = "year"
        self._chosen_decade = decade
        self._set_title(self._breadcrumb())
        option_list = self._option_list()
        option_list.clear_options()
        years_in_decade = [y for y in self._years if y // 10 * 10 == decade]
        for year in years_in_decade:  # already descending
            option_list.add_option(
                Option(self._year_prompt(year), id=f"year:{year}")
            )
        # Land on the default year when it lives in this decade, else the top.
        default_index = (
            years_in_decade.index(self._default_year)
            if self._default_year in years_in_decade
            else 0
        )
        self._focus_list(default_index)

    # --- Helpers --------------------------------------------------------

    def _decades_list(self) -> List[int]:
        """The decades offered, descending (exposed for direct unit tests)."""
        return self._decades

    def _years_in_decade(self, decade: int) -> List[int]:
        """Years of ``self._years`` in ``decade``, descending (unit-test seam)."""
        return [y for y in self._years if y // 10 * 10 == decade]

    def _year_prompt(self, year: int) -> str:
        """Year-option label, with the cached/fetch marker when annotated.

        ``● cached`` (in-DB, offline-instant pick) vs. ``↓ fetch`` (needs a
        network download on pick), driven by the ``cached`` map the flow builds
        from ``repo.has_schedule``. A year with no entry (or no map at all)
        renders bare — the unannotated picker is unchanged (FRE-161).
        """
        if year not in self._cached:
            return str(year)
        if self._cached[year]:
            # In-DB already: a green dot in the panel's accent, "cached" dimmed.
            return f"{year}  [#3e5c40]●[/] [dim]cached[/dim]"
        # Needs a network fetch on pick: a gold down-arrow, "fetch" dimmed.
        return f"{year}  [#d4a843]↓[/] [dim]fetch[/dim]"

    def _default_decade(self) -> int:
        """Index of the default year's decade in the decade list (else 0)."""
        if self._default_year is None:
            return 0
        decade = self._default_year // 10 * 10
        return self._decades.index(decade) if decade in self._decades else 0

    def _option_list(self) -> OptionList:
        return self.query_one("#historical-year-option-list", OptionList)

    def _set_title(self, text: str) -> None:
        self.query_one("#historical-year-title", Label).update(text)

    def _focus_list(self, index: int = 0) -> None:
        option_list = self._option_list()
        if option_list.option_count:
            option_list.highlighted = index
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
        if self._phase == "year":
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
            self.dismiss(int(value))
