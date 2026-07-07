"""Tests for series-mode save/resume (FRE-49).

Extends the single-game save/load layer to a best-of-N series: the
``SeriesSnapshot`` bundle (standings + both rest ledgers) and the app-level
restore wiring that rebuilds a ``SeriesController`` and re-establishes the
series ``_on_game_complete`` hook so finishing the resumed game advances the
series. All tests are DB-free and Pilot-free, in the house style:

  * Pure round-trip / controller-bridge tests with synthetic ``SeriesState`` +
    ``RestLedger`` pieces (mirroring ``tests/test_rest_and_series.py`` and
    ``tests/test_persistence.py``).
  * mock-``self`` unit tests for ``GameScreen._build_save_file`` (series branch)
    and ``BaseballSimApp._restore_series_game`` / ``_resume_saved_game``.
"""

import json
from types import SimpleNamespace

import pytest

import src.tui.app as app_module
from src.game.persistence import (
    CorruptSaveError,
    SaveFile,
    SeriesSnapshot,
    load_game,
    save_game,
)
from src.series.controller import GameWorkloads, SeriesController
from src.series.state import GameRecord, SeriesState
from src.manager.rest import RestLedger
from src.tui.app import BaseballSimApp
from src.tui.game_config import GameConfig
from src.tui.screens.game_screen import GameScreen

# Reuse the single-game snapshot factory and Team/lineup stubs already in place.
from tests.test_persistence import make_snapshot
from tests.test_game_screen_save import (
    _away_lineup_dict,
    _home_lineup_dict,
    _make_mock_self,
    _make_team,
)


# --- Factories --------------------------------------------------------------


def make_controller() -> SeriesController:
    """A best-of-5 controller mid-series: away leads 2-1, ledgers populated.

    Three games have been played (so the in-progress game would be game 4);
    both rest ledgers carry real outings across days 0-2.
    """
    controller = SeriesController(best_of=5)
    # Day 0: game 1 (away wins 5-2). Day 1: game 2 (home wins 1-3).
    # Day 2: game 3 (away wins 4-0). Away leads 2-1, game 4 up next.
    controller.record_game(5, 2, GameWorkloads(away={"a_ace": 30}, home={"h_ace": 25}))
    controller.record_game(1, 3, GameWorkloads(away={"a_two": 28}, home={"h_two": 27}))
    controller.record_game(4, 0, GameWorkloads(away={"a_ace": 26, "a_pen": 5},
                                               home={"h_three": 24}))
    return controller


def make_series_snapshot() -> SeriesSnapshot:
    return SeriesSnapshot.from_controller(make_controller())


def make_series_save() -> SaveFile:
    return SaveFile(
        kind="series",
        created_at="2026-07-07T12:00:00+00:00",
        label="1927 NYA @ 1927 CHN — B4, 2-1 series",
        game=make_snapshot(),
        series=make_series_snapshot(),
    )


# --- SeriesSnapshot round-trip ----------------------------------------------


class TestSeriesSnapshotRoundTrip:
    def test_snapshot_round_trip_in_memory(self):
        snap = make_series_snapshot()
        assert SeriesSnapshot.from_dict(snap.to_dict()) == snap

    def test_round_trip_preserves_standings_and_ledgers(self):
        controller = make_controller()
        snap = SeriesSnapshot.from_controller(controller)
        restored = SeriesSnapshot.from_dict(snap.to_dict())

        # Standings: best_of, the recorded results, and the derived
        # current_game_number all survive.
        assert restored.best_of == 5
        assert restored.current_game_number == 4  # 3 played -> game 4 next
        assert [r.to_dict() for r in restored.results] == [
            {"game_number": 1, "away_score": 5, "home_score": 2},
            {"game_number": 2, "away_score": 1, "home_score": 3},
            {"game_number": 3, "away_score": 4, "home_score": 0},
        ]
        # Both rest ledgers survive with int day keys intact.
        assert restored.away_ledger.outings == controller.away_ledger.outings
        assert restored.home_ledger.outings == controller.home_ledger.outings

    def test_is_plain_json_serializable(self):
        json.dumps(make_series_snapshot().to_dict())

    def test_in_progress_game_is_not_recorded_in_results(self):
        """from_controller captures only completed games; the in-progress game
        (captured separately as the GameSnapshot) is not double-counted."""
        controller = make_controller()  # 3 completed
        snap = SeriesSnapshot.from_controller(controller)
        assert len(snap.results) == 3
        assert snap.current_game_number == 4


# --- SeriesController bridge (the cross-game carryover) ----------------------


