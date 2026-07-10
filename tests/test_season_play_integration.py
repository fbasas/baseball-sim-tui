"""Callback-level tests for the season play/sim integration (FRE-96).

The season flow wires ``BaseballSimApp`` behind the ``SeasonHubScreen``'s
actions: play the user's game interactively, sim a day, or drive a multi-day
sim-ahead on a worker — every path recording through one ``SeasonController``.
Following the house mock-``self`` idiom (``tests/test_load_resume_flow.py``),
the app methods are exercised as unbound functions against a ``SimpleNamespace``
``self`` with a monkeypatched controller, so the wiring is proven DB-free and
Pilot-free. The correctness-sensitive claims — contexts synced to the right
ledger/day, the completion payload recorded exactly once, sim-ahead stopping at
the user's game / end of season, and a PA-cap stop preserving recorded games —
are each asserted directly.
"""

from types import SimpleNamespace

import pytest

import src.tui.app as app_module
from src.tui.app import BaseballSimApp
from src.tui.screens.choice_screen import ChoiceScreen
from src.tui.screens.season_hub_screen import HubChoice, SeasonHubScreen
from src.season.schedule import ScheduledGame


# --- Fakes -----------------------------------------------------------------


def _game(game_id=1, day=3, home_key="H", away_key="A") -> ScheduledGame:
    return ScheduledGame(game_id=game_id, day=day, home_key=home_key, away_key=away_key)


def _ctx() -> SimpleNamespace:
    """A stand-in TeamManagerContext: only ``ledger``/``day`` are synced."""
    return SimpleNamespace(ledger=None, day=None)


def _fake_season(*, user_team_key="H", day=3, results=None, game=None):
    """A minimal ``SeasonController`` stand-in for the app-side handlers."""
    game = game if game is not None else _game(day=day)
    ledgers = {"H": object(), "A": object()}
    contexts = {"H": _ctx(), "A": _ctx()}
    teams = {"H": SimpleNamespace(name="home"), "A": SimpleNamespace(name="away")}
    return SimpleNamespace(
        state=SimpleNamespace(
            user_team_key=user_team_key,
            results=results if results is not None else [],
        ),
        current_day=day,
        teams=teams,
        contexts=contexts,
        ledgers=ledgers,
        next_user_game=lambda: game,
    )


class _FakeGameScreen:
    """Records the args ``_play_user_game`` constructs a GameScreen with."""

    last = None

    def __init__(self, repo, away_team, home_team, away_pid, home_pid,
                 away_ctx=None, home_ctx=None, on_game_complete=None):
        _FakeGameScreen.last = SimpleNamespace(
            repo=repo, away_team=away_team, home_team=home_team,
            away_pid=away_pid, home_pid=home_pid,
            away_ctx=away_ctx, home_ctx=home_ctx,
            on_game_complete=on_game_complete,
        )


# --- Play my game ----------------------------------------------------------


def _play_mock(season):
    """A mock-``self`` whose ``_pick_series_starter`` immediately returns a pid."""
    pushed = []
    picks = {}

    def pick(team, ctx, role, cont):
        picks.update(team=team, ctx=ctx, role=role)
        cont("PIDX")  # the user's chosen starter

    return SimpleNamespace(
        season=season,
        repo=SimpleNamespace(),
        _pick_series_starter=pick,
        push_screen=lambda screen: pushed.append(screen),
        notify=lambda *a, **k: None,
        _on_season_game_complete=lambda g, p: None,
    ), pushed, picks


def test_play_user_game_user_home_syncs_ai_side_and_wires_screen(monkeypatch):
    monkeypatch.setattr(app_module, "GameScreen", _FakeGameScreen)
    game = _game(day=3, home_key="H", away_key="A")
    season = _fake_season(user_team_key="H", game=game)
    mock, pushed, picks = _play_mock(season)

    BaseballSimApp._play_user_game(mock)

    # The user's (home) side is human: no context, and the pitcher modal ran.
    assert picks["team"] is season.teams["H"]
    assert picks["ctx"] is None
    assert picks["role"] == "Home"

    screen = _FakeGameScreen.last
    # Home is the user → home context withheld, away is the AI opponent.
    assert screen.home_ctx is None
    assert screen.away_ctx is season.contexts["A"]
    # The AI side is synced to its own ledger and the game's day.
    assert screen.away_ctx.ledger is season.ledgers["A"]
    assert screen.away_ctx.day == 3
    # The user's chosen starter goes to the home slot; AI away picks its own.
    assert screen.home_pid == "PIDX"
    assert screen.away_pid is None
    assert callable(screen.on_game_complete)
    assert len(pushed) == 1  # the constructed GameScreen was pushed


