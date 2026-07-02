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

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.game.engine import GameEngine
from src.game.state import InningHalf
from src.game.substitutions import SubstitutionManager
from src.tui.screens.game_screen import GameScreen

_DB_PATH = Path(__file__).parent.parent / "data" / "lahman.sqlite"


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


# ---------------------------------------------------------------------------
# _reset_game — replay restores starting pitchers and rebuilds lineups
# ---------------------------------------------------------------------------


class _FakeLog:
    """Stand-in for PlayByPlayLog so _reset_game's log calls are no-ops."""

    def clear(self):
        pass

    def add_inning_divider(self, *args):
        pass


def test_reset_game_restores_starting_pitchers_and_rebuilds_lineup():
    """Replay must restore both starting pitchers into GameState and rebuild
    the lineups.

    Regression test: a played game leaves GameState pitcherless (pitching
    changes live on GameState, not the lineup) and mutates the batting order
    in place via pinch hitters. The old _reset_game built a bare GameState(),
    so a replayed game showed "Unknown" pitchers and kept the prior game's
    pinch hitters in the order.
    """
    if not _DB_PATH.exists():
        pytest.skip("lahman.sqlite not found - run build_lahman_db.py first")

    from src.data.lahman import LahmanRepository
    from src.game.team import Team
    from src.game.lineup_builder import build_lineup, get_default_starter
    from src.game.state import GameState

    with LahmanRepository(str(_DB_PATH)) as repo:
        away = Team.load_from_repository(repo, "NYA", 1927)
        home = Team.load_from_repository(repo, "CHN", 1927)
        away_pid = get_default_starter(away, repo)
        home_pid = get_default_starter(home, repo)
        build_lineup(away, repo, pitcher_id=away_pid)
        build_lineup(home, repo, pitcher_id=home_pid)

        original_leadoff = away.lineup.slots[0].player_id

        mock_self = SimpleNamespace(
            away_team=away,
            home_team=home,
            repo=repo,
            _away_pitcher_id=away_pid,
            _home_pitcher_id=home_pid,
            engine=SimpleNamespace(sub_manager=None),
            sub_manager=SubstitutionManager(),
            # Simulate a finished game: bare (pitcherless) state + dirty trackers.
            game_state=GameState(),
            away_hits=9,
            home_hits=7,
            _current_half_inning=(9, InningHalf.BOTTOM),
            _player_hit_counts={"x": 3},
            _pitcher_consecutive_retired=4,
            _inning_runs=2,
            _batting_lines={"stale": {}},
            _pitching_lines={"stale": {}},
            _pitcher_teams={"stale": "away"},
            _inning_scores=[(1, 0), (0, 2)],
            _away_errors=2,
            _home_errors=1,
            _current_inning_away_runs=1,
            _current_inning_home_runs=1,
            # No manager AI on either side for this regression test.
            _away_ctx=None,
            _home_ctx=None,
        )
        # Bind the real helpers _reset_game depends on; stub widget-touchers.
        mock_self._build_lineups = lambda: GameScreen._build_lineups(mock_self)
        mock_self._reset_sub_manager = lambda: GameScreen._reset_sub_manager(mock_self)
        mock_self._reset_tracking = lambda: GameScreen._reset_tracking(mock_self)
        mock_self._init_stat_lines = lambda: GameScreen._init_stat_lines(mock_self)
        mock_self.query_one = lambda *a, **k: _FakeLog()
        mock_self._update_lineup_cards = lambda: None
        mock_self._update_all_widgets = lambda: None

        # Simulate the prior game's in-place pinch-hitter mutation.
        away.lineup.slots[0].player_id = "PINCH_HITTER_SENTINEL"

        GameScreen._reset_game(mock_self)

        # The reported bug: starting pitchers were lost (None). Now restored.
        assert mock_self.game_state.away_pitcher_id == away_pid
        assert mock_self.game_state.home_pitcher_id == home_pid
        # Fresh game state.
        assert mock_self.game_state.inning == 1
        assert mock_self.game_state.half == InningHalf.TOP
        # Lineup rebuilt: the sentinel pinch hitter is gone, leadoff restored.
        assert away.lineup.slots[0].player_id == original_leadoff
        # Per-game trackers cleared, stat lines re-seeded for the new lineup.
        assert mock_self.away_hits == 0
        assert mock_self.home_hits == 0
        assert mock_self._inning_scores == []
        assert original_leadoff in mock_self._batting_lines
        assert "stale" not in mock_self._batting_lines
