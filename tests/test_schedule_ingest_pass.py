"""Unit tests for the on-demand schedule-fetch pass (FRE-145).

DB-free (for the pass) and network-free in the house callback-driven idiom: a
fake app records ``notify``/``run_worker`` and runs the worker inline, and the
network + parse is an **injected** ``fetch_rows`` stub — no real Retrosheet
download ever happens. The ``LahmanRepository.ingest_schedule`` write path is
exercised separately against a real in-memory sqlite DB, round-tripping through
the existing ``get_schedule``.

Coverage (the Part-2 DoD, ingest half):

- present ⇒ skip: ``has_schedule(year)`` true ⇒ ``on_success`` fires with no
  worker, no fetch, no write;
- missing ⇒ fetch ⇒ write ⇒ continue: the rows are fetched on the worker and
  persisted via ``repo.ingest_schedule`` before ``on_success``;
- the DB write stays on the **main thread**: with a thread-affine repo (raising
  ``ProgrammingError`` off its creating thread, like the real connection) and a
  real background worker, the fetch runs on the worker but the write does not —
  the season continues and the worker never blows up;
- failure taxonomy, each ⇒ named notify + ``on_failure`` (back to picker):
  no network (``URLError`` / socket timeout), unavailable year (``ValueError``
  from the ZIP-magic / no-member checks), zero parsed rows, and any other error
  escaping the worker.
"""

import socket
import sqlite3
import threading
from urllib.error import URLError

import pytest

import src.tui.schedule_ingest_pass as pass_module
from src.data.lahman import LahmanRepository
from src.data.schedule_ingest import ingest_rows
from src.tui.schedule_ingest_pass import ScheduleIngest


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class FakeApp:
    """Records notifies/workers and runs the worker body inline (main thread)."""

    def __init__(self):
        self.notes = []       # list of (message, kwargs)
        self.worker_kwargs = None

    def notify(self, message, **kwargs):
        self.notes.append((message, kwargs))

    def run_worker(self, work, **kwargs):
        self.worker_kwargs = kwargs
        work()

    def call_from_thread(self, fn, *args, **kwargs):
        return fn(*args, **kwargs)

    @property
    def error_notes(self):
        return [msg for msg, kw in self.notes if kw.get("severity") == "error"]


class FakeRepo:
    """Repo double: records ``ingest_schedule`` calls; scriptable schedule set.

    ``corrupt_years`` scripts ``schedule_needs_repair`` — a cached year in that
    set is reported corrupt (until re-ingested), so the fetch guard treats it
    like a missing year (FRE-147).
    """

    def __init__(self, has_years=(), corrupt_years=()):
        self._has = set(has_years)
        self._corrupt = set(corrupt_years)
        self.ingested = []  # list of (year, rows)

    def has_schedule(self, year):
        return year in self._has

    def schedule_needs_repair(self, year):
        return year in self._corrupt

    def ingest_schedule(self, year, rows):
        self.ingested.append((year, rows))
        self._has.add(year)
        self._corrupt.discard(year)  # a fresh re-ingest heals the corruption
        return len(rows)


def _run(app, repo, year, fetch_rows=None):
    """Run the pass, returning the ``{success|failure}`` outcome captured."""
    captured = {}
    ScheduleIngest(app, repo, fetch_rows=fetch_rows).run(
        year,
        on_success=lambda: captured.update(success=True),
        on_failure=lambda: captured.update(failure=True),
    )
    return captured


# A minimal parsed-row tuple (shape mirrors schedule_ingest.SCHEDULE_COLUMNS).
def _row(year, date=19270405):
    return (year, date, 0, "Tue", "rA", "AL", "rB", "AL", "D", None, None)


# ---------------------------------------------------------------------------
# present ⇒ skip
# ---------------------------------------------------------------------------


def test_cached_year_skips_fetch_and_worker():
    app, repo = FakeApp(), FakeRepo(has_years={2016})

    def fetch_rows(year):  # pragma: no cover - must not run
        raise AssertionError("no fetch when the year is already cached")

    captured = _run(app, repo, 2016, fetch_rows=fetch_rows)

    assert captured == {"success": True}
    assert app.worker_kwargs is None  # no worker dispatched
    assert repo.ingested == []        # nothing written
    assert app.notes == []            # no "Fetching…" toast


