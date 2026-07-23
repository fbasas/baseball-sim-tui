"""Tests for the GameScreen restore/resume path (FRE-47).

Two layers, matching the house style (mock-``self``, no Textual ``Pilot``):

  * **Pure unit tests (no DB)** of the injection logic —
    ``_apply_restored_state`` / ``_restore_box_score`` / ``_finalize_restore``
    and the ``_finalize_game_setup`` routing guard — driven with a
    ``SimpleNamespace`` mock ``self`` and the synthetic ``make_snapshot``
    factory from ``tests/test_persistence.py``. These prove the restore injects
    engine/state/box/RNG, preserves substitution invariants, and — critically —
    does NOT run the fresh-game rebuild that would clobber restored state.

  * **DB-guarded integration test** (skipped when ``data/lahman.sqlite`` is
    absent) proving the determinism acceptance bar: a game advanced K at-bats,
    saved to disk, reloaded and restored, whose next ``_advance_one()`` yields
    the identical outcome + resulting ``GameState`` as the un-saved control's
    next ``_advance_one()``.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.game.engine import GameEngine
from src.game.persistence import (
    BoxScore,
    GameSnapshot,
    SaveFile,
    TeamRef,
    capture_rng,
    load_game,
    restore_rng,
    save_game,
)
from src.game.state import GameState, InningHalf
from src.game.substitutions import SubstitutionManager
from src.simulation.rng import SimulationRNG
from src.tui.game_config import GameConfig
from src.tui.screens.game_screen import GameScreen

# Reuse the synthetic FRE-45 snapshot factory rather than duplicating it.
from tests.test_persistence import make_snapshot

_DB_PATH = Path(__file__).parent.parent / "data" / "lahman.sqlite"


class _FakeLog:
    """Stand-in for PlayByPlayLog so log calls on the restore/advance paths
    are no-ops (mirrors the fake used in test_game_screen_substitutions)."""

    def add_play(self, *args):
        pass

    def add_inning_divider(self, *args):
        pass

    def clear(self):
        pass


# ---------------------------------------------------------------------------
# Pure injection logic — no DB, no Textual
# ---------------------------------------------------------------------------


def test_apply_restored_state_injects_engine_state_box_and_rng():
    """_apply_restored_state installs the saved SubstitutionManager (shared into
    a fresh engine), restores the numpy generator state, the GameState, and the
    loose box-score accumulators."""
    snap = make_snapshot()
    ms = SimpleNamespace()
    ms._restore_box_score = lambda b: GameScreen._restore_box_score(ms, b)

    GameScreen._apply_restored_state(ms, snap)

    # SubstitutionManager is the saved instance, shared into the engine seam.
    assert ms.sub_manager is snap.substitutions
    assert ms.engine.sub_manager is ms.sub_manager
    # Canonical GameState restored verbatim.
    assert ms.game_state == snap.game_state
    # Box-score accumulator restored (by value) as the live self._box.
    box = snap.box_score
    assert ms._box.batting_lines == box.batting_lines
    assert ms._box.pitching_lines == box.pitching_lines
    assert ms._box.pitcher_teams == box.pitcher_teams
    assert ms._box.away_hits == box.away_hits
    assert ms._box.home_hits == box.home_hits
    assert ms._box.inning_scores == box.inning_scores
    assert ms._box.away_errors == box.away_errors
    assert ms._box.home_errors == box.home_errors
    assert ms._box.current_inning_away_runs == box.current_inning_away_runs
    assert ms._box.current_inning_home_runs == box.current_inning_home_runs
    assert ms._box.current_half_inning == box.current_half_inning
    # RNG restored to the exact captured generator state (deterministic resume).
    ref = SimulationRNG()
    restore_rng(ref, snap.rng)
    assert ms.engine.sim.rng.random() == ref.random()


def test_restore_box_score_copies_containers():
    """_restore_box_score installs a fresh BoxScore.copy so later live-game
    mutation can't reach back into the snapshot's box score."""
    box = make_snapshot().box_score
    ms = SimpleNamespace()

    GameScreen._restore_box_score(ms, box)

    assert ms._box is not box  # a distinct accumulator
    assert ms._box.inning_scores == box.inning_scores
    assert ms._box.inning_scores is not box.inning_scores  # fresh copy
    assert ms._box.batting_lines == box.batting_lines
    assert ms._box.batting_lines is not box.batting_lines
    # Nested per-player line dicts are copied too: mutating the live box score
    # must not reach back into the snapshot.
    a_player = next(iter(ms._box.batting_lines))
    ms._box.batting_lines[a_player]["H"] += 99
    assert box.batting_lines[a_player]["H"] != ms._box.batting_lines[a_player]["H"]


def test_apply_restored_state_preserves_substitution_invariants():
    """Removed players stay removed (no re-entry) and DH forfeiture survives the
    restore — and the engine validates against the same restored manager."""
    snap = make_snapshot()  # substitutions = make_populated_sub_manager()
    ms = SimpleNamespace()
    ms._restore_box_score = lambda b: GameScreen._restore_box_score(ms, b)

    GameScreen._apply_restored_state(ms, snap)

    # The three players removed in make_populated_sub_manager cannot re-enter.
    assert ms.sub_manager.is_player_available("b_out") is False
    assert ms.sub_manager.is_player_available("sp") is False
    assert ms.sub_manager.is_player_available("home_dh") is False
    # Home DH was forfeited (DH-takes-field); away DH still active.
    assert ms.sub_manager.home_dh_active is False
    assert ms.sub_manager.away_dh_active is True
    # The engine shares the manager, so its validation sees the same set.
    valid, error = ms.engine.sub_manager.validate_pinch_hitter("x", "b_out")
    assert valid is False
    assert "removed" in error


def test_finalize_game_setup_routes_to_restore_when_restoring():
    """With a snapshot present, _finalize_game_setup must take the restore path
    and NEVER call the fresh-game _build_lineups()."""
    called = []
    ms = SimpleNamespace(_restore=object())
    ms._finalize_restore = lambda: called.append("restore")
    ms._build_lineups = lambda: called.append("build")

    GameScreen._finalize_game_setup(ms)

    assert called == ["restore"]


def test_finalize_restore_injects_state_without_rebuild_or_reset():
    """_finalize_restore injects saved state and renders, but must NOT invoke
    the fresh-lineup rebuild or the tracking reset (the clobber it exists to
    avoid)."""
    snap = make_snapshot()

    def _boom(*args, **kwargs):
        raise AssertionError("restore must not rebuild lineups / reset tracking")

    # No teams set: the restore-path batter-starts capture (FRE-177) reads
    # self.away_team/home_team and must no-op cleanly when they're absent.
    ms = SimpleNamespace(_restore=snap, away_team=None, home_team=None)
    # These would clobber restored state — binding them to raise proves the
    # restore path never reaches them.
    ms._build_lineups = _boom
    ms._init_stat_lines = _boom
    ms._reset_tracking = _boom
    # Real injection helpers.
    ms._apply_restored_state = lambda s: GameScreen._apply_restored_state(ms, s)
    ms._restore_box_score = lambda b: GameScreen._restore_box_score(ms, b)
    # Stub the widget-touchers.
    ms._set_panel_titles = lambda: None
    ms._update_lineup_cards = lambda: None
    ms._update_all_widgets = lambda: None
    ms.query_one = lambda *a, **k: _FakeLog()

    GameScreen._finalize_restore(ms)

    # State was injected from the snapshot.
    assert ms.game_state == snap.game_state
    assert ms._box.inning_scores == snap.box_score.inning_scores
    assert ms.engine.sub_manager is ms.sub_manager


# ---------------------------------------------------------------------------
# Advance harness shared by the determinism integration test
# ---------------------------------------------------------------------------


def _wire_advance(ms: SimpleNamespace) -> SimpleNamespace:
    """Bind the collaborators _advance_one / _log_play need onto a mock self so
    a real at-bat can be simulated without a Textual App."""
    ms._run_ai_managers = lambda: None
    ms._show_game_over = lambda: setattr(ms, "_game_over_called", True)
    ms.query_one = lambda *a, **k: _FakeLog()
    ms._fast_forward_timer = None
    ms._log_play = lambda result, team, pid: GameScreen._log_play(ms, result, team, pid)
    return ms


def _fresh_tracking(**overrides):
    """The mock self's game-start tracking state: a fresh box-score accumulator
    plus the narrative streak counters that live outside it."""
    base = dict(
        _box=BoxScore(),
        _player_hit_counts={},
        _pitcher_consecutive_retired=0,
        _inning_runs=0,
    )
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# DB-guarded determinism integration test (the acceptance bar)
# ---------------------------------------------------------------------------


def test_restore_advance_matches_control(tmp_path):
    """Save → load → restore → one advance == the un-saved control's next
    advance. Proves the RNG bit_generator.state restore and that the restored
    screen reflects the saved inning/half/score/lineups/box score."""
    if not _DB_PATH.exists():
        pytest.skip("lahman.sqlite not found - run build_lahman_db.py first")

    from src.data.lahman import LahmanRepository
    from src.game.lineup_builder import build_lineup, get_default_starter
    from src.game.team import Team

    with LahmanRepository(str(_DB_PATH)) as repo:
        # --- Build a control game and advance it K at-bats ------------------
        away = Team.load_from_repository(repo, "NYA", 1927)
        home = Team.load_from_repository(repo, "CHN", 1927)
        away_pid = get_default_starter(away, repo)
        home_pid = get_default_starter(home, repo)
        build_lineup(away, repo, pitcher_id=away_pid)
        build_lineup(home, repo, pitcher_id=home_pid)

        sub = SubstitutionManager()
        engine = GameEngine(substitution_manager=sub)
        engine.reset_rng(1927)  # seed only so the test itself is reproducible

        control = SimpleNamespace(
            away_team=away,
            home_team=home,
            repo=repo,
            engine=engine,
            sub_manager=sub,
            game_state=GameState(
                away_pitcher_id=away.lineup.starting_pitcher_id,
                home_pitcher_id=home.lineup.starting_pitcher_id,
            ),
            **_fresh_tracking(),
        )
        GameScreen._init_stat_lines(control)
        _wire_advance(control)

        K = 25
        for _ in range(K):
            GameScreen._advance_one(control)
        assert not getattr(control, "_game_over_called", False)  # still mid-game

        # --- Snapshot the control at this at-bat boundary, save to disk -----
        snap = GameSnapshot(
            config=GameConfig(),
            away_ref=TeamRef("NYA", 1927),
            home_ref=TeamRef("CHN", 1927),
            away_lineup=control.away_team.lineup.to_dict(),
            home_lineup=control.home_team.lineup.to_dict(),
            game_state=control.game_state,
            substitutions=control.sub_manager,
            box_score=control._box.copy(),
            rng=capture_rng(control.engine.sim.rng),
        )
        save = SaveFile(
            kind="single",
            created_at="2026-07-07T00:00:00+00:00",
            label="determinism",
            game=snap,
        )
        path = tmp_path / "control.json"
        save_game(save, path)
        loaded = load_game(path)  # independent of `control` from here on

        saved_state_dict = loaded.game.game_state.to_dict()

        # --- Restore into a fresh mock self via the real re-hydration -------
        r_away, r_home = loaded.rehydrate_teams(repo)
        restored = SimpleNamespace(
            away_team=r_away,
            home_team=r_home,
            repo=repo,
            _player_hit_counts={},
            _pitcher_consecutive_retired=0,
            _inning_runs=0,
        )
        restored._restore_box_score = lambda b: GameScreen._restore_box_score(restored, b)
        GameScreen._apply_restored_state(restored, loaded.game)
        _wire_advance(restored)

        # The restored screen reflects the saved state (2nd DoD bullet).
        assert restored.game_state.to_dict() == saved_state_dict
        assert restored.away_team.lineup.to_dict() == loaded.game.away_lineup
        assert restored.home_team.lineup.to_dict() == loaded.game.home_lineup
        assert restored._box.inning_scores == loaded.game.box_score.inning_scores
        assert restored._box.away_hits == loaded.game.box_score.away_hits
        assert restored._box.batting_lines == loaded.game.box_score.batting_lines

        # --- Advance both once and demand identical results ----------------
        GameScreen._advance_one(control)   # control's (K+1)th at-bat
        GameScreen._advance_one(restored)  # restored's 1st at-bat

        # Same resulting GameState (outcome + score + bases + outs + pitchers).
        assert restored.game_state.to_dict() == control.game_state.to_dict()
        # And the box-score accumulation moved identically — the strongest proof
        # the same at-bat was simulated from the same generator state.
        assert restored._box.batting_lines == control._box.batting_lines
        assert restored._box.pitching_lines == control._box.pitching_lines
        assert restored._box.away_hits == control._box.away_hits
        assert restored._box.home_hits == control._box.home_hits


def test_restore_from_rehydrates_and_arms_restore(tmp_path):
    """The restore_from classmethod re-hydrates both teams (saved lineups
    re-applied) and arms the screen so mount will take the restore path."""
    if not _DB_PATH.exists():
        pytest.skip("lahman.sqlite not found - run build_lahman_db.py first")

    from src.data.lahman import LahmanRepository
    from src.game.lineup_builder import build_lineup, get_default_starter
    from src.game.team import Team

    with LahmanRepository(str(_DB_PATH)) as repo:
        away = Team.load_from_repository(repo, "NYA", 1927)
        home = Team.load_from_repository(repo, "CHN", 1927)
        build_lineup(away, repo, pitcher_id=get_default_starter(away, repo))
        build_lineup(home, repo, pitcher_id=get_default_starter(home, repo))

        snap = make_snapshot()
        snap.away_ref = TeamRef("NYA", 1927)
        snap.home_ref = TeamRef("CHN", 1927)
        snap.away_lineup = away.lineup.to_dict()
        snap.home_lineup = home.lineup.to_dict()
        save = SaveFile(
            kind="single",
            created_at="2026-07-07T00:00:00+00:00",
            label="restore_from",
            game=snap,
        )
        path = tmp_path / "s.json"
        save_game(save, path)
        loaded = load_game(path)

        screen = GameScreen.restore_from(loaded, repo)

        # Armed for the restore path, teams re-hydrated with the saved lineup.
        # (The state injection itself runs on mount — _finalize_restore — and is
        # covered headless by the _apply_restored_state / determinism tests;
        # mounting a real Screen needs a running App, out of scope for a unit
        # test.)
        assert screen._restore is loaded.game
        assert screen.away_team.info.team_id == "NYA"
        assert screen.home_team.info.team_id == "CHN"
        assert screen.away_team.lineup.to_dict() == loaded.game.away_lineup
        assert screen.home_team.lineup.to_dict() == loaded.game.home_lineup
        # The chosen-pitcher fields fall back to the saved lineup's starter
        # (informational on the restore path; the live pitcher is in GameState).
        assert screen._away_pitcher_id == screen.away_team.lineup.starting_pitcher_id
