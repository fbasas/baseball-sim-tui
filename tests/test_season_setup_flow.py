"""Unit tests for the season setup flow (FRE-95).

DB-free and Pilot-free, in the house callback-driven idiom: a fake app records
each ``push_screen(screen, callback)`` so the test can inspect the pushed screen
and invoke the callback with the value a real screen would dismiss. Team loads
are monkeypatched (no Lahman DB), and role cards are written into a tmp dir.

Coverage (the DoD):

- full happy path builds a ``SeasonController`` with N teams, the right
  schedule length, and the chosen user team;
- a duplicate ``(team_id, year)`` pick re-prompts that slot;
- back-navigation at each step returns to the previous question, and cancel at
  the first step returns to the mode menu (``on_cancel``);
- the role-card pass: cards present ⇒ no build attempted; one missing ⇒ built
  in-process and the season starts; an unbuildable team ⇒ the error names it and
  the season does not start;
- the watch-only choice yields ``user_team_key is None``.

``SetupFlow`` mode routing into the season flow is covered alongside the load
routing in ``test_load_resume_flow.py`` style, here for the ``"season"`` id.
"""

import sqlite3
import threading
from types import SimpleNamespace

import src.tui.role_card_pass as role_card_pass_module
from src.game.team import Team
from src.manager.roles import TeamRoleCard, save_role_card
from src.tui.screens.choice_screen import ChoiceScreen
from src.tui.screens.team_select_screen import TeamSelectScreen
from src.tui.season_setup_flow import SeasonSetupFlow
from src.tui.setup_flow import SetupFlow


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class FakeApp:
    """Records pushed screens/callbacks, notifies, and runs workers inline."""

    def __init__(self):
        self.pushed = []  # list of (screen, callback)
        self.notes = []   # list of (message, kwargs)

    def push_screen(self, screen, callback=None):
        self.pushed.append((screen, callback))

    def notify(self, message, **kwargs):
        self.notes.append((message, kwargs))

    def run_worker(self, work, **kwargs):
        # Run the worker body synchronously so the flow completes in-test.
        work()

    def call_from_thread(self, fn, *args, **kwargs):
        return fn(*args, **kwargs)

    @property
    def last_screen(self):
        return self.pushed[-1][0]

    @property
    def last_callback(self):
        return self.pushed[-1][1]


class FakeRepo:
    """Minimal repo: enough for ``TeamSelectScreen`` construction only."""

    def get_available_years(self):
        return [2016, 1975, 1927, 1906]


def _fake_team(team_id, year):
    return SimpleNamespace(
        info=SimpleNamespace(
            team_id=team_id, year=year, team_name=f"{team_id} Club"
        )
    )


def _install_team_loader(monkeypatch, raise_for=()):
    """Monkeypatch ``Team.load_from_repository`` to return synthetic teams.

    Any ``(team_id, year)`` in ``raise_for`` raises (a sparse-roster failure).
    """

    def fake_load(repo, team_id, year):
        if (team_id, year) in raise_for:
            raise ValueError("sparse roster")
        return _fake_team(team_id, year)

    monkeypatch.setattr(Team, "load_from_repository", staticmethod(fake_load))


def _write_card(roles_dir, team_id, year):
    """Write a minimal, loadable role card into ``roles_dir``."""
    card = TeamRoleCard(
        team_id=team_id,
        year=year,
        pitchers={},
        batters={},
        batting_order=[],
        lineup_positions={},
    )
    save_role_card(card, roles_dir)


_FOUR_TEAMS = [("AAA", 1927), ("BBB", 1975), ("CCC", 2016), ("DDD", 1906)]
_FOUR_KEYS = ["AAA-1927", "BBB-1975", "CCC-2016", "DDD-1906"]


def _make_flow(app, repo, roles_dir, captured):
    return SeasonSetupFlow(
        app,
        repo,
        on_complete=lambda controller: captured.update(controller=controller),
        on_cancel=lambda: captured.update(cancel=True),
        roles_dir=roles_dir,
    )