def test_play_user_game_user_away_syncs_ai_side_and_wires_screen(monkeypatch):
    monkeypatch.setattr(app_module, "GameScreen", _FakeGameScreen)
    game = _game(day=5, home_key="H", away_key="A")
    season = _fake_season(user_team_key="A", game=game)
    mock, pushed, picks = _play_mock(season)

    BaseballSimApp._play_user_game(mock)

    assert picks["team"] is season.teams["A"]
    assert picks["ctx"] is None
    assert picks["role"] == "Away"

    screen = _FakeGameScreen.last
    assert screen.away_ctx is None
    assert screen.home_ctx is season.contexts["H"]
    assert screen.home_ctx.ledger is season.ledgers["H"]
    assert screen.home_ctx.day == 5
    assert screen.away_pid == "PIDX"
    assert screen.home_pid is None


def test_play_user_game_no_game_notifies_and_returns():
    season = _fake_season()
    season.next_user_game = lambda: None
    notes = []
    mock = SimpleNamespace(
        season=season,
        _pick_series_starter=lambda *a: notes.append("picked"),
        notify=lambda msg, **k: notes.append(("notify", msg)),
    )
    BaseballSimApp._play_user_game(mock)
    assert notes and notes[0][0] == "notify"
    assert "picked" not in notes  # never advanced to a pitcher pick


def test_play_user_game_on_complete_records_this_game(monkeypatch):
    monkeypatch.setattr(app_module, "GameScreen", _FakeGameScreen)
    game = _game(game_id=7, day=2, home_key="H", away_key="A")
    season = _fake_season(user_team_key="H", game=game)
    captured = {}
    mock, _pushed, _picks = _play_mock(season)
    mock._on_season_game_complete = lambda g, p: captured.update(game=g, payload=p)

    BaseballSimApp._play_user_game(mock)
    payload = {"away_score": 1, "home_score": 2}
    _FakeGameScreen.last.on_game_complete(payload)

    # The completion callback is bound to *this* scheduled game.
    assert captured["game"] is game
    assert captured["payload"] is payload


# --- Recording a completed interactive game --------------------------------


def test_on_season_game_complete_records_once_then_sims_day_and_refreshes():
    game = _game(game_id=4, day=6)
    recorded = []
    events = []
    mock = SimpleNamespace(
        season=SimpleNamespace(record_user_game=lambda g, p: recorded.append((g, p))),
        pop_screen=lambda: events.append("pop"),
        _sim_day_guarded=lambda day: events.append(("sim_day", day)),
        _refresh_hub=lambda: events.append("refresh"),
    )
    payload = {"away_score": 3, "home_score": 4, "box_score": object()}

    BaseballSimApp._on_season_game_complete(mock, game, payload)

    assert recorded == [(game, payload)]  # exactly once
    # Order: tear down the game screen, sim the rest of that day, refresh hub.
    assert events == ["pop", ("sim_day", 6), "refresh"]


# --- Sim my game / sim this day --------------------------------------------


def test_sim_current_day_sims_current_day_and_refreshes():
    events = []
    mock = SimpleNamespace(
        season=SimpleNamespace(current_day=2),
        _sim_day_guarded=lambda day: events.append(("sim", day)),
        _refresh_hub=lambda: events.append("refresh"),
    )
    BaseballSimApp._sim_current_day(mock)
    assert events == [("sim", 2), "refresh"]


def test_sim_day_guarded_success_records_no_notice():
    simmed = []
    notes = []
    mock = SimpleNamespace(
        season=SimpleNamespace(sim_day=lambda day: simmed.append(day) or ["r1", "r2"]),
        _notify_pa_cap=lambda exc: notes.append(exc),
    )
    BaseballSimApp._sim_day_guarded(mock, 1)
    assert simmed == [1]
    assert notes == []


def test_sim_day_guarded_pa_cap_notifies_and_swallows():
    def boom(day):
        raise RuntimeError("Plate-appearance cap exceeded")

    notes = []
    mock = SimpleNamespace(
        season=SimpleNamespace(sim_day=boom),
        _notify_pa_cap=lambda exc: notes.append(str(exc)),
    )
    # Must not raise — the day is left partly played, games already simmed stand.
    BaseballSimApp._sim_day_guarded(mock, 0)
    assert notes == ["Plate-appearance cap exceeded"]


# --- Sim ahead: span mapping + worker --------------------------------------


@pytest.mark.parametrize(
    "mode, expected",
    [
        ("user", {"stop_before_user_game": True}),
        ("week", {"through_day": 5 + app_module._SIM_AHEAD_WEEK_DAYS - 1}),
        ("end", {}),
    ],
)
def test_sim_ahead_kwargs_maps_span(mode, expected):
    mock = SimpleNamespace(season=SimpleNamespace(current_day=5))
    assert BaseballSimApp._sim_ahead_kwargs(mock, mode) == expected


