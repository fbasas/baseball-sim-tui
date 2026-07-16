"""On-demand Retrosheet schedule fetch for the historical setup flow (FRE-145).

The historical-season picker offers every year the app has a Lahman roster for
*and* Retrosheet publishes a schedule for (``schedule_available_for``), not just
the years whose schedule was pre-ingested by ``scripts/build_schedule_db.py``.
When the user picks a year whose schedule is not yet cached in the local
``Schedules`` table, this pass fetches it on demand — download the year's ZIP,
parse it, persist the rows — then hands back to the rest of the setup flow. The
write persists as a cache, so a second play of that year skips the download.

This mirrors :class:`~src.tui.role_card_pass.RoleCardPass`'s worker + thread
discipline. The ``LahmanRepository`` wraps a single thread-affine ``sqlite3``
connection, so only the pure network + parse (``fetch_schedule_rows``, no DB
touch) runs on the background Textual worker; the DB write
(``repo.ingest_schedule``) runs back on the **main thread**. Touching the
connection from the worker would raise ``sqlite3.ProgrammingError``, exactly the
hazard ``RoleCardPass`` documents.

Every failure — no network / timeout, a 404 / not-a-ZIP / no schedule member /
zero parsed rows, and any other error escaping the worker — is surfaced by a
**named** notification and returns control to the year picker, never a crash or a
hung progress toast (the ``RoleCardPass`` precedent).

The schedule data is copyrighted by and obtained free of charge from Retrosheet
(https://www.retrosheet.org/); the required notice already ships in ``README.md``
and the in-product credits, and covers these on-demand-fetched rows too.
"""

import socket
from typing import Callable, Optional
from urllib.error import URLError

from src.data.schedule_ingest import fetch_schedule_rows


class ScheduleIngest:
    """Fetch-if-missing a year's schedule, then continue the setup flow.

    Args:
        app: the Textual App used to ``notify`` and ``run_worker`` the fetch.
        repo: open ``LahmanRepository`` exposing ``has_schedule(year)``,
            ``schedule_needs_repair(year)`` and ``ingest_schedule(year, rows)``
            (all touched only on the main thread — the connection is
            thread-affine).
        fetch_rows: callable ``(year) -> rows`` doing the network + parse,
            injected so tests never hit the network. Defaults (when ``None``) to
            the module-level :func:`~src.data.schedule_ingest.fetch_schedule_rows`,
            resolved at construction so tests can also monkeypatch the module
            global.
    """

    def __init__(
        self,
        app,
        repo,
        fetch_rows: Optional[Callable[[int], list]] = None,
    ) -> None:
        self._app = app
        self._repo = repo
        self._fetch_rows = fetch_rows if fetch_rows is not None else fetch_schedule_rows
        self._year: int = 0
        self._on_success: Callable[[], None] = lambda: None
        self._on_failure: Callable[[], None] = lambda: None

    def run(
        self,
        year: int,
        on_success: Callable[[], None],
        on_failure: Callable[[], None],
    ) -> None:
        """Ensure the year's schedule is cached, then dispatch a continuation.

        If ``repo.has_schedule(year)`` is already true (script-ingested or a
        previously-cached year) **and** the cached rows are not corrupt,
        ``on_success`` fires immediately — no download, no worker. A year cached
        by the old parser from a 2024+ (13-column) file is detected as corrupt
        (``repo.schedule_needs_repair``) and re-fetched exactly like a missing
        year — the re-ingest replaces the year's rows, so the stale cache
        self-heals (FRE-147). Otherwise the network + parse runs on a background
        Textual worker; back on the main thread the rows are written via
        ``repo.ingest_schedule`` and ``on_success`` continues the flow. Any
        failure calls ``on_failure`` after a named notify (the caller returns to
        the year picker).
        """
        self._year = year
        self._on_success = on_success
        self._on_failure = on_failure

        if self._repo.has_schedule(year) and not self._repo.schedule_needs_repair(year):
            on_success()
            return

        self._app.notify(
            f"Fetching {year} schedule…",
            title="Historical season",
            timeout=6,
        )

        def work() -> None:
            # Network + parse only — no DB touch off the main thread (the repo's
            # sqlite3 connection is thread-affine). The DB write happens back on
            # the main thread in _finish.
            try:
                rows = self._fetch_rows(year)
            except (URLError, socket.error, TimeoutError):
                self._app.call_from_thread(self._fail_network)
                return
            except ValueError:
                # 404 body fails the ZIP-magic check, or a ZIP with no schedule
                # member — reported as "no schedule available".
                self._app.call_from_thread(self._fail_unavailable)
                return
            except Exception as exc:  # noqa: BLE001 - never hang on the toast
                self._app.call_from_thread(self._fail_other, str(exc))
                return
            self._app.call_from_thread(self._finish, rows)

        self._app.run_worker(
            work, thread=True, exclusive=True, group="schedule_ingest"
        )

    # --- Continuation (main thread) ----------------------------------------

    def _finish(self, rows: list) -> None:
        """Write the fetched rows and continue, or report failure (main thread).

        Runs on the main thread so the thread-affine DB write is safe. Zero
        parsed rows means the year has no usable schedule (treated like an
        unavailable year); otherwise the rows are persisted (idempotent per
        year, so this doubles as the cache) and ``on_success`` continues the
        flow.
        """
        if not rows:
            self._fail_unavailable()
            return
        try:
            self._repo.ingest_schedule(self._year, rows)
        except Exception as exc:  # noqa: BLE001 - surface, never hang
            self._fail_other(str(exc))
            return
        self._on_success()

    # --- Named failures (main thread) --------------------------------------

    def _fail_network(self) -> None:
        """No network / host unreachable / timeout — named, back to picker."""
        self._app.notify(
            f"Couldn't reach Retrosheet to fetch the {self._year} schedule. "
            "Check your connection and try again.",
            title="Historical season unavailable",
            severity="error",
            timeout=12,
        )
        self._on_failure()

    def _fail_unavailable(self) -> None:
        """Year not published / not a ZIP / no rows — named, back to picker."""
        self._app.notify(
            f"No schedule is available for {self._year}.",
            title="Historical season unavailable",
            severity="error",
            timeout=12,
        )
        self._on_failure()

    def _fail_other(self, message: str) -> None:
        """Any other error escaping the worker — named, back to picker.

        The safety net (mirroring ``RoleCardPass._fail``) so an unexpected error
        — e.g. a DB write I/O error — is reported instead of leaving the flow
        hung on the "Fetching…" toast.
        """
        self._app.notify(
            f"Couldn't fetch the {self._year} schedule: {message}.",
            title="Historical season unavailable",
            severity="error",
            timeout=12,
        )
        self._on_failure()
