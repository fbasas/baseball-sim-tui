# Spec: 2024+ Retrosheet schedule format fix (13-column layout)

**Source issue:** FRE-147 · **Date:** 2026-07-16 · **Status:** active

## Goal

Historical seasons for **2024 and 2025** are game-breaking today: 2025 fails to
start at all ("no played games in the 2025 schedule"), and 2024 "starts" as an
absurd 2-team / 1-game season. The cause is a Retrosheet schedule-file format
change in 2024 that the fixed-index parser misreads. This spec makes the schedule
parser handle **both** the pre-2024 (12-column) and 2024+ (13-column) layouts
correctly, and — because the broken rows are already cached in each user's local
`data/lahman.sqlite` and would otherwise never be re-fetched — **repairs the
stale cache** so an existing corrupt DB self-heals on the next play of an
affected year. The done vision: a player picks 2024 or 2025 in the historical
setup flow and gets the correct full-league slate, on a fresh DB *and* on a DB
that already cached the corrupt rows.

## Background — the exact defect

Retrosheet inserted a 13th field, **`Location`** (the park code), between
`Day/Night` and `Postponed`, starting with the **2024** schedule file. The files
ship a header row (verified against the real files and mirrored by the existing
test fixture in `tests/test_schedule_ingest.py`):

```
2023 (12 cols): Date,Num,Day,Visitor,League,Game,Home,League,Game,Day/Night,Postponed,Makeup
2024 (13 cols): Date,Num,Day,Visitor,League,Game,Home,League,Game,Day/Night,Location,Postponed,Makeup
```

`parse_schedule_rows` in `src/data/schedule_ingest.py` reads **fixed field
indices**: `fields[10]` → `postponed`, `fields[11]` → `makeup_date`. On a
13-column row that puts the **park code** (`SEO01`, `NYC20`, `TOK01`, `OAK01`, …)
into `postponed`, and shifts the real postponement text into the makeup slot.
Because *every* game has a location, *every* 2024/2025 row then looks postponed.
Downstream, `_effective_date` in `src/season/historical.py` treats a non-empty
`postponed` with a non-8-digit `makeup_date` as "cancelled — never made up" and
drops the game. For 2024, exactly one row's 13th field happened to parse as an
8-digit makeup date and survived (→ the 2-team/1-game season); for 2025, zero
survived (→ "no played games").

**Verified in the live DB (from the issue):** all 2,430 cached rows for each of
2024 and 2025 carry a park id in `postponed`; years ≤ 2023 (12-column) parse
correctly (e.g. 2012: 22 postponed rows, all with real makeup dates).

> Note: Retrosheet's public *format* doc page (retrosheet.org/schedule/) still
> describes the classic 12-field layout and does not mention the header row or
> the 2024 `Location` addition. Do not rely on it — the **actual downloaded
> files** carry a header and the 2024+ `Location` column, as verified above and
> in the test fixture. Retrosheet's 2024 semi-annual update is the source of the
> new location field (expanded elsewhere to city/state/country, but a single
> park-code column in the schedule file).

## Non-goals

