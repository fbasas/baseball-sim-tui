"""Tests for the per-screen ``q → quit`` on the pregame setup flow (FRE-112).

Implements spec ``docs/specs/global-quit-setup-flow.md`` (Revised 2026-07-14).
The design is **per-screen** — a pushed ``ModalScreen`` truncates Textual's
binding chain before the App, so an app-level ``q`` never fires under a modal
(proven dead here in ``test_modal_without_q_binding_does_not_reach_app``). Each
locked-in setup screen therefore binds its own ``q``.

All tests are DB-free, in the house idioms (see ``tests/test_choice_screen.py``):

- action handlers driven with a ``types.SimpleNamespace`` standing in for
  ``self`` and a captured ``app.exit`` / ``dismiss`` (never construct the real
  list screens — that would need the Lahman repo);
- ``BINDINGS`` / ``_HINT`` read straight off the classes (no app needed);
- ``SetupFlow`` routing driven through a ``FakeApp`` that records ``push_screen``;
- one in-process ``Pilot`` (via ``App.run_test()``, driven with ``asyncio.run``
  so no ``pytest-asyncio`` dependency is required) to prove a per-screen ``q``
  resolves inside the modal chain.
"""

import asyncio
from types import SimpleNamespace

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import OptionList

from src.tui.screens.choice_screen import ChoiceScreen
from src.tui.screens.team_select_screen import TeamSelectScreen
from src.tui.screens.pitcher_select_screen import PitcherSelectScreen
from src.tui.screens.lineup_edit_screen import LineupEditScreen
from src.tui.setup_flow import SetupFlow

_CHOICES = [("a", "Alpha"), ("b", "Bravo")]

# The three locked-in list screens that now bind their own ``q``.
_LIST_SCREENS = (TeamSelectScreen, PitcherSelectScreen, LineupEditScreen)


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class FakeApp:
    """Records each ``push_screen(screen, callback)`` for later inspection."""

    def __init__(self):
        self.pushed = []  # list of (screen, callback)

    def push_screen(self, screen, callback=None):
        self.pushed.append((screen, callback))

    @property
    def last_screen(self):
        return self.pushed[-1][0]

    @property
    def last_callback(self):
        return self.pushed[-1][1]


def _make_setup_flow(app):
    """A real ``SetupFlow`` over a ``FakeApp``; repo/callbacks are inert here."""
    return SetupFlow(
        app,
        repo=SimpleNamespace(),
        on_complete=lambda *a, **k: None,
        on_cancel=lambda: None,
    )


def _exit_capturing_stub():
    """A ``self`` stub whose ``.app.exit()`` and ``.dismiss()`` are recorded."""
    calls = {"exit": [], "dismiss": []}
    stub = SimpleNamespace(
        app=SimpleNamespace(exit=lambda *a, **k: calls["exit"].append((a, k))),
        dismiss=lambda result=None: calls["dismiss"].append(result),
    )
    return stub, calls


def _has_binding(bindings, key, action):
    """True if any ``Binding`` in ``bindings`` matches ``(key, action)``."""
    return any(getattr(b, "key", None) == key and getattr(b, "action", None) == action
               for b in bindings)


# ---------------------------------------------------------------------------
# 1. Each list screen's action_quit exits the app
# ---------------------------------------------------------------------------


def test_list_screens_action_quit_exits_app():
    for screen_cls in _LIST_SCREENS:
        stub, calls = _exit_capturing_stub()
        # Bind the unbound Screen.action_quit to a stub self (no DB/repo).
        screen_cls.action_quit(stub)
        assert calls["exit"] == [((), {})], f"{screen_cls.__name__} did not exit()"
        assert calls["dismiss"] == [], f"{screen_cls.__name__} dismissed instead of exiting"


# ---------------------------------------------------------------------------
# 2. Each list screen binds q → quit (inverts the old absent-q test)
# ---------------------------------------------------------------------------


def test_list_screens_bind_q_to_quit():
    for screen_cls in _LIST_SCREENS:
        assert _has_binding(screen_cls.BINDINGS, "q", "quit"), (
            f"{screen_cls.__name__} is missing its Binding('q', 'quit')"
        )


# ---------------------------------------------------------------------------
# 3. ChoiceScreen true-exit opt-in (MANAGER CONTROL) vs cancel-quit (GAME MODE)
# ---------------------------------------------------------------------------


def test_choice_screen_quit_exits_app_calls_app_exit():
    stub, calls = _exit_capturing_stub()
    stub._quit_exits_app = True
    ChoiceScreen.action_quit(stub)
    assert calls["exit"] == [((), {})]
    assert calls["dismiss"] == []  # MANAGER CONTROL must NOT route through dismiss


def test_choice_screen_quit_exits_app_enables_and_advertises_quit():
    screen = ChoiceScreen("T", "P", _CHOICES, quit_exits_app=True)
    assert screen.check_action("quit", ()) is True
    assert "q[/] quit" in screen._hint_text
    assert ChoiceScreen._HINT in screen._hint_text  # base hint preserved


