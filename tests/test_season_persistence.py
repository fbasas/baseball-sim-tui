"""Tests for season-mode save/resume (FRE-97).

Extends the save/load layer to a whole season: the ``SeasonSnapshot`` bundle
(``SeasonState`` + ``SeasonStats`` + one ``RestLedger`` per team key), the
``SaveFile`` extension that makes ``game`` optional and adds ``season``, and the
app-level restore wiring that rebuilds a ``SeasonController`` and — for a
mid-game save — re-establishes the ``on_game_complete`` hook so finishing the
resumed game records into the season. All tests are DB-free and Pilot-free, in
the house style (``tests/test_series_persistence.py`` is the direct precedent):

  * Pure round-trip / controller-bridge tests with synthetic ``SeasonState`` +
    ``SeasonStats`` + ``RestLedger`` pieces (no engine, no DB).
  * mock-``self`` unit tests for ``GameScreen._build_save_file`` (season branch)
    and ``BaseballSimApp._restore_season_game`` / ``_resume_saved_game``.
"""

import json
from types import SimpleNamespace

import pytest

import src.tui.app as app_module
from src.game.persistence import (
    CorruptSaveError,
    SaveFile,
    SeasonSnapshot,
    load_game,
    save_game,
)
from src.manager.rest import RestLedger
from src.manager.roles import PitcherRoleCard, PitcherRoleType
from src.season.controller import SeasonController
from src.season.state import LeagueTeam, SeasonGameRecord, SeasonState
from src.tui.app import BaseballSimApp
from src.tui.game_config import GameConfig
from src.tui.screens.game_screen import GameScreen
from src.tui.screens.season_hub_screen import SeasonHubScreen

# Reuse the single-game snapshot + box factories and the save fixtures.
from tests.test_persistence import make_box_score, make_save, make_snapshot
from tests.test_series_persistence import make_series_save


# --- Factories --------------------------------------------------------------


def make_league_teams() -> list:
    """Four cross-era team-seasons keyed ``"{team_id}-{year}"``."""
    return [
        LeagueTeam("NYA", 1927, "1927 Yankees"),
        LeagueTeam("CHN", 1927, "1927 Cubs"),
        LeagueTeam("BOS", 1975, "1975 Red Sox"),
        LeagueTeam("CIN", 1975, "1975 Reds"),
    ]


def make_season_controller() -> SeasonController:
    """A mid-season controller: one game recorded, ledgers + stats populated.

    Built without the engine — the first scheduled game is recorded by hand
    (appended result + logged pitcher workloads + one folded box score) so the
    snapshot carries real standings, rest, and stat state to round-trip.
    """
    state = SeasonState.create(
        make_league_teams(), games_per_opponent=2, user_team_key="NYA-1927"
    )
    controller = SeasonController(state=state, teams={}, contexts={})

    game = state.schedule[0][0]  # game_id 0, day 0
    state.results.append(
        SeasonGameRecord(
            game_id=game.game_id,
            day=game.day,
            home_key=game.home_key,
            away_key=game.away_key,
            home_score=5,
            away_score=2,
            innings=9,
        )
    )
    controller.ledgers[game.away_key].record(game.day, {"a_ace": 30})
    controller.ledgers[game.home_key].record(game.day, {"h_ace": 27})
    controller.stats.ingest(
        make_box_score(), home_key=game.home_key, away_key=game.away_key
    )
    return controller


def make_season_snapshot() -> SeasonSnapshot:
    return SeasonSnapshot.from_controller(make_season_controller())


def make_season_save() -> SaveFile:
    """A between-games (hub) season save: no ``game``, season state only."""
    return SaveFile(
        kind="season",
        created_at="2026-07-10T12:00:00+00:00",
        label="Season Day 1/6 — 1927 NYA 0-1, 4th",
        game=None,
        season=make_season_snapshot(),
    )


