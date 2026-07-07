"""Unit tests for the Load/Resume wiring (FRE-48).

Covers the two ends of the "Load saved game" path, DB-free and Pilot-free in
the house mock-``self`` idiom:

- ``SetupFlow`` — the mode list routes "load" into ``_select_saved_game``, and
  that pushes a ``SaveSelectScreen`` whose result either returns to the menu
  (Esc/None) or forwards the chosen path to ``on_load``.
- ``BaseballSimApp._resume_saved_game`` — the selection→load handler:
  ``load_game`` + ``GameScreen.restore_from`` on success (pushes the restored
  screen, syncs app matchup state), and a visible ``notify`` + return-to-menu on
  any ``SaveError`` (corrupt JSON, wrong schema_version, missing team).
"""

from pathlib import Path
from types import SimpleNamespace

import src.tui.app as app_module
import src.tui.setup_flow as setup_flow_module
from src.game.persistence import CorruptSaveError, MissingTeamError, SaveVersionError
from src.tui.app import BaseballSimApp
from src.tui.game_config import GameConfig
from src.tui.screens.save_select_screen import SaveSelectScreen
from src.tui.setup_flow import SetupFlow


# ---------------------------------------------------------------------------
# SetupFlow: mode routing
# ---------------------------------------------------------------------------


def _push_capture():
    """A stub app whose push_screen records (screen, callback)."""
    pushed = {}
    app = SimpleNamespace(
        push_screen=lambda screen, callback=None: pushed.update(
            screen=screen, callback=callback
        )
    )
    return app, pushed


def test_mode_load_routes_to_select_saved_game():
    calls = {}
    app, pushed = _push_capture()
    mock = SimpleNamespace(
        _app=app,
        _on_cancel=lambda: calls.setdefault("cancel", True),
        _select_control=lambda: calls.setdefault("control", True),
        _select_saved_game=lambda: calls.setdefault("saved", True),
    )

    SetupFlow._select_mode(mock)
    pushed["callback"]("load")

    assert calls == {"saved": True}


def test_mode_single_routes_to_control():
    calls = {}
    app, pushed = _push_capture()
    mock = SimpleNamespace(
        _app=app,
        _on_cancel=lambda: calls.setdefault("cancel", True),
        _select_control=lambda: calls.setdefault("control", True),
        _select_saved_game=lambda: calls.setdefault("saved", True),
    )

    SetupFlow._select_mode(mock)
    pushed["callback"]("single")

    assert calls == {"control": True}
    assert mock._mode_id == "single"


def test_mode_cancel_calls_on_cancel():
    calls = {}
    app, pushed = _push_capture()
    mock = SimpleNamespace(
        _app=app,
        _on_cancel=lambda: calls.setdefault("cancel", True),
        _select_control=lambda: calls.setdefault("control", True),
        _select_saved_game=lambda: calls.setdefault("saved", True),
    )

    SetupFlow._select_mode(mock)
    pushed["callback"](None)

    assert calls == {"cancel": True}


# ---------------------------------------------------------------------------
# SetupFlow._select_saved_game
# ---------------------------------------------------------------------------


def test_select_saved_game_pushes_picker_and_routes_choice(monkeypatch):
    monkeypatch.setattr(setup_flow_module, "saves_dir", lambda: Path("/nonexistent"))
    monkeypatch.setattr(setup_flow_module, "list_save_entries", lambda directory: [])

    calls = {}
    app, pushed = _push_capture()
    mock = SimpleNamespace(
        _app=app,
        _on_load=lambda path: calls.setdefault("loaded", path),
        _select_mode=lambda: calls.setdefault("menu", True),
    )

    SetupFlow._select_saved_game(mock)

    # A SaveSelectScreen was pushed with a result callback.
    assert isinstance(pushed["screen"], SaveSelectScreen)
    callback = pushed["callback"]

    # Backing out returns to the mode menu.
    callback(None)
    assert calls.get("menu") is True

    # Picking a save forwards its path to on_load.
    callback(Path("data/saves/save-x.json"))
    assert calls.get("loaded") == Path("data/saves/save-x.json")


