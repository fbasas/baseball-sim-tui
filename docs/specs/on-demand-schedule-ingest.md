# Spec: On-demand historical schedule ingestion

**Source issue:** FRE-143 · **Date:** 2026-07-16 · **Status:** active

## Goal

A player should be able to start a **historical season** for any supported year
without first running a build script. Today the day-by-day schedule for a year
only exists after a human runs `scripts/build_schedule_db.py --year Y` and
rebuilds the database; the setup flow hides years that were never ingested. This
spec makes the app **fetch and ingest a year's Retrosheet schedule on demand,
the moment the user starts a season for it** — download → parse → persist into
the local `Schedules` table → build the season — with the result cached so a
second play of that year is instant.

The source issue set a decision gate: *"If schedules take longer than 20 seconds
to generate then this story should become a story about pre-generating
schedules."* This was **resolved empirically at planning time** (see
[Timing](#timing-the-20-second-gate)): a single year costs **well under one
second** end to end. The gate is not tripped, so this is on-demand generation at
season start, **not** pre-generation.

## Non-goals

- **No pre-generation / bundling.** We do not ship schedule data in the repo,
  bulk-download every year at DB-build time, or add a background prefetch. The
  issue's 20-second gate that would have justified that is not met (Timing).
- **No change to what a schedule *is*.** This is about *acquiring* the
  Retrosheet schedule rows automatically; the transformation of those rows into
  a `SeasonState` (`src/season/historical.build_historical_season`) and the
  "generated" reshuffle variant (`build_generated_historical_season`) are
  unchanged. "Automatically generated upon season start" means the data is
  acquired automatically, not that the matchups are invented.
- **No change to the Lahman roster/stats path.** `build_lahman_db.py` and the
  roster/stat/park-factor data remain a prerequisite built by the user (the
  whole app needs it). Only the *schedule* becomes on-demand. A year with no
  Lahman roster is not offered.
- **No offline synthesis fallback.** If the user has no network and the year was
  never ingested, that year cannot start — it is reported and the user returns
  to the year picker. Already-ingested years still work fully offline.
- **No round-robin / other-mode changes.** Single, series, and round-robin
  season modes are untouched. This only affects the historical-season setup
  flow.
- **No schema or persistence changes.** The `Schedules` table, `ScheduleRow`,
  `get_schedule`, `has_schedule`, and `SeasonSnapshot` are all unchanged; a save
  from an on-demand-ingested season is identical on disk to one built from
  script-ingested data.
- **No new attribution work beyond confirming it stays present.** Retrosheet
  data is already surfaced with the required notice (README + in-product); the
  same notice covers on-demand-fetched rows.

## Background — the current gap

Historical season mode (`docs/specs/historical-season-mode.md`) is fully built
(FRE-116…FRE-141). Its data pipeline is:

```
scripts/build_schedule_db.py  ──(manual, human-run)──▶  Schedules table in data/lahman.sqlite
                                                              │  get_schedule(year)
HistoricalSeasonSetupFlow ── year picker gated on has_schedule(year) ──▶ build_historical_season
```

The friction is the **manual, human-run** step. `HistoricalSeasonSetupFlow`
(`src/tui/historical_setup_flow.py`) offers only years where
`repo.has_schedule(year)` is already true, and when none are ingested it tells
the user to *"Ingest it with scripts/build_schedule_db.py, then rebuild the
database."* A shipped-app player will not run scripts. This spec removes that
step: the app fetches the schedule itself, on demand, at season start.

### The download logic already exists

`scripts/build_schedule_db.py` already downloads
`https://www.retrosheet.org/schedule/{year}SKED.zip`, unzips it, parses the
12-field records, and inserts them into the `Schedules` table idempotently
(clear-then-reinsert per year). The record layout, the 2020 two-file special
case, the ZIP-magic-byte validation, and the retro↔lahman join are all specified
and implemented (see `build_schedule_db.py` and
`docs/adr/001-historical-schedule-data.md`). **The only missing piece is a
runtime, importable path to that logic and a UI seam that calls it.** This spec
does not re-derive the Retrosheet format — it reuses the existing, working code.

### Timing (the 20-second gate)

Measured at planning time (2026-07-16), single-year end-to-end cost:

| Year | ZIP size | Download | Parse + SQLite insert | Rows |
| --- | --- | --- | --- | --- |
| 1927 | 10.2 KB | ~0.29 s | ~0.006 s | 1,232 |
| 2016 | 17.8 KB | ~0.50 s | ~0.010 s | 2,430 |
| 2023 | 17.8 KB | ~0.36 s | — | — |

A year's schedule ZIP is 10–24 KB; even on a slow link the download dominates
and stays comfortably sub-second (18 KB is ~3 s on a 56 kbps link). **Total
on-demand cost ≪ 20 s**, so per the issue's own conditional this is on-demand
generation, not pre-generation. Coverage was re-verified: Retrosheet publishes
`{year}SKED.zip` for **1877–2026 inclusive, except 1876** (which returns a 404
HTML page — caught by the existing ZIP-magic-byte check).

## Design

### Data flow (new path)

```
                       ┌──────────────── on the year the user picks, if not already cached ───────────────┐
                       ▼                                                                                    │
user picks year Y ─▶ has_schedule(Y)? ──no──▶ ScheduleIngest (Textual worker)                              │
                       │                        download {Y}SKED.zip + parse  ──▶ rows   (network + CPU)    │
                       │                                     │                                              │
                       │                        back on main thread: repo.ingest_schedule(Y, rows)         │
                       │                                     │        (thread-affine sqlite write)         │
                       └──yes──────────────────────────────▶┴──▶ has_schedule(Y) now true ─────────────────┘
                                                                        │
                                                     existing: schedule-type toggle ─▶ build_historical_season ─▶ …
```

Everything to the right of "has_schedule(Y) now true" is the **existing,
unchanged** historical setup flow (schedule-type toggle, league build, your-team
pick, role-card pass, launch). The new work is: an importable ingest module, a
repository write method, and one new step at the front of the setup flow.

### Part 1 — Runtime-importable schedule ingest module

Extract the download/parse/insert core of `scripts/build_schedule_db.py` into a
new importable module **`src/data/schedule_ingest.py`**, and refactor the script
into a thin CLI wrapper over it. The runtime path (Part 2) and the CLI must share
one code path — the same parsing, the same idempotent per-year replace, the same
2020 handling — so there is exactly one place the Retrosheet format lives.

Module surface (names indicative; keep the existing behavior):

- `SCHEDULE_URL` — the `.../{year}SKED.zip` template (moved from the script).
- Coverage constants + predicate: `SCHEDULE_MIN_YEAR = 1877`,
  `SCHEDULE_MAX_YEAR = 2026`, and `schedule_available_for(year) -> bool`
  (`MIN ≤ year ≤ MAX and year != 1876`). Drives which years the picker offers.
- `download_zip(url, *, timeout=DOWNLOAD_TIMEOUT) -> bytes` — a **quiet** fetch
  (no stdout; the TUI cannot print a progress bar). Validates the ZIP magic
  bytes and raises a clear error otherwise (reuses the existing `PK\x03\x04`
  check). The CLI keeps its own progress-bar wrapper, or passes a callback.
- `parse_zip_bytes(data, year) -> List[tuple]` — the existing member-pick
  (`pick_schedule_member`, incl. the 2020 non-`orig` rule) + `parse_schedule_rows`
  combined: ZIP bytes → `Schedules` row tuples. Pure, no network, no DB.
- `fetch_schedule_rows(year, *, fetch=download_zip, url_template=SCHEDULE_URL,
  local_zip=None) -> List[tuple]` — orchestrates fetch + parse; `fetch` and
  `local_zip` are injectable so **tests never hit the network**.
- `ingest_rows(conn, year, rows) -> int` — the existing
  `create_schedule_table` + `replace_year` (idempotent per year), returning rows
  inserted. Takes a `sqlite3.Connection` so both the CLI and the repo can call it.

The CLI (`scripts/build_schedule_db.py`) imports these and keeps its argparse,
progress bar, `--local-zip`, `--url`, `--start/--end`, and verification —
**observable script behavior is unchanged**. The module must have **no
network-at-import** and no side effects at import.

**DoD (Part 1):** `src/data/schedule_ingest.py` exists and
`build_schedule_db.py` delegates to it with unchanged CLI behavior;
`fetch_schedule_rows`/`ingest_rows` are unit-tested against a **synthetically
built in-test ZIP** (via `zipfile`, no network, no fixture download) covering a
normal year, the header-row skip, a postponed-with-makeup and a
postponed-no-makeup row, and the idempotent per-year replace (re-ingest same
year → same row count); `schedule_available_for` covers the 1876 gap and the
1877/2026 bounds. Rows round-trip through an in-memory DB + the existing
`get_schedule`. No UI, no runtime wiring in this part. (Not `risk:high`: pure
refactor + local functions; the network call is exercised only by the CLI, whose
behavior is unchanged, and by Part 2.)

### Part 2 — On-demand ingest at season start (`risk:high`)

Wire the ingest into `HistoricalSeasonSetupFlow` so picking a year with no
cached schedule fetches it automatically.

**Year picker — offer every buildable year, not just ingested ones.**
`_available_years()` changes from *"Lahman years ∩ `has_schedule`"* to *"Lahman
years ∩ `schedule_available_for(year)`"* — i.e. every year the app has a roster
for and Retrosheet publishes a schedule for. Years never ingested are now
offered (they were hidden before). The empty-list case becomes "no Lahman data /
no overlapping year" (the Lahman DB is missing) rather than "run the script".

**Repository write method.** Add
`LahmanRepository.ingest_schedule(year, rows) -> int` that calls
`schedule_ingest.ingest_rows(self.conn, year, rows)`. This keeps the
thread-affine `sqlite3` connection encapsulated in the repo and gives the flow a
single call. The app's repo connection is a normal writable
`sqlite3.connect(db_path)` (see `src/data/lahman.py`), so the write succeeds
against the user's local DB and **persists as a cache** — the next play of that
year skips the download.

**New setup step: fetch-if-missing.** After the year is chosen and before the
existing schedule-type toggle, insert a gate:

- If `repo.has_schedule(year)` is already true → proceed straight to the
  existing `_select_schedule_type(year)` (no download; instant — script-ingested
  or previously-cached years are unchanged in behavior).
- Otherwise run a **`ScheduleIngest` pass** modeled on `RoleCardPass`
  (`src/tui/role_card_pass.py`) — the same worker + thread-affinity discipline:
  1. Show a blocking/progress line ("Fetching {year} schedule…"), consistent
     with how the role-card pass and sim-ahead surface long work.
  2. On a **Textual worker**, run the **network + parse only**
     (`schedule_ingest.fetch_schedule_rows(year)`) — no DB touch on the worker
     (the repo's `sqlite3` connection is thread-affine; touching it off the main
     thread raises `ProgrammingError`, exactly the hazard `RoleCardPass`
     documents).
  3. Back on the **main thread**, write via `repo.ingest_schedule(year, rows)`.
  4. On success → `has_schedule(year)` is now true → continue to
     `_select_schedule_type(year)`.
  5. On failure → a **named** notification and return to the **year picker**
     (`_select_year()`), never a crash or a hung toast.

**Failure taxonomy (all → notify + back to year picker):**

- No network / host unreachable / timeout (`urllib.error.URLError`, socket
  errors) → "Couldn't reach Retrosheet to fetch the {year} schedule. Check your
  connection and try again."
- Year not published / 404 (the 404 body fails the ZIP-magic check →
  `ValueError`) or ZIP with no schedule member or 0 parsed rows → "No schedule is
  available for {year}." (Should be rare for an offered year, but the picker
  offers by coverage range, not by per-year confirmation.)
