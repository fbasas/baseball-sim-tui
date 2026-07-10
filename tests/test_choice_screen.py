"""Unit tests for the opt-in ``q → quit`` binding on ChoiceScreen (FRE-99).

DB-free and Pilot-free, in the house idioms:

- action / gating handlers driven with a ``types.SimpleNamespace`` standing in
  for ``self`` and a captured ``dismiss`` (mirroring ``test_save_select_screen``);
- the hint string read straight off a real ``ChoiceScreen`` (no app needed);
- ``SetupFlow`` mode/control routing driven through a ``FakeApp`` that records
  each ``push_screen(screen, callback)`` (mirroring ``test_season_setup_flow``).

Covers the definition of done: ``action_quit`` dismisses ``None``; ``check_action``
gates ``quit`` on ``allow_quit`` while leaving other actions enabled; the hint
advertises ``q`` only when opted in; ``_select_mode`` opts in and ``_select_control``
does not.
"""

from types import SimpleNamespace

from src.tui.screens.choice_screen import ChoiceScreen
from src.tui.setup_flow import SetupFlow

_CHOICES = [("a", "Alpha"), ("b", "Bravo")]


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


# ---------------------------------------------------------------------------
# action_quit — dismisses None (routes through the flow's cancel path)
# ---------------------------------------------------------------------------


def test_action_quit_dismisses_none():
    captured = []
    mock = SimpleNamespace(dismiss=lambda result=None: captured.append(result))

    ChoiceScreen.action_quit(mock)

    assert captured == [None]


# ---------------------------------------------------------------------------
# check_action — gates the quit key on allow_quit, leaves others enabled
# ---------------------------------------------------------------------------


def test_check_action_quit_enabled_when_allow_quit():
    mock = SimpleNamespace(_allow_quit=True)
    assert ChoiceScreen.check_action(mock, "quit", ()) is True


def test_check_action_quit_hidden_when_not_allow_quit():
    mock = SimpleNamespace(_allow_quit=False)
    # None both disables and hides the binding (Textual convention).
    assert ChoiceScreen.check_action(mock, "quit", ()) is None


def test_check_action_non_quit_always_enabled():
    for allow_quit in (True, False):
        mock = SimpleNamespace(_allow_quit=allow_quit)
        assert ChoiceScreen.check_action(mock, "confirm", ()) is True
        assert ChoiceScreen.check_action(mock, "use_default", ()) is True


# ---------------------------------------------------------------------------
# Hint text — advertises q only when opted in
# ---------------------------------------------------------------------------


def test_hint_includes_quit_affordance_when_allow_quit():
    screen = ChoiceScreen("T", "P", _CHOICES, allow_quit=True)
    hint = screen._hint_text
    assert "q[/] quit" in hint
    # The base hint is preserved, unchanged.
    assert ChoiceScreen._HINT in hint


def test_hint_excludes_quit_affordance_by_default():
    screen = ChoiceScreen("T", "P", _CHOICES)
    assert screen._hint_text == ChoiceScreen._HINT
    assert "quit" not in screen._hint_text


# ---------------------------------------------------------------------------
# ChoiceScreen defaults — allow_quit is opt-in
# ---------------------------------------------------------------------------


def test_allow_quit_defaults_false():
    assert ChoiceScreen("T", "P", _CHOICES)._allow_quit is False


# ---------------------------------------------------------------------------
# SetupFlow routing — mode menu opts in, control question does not
# ---------------------------------------------------------------------------


def test_select_mode_pushes_screen_with_allow_quit_true():
    app = FakeApp()
    flow = _make_setup_flow(app)

    flow._select_mode()

    assert isinstance(app.last_screen, ChoiceScreen)
    assert app.last_screen._title == "⚾ GAME MODE"
    assert app.last_screen._allow_quit is True


def test_select_control_pushes_screen_with_allow_quit_false():
    app = FakeApp()
    flow = _make_setup_flow(app)

    flow._select_mode()
    # Pick a non-branching mode id -> flow advances to the control question.
    app.last_callback("single")

    assert isinstance(app.last_screen, ChoiceScreen)
    assert app.last_screen._title == "⚾ MANAGER CONTROL"
    assert app.last_screen._allow_quit is False