def make_season_midgame_save() -> SaveFile:
    """A mid-game season save: both a ``GameSnapshot`` and the season state."""
    return SaveFile(
        kind="season",
        created_at="2026-07-10T12:30:00+00:00",
        label="1927 NYA @ 1975 CIN — T5, 1-0",
        game=make_snapshot(),
        season=make_season_snapshot(),
    )


# --- SeasonSnapshot round-trip ----------------------------------------------


class TestSeasonSnapshotRoundTrip:
    def test_snapshot_round_trip_in_memory(self):
        snap = make_season_snapshot()
        assert SeasonSnapshot.from_dict(snap.to_dict()) == snap

    def test_is_plain_json_serializable(self):
        json.dumps(make_season_snapshot().to_dict())

    def test_round_trip_preserves_state_stats_and_ledgers(self):
        controller = make_season_controller()
        snap = SeasonSnapshot.from_controller(controller)
        restored = SeasonSnapshot.from_dict(snap.to_dict())

        # League config + results survive (standings derive from them).
        assert restored.state.team_keys == controller.state.team_keys
        assert restored.state.games_per_opponent == 2
        assert restored.state.user_team_key == "NYA-1927"
        assert [r.to_dict() for r in restored.state.results] == [
            r.to_dict() for r in controller.state.results
        ]
        # Season stats survive intact.
        assert restored.stats.to_dict() == controller.stats.to_dict()
        # Every rest ledger survives with int day keys intact.
        for key in controller.state.team_keys:
            assert restored.ledgers[key].outings == controller.ledgers[key].outings

    def test_in_progress_game_is_not_in_results(self):
        """from_controller captures only recorded games; a mid-game save's
        in-progress game rides along as the GameSnapshot, not in results."""
        controller = make_season_controller()  # 1 game recorded
        snap = SeasonSnapshot.from_controller(controller)
        assert len(snap.state.results) == 1


# --- SeasonController bridge (the cross-game carryover) ----------------------


class TestControllerBridge:
    def test_to_controller_restores_standings_stats_and_day(self):
        original = make_season_controller()
        snap = SeasonSnapshot.from_controller(original)
        restored = snap.to_controller(teams={}, contexts={})

        # Standings reconstruct identically from the restored results.
        assert [row.__dict__ for row in restored.state.standings] == [
            row.__dict__ for row in original.state.standings
        ]
        # Current day continues from where the season left off.
        assert restored.current_day == original.current_day
        # Stats and every ledger carry over exactly.
        assert restored.stats.to_dict() == original.stats.to_dict()
        for key in original.state.team_keys:
            assert restored.ledgers[key].outings == original.ledgers[key].outings

    def test_ledger_rest_rule_survives_restore(self):
        """Rest availability (what the ledger governs) is identical pre/post
        restore — proving the carryover is more than dict equality."""
        original = make_season_controller()
        restored = SeasonSnapshot.from_controller(original).to_controller(
            teams={}, contexts={}
        )
        rec = original.state.results[0]  # a_ace threw for the away side on day 0
        ace = PitcherRoleCard(
            player_id="a_ace", role=PitcherRoleType.STARTER, rotation_slot=1,
            leash_bf=25, leash_fatigue=0.6, typical_rest_days=4,
            appearance_share=0.2, metrics={},
        )
        # On day 1 the ace is a day short of his 4 days rest in both ledgers.
        assert original.ledgers[rec.away_key].is_available(ace, today=1) is False
        assert restored.ledgers[rec.away_key].is_available(ace, today=1) is False


# --- SaveFile carrying a season ---------------------------------------------