def _drive_to_user_team(app, flow, teams=_FOUR_TEAMS, size="4", games="2"):
    """Run the flow through league size, games, and all N team picks."""
    flow.begin()
    app.last_callback(size)   # league size
    app.last_callback(games)  # games per opponent
    for pick in teams:
        app.last_callback(pick)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_full_happy_path_builds_controller(monkeypatch, tmp_path):
    _install_team_loader(monkeypatch)
    for team_id, year in _FOUR_TEAMS:
        _write_card(tmp_path, team_id, year)  # all cards present

    # Spy: assert no build is attempted when every card exists.
    build_calls = []
    monkeypatch.setattr(
        role_card_pass_module,
        "build_role_card",
        lambda *a, **k: build_calls.append(a) or None,
    )

    app, repo, captured = FakeApp(), FakeRepo(), {}
    flow = _make_flow(app, repo, tmp_path, captured)

    _drive_to_user_team(app, flow)
    # The your-team ChoiceScreen is up; pick the first team.
    assert isinstance(app.last_screen, ChoiceScreen)
    app.last_callback("AAA-1927")

    controller = captured["controller"]
    assert [t.key for t in controller.state.teams] == _FOUR_KEYS
    assert controller.state.games_per_opponent == 2
    assert controller.state.user_team_key == "AAA-1927"
    # 4 teams, 2 games vs each: (N-1)*G = 6 games/team, 12 total.
    assert controller.state.total_games == 12
    assert len(controller.contexts) == 4
    assert set(controller.contexts) == set(_FOUR_KEYS)
    assert set(controller.teams) == set(_FOUR_KEYS)
    assert build_calls == []  # no build attempted
    assert "cancel" not in captured


def test_your_team_offers_watch_only_and_the_picks(monkeypatch, tmp_path):
    _install_team_loader(monkeypatch)
    for team_id, year in _FOUR_TEAMS:
        _write_card(tmp_path, team_id, year)

    app, repo, captured = FakeApp(), FakeRepo(), {}
    flow = _make_flow(app, repo, tmp_path, captured)
    _drive_to_user_team(app, flow)

    choice_ids = [cid for cid, _label in app.last_screen._choices]
    assert choice_ids == _FOUR_KEYS + ["watch only"]


def test_watch_only_yields_no_user_team(monkeypatch, tmp_path):
    _install_team_loader(monkeypatch)
    for team_id, year in _FOUR_TEAMS:
        _write_card(tmp_path, team_id, year)

    app, repo, captured = FakeApp(), FakeRepo(), {}
    flow = _make_flow(app, repo, tmp_path, captured)
    _drive_to_user_team(app, flow)
    app.last_callback("watch only")

    controller = captured["controller"]
    assert controller.state.user_team_key is None


# ---------------------------------------------------------------------------
# Team-picker loop: duplicates and validation
# ---------------------------------------------------------------------------


def test_duplicate_pick_reprompts_same_slot(monkeypatch, tmp_path):
    _install_team_loader(monkeypatch)
    app, repo, captured = FakeApp(), FakeRepo(), {}
    flow = _make_flow(app, repo, tmp_path, captured)

    flow.begin()
    app.last_callback("4")   # size
    app.last_callback("2")   # games
    app.last_callback(("AAA", 1927))  # slot 0
    n_pushed = len(app.pushed)
    # Slot 1: pick the same team-season again -> re-prompt, no progress.
    app.last_callback(("AAA", 1927))

    assert flow._league_teams[-1].key == "AAA-1927"
    assert len(flow._league_teams) == 1  # still only one accepted pick
    assert isinstance(app.last_screen, TeamSelectScreen)
    # A fresh TeamSelectScreen for the same slot was pushed.
    assert len(app.pushed) == n_pushed + 1
    # A distinct team-season is accepted and advances.
    app.last_callback(("BBB", 1975))
    assert [t.key for t in flow._league_teams] == ["AAA-1927", "BBB-1975"]