def test_prompt_sim_ahead_defaults_to_user_game_when_managing():
    pushed = {}
    mock = SimpleNamespace(
        season=SimpleNamespace(state=SimpleNamespace(user_team_key="H"), current_day=0),
        push_screen=lambda screen, cb: pushed.update(screen=screen, cb=cb),
        _on_sim_ahead_choice=lambda mode: None,
    )
    BaseballSimApp._prompt_sim_ahead(mock)
    assert isinstance(pushed["screen"], ChoiceScreen)
    assert pushed["screen"]._default_id == "user"


def test_prompt_sim_ahead_defaults_to_week_when_watch_only():
    pushed = {}
    mock = SimpleNamespace(
        season=SimpleNamespace(state=SimpleNamespace(user_team_key=None), current_day=0),
        push_screen=lambda screen, cb: pushed.update(screen=screen, cb=cb),
        _on_sim_ahead_choice=lambda mode: None,
    )
    BaseballSimApp._prompt_sim_ahead(mock)
    assert pushed["screen"]._default_id == "week"


def test_on_sim_ahead_choice_none_is_noop():
    calls = []
    mock = SimpleNamespace(
        _sim_ahead_kwargs=lambda mode: calls.append(mode) or {},
        run_worker=lambda *a, **k: calls.append("worker"),
        notify=lambda *a, **k: None,
    )
    BaseballSimApp._on_sim_ahead_choice(mock, None)
    assert calls == []  # no kwargs built, no worker launched


def test_on_sim_ahead_choice_launches_worker():
    launched = {}
    mock = SimpleNamespace(
        _sim_ahead_kwargs=lambda mode: {"mode": mode},
        run_worker=lambda fn, **k: launched.update(fn=fn, group=k.get("group"), thread=k.get("thread")),
        notify=lambda *a, **k: None,
    )
    BaseballSimApp._on_sim_ahead_choice(mock, "end")
    assert launched["thread"] is True
    assert launched["group"] == "season_sim_ahead"
    assert callable(launched["fn"])


def _worker_mock(gen_records, *, raise_after=None):
    """A mock-``self`` for the sim-ahead worker.

    ``call_from_thread`` runs the marshalled callback inline (no real thread),
    and the fake ``simulate_ahead`` records into ``played`` as it yields so a
    PA-cap stop's "games already recorded stand" claim is checkable.
    """
    played = []
    finished = {}
    stopped = {}
    progressed = []

    def simulate_ahead(**kwargs):
        finished["kwargs"] = kwargs

        def gen():
            for i, rec in enumerate(gen_records):
                played.append(rec)
                yield rec
                if raise_after is not None and i + 1 == raise_after:
                    raise RuntimeError("Plate-appearance cap exceeded")
        return gen()

    mock = SimpleNamespace(
        season=SimpleNamespace(simulate_ahead=simulate_ahead),
        call_from_thread=lambda fn, *a: fn(*a),
        _sim_ahead_progress=lambda count: progressed.append(count),
        _sim_ahead_finished=lambda count: finished.update(count=count),
        _sim_ahead_stopped=lambda msg, count: stopped.update(msg=msg, count=count),
    )
    return mock, played, finished, stopped, progressed


def test_sim_ahead_worker_runs_to_completion():
    records = list(range(23))  # more than one progress tick
    mock, played, finished, stopped, progressed = _worker_mock(records)
    BaseballSimApp._sim_ahead_worker(mock, {"through_day": 9})

    assert finished["count"] == 23
    assert finished["kwargs"] == {"through_day": 9}
    assert not stopped
    assert played == records
    # Progress ticked at each _SIM_AHEAD_PROGRESS_EVERY boundary.
    every = app_module._SIM_AHEAD_PROGRESS_EVERY
    assert progressed == [every, 2 * every]


def test_sim_ahead_worker_pa_cap_preserves_recorded_games():
    records = ["g0", "g1", "g2", "g3"]
    mock, played, finished, stopped, progressed = _worker_mock(records, raise_after=2)
    BaseballSimApp._sim_ahead_worker(mock, {})

    # Stopped, not finished; the two games simmed before the cap are recorded.
    assert "count" not in finished
    assert stopped["count"] == 2
    assert "cap" in stopped["msg"]
    assert played == ["g0", "g1"]


# --- Quit / save / dirty tracking ------------------------------------------


def test_has_unsaved_games_tracks_results_against_saved_count():
    mock = SimpleNamespace(
        season=SimpleNamespace(state=SimpleNamespace(results=[1, 2, 3])),
        _season_saved_count=1,
    )
    assert BaseballSimApp._season_has_unsaved_games(mock) is True
    mock._season_saved_count = 3
    assert BaseballSimApp._season_has_unsaved_games(mock) is False