class TestSeasonSaveFile:
    def test_hub_save_round_trips_through_disk(self, tmp_path):
        save = make_season_save()
        path = tmp_path / "season.json"
        save_game(save, path)
        loaded = load_game(path)
        assert loaded == save
        assert loaded.kind == "season"
        assert loaded.game is None  # a hub save carries no in-progress game
        assert loaded.season is not None

    def test_midgame_save_round_trips_through_disk(self, tmp_path):
        save = make_season_midgame_save()
        path = tmp_path / "season-midgame.json"
        save_game(save, path)
        loaded = load_game(path)
        assert loaded == save
        assert loaded.kind == "season"
        assert loaded.game is not None  # a mid-game save carries the game
        assert loaded.season is not None

    def test_hub_save_omits_game_key(self, tmp_path):
        path = tmp_path / "season.json"
        save_game(make_season_save(), path)
        data = json.loads(path.read_text())
        assert "game" not in data
        assert data["kind"] == "season"
        assert "season" in data and "series" not in data

    def test_season_kind_missing_season_block_is_corrupt(self, tmp_path):
        """A ``kind == "season"`` save with no ``season`` payload and no game is
        a loud CorruptSaveError, not a silent empty load."""
        data = make_season_save().to_dict()
        del data["season"]
        path = tmp_path / "broken.json"
        path.write_text(json.dumps(data))
        with pytest.raises(CorruptSaveError):
            load_game(path)


# --- Backward compatibility (single/series unaffected) -----------------------


class TestBackwardCompatibility:
    def test_single_save_still_loads_and_has_no_season_key(self, tmp_path):
        path = tmp_path / "single.json"
        save_game(make_save(), path)
        data = json.loads(path.read_text())
        assert "season" not in data and "series" not in data
        loaded = load_game(path)
        assert loaded == make_save()
        assert loaded.season is None

    def test_series_save_still_loads_and_has_no_season_key(self, tmp_path):
        path = tmp_path / "series.json"
        save_game(make_series_save(), path)
        data = json.loads(path.read_text())
        assert "season" not in data
        loaded = load_game(path)
        assert loaded.kind == "series"
        assert loaded.series is not None and loaded.season is None

    def test_single_save_missing_game_is_corrupt(self, tmp_path):
        """``game`` is now optional on the dataclass, but a single/series save
        without it is still a loud CorruptSaveError."""
        data = make_save().to_dict()
        del data["game"]
        path = tmp_path / "broken-single.json"
        path.write_text(json.dumps(data))
        with pytest.raises(CorruptSaveError):
            load_game(path)


# --- GameScreen._build_save_file: season branch (mock-self) ------------------


def _season_mock_self() -> SimpleNamespace:
    """A save-building mock whose app is in season mode (app.season set)."""
    from tests.test_game_screen_save import _make_mock_self

    mock_self = _make_mock_self()
    controller = make_season_controller()
    mock_self.app = SimpleNamespace(
        config=GameConfig(mode="season"),
        season=controller,
        series=None,
    )
    mock_self._season_controller = controller  # handle for assertions
    return mock_self


def test_build_save_file_season_captures_controller():
    mock_self = _season_mock_self()

    save = GameScreen._build_save_file(mock_self, created_at="2026-07-10T12:30:00+00:00")

    assert save.kind == "season"
    assert save.season is not None
    assert save.series is None
    # Season state captured from the app's live controller.
    assert save.season.state.user_team_key == "NYA-1927"
    assert [r.to_dict() for r in save.season.state.results] == [
        r.to_dict() for r in mock_self._season_controller.state.results
    ]
    # The in-progress game snapshot is still captured alongside.
    assert save.game.game_state is mock_self.game_state


def test_build_save_file_season_round_trips_through_disk(tmp_path):
    mock_self = _season_mock_self()
    save = GameScreen._build_save_file(mock_self, created_at="2026-07-10T12:30:00+00:00")

    path = save_game(save, tmp_path / "season-save.json")
    loaded = load_game(path)

    assert loaded == save
    assert loaded.season.state.user_team_key == "NYA-1927"


def test_build_save_file_season_takes_precedence_over_series():
    """With both attrs present (defensive), season wins and series is dropped."""
    mock_self = _season_mock_self()
    mock_self.app.series = object()  # would never happen live; ensure season wins

    save = GameScreen._build_save_file(mock_self, created_at="t")

    assert save.kind == "season"
    assert save.series is None