- Any other error escaping the worker is surfaced too (the `RoleCardPass`
  precedent: never leave the flow hung on a progress toast).

**Caching / idempotency.** `ingest_schedule` uses the existing clear-then-insert
per year, so a re-fetch (e.g. after a partial earlier attempt) is safe, and a
successful ingest persists — the download happens at most once per year per DB.

**Attribution.** On-demand fetching surfaces the same Retrosheet-copyrighted
data already covered by the in-product notice; no new attribution copy is
required. Confirm the existing notice remains present (README + the in-product
about/credits surface) — do not remove it.

**Shared helper note.** `ScheduleIngest` and `RoleCardPass` share the
gather/worker/continue shape; a small amount of duplication is acceptable rather
than over-abstracting (their payloads differ — one fetches+writes, one
builds+saves). If a clean shared base emerges, factor it, but it is not required.

**DoD (Part 2):** With a Lahman DB present but **no** ingested schedule for a
year Y (fresh `Schedules` table or none): picking Historical → Y shows a fetch
line, downloads Y's schedule, and starts the season on Y's real league and
schedule (grouped standings, playable/simmable) — with no prior
`build_schedule_db.py` run. Playing Y a **second** time does not re-download
(`has_schedule(Y)` is now true). A year that 404s or a no-network condition is
reported by name and returns to the year picker without crashing. Setup-flow and
ingest logic are tested **without `Pilot`** (mock-`self` / injected-fetcher house
style, no real network): the fetch-if-missing branch (present → skip; missing →
fetch → continue; failure → back-to-picker), and the worker's DB write staying on
the main thread. `risk:high` (external network at runtime + integration → routes
through `Verify`); the Verifier proves the live download-and-play on an
un-ingested year.

