"""Unit tests for GameScreen's save action (FRE-46).

These exercise the snapshot-building helper and the Ctrl+S action without
spinning up a Textual App context, following the house mock-``self`` idiom
(``tests/test_game_screen_substitutions.py``): the methods are called as
unbound methods on the class with a ``types.SimpleNamespace`` standing in for
``self``, and the real helpers they depend on are lambda-bound. No Textual
``Pilot``/``run_test()`` and no database are involved.

Covered:

- ``GameScreen._build_save_file`` captures every live field (game_state,
  sub_manager, both lineups + team refs, RNG state, GameConfig, and every
  box-score accumulator) into a ``SaveFile``/``GameSnapshot`` with a
  human-readable label.
- The produced ``SaveFile`` round-trips through ``save_game`` -> file ->
  ``load_game`` to an equal object whose snapshot reflects the live
  inning/score/box score/RNG.
- The cosmetic narrative streak counters are NOT persisted (spec non-goal).
- ``GameScreen.action_save_game`` writes a timestamped file under the saves
  directory and flashes a confirmation via ``notify``.
"""

import json
from types import SimpleNamespace

from src.game.persistence import (
    SCHEMA_VERSION,
    BoxScore,
    GameSnapshot,
    SaveFile,
    TeamRef,
    capture_rng,
    load_game,
)
from src.game.state import GameState, InningHalf
from src.game.substitutions import SubstitutionManager
from src.simulation.rng import SimulationRNG
from src.tui.game_config import GameConfig
from src.tui.screens.game_screen import GameScreen


# ---------------------------------------------------------------------------
# Fixtures / factories
# ---------------------------------------------------------------------------


def _make_team(team_id: str, year: int, lineup_dict: dict):
    """A stand-in Team exposing only what _build_save_file reads."""
    return SimpleNamespace(
        info=SimpleNamespace(team_id=team_id, year=year),
        lineup=SimpleNamespace(to_dict=lambda: lineup_dict),
    )


def _away_lineup_dict() -> dict:
    return {
        "slots": [
            {"player_id": f"away{i}", "position_abbrev": "CF"} for i in range(9)
        ],
        "starting_pitcher_id": "awayp01",
    }


def _home_lineup_dict() -> dict:
    return {
        "slots": [
            {"player_id": f"home{i}", "position_abbrev": "DH"} for i in range(9)
        ],
        "starting_pitcher_id": "homep01",
    }


def _make_mock_self():
    """Build a SimpleNamespace mock-``self`` for GameScreen save helpers.

    Mirrors a mid-game screen: a non-default GameState, a populated substitution
    manager, a stepped-through RNG, and non-zero box-score accumulators.
    """
    # A live-ish game state: bottom of the 7th, 3-2.
    state = GameState(
        inning=7,
        half=InningHalf.BOTTOM,
        outs=1,
        away_score=3,
        home_score=2,
        away_batting_index=4,
        home_batting_index=6,
    )

    sub_manager = SubstitutionManager()
    sub_manager.removed_players.add("home3")

    rng = SimulationRNG(seed=1927)
    # Advance the generator so the captured state is past the seed origin.
    for _ in range(5):
        rng.random()

    mock_self = SimpleNamespace(
        app=SimpleNamespace(config=GameConfig(mode="single", away_ai=False, home_ai=True)),
        engine=SimpleNamespace(sim=SimpleNamespace(rng=rng)),
        away_team=_make_team("NYA", 1927, _away_lineup_dict()),
        home_team=_make_team("CHN", 1927, _home_lineup_dict()),
        game_state=state,
        sub_manager=sub_manager,
        # Box-score accumulators.
        away_hits=8,
        home_hits=5,
        _batting_lines={"away0": {"AB": 4, "R": 1, "H": 2, "RBI": 1, "BB": 0, "K": 1}},
        _pitching_lines={"homep01": {"outs": 19, "H": 8, "R": 3, "ER": 3, "BB": 2, "K": 4}},
        _pitcher_teams={"homep01": "home", "awayp01": "away"},
        _batter_teams={"away0": "away"},
        _inning_scores=[(1, 0), (0, 1), (2, 0), (0, 1), (0, 0), (0, 0)],
        _away_errors=1,
        _home_errors=0,
        _current_inning_away_runs=0,
        _current_inning_home_runs=0,
        _current_half_inning=(7, InningHalf.BOTTOM),
        # Cosmetic streak counters — must NOT be persisted.
        _player_hit_counts={"away0": 2},
        _pitcher_consecutive_retired=3,
    )
    # Bind the real helpers _build_save_file depends on (house-style pattern).
    mock_self._save_label = lambda a, h, s: GameScreen._save_label(a, h, s)
    return mock_self


# ---------------------------------------------------------------------------
# _build_save_file — captures the live fields
# ---------------------------------------------------------------------------


def test_build_save_file_captures_live_fields():
    """The builder packs every live field into the SaveFile/GameSnapshot."""
    mock_self = _make_mock_self()

    save = GameScreen._build_save_file(mock_self, created_at="2026-07-07T06:20:00+00:00")

    assert isinstance(save, SaveFile)
    assert save.kind == "single"
    assert save.created_at == "2026-07-07T06:20:00+00:00"
    assert save.schema_version == SCHEMA_VERSION

    snap = save.game
    assert isinstance(snap, GameSnapshot)
    # Team refs (rosters are re-hydrated from these, not serialized).
    assert snap.away_ref == TeamRef(team_id="NYA", year=1927)
    assert snap.home_ref == TeamRef(team_id="CHN", year=1927)
    # Lineups captured verbatim as serialized dicts.
    assert snap.away_lineup == _away_lineup_dict()
    assert snap.home_lineup == _home_lineup_dict()
    # Live game state carried through unchanged.
    assert snap.game_state is mock_self.game_state
    # Substitution manager shared (same instance) so invariants survive.
    assert snap.substitutions is mock_self.sub_manager
    # Config from the app.
    assert snap.config == GameConfig(mode="single", away_ai=False, home_ai=True)
    # RNG generator state captured (not just the seed).
    assert snap.rng == capture_rng(mock_self.engine.sim.rng)
    assert snap.rng["seed"] == 1927