# --- BaseballSimApp season restore wiring (mock-self) ------------------------


def _season_restore_mock():
    """A restore mock exposing the collaborators _restore_season_game touches."""
    pushed = []
    mock = SimpleNamespace(
        repo=SimpleNamespace(),
        push_screen=lambda screen: pushed.append(screen),
        _on_hub_choice=lambda choice: None,
        _on_season_game_complete=lambda game, payload: None,
    )
    return mock, pushed


def test_restore_season_hub_save_rebuilds_controller_and_returns_hub(monkeypatch):
    """A between-games save rebuilds the season and returns a hub to push."""
    teams, contexts = {}, {}
    monkeypatch.setattr(
        app_module, "rehydrate_season_teams", lambda state, repo: (teams, contexts)
    )
    mock, pushed = _season_restore_mock()
    save = make_season_save()

    screen = BaseballSimApp._restore_season_game(mock, save)

    assert isinstance(screen, SeasonHubScreen)
    assert isinstance(mock.season, SeasonController)
    assert mock.season.state.user_team_key == "NYA-1927"
    assert mock.series is None
    # A hub save records no in-progress game, so nothing extra was pushed.
    assert pushed == []


def test_restore_season_midgame_wires_completion_and_pushes_hub(monkeypatch):
    """A mid-game save restores the game, pushes a hub underneath, and re-wires
    on_game_complete so finishing records into the season."""
    keys = ["NYA-1927", "CHN-1927", "BOS-1975", "CIN-1975"]
    teams = {k: SimpleNamespace() for k in keys}
    contexts = {k: SimpleNamespace(ledger=None, day=None) for k in keys}
    monkeypatch.setattr(
        app_module, "rehydrate_season_teams", lambda state, repo: (teams, contexts)
    )
    fake_screen = SimpleNamespace(away_team="AWAY", home_team="HOME")
    captured = {}

    def fake_restore(save_arg, repo, on_game_complete=None, away_ctx=None, home_ctx=None):
        captured["on_game_complete"] = on_game_complete
        return fake_screen

    monkeypatch.setattr(app_module.GameScreen, "restore_from", fake_restore)

    completed = {}
    mock, pushed = _season_restore_mock()
    mock._on_season_game_complete = lambda game, payload: completed.update(
        game=game, payload=payload
    )
    mock._restore_season_midgame = lambda save_arg, controller: (
        BaseballSimApp._restore_season_midgame(mock, save_arg, controller)
    )
    save = make_season_midgame_save()

    screen = BaseballSimApp._restore_season_game(mock, save)

    # The restored game screen is returned; a hub was pushed underneath it.
    assert screen is fake_screen
    assert len(pushed) == 1 and isinstance(pushed[0], SeasonHubScreen)
    assert mock._away_team == "AWAY" and mock._home_team == "HOME"
    # Finishing the resumed game records the user's next game into the season.
    captured["on_game_complete"]({"score": 1})
    assert completed["payload"] == {"score": 1}
    assert completed["game"] is mock.season.next_user_game()


def test_resume_saved_game_routes_season_kind(monkeypatch):
    """_resume_saved_game dispatches a season save to _restore_season_game and
    pushes its screen (no error notify / restart)."""
    events = {}
    screen = SimpleNamespace()
    save = SimpleNamespace(kind="season")
    monkeypatch.setattr(app_module, "load_game", lambda path: save)

    def _restore(s):
        events["season"] = s
        return screen

    mock = SimpleNamespace(
        repo=SimpleNamespace(),
        push_screen=lambda s: events.setdefault("pushed", s),
        notify=lambda *a, **k: events.setdefault("notify", (a, k)),
        start_setup=lambda: events.setdefault("restart", True),
        _restore_season_game=_restore,
    )

    BaseballSimApp._resume_saved_game(mock, "data/saves/season.json")

    assert events["season"] is save
    assert events["pushed"] is screen
    assert "notify" not in events and "restart" not in events