def test_sparse_roster_load_failure_reprompts_slot(monkeypatch, tmp_path):
    _install_team_loader(monkeypatch, raise_for={("BAD", 1900)})
    app, repo, captured = FakeApp(), FakeRepo(), {}
    flow = _make_flow(app, repo, tmp_path, captured)

    flow.begin()
    app.last_callback("4")
    app.last_callback("2")
    app.last_callback(("BAD", 1900))  # load raises -> re-prompt slot 0
    assert flow._league_teams == []
    assert isinstance(app.last_screen, TeamSelectScreen)
    app.last_callback(("AAA", 1927))  # good pick advances
    assert [t.key for t in flow._league_teams] == ["AAA-1927"]


# ---------------------------------------------------------------------------
# Back-navigation
# ---------------------------------------------------------------------------


def test_cancel_at_first_step_returns_to_mode_menu(monkeypatch, tmp_path):
    _install_team_loader(monkeypatch)
    app, repo, captured = FakeApp(), FakeRepo(), {}
    flow = _make_flow(app, repo, tmp_path, captured)

    flow.begin()
    assert isinstance(app.last_screen, ChoiceScreen)  # league size
    app.last_callback(None)  # cancel

    assert captured.get("cancel") is True


def test_back_from_games_returns_to_league_size(monkeypatch, tmp_path):
    _install_team_loader(monkeypatch)
    app, repo, captured = FakeApp(), FakeRepo(), {}
    flow = _make_flow(app, repo, tmp_path, captured)

    flow.begin()
    app.last_callback("4")             # -> games question
    assert app.last_screen._title == "⚾ SEASON LENGTH"
    app.last_callback(None)            # back
    assert app.last_screen._title == "⚾ LEAGUE SIZE"
    assert "cancel" not in captured


def test_back_from_first_team_returns_to_games(monkeypatch, tmp_path):
    _install_team_loader(monkeypatch)
    app, repo, captured = FakeApp(), FakeRepo(), {}
    flow = _make_flow(app, repo, tmp_path, captured)

    flow.begin()
    app.last_callback("4")
    app.last_callback("2")
    assert isinstance(app.last_screen, TeamSelectScreen)  # slot 0
    app.last_callback(None)  # back
    assert isinstance(app.last_screen, ChoiceScreen)
    assert app.last_screen._title == "⚾ SEASON LENGTH"


def test_back_from_later_team_reprompts_previous_slot(monkeypatch, tmp_path):
    _install_team_loader(monkeypatch)
    app, repo, captured = FakeApp(), FakeRepo(), {}
    flow = _make_flow(app, repo, tmp_path, captured)

    flow.begin()
    app.last_callback("4")
    app.last_callback("2")
    app.last_callback(("AAA", 1927))  # slot 0 done -> slot 1 up
    assert [t.key for t in flow._league_teams] == ["AAA-1927"]
    app.last_callback(None)  # back out of slot 1

    # The slot-0 pick is undone and its slot re-prompted.
    assert flow._league_teams == []
    assert isinstance(app.last_screen, TeamSelectScreen)
    assert app.last_screen._context_line == ""  # no picks shown again


def test_back_from_your_team_reprompts_last_slot(monkeypatch, tmp_path):
    _install_team_loader(monkeypatch)
    for team_id, year in _FOUR_TEAMS:
        _write_card(tmp_path, team_id, year)
    app, repo, captured = FakeApp(), FakeRepo(), {}
    flow = _make_flow(app, repo, tmp_path, captured)
    _drive_to_user_team(app, flow)

    assert isinstance(app.last_screen, ChoiceScreen)  # your-team
    app.last_callback(None)  # back

    assert [t.key for t in flow._league_teams] == _FOUR_KEYS[:-1]
    assert isinstance(app.last_screen, TeamSelectScreen)  # last slot re-prompt