## Open questions

None requiring a human checkpoint. The one decision the issue flagged — on-demand
vs pre-generation, gated on a 20-second budget — is resolved by measurement
(≪ 20 s ⇒ on-demand; see [Timing](#timing-the-20-second-gate)). Product-taste
calls are resolved in-spec consistent with the existing historical-season spec's
precedent:

- **Offline behavior** — an un-ingested year with no network is reported and
  skipped (not synthesized); already-ingested years work offline. A future
  offline-first option (bundle a few popular years) is a follow-up, not a
  blocker.
- **Which years to offer** — all Lahman years within Retrosheet coverage
  (1877–2026, no 1876), fetched on demand; no per-year availability probe up
  front (a 404 on an offered year degrades to a named "no schedule available"
  message).

If the human later wants pre-bundled schedules, a prefetch-all option, or an
offline-first mode, those are follow-up issues.

## Issue breakdown

Part 1 is the importable foundation (leaves the CLI and app working unchanged);
Part 2 makes the app fetch on demand. Each leaves the app working and merged.

| Issue | Title | Depends on | Risk |
| --- | --- | --- | --- |
| FRE-144 | Extract runtime-importable schedule ingest module (`src/data/schedule_ingest.py`); refactor `build_schedule_db.py` to a thin CLI wrapper | — | — |
| FRE-145 | On-demand schedule fetch at historical season start: year picker by coverage, worker-based ingest, caching, failure handling | FRE-144 | high |
