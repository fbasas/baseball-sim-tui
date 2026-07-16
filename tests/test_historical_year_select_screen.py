"""Unit tests for the Decade ▸ Year historical year picker (FRE-160).

DB-free and Pilot-free, in the house idiom (mirrors
``tests/test_save_select_screen.py``): a mix of

- **pure-logic** assertions on a directly-constructed screen (decade grouping
  from a year list, per-decade year filtering, default-year → decade index, the
  lit-phase breadcrumb) — none of these touch a widget; and
- **mock-``self``** drives of the phase/selection handlers
  (``_enter_decade_phase`` / ``_enter_year_phase`` / ``_select`` /
  ``action_confirm`` / ``action_back``) with a ``types.SimpleNamespace`` standing
  in for ``self``, a fake OptionList recording the options each phase adds, and a
  captured ``dismiss`` — so phase transitions and the returned ``int`` are asserted
  without standing up a Textual app.

The one exception is the persistent ``notice`` line (the FRE-155 unresolved-id
failure seam this screen renders, folded in per FRE-165): its storage is asserted
directly, and because ``compose`` needs a live app, a single mounted ``run_test``
check (driven with ``asyncio.run``, no ``pytest-asyncio`` — the repo idiom from
``tests/test_global_quit.py``) proves the line is composed only when non-empty.
"""

import asyncio
from types import SimpleNamespace

from textual.app import App
from textual.widgets import Label

from src.tui.screens.historical_year_select_screen import HistoricalYearSelectScreen


# A spread of years across several decades, descending (as the flow feeds it).
_YEARS = [2016, 1999, 1998, 1927, 1925, 1906, 1901]


# ---------------------------------------------------------------------------
# Fixtures / factories
# ---------------------------------------------------------------------------


class _FakeOptionList:
    """Records the ``Option``s each phase adds; carries a ``highlighted`` index."""

    def __init__(self):
        self._options = []
        self.highlighted = None
        self.focused = False

    def clear_options(self):
        self._options = []

    def add_option(self, option):
        self._options.append(option)

    @property
    def option_count(self):
        return len(self._options)

    def get_option_at_index(self, idx):
        return self._options[idx]

    def focus(self):
        self.focused = True

    @property
    def ids(self):
        return [opt.id for opt in self._options]