- **No team-id / alias-table work.** Resolving 2024/2025 Retrosheet team ids to
  Lahman `teamID`s — in particular the **Athletics' 2024/2025 relocation** id —
  is **out of scope** and owned by **FRE-156** (which extends the FRE-154 alias
  table for 2022+). This issue only fixes *parsing* and *cache freshness*. See
  [Interplay with team resolution](#interplay-with-team-resolution-fre-154fre-156).
- **No change to the schedule data model, the `Schedules` table columns, or the
  on-demand-fetch worker/thread discipline** (`src/tui/schedule_ingest_pass.py`).
  The stored columns are unchanged: the park code is **not** persisted (the
  `Schedules` table has no location column and this spec does not add one — it is
  simply skipped during parsing).
- **No re-download of already-correct years.** The cache repair must target only
  *corrupt* cached years; it must not invalidate or re-fetch years that parsed
  correctly (≤ 2023, and any future correctly-parsed year).
- **No bulk backfill / pre-generation.** Repair happens lazily, at the moment the
  user starts a season for an affected year (same on-demand model as FRE-145).

## Design

Two coupled changes, both in the schedule-ingest area. Keep them in one issue:
the parser fix alone does not fix an already-corrupt DB (the report explicitly
requires the cache repair "as part of this fix"), and shipping only the parser
would leave every existing user — and the verifier — still broken.

### 1. Layout-aware parsing (`src/data/schedule_ingest.py`)

Make `parse_schedule_rows` locate the `postponed` and `makeup_date` fields
robustly instead of hard-coding indices 10 and 11. The fields that shift are
**only** `Postponed` and `Makeup` — everything at indices 0–9
(`Date … Day/Night`) is *before* the inserted `Location` column and never moves,
including the (duplicated) visitor/home `League`/`Game` columns.

Recommended approach — **header-name first, column-count fallback**:

1. **If a header row is present** (the first non-data row: `fields[0]` is not an
   8-digit date, and the row contains a `Postponed`/`Makeup`-style token), read
   the header to find the indices of the `Postponed` and `Makeup` columns by
   name, and use those indices for the data rows that follow. Keep indices 0–9
   positional.
2. **If no header is present** (headerless file), fall back to **column count**:
   `len(fields) >= 13` → `postponed = fields[11]`, `makeup = fields[12]`
   (location at `fields[10]`, skipped); `len(fields) == 12` → `postponed =
   fields[10]`, `makeup = fields[11]` (today's behavior).

**Gotcha — duplicate header names.** The header has `League` twice (visitor +
home) and `Game` twice, so a naïve `{name: index}` dict collides. This is why
only the *uniquely* named `Postponed` and `Makeup` columns are looked up by name;
everything else stays positional. Match header names case-insensitively and
trimmed (`Day/Night`, `Postponed`, `Makeup` are the canonical spellings; be
tolerant of surrounding quotes/whitespace).

A simpler acceptable alternative — if the implementer prefers — is **pure
column-count** parsing (12 vs 13) without reading the header at all, since the
`Location` column is the only structural change and it is always inserted at the
same position. Either is fine **provided the tests below pass**; the
header-first approach is preferred as the more future-proof of the two (it
survives a further trailing-column addition), but do not over-engineer.

Update the module docstring's "Record layout" section to document the 12- vs
13-column layouts and that `Location` is parsed-and-skipped.

**Do not** change `SCHEDULE_COLUMNS`, the stored tuple shape, `parse_zip_bytes`,
`fetch_schedule_rows`, or `ingest_rows` — the row tuple emitted is identical; only
*which source field* feeds `postponed`/`makeup_date` changes.

### 2. Stale-cache repair (self-heal)

The on-demand flow (`ScheduleIngest.run` in `src/tui/schedule_ingest_pass.py`)
only fetches when `repo.has_schedule(year)` is **false**. Corrupt 2024/2025 rows
make `has_schedule` true, so they are never re-fetched after the parser is fixed.
Add a repair path so an affected year is detected as corrupt and re-fetched.

**Detection — a pure, cheap check on cached rows.** A year is corrupt if its
cached rows show the park-code-in-`postponed` signature. Robust signature: the
year has cached rows AND (nearly) *every* row has a non-empty `postponed` value
matching the park-code shape `^[A-Z]{3}\d{2}$` (e.g. `SEO01`, `NYC20`, `TOK01`).
Real postponement text never looks like this, and in a correctly-parsed year only
a small fraction of rows are postponed at all — so requiring the pattern to hold
on essentially all rows (e.g. ≥ 90%, or simply "all non-empty postponed values
match the park-code shape AND > 50% of rows have a non-empty postponed") cleanly
separates corrupt years from healthy ones. Pick a threshold and justify it in a
code comment; add a test that a healthy year (with a handful of real postponed
rows) is **not** flagged.

Recommendation: implement the check as a small pure helper (e.g.
`schedule_year_is_corrupt(rows) -> bool` in `src/data/schedule_ingest.py`, taking
the same row objects `get_schedule` returns, or a repo method
`LahmanRepository.schedule_needs_repair(year)`), so it is unit-testable without
the TUI.

**Wiring — treat "corrupt" like "missing".** In the fetch-if-missing decision,
re-fetch when the year is missing **or** corrupt:

```
if repo.has_schedule(year) and not schedule_is_corrupt_for(year):
    on_success()          # cached and healthy — no download
    return
# else: fall through to the existing download → parse → ingest path
```

`ingest_rows`/`replace_year` already **delete the year's rows before
re-inserting** (idempotent per year), so a re-fetch cleanly overwrites the
corrupt rows — no separate delete needed. The repair therefore reuses the entire
existing on-demand path (worker/thread discipline, named failure notifications,
the `_finish` main-thread write) unchanged; only the *guard* that decides whether
to fetch changes.

> **Optional, not required:** a persisted "schedule-format version" counter would
> also force re-ingest of stale years and is mentioned in the issue as an
> alternative. It is heavier (a schema/metadata addition) and unnecessary given
> the corruption signature is unambiguous and cheap to check. Prefer the
> content-based detection above; only reach for a version stamp if the detection
> proves insufficient.

### Interplay with team resolution (FRE-154/FRE-156)

Fixing the parse makes 2024/2025 yield the **full ~2,430-game slate** again, which
is the pre-condition for *seeing* the real 2024/2025 Retrosheet team ids. Turning
that slate into a fully-started season also requires every team id to resolve to a
Lahman `teamID` via `retro_to_lahman_team`. Coverage of **2022+ divergences — in
particular the Athletics' 2024/2025 relocation id — is out of scope here and is
FRE-156's job** (blocked by this issue, exactly so those ids become visible).

Consequences for this issue's definition of done (below):

- **2025** — after the fix, `build_historical_season(2025)` must no longer raise
  `ValueError: no played games` (the ~2,430-game slate now parses). It **may**
  still raise `HistoricalSeasonError` naming an unresolved id (most likely the
  relocated Athletics). That is the *expected, correct* new behavior and is
  handed to FRE-156 — it is **not** a regression and **not** in scope to fix here.
- **2024** — the Athletics played their final Oakland season in 2024, so their
  id resolves via the existing `teamID == retro_id` fallback (`OAK`); 2024 is
  expected to build as a **full multi-team league** (not 2 teams / 1 game) after
  the fix. If any single 2024 id fails to resolve, that too is a named
  `HistoricalSeasonError` for FRE-156, not a parse defect.

Do **not** add a "blocked by FRE-156" relation to this issue — that would be
circular. This issue ships independently and unblocks FRE-156.

## Tests (part of the definition of done)

Extend `tests/test_schedule_ingest.py` (and add repair tests near the ingest/
`get_schedule` round-trip, or in `tests/test_schedule_data.py` as fits):

**Parser — both layouts.** Add a 13-column fixture mirroring the real 2024 header
and a location column, alongside the existing 12-column `FIXTURE_SCHEDULE`:

```
Date,Num,Day,Visitor,League,Game,Home,League,Game,Day/Night,Location,Postponed,Makeup
"20240328","0","Thu","OAK","AL",1,"SEA","AL",1,"N","SEO01","",""
"20240402","0","Tue","BOS","AL",1,"OAK","AL",1,"D","OAK01","Rain","20240403"
"20240615","0","Sat","SDN","NL",1,"CHN","NL",1,"D","TOK01","Hurricane",""
```

Assert, for the 13-column parse:
- Row count and years are correct (header skipped).
- A **normal** game: `postponed is None`, `makeup_date is None` — and the park
  code (`SEO01`) is **not** in `postponed`.
- A **postponed-with-makeup** game: `postponed == "Rain"`, `makeup_date ==
  20240403` (int).
- A **postponed-without-makeup** game: `postponed == "Hurricane"`, `makeup_date
  is None`.
- The existing 12-column fixture still parses identically (no regression).
- (If the header-first approach is used) a **headerless** 13-column body still
  parses via the column-count fallback.

**Cache-repair detection.**
- A year whose rows all carry park-code `postponed` values (the corrupt fixture,
  round-tripped through `ingest_rows` + `get_schedule`) is flagged corrupt.
- A **healthy** year (the 12-column fixture: a couple of real postponed rows,
  the rest empty) is **not** flagged.
- End-to-end via the fetch-if-missing guard (using the existing injected
  `fetch_rows`/`ScheduleIngest` test seam in `tests/test_schedule_ingest_pass.py`):
  a repo pre-loaded with corrupt rows triggers a re-fetch (guard returns
  "needs fetch"), and after ingest the year is no longer flagged corrupt.

All existing schedule/historical tests must stay green.

## Open questions

None requiring a human checkpoint. The format change, the corruption signature,
and the fix are all verified from the report + the live DB + the test fixture.
The one deferred unknown (the Athletics' 2024/2025 Retrosheet↔Lahman id) is
already tracked as FRE-156 and is explicitly out of scope here.

## Definition of done

1. `parse_schedule_rows` correctly parses **both** 12- and 13-column Retrosheet
   schedule layouts: on a 13-column file the park code never lands in
   `postponed`, and only genuinely-postponed games have a non-empty `postponed`.
2. Fixture tests cover both layouts (and the headerless fallback if used); all
   existing tests remain green.
3. The stale-cache repair detects a DB whose 2024/2025 rows carry the
   park-code-in-`postponed` signature and forces a re-fetch on the next play of
   that year, while leaving healthy years untouched. Covered by tests.
4. **Live proof (risk:high → Verify):** with a real Retrosheet fetch,
   `build_historical_season(2025)` no longer raises "no played games" (the
   ~2,430-game slate parses), and 2024 builds a full multi-team league rather
   than 2 teams / 1 game. A residual `HistoricalSeasonError` naming an
   unresolved team id (e.g. the relocated Athletics) is acceptable and is
   deferred to FRE-156 — it is *not* a failure of this issue.

## Issue breakdown

This issue is atomic (one coherent bug fix, within the sizing rule) and is
implemented directly as FRE-147 rather than decomposed.

| Issue | Title | Depends on | Risk |
| --- | --- | --- | --- |
| FRE-147 | Fix 2024+ (13-column) Retrosheet schedule parsing + repair stale cache | — | risk:high |
| FRE-156 | Extend the retro→Lahman alias table for 2022+ (Athletics relocation) — *follow-up, blocked by this* | FRE-147, FRE-154 | — |