class TestControllerBridge:
    def test_to_controller_restores_standings_and_ledgers(self):
        original = make_controller()
        restored = SeriesSnapshot.from_controller(original).to_controller()

        aw, hw = restored.state.summary()
        assert (aw, hw) == (2, 1)
        assert restored.state.away_wins == 2
        assert restored.state.home_wins == 1
        assert restored.current_game_number == 4
        assert restored.current_day == 3
        assert restored.away_ledger.outings == original.away_ledger.outings
        assert restored.home_ledger.outings == original.home_ledger.outings

    def test_restored_controller_advances_on_finished_game(self):
        """The DoD's second bullet: a restored SeriesController + a finished game
        records the result and updates the ledgers exactly as an unsaved one."""
        restored = make_series_snapshot().to_controller()
        assert not restored.is_complete

        # Finish game 4: away wins 6-3, clinching the best-of-5 (3rd away win).
        restored.record_game(
            6, 3, GameWorkloads(away={"a_two": 29}, home={"h_ace": 22})
        )

        assert restored.state.away_wins == 3
        assert restored.current_game_number == 5
        assert restored.is_complete
        assert restored.winner == "away"
        # Ledger carryover: game 4 fell on day 3 and is recorded there.
        assert restored.away_ledger.batters_faced_on("a_two", 3) == 29
        assert restored.home_ledger.batters_faced_on("h_ace", 3) == 22
        # Earlier outings are untouched.
        assert restored.away_ledger.batters_faced_on("a_ace", 0) == 30

    def test_ledger_rest_rule_survives_restore(self):
        """Rest availability (what the ledger governs) is identical pre/post
        restore — proving the carryover is more than dict equality."""
        from src.manager.roles import PitcherRoleCard, PitcherRoleType

        original = make_controller()
        restored = SeriesSnapshot.from_controller(original).to_controller()
        ace = PitcherRoleCard(
            player_id="a_ace", role=PitcherRoleType.STARTER, rotation_slot=1,
            leash_bf=25, leash_fatigue=0.6, typical_rest_days=4,
            appearance_share=0.2, metrics={},
        )
        # a_ace last threw on day 2 (game 3); on day 3 (game 4) he is short of
        # his 4 days rest in both the original and the restored ledger.
        assert original.away_ledger.is_available(ace, today=3) is False
        assert restored.away_ledger.is_available(ace, today=3) is False


# --- SaveFile carrying a series ---------------------------------------------


class TestSeriesSaveFile:
    def test_savefile_round_trips_through_disk(self, tmp_path):
        save = make_series_save()
        path = tmp_path / "series.json"
        save_game(save, path)
        loaded = load_game(path)
        assert loaded == save
        assert loaded.kind == "series"
        assert loaded.series is not None

    def test_single_save_has_no_series_key(self, tmp_path):
        """A single-game save omits the ``series`` key entirely (spec format)."""
        from tests.test_persistence import make_save

        path = tmp_path / "single.json"
        save_game(make_save(), path)
        data = json.loads(path.read_text())
        assert "series" not in data
        assert load_game(path).series is None

    def test_series_save_writes_series_block(self, tmp_path):
        path = tmp_path / "series.json"
        save_game(make_series_save(), path)
        data = json.loads(path.read_text())
        assert data["kind"] == "series"
        assert data["series"]["best_of"] == 5
        assert data["series"]["current_game_number"] == 4
        assert "away_ledger" in data["series"] and "home_ledger" in data["series"]

    def test_series_kind_missing_series_block_is_corrupt(self, tmp_path):
        """A ``kind == "series"`` save without the ``series`` payload is a loud
        CorruptSaveError, not a silent single-game load."""
        data = make_series_save().to_dict()
        del data["series"]
        path = tmp_path / "broken.json"
        path.write_text(json.dumps(data))
        with pytest.raises(CorruptSaveError):
            load_game(path)


# --- GameScreen._build_save_file: series branch (mock-self) ------------------


def _series_mock_self() -> SimpleNamespace:
    """A save-building mock whose app is in series mode (app.series set)."""
    mock_self = _make_mock_self()
    controller = make_controller()
    mock_self.app = SimpleNamespace(
        config=GameConfig(mode="series", best_of=5, away_ai=False, home_ai=False),
        series=controller,
    )
    mock_self._series_controller = controller  # handle for assertions
    return mock_self


def test_build_save_file_series_captures_controller():
    mock_self = _series_mock_self()

    save = GameScreen._build_save_file(mock_self, created_at="2026-07-07T12:00:00+00:00")

    assert save.kind == "series"
    assert save.series is not None
    # Standings + ledgers captured from the app's live controller.
    assert save.series.best_of == 5
    assert save.series.current_game_number == 4
    assert save.series.away_ledger.outings == mock_self._series_controller.away_ledger.outings
    # The in-progress game snapshot is still captured alongside.
    assert save.game.game_state is mock_self.game_state