def test_context_line_lists_picks_so_far(monkeypatch, tmp_path):
    _install_team_loader(monkeypatch)
    app, repo, captured = FakeApp(), FakeRepo(), {}
    flow = _make_flow(app, repo, tmp_path, captured)

    flow.begin()
    app.last_callback("4")
    app.last_callback("2")
    app.last_callback(("AAA", 1927))
    app.last_callback(("BBB", 1975))
    # Slot 2 is up; its context lists the first two picks.
    assert app.last_screen._context_line == "picked: 1927 AAA Club, 1975 BBB Club"


# ---------------------------------------------------------------------------
# Role-card pass
# ---------------------------------------------------------------------------


def test_missing_card_is_built_in_process_and_season_starts(monkeypatch, tmp_path):
    _install_team_loader(monkeypatch)
    # Three cards present; DDD-1906 is missing and must be built.
    for team_id, year in _FOUR_TEAMS[:-1]:
        _write_card(tmp_path, team_id, year)

    built = []

    def fake_build(team_season, roster, batting, pitching, appearances):
        # Record the build and return a loadable card for DDD-1906.
        built.append(True)
        return TeamRoleCard(
            team_id="DDD",
            year=1906,
            pitchers={},
            batters={},
            batting_order=[],
            lineup_positions={},
        )

    monkeypatch.setattr(role_card_pass_module, "build_role_card", fake_build)

    # Repo must expose the gather methods the build core calls.
    repo = SimpleNamespace(
        get_available_years=lambda: [2016, 1975, 1927, 1906],
        get_team_season=lambda tid, yr: SimpleNamespace(team_id=tid, year=yr),
        get_team_roster=lambda tid, yr: [],
        get_batting_stats=lambda pid, yr: None,
        get_pitching_stats=lambda pid, yr: None,
        get_appearances=lambda tid, yr: [],
    )

    app, captured = FakeApp(), {}
    flow = _make_flow(app, repo, tmp_path, captured)
    _drive_to_user_team(app, flow)
    app.last_callback("AAA-1927")  # your team -> role-card pass -> launch

    assert built == [True]  # exactly the one missing card built
    assert (tmp_path / "DDD-1906.json").exists()
    controller = captured.get("controller")
    assert controller is not None
    assert controller.state.user_team_key == "AAA-1927"
    assert "cancel" not in captured


def test_unbuildable_team_blocks_season_start(monkeypatch, tmp_path):
    _install_team_loader(monkeypatch)
    for team_id, year in _FOUR_TEAMS[:-1]:
        _write_card(tmp_path, team_id, year)

    def fake_build(*args, **kwargs):
        raise ValueError("no usable pitchers")

    monkeypatch.setattr(role_card_pass_module, "build_role_card", fake_build)

    repo = SimpleNamespace(
        get_available_years=lambda: [2016, 1975, 1927, 1906],
        get_team_season=lambda tid, yr: SimpleNamespace(team_id=tid, year=yr),
        get_team_roster=lambda tid, yr: [],
        get_batting_stats=lambda pid, yr: None,
        get_pitching_stats=lambda pid, yr: None,
        get_appearances=lambda tid, yr: [],
    )

    app, captured = FakeApp(), {}
    flow = _make_flow(app, repo, tmp_path, captured)
    _drive_to_user_team(app, flow)
    app.last_callback("AAA-1927")

    # Season did not start; the error names the offending team.
    assert "controller" not in captured
    assert captured.get("cancel") is True
    assert not (tmp_path / "DDD-1906.json").exists()
    error_notes = [msg for msg, kw in app.notes if kw.get("severity") == "error"]
    assert error_notes
    assert "1906 DDD Club" in error_notes[-1]