def test_quit_with_no_unsaved_goes_straight_to_menu():
    events = []
    mock = SimpleNamespace(
        _season_has_unsaved_games=lambda: False,
        pop_screen=lambda: events.append("pop"),
        start_setup=lambda: events.append("setup"),
        push_screen=lambda *a, **k: events.append("push"),
    )
    BaseballSimApp._quit_season_to_menu(mock)
    assert events == ["pop", "setup"]


def test_quit_with_unsaved_prompts_then_routes_choice():
    pushed = {}
    events = []
    mock = SimpleNamespace(
        _season_has_unsaved_games=lambda: True,
        pop_screen=lambda: events.append("pop"),
        start_setup=lambda: events.append("setup"),
        push_screen=lambda screen, cb: pushed.update(screen=screen, cb=cb),
    )
    BaseballSimApp._quit_season_to_menu(mock)
    assert isinstance(pushed["screen"], ChoiceScreen)

    # Staying leaves the hub untouched.
    pushed["cb"]("stay")
    assert events == []
    # Quitting to the menu tears down the hub and restarts setup.
    pushed["cb"]("menu")
    assert events == ["pop", "setup"]


def test_save_season_writes_file_and_notifies(tmp_path, monkeypatch):
    """Ctrl+S at the hub writes a kind=="season" save (no game) and confirms."""
    from src.game.persistence import load_game
    from tests.test_season_persistence import make_season_controller

    monkeypatch.setattr(app_module, "saves_dir", lambda: tmp_path)

    notes = []
    controller = make_season_controller()
    mock = SimpleNamespace(
        season=controller,
        notify=lambda msg, **k: notes.append((msg, k)),
    )
    mock._season_save_label = lambda: BaseballSimApp._season_save_label(mock)
    mock._season_team_label = lambda key: BaseballSimApp._season_team_label(mock, key)

    BaseballSimApp._save_season(mock)

    written = list(tmp_path.glob("save-*.json"))
    assert len(written) == 1
    loaded = load_game(written[0])
    assert loaded.kind == "season"
    assert loaded.season is not None and loaded.game is None
    # The save baseline advances so the quit prompt stops warning.
    assert mock._season_saved_count == len(controller.state.results)
    assert notes and "Saved" in notes[0][0]


def test_save_season_noop_without_a_season():
    """With no live season, saving is a safe no-op (no crash, no file)."""
    notes = []
    mock = SimpleNamespace(season=None, notify=lambda msg, **k: notes.append(msg))
    BaseballSimApp._save_season(mock)
    assert notes == []


# --- Hub wiring: ready + choice routing ------------------------------------


def test_on_season_ready_registers_season_and_pushes_hub():
    pushed = {}
    controller = SimpleNamespace(state=SimpleNamespace(results=[1, 2]))
    mock = SimpleNamespace(
        push_screen=lambda screen: pushed.update(screen=screen),
        _on_hub_choice=lambda c: None,
    )
    BaseballSimApp._on_season_ready(mock, controller)
    assert mock.season is controller
    assert mock._season_saved_count == 2  # a resumed/nonempty season starts "clean"
    assert isinstance(pushed["screen"], SeasonHubScreen)


@pytest.mark.parametrize(
    "choice, handler",
    [
        (HubChoice.PLAY, "_play_user_game"),
        (HubChoice.SIM_MY_GAME, "_sim_current_day"),
        (HubChoice.SIM_DAY, "_sim_current_day"),
        (HubChoice.SIM_AHEAD, "_prompt_sim_ahead"),
        (HubChoice.SAVE, "_save_season"),
        (HubChoice.QUIT, "_quit_season_to_menu"),
    ],
)
def test_on_hub_choice_routes_to_handler(choice, handler):
    calls = []
    attrs = {
        name: (lambda name=name: calls.append(name))
        for name in (
            "_play_user_game", "_sim_current_day", "_prompt_sim_ahead",
            "_save_season", "_quit_season_to_menu",
        )
    }
    mock = SimpleNamespace(**attrs)
    BaseballSimApp._on_hub_choice(mock, choice)
    assert calls == [handler]


@pytest.mark.parametrize("choice", [HubChoice.NEW_SEASON, HubChoice.MAIN_MENU])
def test_on_hub_choice_end_of_season_nav_restarts_setup(choice):
    events = []
    mock = SimpleNamespace(
        pop_screen=lambda: events.append("pop"),
        start_setup=lambda: events.append("setup"),
    )
    BaseballSimApp._on_hub_choice(mock, choice)
    assert events == ["pop", "setup"]