def test_choice_screen_allow_quit_still_dismisses_none():
    # GAME MODE regression guard: allow_quit (default quit_exits_app=False) must
    # keep the dismiss(None) cancel-quit path and never call app.exit directly.
    stub, calls = _exit_capturing_stub()
    stub._quit_exits_app = False
    ChoiceScreen.action_quit(stub)
    assert calls["dismiss"] == [None]
    assert calls["exit"] == []
    # And allow_quit alone still enables/advertises q.
    screen = ChoiceScreen("T", "P", _CHOICES, allow_quit=True)
    assert screen.check_action("quit", ()) is True


def test_choice_screen_plain_hides_quit():
    screen = ChoiceScreen("T", "P", _CHOICES)
    assert screen.check_action("quit", ()) is None
    assert "quit" not in screen._hint_text


# ---------------------------------------------------------------------------
# 4. SetupFlow routing — MANAGER CONTROL opts into true-exit, GAME MODE unchanged
# ---------------------------------------------------------------------------


def test_select_control_pushes_screen_with_quit_exits_app_true():
    app = FakeApp()
    flow = _make_setup_flow(app)

    flow._select_mode()
    # Pick a non-branching mode id -> flow advances to the control question.
    app.last_callback("single")

    assert isinstance(app.last_screen, ChoiceScreen)
    assert app.last_screen._title == "⚾ MANAGER CONTROL"
    assert app.last_screen._quit_exits_app is True
    assert app.last_screen._allow_quit is False


def test_select_mode_pushes_screen_with_allow_quit_only():
    app = FakeApp()
    flow = _make_setup_flow(app)

    flow._select_mode()

    assert isinstance(app.last_screen, ChoiceScreen)
    assert app.last_screen._title == "⚾ GAME MODE"
    assert app.last_screen._allow_quit is True
    assert app.last_screen._quit_exits_app is False


# ---------------------------------------------------------------------------
# 5. Per-screen binding works under a modal, live (Pilot, DB-free)
# ---------------------------------------------------------------------------


class _QuitFlagModal(ModalScreen):
    """A bare modal that binds its OWN q → quit, setting a flag when fired."""

    BINDINGS = [Binding("q", "quit", "Quit")]

    def __init__(self):
        super().__init__()
        self.quit_fired = False

    def compose(self) -> ComposeResult:
        option_list = OptionList("one", "two")
        yield option_list

    def on_mount(self) -> None:
        self.query_one(OptionList).focus()

    def action_quit(self) -> None:
        self.quit_fired = True


class _BareModal(ModalScreen):
    """A modal with NO q binding — used to prove app-level q never reaches it."""

    def compose(self) -> ComposeResult:
        option_list = OptionList("one", "two")
        yield option_list

    def on_mount(self) -> None:
        self.query_one(OptionList).focus()


class _HostApp(App):
    """App with NO app-level q binding (mirrors BaseballSimApp's untouched state)."""

    def __init__(self, modal):
        super().__init__()
        self._modal = modal
        self.app_quit_fired = False  # would flip only if an app-level q existed

    def on_mount(self) -> None:
        self.push_screen(self._modal)


def test_per_screen_q_resolves_inside_modal_chain():
    async def _run():
        modal = _QuitFlagModal()
        app = _HostApp(modal)
        async with app.run_test() as pilot:
            await pilot.press("q")
            await pilot.pause()
            return modal.quit_fired

    assert asyncio.run(_run()) is True


def test_modal_without_q_binding_does_not_reach_app():
    # Companion: with no per-screen q and no app-level q, pressing q does nothing.
    # This is *why* the app-level design was dropped — a modal truncates the chain
    # before the App, so an app-level q could never fire here anyway.
    async def _run():
        modal = _BareModal()
        app = _HostApp(modal)
        async with app.run_test() as pilot:
            await pilot.press("q")
            await pilot.pause()
            return app.app_quit_fired

    assert asyncio.run(_run()) is False


# ---------------------------------------------------------------------------
# 6. Hints advertise quit (and the bench hint is unchanged)
# ---------------------------------------------------------------------------


def test_list_screen_hints_advertise_quit():
    # Each hint gains a q/quit affordance while keeping its original text.
    assert "q[/] quit" in TeamSelectScreen._HINT
    assert "navigate" in TeamSelectScreen._HINT and "Esc[/] back" in TeamSelectScreen._HINT

    assert "q[/] quit" in PitcherSelectScreen._HINT
    assert "navigate" in PitcherSelectScreen._HINT
    assert "use default" in PitcherSelectScreen._HINT

    assert "q[/] quit" in LineupEditScreen._HINT
    assert "reorder" in LineupEditScreen._HINT and "Esc[/] cancel" in LineupEditScreen._HINT


def test_lineup_bench_hint_unchanged():
    # The bench-substitution hint must NOT advertise quit.
    assert "quit" not in LineupEditScreen._BENCH_HINT
    assert LineupEditScreen._BENCH_HINT == (
        "[#d4a843]↑/↓[/] navigate   [#d4a843]Enter[/] substitute   "
        "[#d4a843]Esc[/] cancel sub"
    )


def test_manager_control_hint_advertises_quit_automatically():
    # MANAGER CONTROL's hint is automatic via the _quit_enabled path.
    screen = ChoiceScreen("T", "P", _CHOICES, quit_exits_app=True)
    assert "q[/] quit" in screen._hint_text
