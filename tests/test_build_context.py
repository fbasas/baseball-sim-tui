"""Tests for ``BaseballSimApp._build_context`` role-card loading (FRE-176).

``_build_context`` loads an AI side's role card with no in-process rebuild
(unlike season rehydrate). After the schema-v2 bump a card left on disk by an
older build is a v1 card, which raises ``RoleCardVersionError`` on load. This
must be treated exactly like a missing card — notify the user and fall back to
manual control — not escape the guard and crash the game. Reached from the
exhibition/quick-game AI path (``_on_setup_complete``) and series resume
(``_restore_series_game``), neither of which runs a rebuild pass first.

Mock-``self`` unit tests in the house style (no Pilot, no DB).
"""

from types import SimpleNamespace

import pytest

import src.tui.app as app_module
from src.tui.app import BaseballSimApp
from src.manager.roles import RoleCardVersionError


def _make_team(team_id: str = "NYA", year: int = 1927, name: str = "Yankees"):
    """A stand-in Team exposing only what ``_build_context`` reads."""
    return SimpleNamespace(
        info=SimpleNamespace(team_id=team_id, year=year, team_name=name)
    )


def _mock_self():
    notifications = []
    mock = SimpleNamespace()
    mock.notify = lambda msg, **kwargs: notifications.append((msg, kwargs))
    mock._notifications = notifications
    return mock


def test_stale_v1_card_falls_back_to_manual(monkeypatch):
    """A stale-schema card on disk drives the manual-fallback branch.

    Post-bump, ``load_manager_for_team`` raises ``RoleCardVersionError`` (a
    ``ValueError``, *not* ``FileNotFoundError``); ``_build_context`` must catch
    it, notify, and return ``None`` rather than propagate the crash.
    """
    def raise_stale(team):
        raise RoleCardVersionError(
            "Unsupported role card schema_version 1 (expected 2)"
        )

    monkeypatch.setattr(app_module, "load_manager_for_team", raise_stale)

    mock = _mock_self()
    result = BaseballSimApp._build_context(mock, _make_team(), want_ai=True)

    assert result is None
    assert len(mock._notifications) == 1
    msg, kwargs = mock._notifications[0]
    assert "manual control" in msg
    assert kwargs.get("severity") == "warning"


def test_missing_card_still_falls_back_to_manual(monkeypatch):
    """The pre-existing ``FileNotFoundError`` fallback is unchanged."""
    def raise_missing(team):
        raise FileNotFoundError("no role card")

    monkeypatch.setattr(app_module, "load_manager_for_team", raise_missing)

    mock = _mock_self()
    result = BaseballSimApp._build_context(mock, _make_team(), want_ai=True)

    assert result is None
    assert len(mock._notifications) == 1


def test_loaded_card_yields_a_context(monkeypatch):
    """A card that loads cleanly returns a manager context (no notify)."""
    sentinel = object()
    monkeypatch.setattr(
        app_module, "load_manager_for_team", lambda team: sentinel
    )
    monkeypatch.setattr(
        app_module, "TeamManagerContext", lambda manager: ("ctx", manager)
    )

    mock = _mock_self()
    result = BaseballSimApp._build_context(mock, _make_team(), want_ai=True)

    assert result == ("ctx", sentinel)
    assert mock._notifications == []


def test_no_ai_side_returns_none_without_loading(monkeypatch):
    """A non-AI side never touches the loader."""
    def fail(team):  # pragma: no cover - must not be called
        raise AssertionError("should not load a card for a manual side")

    monkeypatch.setattr(app_module, "load_manager_for_team", fail)

    mock = _mock_self()
    assert BaseballSimApp._build_context(mock, _make_team(), want_ai=False) is None
    assert mock._notifications == []
