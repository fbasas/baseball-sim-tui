"""Unit tests for the shared role-card pass (FRE-119).

``RoleCardPass`` is the DB-gather-on-main-thread + worker-build + progress +
blocking machinery extracted from ``SeasonSetupFlow`` so both season flows share
one code path (and one copy of the sqlite-thread-affinity fix). These tests cover
the helper directly, in the house callback/fake-app idiom; the two flows' own
tests cover their integration with it.

Coverage:

- all cards present ⇒ ``on_success`` fires immediately, no worker;
- a missing card is gathered on the main thread and built (pure) on the worker,
  then ``on_success`` fires;
- an unbuildable team (inference ``ValueError``) collects a named failure,
  surfaces an error notify, and calls ``on_failure`` (blocks the season);
- an unexpected error escaping the worker is surfaced and aborts via
  ``on_failure``;
- the DB gather runs on the main thread and only the build on the worker — the
  regression guard for the thread-affine-SQLite bug;
- ``_build_cards`` collects every failure with progress (the unit seam).
"""

import sqlite3
import threading
from types import SimpleNamespace

import src.tui.role_card_pass as role_card_pass_module
from src.manager.roles import SCHEMA_VERSION, TeamRoleCard, save_role_card
from src.season.state import LeagueTeam
from src.tui.role_card_pass import RoleCardPass


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class FakeApp:
    """Records notifies and runs workers inline (like the season flow tests)."""

    def __init__(self):
        self.notes = []
        self.worker_kwargs = None

    def notify(self, message, **kwargs):
        self.notes.append((message, kwargs))

    def run_worker(self, work, **kwargs):
        self.worker_kwargs = kwargs
        work()

    def call_from_thread(self, fn, *args, **kwargs):
        return fn(*args, **kwargs)


class ThreadingApp(FakeApp):
    """Runs the worker on a *real* background thread, capturing escapes."""

    def __init__(self):
        super().__init__()
        self.thread_exc = None

    def run_worker(self, work, **kwargs):
        self.worker_kwargs = kwargs

        def runner():
            try:
                work()
            except BaseException as exc:  # noqa: BLE001 - capture like a real worker
                self.thread_exc = exc

        t = threading.Thread(target=runner)
        t.start()
        t.join()


class ThreadAffineRepo:
    """Repo double mimicking SQLite thread affinity (reads only on its thread)."""

    def __init__(self):
        self._owner = threading.get_ident()

    def _guard(self):
        if threading.get_ident() != self._owner:
            raise sqlite3.ProgrammingError(
                "SQLite objects created in a thread can only be used in that "
                "same thread."
            )

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


def _repo():
    return SimpleNamespace(
        get_team_season=lambda tid, yr: SimpleNamespace(team_id=tid, year=yr),
        get_team_roster=lambda tid, yr: [],
        get_batting_stats=lambda pid, yr: None,
        get_pitching_stats=lambda pid, yr: None,
        get_appearances=lambda tid, yr: [],
    )


def _write_card(roles_dir, team_id, year):
    save_role_card(
        TeamRoleCard(team_id, year, {}, {}, [], {}), roles_dir
    )


def _write_stale_card(roles_dir, team_id, year):
    """Write a card, then downgrade its schema_version on disk (a stale v1)."""
    path = save_role_card(TeamRoleCard(team_id, year, {}, {}, [], {}), roles_dir)
    text = path.read_text().replace(
        f'"schema_version": {SCHEMA_VERSION}', '"schema_version": 1'
    )
    path.write_text(text)


_TEAMS = [LeagueTeam("AAA", 1927, "1927 AAA"), LeagueTeam("BBB", 1975, "1975 BBB")]


def _run(app, repo, roles_dir, teams=_TEAMS):
    captured = {}
    RoleCardPass(app, repo, roles_dir).run(
        teams,
        on_success=lambda: captured.setdefault("success", True),
        on_failure=lambda: captured.setdefault("failure", True),
    )
    return captured


# ---------------------------------------------------------------------------
# All present / build / block
# ---------------------------------------------------------------------------


def test_all_cards_present_succeeds_without_worker(tmp_path):
    for team in _TEAMS:
        _write_card(tmp_path, team.team_id, team.year)
    app = FakeApp()
    captured = _run(app, _repo(), tmp_path)
    assert captured == {"success": True}
    assert app.worker_kwargs is None  # no build dispatched