def test_missing_cards_run_on_a_worker(monkeypatch, tmp_path):
    """The build dispatches to a background thread worker (not inline)."""
    _install_team_loader(monkeypatch)
    for team_id, year in _FOUR_TEAMS[:-1]:
        _write_card(tmp_path, team_id, year)
    monkeypatch.setattr(
        role_card_pass_module,
        "build_role_card",
        lambda *a, **k: TeamRoleCard("DDD", 1906, {}, {}, [], {}),
    )

    class RecordingApp(FakeApp):
        def __init__(self):
            super().__init__()
            self.worker_kwargs = None

        def run_worker(self, work, **kwargs):
            self.worker_kwargs = kwargs
            work()

    repo = SimpleNamespace(
        get_available_years=lambda: [2016, 1975, 1927, 1906],
        get_team_season=lambda tid, yr: SimpleNamespace(team_id=tid, year=yr),
        get_team_roster=lambda tid, yr: [],
        get_batting_stats=lambda pid, yr: None,
        get_pitching_stats=lambda pid, yr: None,
        get_appearances=lambda tid, yr: [],
    )
    app, captured = RecordingApp(), {}
    flow = _make_flow(app, repo, tmp_path, captured)
    _drive_to_user_team(app, flow)
    app.last_callback("AAA-1927")

    assert app.worker_kwargs is not None
    assert app.worker_kwargs.get("thread") is True


class ThreadingApp(FakeApp):
    """Runs the worker on a *real* background thread (like Textual ``thread=True``).

    Captures any exception that escapes the worker body — mirroring a real
    worker, which dies silently rather than propagating into the caller — so a
    test can assert the worker didn't blow up.
    """

    def __init__(self):
        super().__init__()
        self.thread_exc = None

    def run_worker(self, work, **kwargs):
        def runner():
            try:
                work()
            except BaseException as exc:  # noqa: BLE001 - capture like a real worker
                self.thread_exc = exc

        t = threading.Thread(target=runner)
        t.start()
        t.join()


class ThreadAffineRepo:
    """Repo double mimicking SQLite thread affinity.

    The real ``LahmanRepository`` opens one ``sqlite3`` connection with no
    ``check_same_thread=False``; any query from another thread raises
    ``sqlite3.ProgrammingError``. This double reproduces exactly that: reads are
    only legal on the thread that constructed it.
    """

    def __init__(self):
        self._owner = threading.get_ident()

    def _guard(self):
        if threading.get_ident() != self._owner:
            raise sqlite3.ProgrammingError(
                "SQLite objects created in a thread can only be used in that "
                "same thread."
            )

    def get_available_years(self):
        return [2016, 1975, 1927, 1906]

    def get_team_season(self, tid, yr):
        self._guard()
        return SimpleNamespace(team_id=tid, year=yr)

    def get_team_roster(self, tid, yr):
        self._guard()
        return []

    def get_batting_stats(self, pid, yr):
        self._guard()
        return None

    def get_pitching_stats(self, pid, yr):
        self._guard()
        return None

    def get_appearances(self, tid, yr):
        self._guard()
        return []


def test_role_card_gather_runs_on_main_thread_not_worker(monkeypatch, tmp_path):
    """Regression for the thread-affine-SQLite bug.

    The DB gather must run on the main thread and only the pure build on the
    worker. With a thread-affine repo (raising ``ProgrammingError`` off its
    creating thread, exactly like the real connection), the old code — which
    read the DB inside the worker — would have raised, escaped the
    ``except ValueError`` guard, killed the worker, and never started the
    season. Here the season must still start, and the build must have genuinely
    run on the background thread.
    """
    main_id = threading.get_ident()
    _install_team_loader(monkeypatch)
    for team_id, year in _FOUR_TEAMS[:-1]:
        _write_card(tmp_path, team_id, year)  # DDD-1906 missing -> must build

    build_threads = []

    def fake_build(*a, **k):
        build_threads.append(threading.get_ident())
        return TeamRoleCard("DDD", 1906, {}, {}, [], {})

    monkeypatch.setattr(role_card_pass_module, "build_role_card", fake_build)

    repo = ThreadAffineRepo()  # owner == main/test thread
    app, captured = ThreadingApp(), {}
    flow = _make_flow(app, repo, tmp_path, captured)
    _drive_to_user_team(app, flow)
    app.last_callback("AAA-1927")

    assert app.thread_exc is None  # gather ran on main thread; worker survived
    assert captured.get("controller") is not None  # season started
    assert "cancel" not in captured
    assert (tmp_path / "DDD-1906.json").exists()
    # The build itself genuinely ran off the main thread.
    assert build_threads and all(tid != main_id for tid in build_threads)


