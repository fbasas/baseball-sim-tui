"""Unit tests for GameScreen substitution-routing helpers.

These tests exercise the two helpers extracted in Phase 06 Plan 03 without
spinning up a Textual App context:

- `GameScreen._is_away_team_for_substitution(sub_type, half)` — pure
  function of its arguments, so we call it as an unbound method on the
  class with `self=None`. All four (sub_type, half) combinations are
  covered.

- `GameScreen._reset_sub_manager(self)` — touches `self.sub_manager` and
  `self.engine`. We mock `self` with a `SimpleNamespace` so we don't have
  to instantiate the full Textual Screen.

These tests prove the replay path (gap 4 / SUBS-03) without needing a
human checkpoint.
"""

from types import SimpleNamespace

import pytest

from src.game.engine import GameEngine
from src.game.state import InningHalf
from src.game.substitutions import SubstitutionManager
from src.tui.screens.game_screen import GameScreen


# ---------------------------------------------------------------------------
# _is_away_team_for_substitution — all four (sub_type, half) combinations
# ---------------------------------------------------------------------------


def test_is_away_team_for_substitution__pitching_change_top():
    """TOP -> home team fields, so home (not away) makes the pitching change."""
    assert GameScreen._is_away_team_for_substitution(
        None, "pitching_change", InningHalf.TOP
    ) is False


def test_is_away_team_for_substitution__pitching_change_bottom():
    """BOTTOM -> away team fields, so away makes the pitching change."""
    assert GameScreen._is_away_team_for_substitution(
        None, "pitching_change", InningHalf.BOTTOM
    ) is True


def test_is_away_team_for_substitution__pinch_hitter_top():
    """TOP -> away team bats, so away makes the pinch hit."""
    assert GameScreen._is_away_team_for_substitution(
        None, "pinch_hitter", InningHalf.TOP
    ) is True


def test_is_away_team_for_substitution__pinch_hitter_bottom():
    """BOTTOM -> home team bats, so home (not away) makes the pinch hit."""
    assert GameScreen._is_away_team_for_substitution(
        None, "pinch_hitter", InningHalf.BOTTOM
    ) is False


def test_is_away_team_for_substitution__unknown_sub_type_raises():
    """An unrecognised sub_type is a programmer error and must raise."""
    with pytest.raises(ValueError, match="Unknown sub_type"):
        GameScreen._is_away_team_for_substitution(
            None, "double_switch", InningHalf.TOP
        )


# ---------------------------------------------------------------------------
# _reset_sub_manager — fresh manager + engine rewired
# ---------------------------------------------------------------------------


def test_reset_sub_manager_creates_fresh_manager_and_rewires_engine():
    """After _reset_sub_manager(), sub_manager is a new instance with empty
    removed_players, and the engine references the same new instance.
    """
    original_manager = SubstitutionManager()
    # Simulate that a previous game removed a player.
    original_manager.removed_players.add("test-player-id")
    assert original_manager.is_player_available("test-player-id") is False

    engine = GameEngine(substitution_manager=original_manager)
    mock_self = SimpleNamespace(sub_manager=original_manager, engine=engine)
    old_manager_id = id(mock_self.sub_manager)

    GameScreen._reset_sub_manager(mock_self)

    # New SubstitutionManager instance
    assert id(mock_self.sub_manager) != old_manager_id
    # Previously-removed player is available again
    assert mock_self.sub_manager.is_player_available("test-player-id") is True
    # Engine re-wired to the new manager (same instance, not just equal)
    assert mock_self.engine.sub_manager is mock_self.sub_manager


def test_reset_sub_manager_with_no_engine_does_not_crash():
    """Defensive: if the engine has not been constructed yet (pre-finalize),
    _reset_sub_manager still replaces sub_manager and leaves engine None.
    """
    mock_self = SimpleNamespace(sub_manager=SubstitutionManager(), engine=None)
    original = mock_self.sub_manager

    GameScreen._reset_sub_manager(mock_self)

    assert mock_self.sub_manager is not original
    assert mock_self.engine is None