def test_missing_card_built_then_succeeds(monkeypatch, tmp_path):
    _write_card(tmp_path, "AAA", 1927)  # BBB-1975 missing -> must build
    built = []

    def fake_build(*a, **k):
        built.append(True)
        return TeamRoleCard("BBB", 1975, {}, {}, [], {})

    monkeypatch.setattr(role_card_pass_module, "build_role_card", fake_build)
    app = FakeApp()
    captured = _run(app, _repo(), tmp_path)

    assert built == [True]
    assert (tmp_path / "BBB-1975.json").exists()
    assert captured == {"success": True}
    assert app.worker_kwargs.get("thread") is True


def test_stale_version_card_is_rebuilt(monkeypatch, tmp_path):
    """A stale-schema card on disk counts as missing and is regenerated.

    Cards are regenerated, never migrated in place (FRE-176). Setup must
    overwrite a prior-schema card rather than leave it to crash the later
    in-game load.
    """
    _write_card(tmp_path, "AAA", 1927)          # current schema -> usable
    _write_stale_card(tmp_path, "BBB", 1975)    # stale v1 -> must rebuild
    built = []

    def fake_build(team_season, *a, **k):
        built.append((team_season.team_id, team_season.year))
        return TeamRoleCard(team_season.team_id, team_season.year, {}, {}, [], {})

    monkeypatch.setattr(role_card_pass_module, "build_role_card", fake_build)
    app = FakeApp()
    captured = _run(app, _repo(), tmp_path)

    # Only the stale team was rebuilt; the current-schema card was left alone.
    assert built == [("BBB", 1975)]
    assert captured == {"success": True}


def test_unbuildable_team_blocks_named(monkeypatch, tmp_path):
    _write_card(tmp_path, "AAA", 1927)

    def fake_build(*a, **k):
        raise ValueError("no usable pitchers")

    monkeypatch.setattr(role_card_pass_module, "build_role_card", fake_build)
    app = FakeApp()
    captured = _run(app, _repo(), tmp_path)

    assert captured == {"failure": True}
    error_notes = [msg for msg, kw in app.notes if kw.get("severity") == "error"]
    assert error_notes and "1975 BBB" in error_notes[-1]
    assert not (tmp_path / "BBB-1975.json").exists()


def test_unexpected_error_surfaced_and_aborts(monkeypatch, tmp_path):
    _write_card(tmp_path, "AAA", 1927)

    def fake_build(*a, **k):
        raise RuntimeError("disk gremlins")

    monkeypatch.setattr(role_card_pass_module, "build_role_card", fake_build)
    app = FakeApp()
    captured = _run(app, _repo(), tmp_path)

    assert captured == {"failure": True}
    error_notes = [msg for msg, kw in app.notes if kw.get("severity") == "error"]
    assert error_notes and "disk gremlins" in error_notes[-1]


def test_gather_on_main_thread_build_on_worker(monkeypatch, tmp_path):
    """Regression: the DB gather runs on the main thread, the build on the worker.

    With a thread-affine repo (raising ``ProgrammingError`` off its creating
    thread, like the real connection), reading the DB inside the worker would
    escape the ``except ValueError`` guard and silently kill it. The season must
    still start, and the build must genuinely have run off the main thread.
    """
    main_id = threading.get_ident()
    _write_card(tmp_path, "AAA", 1927)  # BBB-1975 missing -> must build
    build_threads = []

    def fake_build(*a, **k):
        build_threads.append(threading.get_ident())
        return TeamRoleCard("BBB", 1975, {}, {}, [], {})

    monkeypatch.setattr(role_card_pass_module, "build_role_card", fake_build)
    app = ThreadingApp()
    captured = _run(app, ThreadAffineRepo(), tmp_path)

    assert app.thread_exc is None  # gather ran on main thread; worker survived
    assert captured == {"success": True}
    assert (tmp_path / "BBB-1975.json").exists()
    assert build_threads and all(tid != main_id for tid in build_threads)


# ---------------------------------------------------------------------------
# Unit seam: _build_cards collects every failure with progress
# ---------------------------------------------------------------------------


def test_build_cards_collects_failures_with_progress(monkeypatch, tmp_path):
    def fake_build(*a, **k):
        raise ValueError("bad")

    monkeypatch.setattr(role_card_pass_module, "build_role_card", fake_build)
    pass_ = RoleCardPass(FakeApp(), _repo(), tmp_path)
    # Gather on the main thread (here), then build (pure) below.
    prepared = [(team, pass_._gather_inputs(team)) for team in _TEAMS]
    progress = []
    failures = pass_._build_cards(
        prepared, progress=lambda i, n, t: progress.append((i, n, t.key))
    )
    assert failures == ["1927 AAA", "1975 BBB"]
    assert progress == [(1, 2, "AAA-1927"), (2, 2, "BBB-1975")]