def test_cached_but_corrupt_year_is_refetched_and_healed():
    # FRE-147: a year cached by the old parser (park code in `postponed`) is
    # present but corrupt — the guard must treat it like missing, re-fetch, and
    # overwrite the stale rows so it self-heals.
    app, repo = FakeApp(), FakeRepo(has_years={2024}, corrupt_years={2024})
    fresh = [_row(2024)]

    captured = _run(app, repo, 2024, fetch_rows=lambda year: fresh)

    assert captured == {"success": True}
    assert repo.ingested == [(2024, fresh)]          # re-fetched despite has_schedule
    assert app.worker_kwargs is not None             # a worker was dispatched
    assert any("Fetching 2024 schedule" in msg for msg, _ in app.notes)
    assert repo.schedule_needs_repair(2024) is False  # healed after re-ingest


# ---------------------------------------------------------------------------
# missing ⇒ fetch ⇒ write ⇒ continue
# ---------------------------------------------------------------------------


def test_missing_year_fetches_writes_and_continues():
    app, repo = FakeApp(), FakeRepo()  # nothing cached
    rows = [_row(1927), _row(1927, 19270406)]

    captured = _run(app, repo, 1927, fetch_rows=lambda year: rows)

    assert captured == {"success": True}
    assert repo.ingested == [(1927, rows)]  # written on the (main) thread
    assert app.worker_kwargs is not None    # a worker was dispatched
    assert app.worker_kwargs.get("thread") is True
    # A "Fetching…" progress line was shown before the work.
    assert any("Fetching 1927 schedule" in msg for msg, _ in app.notes)


def test_fetch_receives_the_picked_year():
    app, repo = FakeApp(), FakeRepo()
    seen = []
    _run(app, repo, 1975, fetch_rows=lambda year: seen.append(year) or [_row(1975)])
    assert seen == [1975]


# ---------------------------------------------------------------------------
# DB write stays on the main thread (thread-affinity regression)
# ---------------------------------------------------------------------------


class ThreadingApp(FakeApp):
    """Runs the worker on a real background thread, like Textual ``thread=True``.

    Models the defining property of the real ``call_from_thread``: it marshals
    the callable back to the creating (main/test) thread. Since that thread is
    blocked in ``join()`` while the worker runs, callables are queued from the
    worker and drained **on the main thread** after the worker finishes — so a
    continuation that touches the thread-affine repo runs where it legally can,
    and code that instead touched the repo *inside* ``work()`` would raise on the
    worker thread and be captured in ``thread_exc``.
    """

    def __init__(self):
        super().__init__()
        self._owner = threading.get_ident()
        self.thread_exc = None
        self.fetch_thread = None
        self._deferred = []  # (fn, args, kwargs) queued from the worker

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
        # Drain the marshalled continuations on the main (owner) thread.
        for fn, args, kwargs in self._deferred:
            fn(*args, **kwargs)

    def call_from_thread(self, fn, *args, **kwargs):
        # Real Textual runs this on the main thread; queue it to run there.
        self._deferred.append((fn, args, kwargs))


class ThreadAffineRepo:
    """Repo double mimicking sqlite thread affinity for the write.

    ``ingest_schedule`` (the write) raises ``ProgrammingError`` if called off
    the creating thread, exactly like the real thread-affine connection. If the
    pass wrote from the worker instead of the main thread, this would raise.
    """

    def __init__(self):
        self._owner = threading.get_ident()
        self.ingested = []

    def has_schedule(self, year):
        return False

    def schedule_needs_repair(self, year):
        return False

    def ingest_schedule(self, year, rows):
        if threading.get_ident() != self._owner:
            raise sqlite3.ProgrammingError(
                "SQLite objects created in a thread can only be used in that "
                "same thread."
            )
        self.ingested.append((year, rows))
        return len(rows)


def test_write_runs_on_main_thread_not_worker():
    main_id = threading.get_ident()
    app, repo = ThreadingApp(), ThreadAffineRepo()
    rows = [_row(1927)]

    def fetch_rows(year):
        # The network + parse genuinely runs on the worker thread.
        app.fetch_thread = threading.get_ident()
        return rows

    captured = _run(app, repo, 1927, fetch_rows=fetch_rows)

    assert app.thread_exc is None            # write did NOT raise off-thread
    assert captured == {"success": True}     # season continues
    assert repo.ingested == [(1927, rows)]   # write happened, on the main thread
    assert app.fetch_thread is not None and app.fetch_thread != main_id


# ---------------------------------------------------------------------------
# Failure taxonomy — all ⇒ named notify + back to picker (on_failure)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "exc",
    [URLError("no route to host"), socket.timeout("timed out"), TimeoutError()],
)
def test_network_failure_is_named_and_returns_to_picker(exc):
    app, repo = FakeApp(), FakeRepo()

    def fetch_rows(year):
        raise exc

    captured = _run(app, repo, 1927, fetch_rows=fetch_rows)

    assert captured == {"failure": True}
    assert repo.ingested == []
    assert app.error_notes
    assert "Couldn't reach Retrosheet" in app.error_notes[-1]
    assert "1927" in app.error_notes[-1]