def _mock_screen(years=_YEARS, default_year=None):
    """A mock-``self`` for the phase/selection handlers.

    Returns ``(mock, state)`` where ``state`` collects side effects: the fake
    ``option_list``, recorded ``titles`` / ``focused`` indices, and ``dismissed``
    results. The widget-touching leaves (``_option_list`` / ``_set_title`` /
    ``_focus_list`` / ``dismiss``) are stubbed; every phase/selection method under
    test is lambda-bound to the real implementation (house style).
    """
    cls = HistoricalYearSelectScreen
    option_list = _FakeOptionList()
    state = SimpleNamespace(
        option_list=option_list, titles=[], focused=[], dismissed=[]
    )
    mock = SimpleNamespace(
        _years=list(years),
        _default_year=default_year,
        _decades=sorted({y // 10 * 10 for y in years}, reverse=True),
        _phase="decade",
        _chosen_decade=None,
    )
    mock._option_list = lambda: option_list
    mock._set_title = lambda text: state.titles.append(text)
    mock._focus_list = lambda index=0: state.focused.append(index)
    mock.dismiss = lambda result=None: state.dismissed.append(result)
    # Real methods under test, bound to the mock self.
    mock._breadcrumb = lambda: cls._breadcrumb(mock)
    mock._default_decade = lambda: cls._default_decade(mock)
    mock._enter_decade_phase = lambda: cls._enter_decade_phase(mock)
    mock._enter_year_phase = lambda decade: cls._enter_year_phase(mock, decade)
    mock._select = lambda option_id: cls._select(mock, option_id)
    mock.action_confirm = lambda: cls.action_confirm(mock)
    mock.action_back = lambda: cls.action_back(mock)
    return mock, state


# ---------------------------------------------------------------------------
# Pure logic (directly-constructed screen; no widgets touched)
# ---------------------------------------------------------------------------


def test_decades_grouped_descending():
    screen = HistoricalYearSelectScreen(_YEARS)
    # One entry per distinct decade present, most-recent-first.
    assert screen._decades == [2010, 1990, 1920, 1900]


def test_single_decade_when_all_years_share_one():
    screen = HistoricalYearSelectScreen([1929, 1927, 1920])
    assert screen._decades == [1920]


def test_years_in_decade_filters_and_stays_descending():
    screen = HistoricalYearSelectScreen(_YEARS)
    assert screen._years_in_decade(1920) == [1927, 1925]
    assert screen._years_in_decade(1990) == [1999, 1998]
    assert screen._years_in_decade(2010) == [2016]
    # A decade with no years present yields an empty list.
    assert screen._years_in_decade(1950) == []


def test_default_decade_indexes_the_default_years_decade():
    screen = HistoricalYearSelectScreen(_YEARS, default_year=1927)
    # 1927 -> the 1920s, which is index 2 in [2010, 1990, 1920, 1900].
    assert screen._default_decade() == 2


def test_default_decade_falls_back_to_zero():
    # No default -> the top (most recent) decade.
    assert HistoricalYearSelectScreen(_YEARS)._default_decade() == 0
    # A default whose decade isn't present -> the top, not a crash.
    assert HistoricalYearSelectScreen(_YEARS, default_year=1975)._default_decade() == 0


def test_breadcrumb_lights_the_active_phase():
    screen = HistoricalYearSelectScreen(_YEARS)
    # Decade phase: the "Decade" crumb is lit (bold gold), "Year" is a placeholder.
    decade_crumb = screen._breadcrumb()
    assert "[bold #d4a843]Decade[/]" in decade_crumb
    assert "Year" in decade_crumb and "[bold #d4a843]Year[/]" not in decade_crumb
    # Year phase for the 1920s: the decade crumb shows "1920s", "Year" is lit.
    screen._phase = "year"
    screen._chosen_decade = 1920
    year_crumb = screen._breadcrumb()
    assert "1920s" in year_crumb
    assert "[bold #d4a843]Year[/]" in year_crumb


# ---------------------------------------------------------------------------
# Decade phase (mock-self)
# ---------------------------------------------------------------------------


def test_enter_decade_phase_lists_decades_descending():
    mock, state = _mock_screen(default_year=1927)
    mock._enter_decade_phase()

    assert mock._phase == "decade"
    assert mock._chosen_decade is None
    assert state.option_list.ids == [
        "decade:2010",
        "decade:1990",
        "decade:1920",
        "decade:1900",
    ]
    # Highlight lands on the default year's decade (1920s -> index 2).
    assert state.focused == [2]


def test_select_decade_advances_to_year_phase():
    mock, state = _mock_screen()
    mock._select("decade:1920")

    assert mock._phase == "year"
    assert mock._chosen_decade == 1920
    # Only the chosen decade's years, descending.
    assert state.option_list.ids == ["year:1927", "year:1925"]
    assert state.dismissed == []  # advancing a phase never dismisses


# ---------------------------------------------------------------------------
# Year phase (mock-self)
# ---------------------------------------------------------------------------


def test_year_phase_highlights_the_default_year():
    mock, state = _mock_screen(default_year=1925)
    mock._enter_year_phase(1920)

    # 1925 is the second (index 1) year in the 1920s [1927, 1925].
    assert state.option_list.ids == ["year:1927", "year:1925"]
    assert state.focused == [1]


def test_year_phase_defaults_to_top_when_default_outside_decade():
    mock, state = _mock_screen(default_year=1999)
    mock._enter_year_phase(1920)  # default 1999 isn't in the 1920s

    assert state.focused == [0]


def test_select_year_dismisses_that_int():
    mock, state = _mock_screen()
    mock._enter_year_phase(1920)
    mock._select("year:1927")

    assert state.dismissed == [1927]
    # The DoD: the value handed back is an int, not the "year:1927" id string.
    (result,) = state.dismissed
    assert isinstance(result, int)


def test_confirm_selects_the_highlighted_year():
    mock, state = _mock_screen()
    mock._enter_year_phase(1990)  # options: 1999, 1998
    state.option_list.highlighted = 1  # 1998
    mock.action_confirm()

    assert state.dismissed == [1998]


def test_confirm_on_a_decade_advances_rather_than_dismisses():
    mock, state = _mock_screen()
    mock._enter_decade_phase()
    state.option_list.highlighted = 2  # the 1920s row
    mock.action_confirm()

    assert mock._phase == "year"
    assert mock._chosen_decade == 1920
    assert state.dismissed == []


# ---------------------------------------------------------------------------
# Esc: step back / cancel (mock-self)
# ---------------------------------------------------------------------------


def test_esc_from_year_steps_back_to_decade():
    mock, state = _mock_screen()
    mock._enter_year_phase(1920)
    assert mock._phase == "year"

    mock.action_back()

    assert mock._phase == "decade"
    # The decade list is repopulated; nothing is dismissed (it's a step-back).
    assert state.option_list.ids == [
        "decade:2010",
        "decade:1990",
        "decade:1920",
        "decade:1900",
    ]
    assert state.dismissed == []


def test_esc_from_decade_cancels_with_none():
    mock, state = _mock_screen()
    mock._enter_decade_phase()

    mock.action_back()

    assert state.dismissed == [None]


# ---------------------------------------------------------------------------
# Persistent notice — stored, and composed only when non-empty. FRE-155's
# unresolved-Retrosheet-id failure line renders on this screen (FRE-165 folded
# the screen-side seam into FRE-160); the flow passes it via _select_year.
# ---------------------------------------------------------------------------


def test_notice_defaults_none():
    # The picker is unadorned unless a caller passes a failure message.
    assert HistoricalYearSelectScreen(_YEARS)._notice is None


def test_notice_stored_when_given():
    screen = HistoricalYearSelectScreen(_YEARS, notice="rebuild the database")
    assert screen._notice == "rebuild the database"


class _HostApp(App):
    """Minimal host that mounts a single modal, to exercise its ``compose``."""

    def __init__(self, modal):
        super().__init__()
        self._modal = modal

    def on_mount(self) -> None:
        self.push_screen(self._modal)


def _rendered_notice(notice):
    """Mount the screen and return the ``#historical-year-notice`` line's text,
    or ``None`` when the line isn't composed (DB-free; drives the screen directly
    via a one-modal host app, the repo's ``asyncio.run`` + ``run_test`` idiom)."""

    async def _run():
        screen = HistoricalYearSelectScreen(_YEARS, default_year=1927, notice=notice)
        app = _HostApp(screen)
        async with app.run_test():
            lines = screen.query("#historical-year-notice")
            return str(lines.first(Label).render()) if lines else None

    return asyncio.run(_run())


def test_notice_line_renders_when_non_empty():
    text = _rendered_notice("Couldn't build 1927 — rebuild via build_lahman_db.py")
    assert text is not None
    assert "build_lahman_db.py" in text  # the actionable message reaches the line


def test_notice_line_absent_when_none():
    # No notice -> no error line composed at all (the picker stays unadorned).
    assert _rendered_notice(None) is None