def test_build_save_file_captures_every_box_score_field():
    """All box-score accumulators are copied into the snapshot's BoxScore."""
    mock_self = _make_mock_self()

    box = GameScreen._build_save_file(mock_self, created_at="t").game.box_score

    assert isinstance(box, BoxScore)
    assert box.batting_lines == mock_self._batting_lines
    assert box.pitching_lines == mock_self._pitching_lines
    assert box.pitcher_teams == mock_self._pitcher_teams
    assert box.batter_teams == mock_self._batter_teams
    assert box.away_hits == 8
    assert box.home_hits == 5
    assert box.inning_scores == mock_self._inning_scores
    assert box.away_errors == 1
    assert box.home_errors == 0
    assert box.current_inning_away_runs == 0
    assert box.current_inning_home_runs == 0
    assert box.current_half_inning == (7, InningHalf.BOTTOM)


def test_build_save_file_label_is_human_readable():
    """Label is matchup + inning (T/B) + score, for the load list."""
    mock_self = _make_mock_self()

    save = GameScreen._build_save_file(mock_self, created_at="t")

    assert save.label == "1927 NYA @ 1927 CHN — B7, 3-2"


def test_save_label_top_of_inning():
    """A top-half state renders with the 'T' prefix."""
    away = _make_team("NYA", 1927, _away_lineup_dict())
    home = _make_team("CHN", 1927, _home_lineup_dict())
    state = GameState(inning=1, half=InningHalf.TOP, away_score=0, home_score=0)

    assert GameScreen._save_label(away, home, state) == "1927 NYA @ 1927 CHN — T1, 0-0"


def test_build_save_file_falls_back_to_default_config():
    """When the app exposes no config, a default GameConfig is used."""
    mock_self = _make_mock_self()
    mock_self.app = SimpleNamespace(config=None)

    save = GameScreen._build_save_file(mock_self, created_at="t")

    assert save.game.config == GameConfig()


# ---------------------------------------------------------------------------
# Round-trip: builder -> save_game -> file -> load_game
# ---------------------------------------------------------------------------


def test_save_file_round_trips_through_disk(tmp_path):
    """The produced save writes valid JSON that load_game reads back equal."""
    from src.game.persistence import save_game

    mock_self = _make_mock_self()
    save = GameScreen._build_save_file(mock_self, created_at="2026-07-07T06:20:00+00:00")

    path = save_game(save, tmp_path / "save-test.json")
    loaded = load_game(path)

    # Equality is defined over the serialized form (SaveFile.__eq__).
    assert loaded == save
    # And the reloaded snapshot reflects the live inning/score/box score/RNG.
    snap = loaded.game
    assert snap.game_state.inning == 7
    assert snap.game_state.half == InningHalf.BOTTOM
    assert snap.game_state.away_score == 3
    assert snap.game_state.home_score == 2
    assert snap.box_score.away_hits == 8
    assert snap.box_score.inning_scores == [(1, 0), (0, 1), (2, 0), (0, 1), (0, 0), (0, 0)]
    assert "home3" in snap.substitutions.removed_players
    assert snap.rng == save.game.rng


def test_save_does_not_persist_cosmetic_streak_counters():
    """The narrative streak counters are an explicit non-goal — never written."""
    mock_self = _make_mock_self()

    blob = json.dumps(
        GameScreen._build_save_file(mock_self, created_at="t").to_dict()
    )

    assert "_player_hit_counts" not in blob
    assert "player_hit_counts" not in blob
    assert "_pitcher_consecutive_retired" not in blob
    assert "pitcher_consecutive_retired" not in blob


# ---------------------------------------------------------------------------
# action_save_game — writes a timestamped file + notifies
# ---------------------------------------------------------------------------


def test_action_save_game_writes_file_and_notifies(tmp_path, monkeypatch):
    """Ctrl+S writes a timestamped data/saves/*.json and flashes confirmation."""
    import src.tui.screens.game_screen as game_screen_module

    monkeypatch.setattr(game_screen_module, "saves_dir", lambda: tmp_path)

    notifications = []
    mock_self = _make_mock_self()
    mock_self.notify = lambda msg, **kwargs: notifications.append((msg, kwargs))
    mock_self._build_save_file = lambda created_at: GameScreen._build_save_file(
        mock_self, created_at
    )

    GameScreen.action_save_game(mock_self)

    written = list(tmp_path.glob("save-*.json"))
    assert len(written) == 1
    # The file is a valid, reloadable save.
    loaded = load_game(written[0])
    assert loaded.label == "1927 NYA @ 1927 CHN — B7, 3-2"
    # Confirmation was flashed.
    assert len(notifications) == 1
    assert "1927 NYA @ 1927 CHN" in notifications[0][0]


def test_action_save_game_noop_before_setup():
    """Before the engine/teams exist, saving is a safe no-op."""
    calls = []
    mock_self = SimpleNamespace(
        engine=None,
        away_team=None,
        home_team=None,
        notify=lambda *a, **k: calls.append(a),
    )

    GameScreen.action_save_game(mock_self)

    assert calls == []