def test_unavailable_year_valueerror_is_named_and_returns_to_picker():
    app, repo = FakeApp(), FakeRepo()

    def fetch_rows(year):
        # e.g. a 404 HTML page failing the ZIP-magic check, or no schedule member.
        raise ValueError("1876: file is not a valid ZIP archive")

    captured = _run(app, repo, 1876, fetch_rows=fetch_rows)

    assert captured == {"failure": True}
    assert repo.ingested == []
    assert app.error_notes
    assert app.error_notes[-1] == "No schedule is available for 1876."


def test_zero_rows_is_treated_as_unavailable():
    app, repo = FakeApp(), FakeRepo()

    captured = _run(app, repo, 1927, fetch_rows=lambda year: [])

    assert captured == {"failure": True}
    assert repo.ingested == []  # nothing written for an empty schedule
    assert app.error_notes[-1] == "No schedule is available for 1927."


def test_unexpected_error_is_surfaced_and_returns_to_picker():
    app, repo = FakeApp(), FakeRepo()

    def fetch_rows(year):
        raise RuntimeError("gremlins")

    captured = _run(app, repo, 1927, fetch_rows=fetch_rows)

    assert captured == {"failure": True}
    assert app.error_notes
    assert "gremlins" in app.error_notes[-1]


def test_write_error_is_surfaced_not_hung():
    app = FakeApp()

    class ExplodingRepo(FakeRepo):
        def ingest_schedule(self, year, rows):
            raise OSError("disk full")

    captured = _run(app, ExplodingRepo(), 1927, fetch_rows=lambda year: [_row(1927)])

    assert captured == {"failure": True}
    assert app.error_notes
    assert "disk full" in app.error_notes[-1]


# ---------------------------------------------------------------------------
# Default fetcher wiring (no real network — monkeypatched global)
# ---------------------------------------------------------------------------


def test_default_fetcher_is_the_module_global(monkeypatch):
    """With no injected fetcher the pass uses the module-level global.

    Resolved at construction, so monkeypatching the module attribute takes
    effect — this is the seam the flow tests rely on (no network).
    """
    app, repo = FakeApp(), FakeRepo()
    calls = []
    monkeypatch.setattr(
        pass_module, "fetch_schedule_rows", lambda year: calls.append(year) or [_row(year)]
    )

    captured = _run(app, repo, 1927, fetch_rows=None)

    assert calls == [1927]
    assert captured == {"success": True}


# ---------------------------------------------------------------------------
# Repository write path — real in-memory DB round-trip
# ---------------------------------------------------------------------------


def _repo_on_memory_db():
    """A ``LahmanRepository`` backed by a shared in-memory sqlite DB."""
    repo = LahmanRepository.__new__(LahmanRepository)
    repo.conn = sqlite3.connect(":memory:")
    repo.conn.row_factory = sqlite3.Row
    return repo


def test_ingest_schedule_persists_and_round_trips():
    repo = _repo_on_memory_db()
    rows = [
        _row(1927, 19270412),
        (1927, 19270413, 0, "Wed", "rB", "AL", "rA", "AL", "N", None, None),
    ]

    assert repo.has_schedule(1927) is False
    inserted = repo.ingest_schedule(1927, rows)
    assert inserted == 2
    assert repo.has_schedule(1927) is True

    got = repo.get_schedule(1927)
    assert [(r.date, r.vis_team, r.home_team) for r in got] == [
        (19270412, "rA", "rB"),
        (19270413, "rB", "rA"),
    ]
    repo.close()


def test_ingest_schedule_is_idempotent_per_year():
    repo = _repo_on_memory_db()
    rows = [_row(1927), _row(1927, 19270406)]

    repo.ingest_schedule(1927, rows)
    # Re-ingest the same year: clear-then-insert, same count, no duplication.
    repo.ingest_schedule(1927, rows)

    assert len(repo.get_schedule(1927)) == 2
    repo.close()


def test_repo_delegates_to_ingest_rows(monkeypatch):
    """``ingest_schedule`` is a thin delegate to ``schedule_ingest.ingest_rows``."""
    repo = _repo_on_memory_db()
    seen = {}

    def spy(conn, year, rows):
        seen["args"] = (conn is repo.conn, year, rows)
        return ingest_rows(conn, year, rows)

    monkeypatch.setattr("src.data.lahman.schedule_ingest.ingest_rows", spy)
    repo.ingest_schedule(1927, [_row(1927)])

    assert seen["args"][0] is True   # the repo's own connection
    assert seen["args"][1] == 1927
    repo.close()