def test_select_saved_game_without_on_load_returns_to_menu(monkeypatch):
    monkeypatch.setattr(setup_flow_module, "saves_dir", lambda: Path("/nonexistent"))
    monkeypatch.setattr(setup_flow_module, "list_save_entries", lambda directory: [])

    calls = {}
    app, pushed = _push_capture()
    mock = SimpleNamespace(
        _app=app,
        _on_load=None,
        _select_mode=lambda: calls.setdefault("menu", True),
    )

    SetupFlow._select_saved_game(mock)

    assert calls == {"menu": True}
    assert "screen" not in pushed  # no picker pushed without a load handler


# ---------------------------------------------------------------------------
# BaseballSimApp._resume_saved_game
# ---------------------------------------------------------------------------


def _resume_mock():
    events = {}
    mock = SimpleNamespace(
        repo=SimpleNamespace(),
        push_screen=lambda screen: events.setdefault("pushed", screen),
        notify=lambda message, **kwargs: events.setdefault("notify", (message, kwargs)),
        start_setup=lambda: events.setdefault("restart", True),
    )
    return mock, events


def test_resume_saved_game_pushes_restored_screen(monkeypatch):
    config = GameConfig(mode="single", away_ai=False, home_ai=True)
    save = SimpleNamespace(game=SimpleNamespace(config=config))
    screen = SimpleNamespace(away_team="AWAY", home_team="HOME")

    monkeypatch.setattr(app_module, "load_game", lambda path: save)
    monkeypatch.setattr(
        app_module.GameScreen, "restore_from", lambda save_arg, repo: screen
    )

    mock, events = _resume_mock()
    BaseballSimApp._resume_saved_game(mock, Path("data/saves/save-x.json"))

    assert events["pushed"] is screen
    assert "notify" not in events
    assert "restart" not in events
    # App matchup state is synced from the save (so a re-save is correct).
    assert mock.config is config
    assert mock._away_team == "AWAY"
    assert mock._home_team == "HOME"
    assert mock.series is None
    assert mock._away_ctx is None and mock._home_ctx is None


def test_resume_saved_game_corrupt_notifies_and_returns_to_menu(monkeypatch):
    def boom(path):
        raise CorruptSaveError("not valid JSON")

    monkeypatch.setattr(app_module, "load_game", boom)

    mock, events = _resume_mock()
    BaseballSimApp._resume_saved_game(mock, Path("data/saves/broken.json"))

    assert "pushed" not in events  # never pushed a game screen
    assert events.get("restart") is True  # returned to the setup menu
    message, kwargs = events["notify"]
    assert "not valid JSON" in message
    assert kwargs["severity"] == "error"


def test_resume_saved_game_wrong_version_notifies(monkeypatch):
    def boom(path):
        raise SaveVersionError("Unsupported save schema_version 2")

    monkeypatch.setattr(app_module, "load_game", boom)

    mock, events = _resume_mock()
    BaseballSimApp._resume_saved_game(mock, Path("data/saves/v2.json"))

    assert "pushed" not in events
    assert events.get("restart") is True
    assert "schema_version" in events["notify"][0]


def test_resume_saved_game_missing_team_notifies(monkeypatch):
    # load_game succeeds; the failure comes from restore_from's team re-hydration.
    save = SimpleNamespace(game=SimpleNamespace(config=GameConfig()))
    monkeypatch.setattr(app_module, "load_game", lambda path: save)

    def boom(save_arg, repo):
        raise MissingTeamError("This save references NYA 1927, which isn't in your local database")

    monkeypatch.setattr(app_module.GameScreen, "restore_from", boom)

    mock, events = _resume_mock()
    BaseballSimApp._resume_saved_game(mock, Path("data/saves/missing.json"))

    assert "pushed" not in events
    assert events.get("restart") is True
    assert "isn't in your local database" in events["notify"][0]