def test_build_save_file_single_when_no_series():
    """With no app.series, the save stays single (kind == "single", series None)."""
    mock_self = _make_mock_self()  # app has config but no `series` attr

    save = GameScreen._build_save_file(mock_self, created_at="t")

    assert save.kind == "single"
    assert save.series is None


def test_build_save_file_series_round_trips_through_disk(tmp_path):
    mock_self = _series_mock_self()
    save = GameScreen._build_save_file(mock_self, created_at="2026-07-07T12:00:00+00:00")

    path = save_game(save, tmp_path / "series-save.json")
    loaded = load_game(path)

    assert loaded == save
    assert loaded.series.to_controller().state.summary() == (2, 1)


# --- BaseballSimApp series restore wiring (mock-self) ------------------------


def _series_restore_mock():
    """A restore mock exposing the collaborators _restore_series_game touches."""
    events = {}
    mock = SimpleNamespace(
        repo=SimpleNamespace(),
        _on_series_game_complete=lambda result: events.setdefault("advanced", result),
        # No DB: AI contexts resolve to None (no manager cards loaded).
        _build_context=lambda team, want_ai: None,
    )
    return mock, events


def _series_save_stub(config=None):
    """A stand-in SaveFile for the restore path: real SeriesSnapshot (so
    to_controller works) + a lightweight game carrying only the config."""
    config = config or GameConfig(mode="series", best_of=5, away_ai=False, home_ai=False)
    return SimpleNamespace(
        kind="series",
        series=make_series_snapshot(),
        game=SimpleNamespace(config=config),
    )


def test_restore_series_game_rebuilds_controller_and_wires_advance(monkeypatch):
    captured = {}
    screen = SimpleNamespace(away_team="AWAY", home_team="HOME",
                             _away_ctx="unset", _home_ctx="unset")

    def fake_restore(save_arg, repo, on_game_complete=None):
        captured["save"] = save_arg
        captured["on_game_complete"] = on_game_complete
        return screen

    monkeypatch.setattr(app_module.GameScreen, "restore_from", fake_restore)

    mock, events = _series_restore_mock()
    save = _series_save_stub()

    result = BaseballSimApp._restore_series_game(mock, save)

    assert result is screen
    # Controller rebuilt with the saved standings + ledgers.
    assert isinstance(mock.series, SeriesController)
    assert mock.series.state.summary() == (2, 1)
    assert mock.series.current_game_number == 4
    # Series advance hook re-established on the restored screen.
    assert captured["on_game_complete"] is mock._on_series_game_complete
    # App matchup state synced from the save.
    assert mock.config is save.game.config
    assert mock._away_team == "AWAY"
    assert mock._home_team == "HOME"
    # No-AI config -> contexts are None, propagated onto the screen too.
    assert mock._away_ctx is None and mock._home_ctx is None
    assert screen._away_ctx is None and screen._home_ctx is None


def test_restore_series_game_syncs_ai_contexts_to_ledgers(monkeypatch):
    """When a side is AI, its context is synced to the restored ledger + the
    in-progress game's day (current_day), mirroring _push_game."""
    screen = SimpleNamespace(away_team="AWAY", home_team="HOME",
                             _away_ctx=None, _home_ctx=None)
    monkeypatch.setattr(
        app_module.GameScreen, "restore_from",
        lambda save_arg, repo, on_game_complete=None: screen,
    )

    mock, _ = _series_restore_mock()
    # AI on the away side: hand back a context object to be synced.
    away_ctx = SimpleNamespace(ledger=None, day=None)
    mock._build_context = lambda team, want_ai: away_ctx if want_ai else None
    save = _series_save_stub(
        GameConfig(mode="series", best_of=5, away_ai=True, home_ai=False)
    )

    BaseballSimApp._restore_series_game(mock, save)

    assert mock._away_ctx is away_ctx
    assert away_ctx.ledger is mock.series.away_ledger
    assert away_ctx.day == mock.series.current_day  # == 3 (game 4's day)
    assert mock._home_ctx is None


def test_resume_saved_game_routes_series_kind(monkeypatch):
    """_resume_saved_game dispatches a series save to _restore_series_game and
    pushes its screen."""
    events = {}
    screen = SimpleNamespace()
    save = _series_save_stub()
    monkeypatch.setattr(app_module, "load_game", lambda path: save)

    def _restore(s):
        events["series"] = s
        return screen

    mock = SimpleNamespace(
        repo=SimpleNamespace(),
        push_screen=lambda s: events.setdefault("pushed", s),
        notify=lambda *a, **k: events.setdefault("notify", (a, k)),
        start_setup=lambda: events.setdefault("restart", True),
        _restore_series_game=_restore,
    )

    BaseballSimApp._resume_saved_game(mock, "data/saves/series.json")

    assert events["series"] is save
    assert events["pushed"] is screen
    assert "notify" not in events and "restart" not in events