def test_worker_surfaces_unexpected_failure_and_aborts(monkeypatch, tmp_path):
    """A non-``ValueError`` escaping the worker is surfaced, not swallowed.

    ``ValueError`` means "unbuildable team" (named, blocks start); any other
    error (e.g. a save I/O failure) must still report and return to the mode
    menu via ``on_cancel`` rather than hanging on the progress toast.
    """
    _install_team_loader(monkeypatch)
    for team_id, year in _FOUR_TEAMS[:-1]:
        _write_card(tmp_path, team_id, year)

    def fake_build(*a, **k):
        raise RuntimeError("disk gremlins")

    monkeypatch.setattr(role_card_pass_module, "build_role_card", fake_build)

    repo = SimpleNamespace(
        get_available_years=lambda: [2016, 1975, 1927, 1906],
        get_team_season=lambda tid, yr: SimpleNamespace(team_id=tid, year=yr),
        get_team_roster=lambda tid, yr: [],
        get_batting_stats=lambda pid, yr: None,
        get_pitching_stats=lambda pid, yr: None,
        get_appearances=lambda tid, yr: [],
    )
    app, captured = FakeApp(), {}
    flow = _make_flow(app, repo, tmp_path, captured)
    _drive_to_user_team(app, flow)
    app.last_callback("AAA-1927")

    assert "controller" not in captured
    assert captured.get("cancel") is True
    error_notes = [msg for msg, kw in app.notes if kw.get("severity") == "error"]
    assert error_notes
    assert "disk gremlins" in error_notes[-1]


def test_all_cards_present_uses_no_worker(monkeypatch, tmp_path):
    _install_team_loader(monkeypatch)
    for team_id, year in _FOUR_TEAMS:
        _write_card(tmp_path, team_id, year)

    class NoWorkerApp(FakeApp):
        def run_worker(self, work, **kwargs):  # pragma: no cover - must not run
            raise AssertionError("no worker should run when all cards exist")

    app, repo, captured = NoWorkerApp(), FakeRepo(), {}
    flow = _make_flow(app, repo, tmp_path, captured)
    _drive_to_user_team(app, flow)
    app.last_callback("AAA-1927")

    assert "controller" in captured


# ---------------------------------------------------------------------------
# SetupFlow mode routing into the season flow
# ---------------------------------------------------------------------------


def test_mode_season_routes_to_select_season():
    calls = {}
    pushed = {}
    app = SimpleNamespace(
        push_screen=lambda screen, callback=None: pushed.update(
            screen=screen, callback=callback
        )
    )
    mock = SimpleNamespace(
        _app=app,
        _on_cancel=lambda: calls.setdefault("cancel", True),
        _select_control=lambda: calls.setdefault("control", True),
        _select_saved_game=lambda: calls.setdefault("saved", True),
        _select_season=lambda: calls.setdefault("season", True),
    )

    SetupFlow._select_mode(mock)
    pushed["callback"]("season")

    assert calls == {"season": True}


def test_select_season_invokes_on_season_callback():
    calls = {}
    mock = SimpleNamespace(
        _on_season=lambda: calls.setdefault("season", True),
        _select_mode=lambda: calls.setdefault("menu", True),
    )
    SetupFlow._select_season(mock)
    assert calls == {"season": True}


def test_select_season_without_callback_returns_to_menu():
    calls = {}
    mock = SimpleNamespace(
        _on_season=None,
        _select_mode=lambda: calls.setdefault("menu", True),
    )
    SetupFlow._select_season(mock)
    assert calls == {"menu": True}
