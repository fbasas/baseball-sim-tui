# Spec: Schedule / historical-season test hardening (close the test gap)

**Source issue:** FRE-150 · **Date:** 2026-07-16 · **Status:** active

## Goal

Make the test suite *capable of catching* the class of failure that let FRE-147
and FRE-148 ship green: 1045 tests passed while every historical season from
1970–2025 except 1998–2004 was unplayable. Three structural blind spots did it —
all parser fixtures were synthetic 12-column rows (so the 13-column 2024+ layout
was never exercised), no test covered a Retrosheet-id ≠ Lahman-id team join, and
the DB-backed integration tests skipped silently on exactly the broken condition
(they guard on `has_schedule(<year never ingested>)`, so they have plausibly
never run anywhere). This spec adds **real-format fixtures**, a **runnable
end-to-end integration test with strong season invariants**, and **alias-era join
coverage** so a regression in any of these surfaces as a red test, not a green
suite over a broken product.

This is test-only work. It does **not** fix the underlying bugs — those are
FRE-147 (parser), FRE-154 (join alias table), FRE-155 (error surface), FRE-149
(degenerate-league validation). It builds the net that would have caught them.

## Non-goals

- **No production-code bug fixes.** The parser fix lives in FRE-147, the
  Retrosheet→Lahman join fix in FRE-154, the actionable-error surface in FRE-155,
  and the degenerate-season validation in FRE-149. This spec only adds/strengthens
  tests and test fixtures. Where a test asserts behavior a sibling issue delivers,
  this spec **blocks on that sibling** rather than duplicating the fix.
- **No duplication of a sibling's regression test.** In particular, the
  **stale-DB (no `teamIDretro` column) alias-table resolution** is FRE-154's own
  regression surface (it is `risk:high` and routes through Verify). This spec
  covers the **`teamIDretro`-column-present** resolution path (a fresh / rebuilt
  DB) across the real alias eras — a different code path and scenario — and does
  not re-assert the column-absent path.
- **No CI system.** The repo has no GitHub Actions / CI today. "Make the
  integration tests run" is delivered by a **committed, offline fixture dataset**
  the tests always exercise — not by standing up CI. (A CI workflow is worth a
  separate future issue but is out of scope here.)
- **No network in tests.** Every fixture is committed or constructed in-process.
  No test may reach retrosheet.org or any Lahman host.
- **No new runtime dependency**, no change to `data/lahman.sqlite` on disk.

## Background — the code under test (unchanged by this spec)

- **Parsing** lives in `src/data/schedule_ingest.py` (`parse_schedule_rows`,
  `parse_zip_bytes`, `pick_schedule_member`, `fetch_schedule_rows`,
  `ingest_rows`). `scripts/build_schedule_db.py` re-exports the same functions
  for the CLI, and `tests/test_schedule_data.py` currently imports the CLI copy.
  `parse_schedule_rows` reads **fixed field indices** (`fields[10]`→postponed,
  `fields[11]`→makeup) and is the FRE-147 bug: on a 13-column file those indices
  point at the wrong fields.
- **Join** is `LahmanRepository.retro_to_lahman_team(retro_id, year)`
  (`src/data/lahman.py`): step 1 `teamIDretro` column, step 2 exact
  `teamID == retro_id`, else `None`. FRE-154 adds a committed year-scoped alias
  table as step 3 (reached only when the column is absent).
- **Build** is `build_historical_season(repo, year, user_team_key=None)`
  (`src/season/historical.py`): drops cancellations (`_effective_date`), resolves
  every played-slate Retrosheet id, loads each team's season + roster, and groups
  played rows into `SeasonDay`s (day ordinal == list index). It needs the repo to
  expose `get_schedule`, `retro_to_lahman_team`, `get_team_season`,
  `get_team_roster`.

### The real Retrosheet formats (authoritative — downloaded 2026-07-16)

Verified by downloading the actual `2012SKED.zip`, `2020SKED.zip`, and
`2024SKED.zip` from retrosheet.org. Implementer sessions have no web access, so
the **verbatim sample rows below are the fixture source of record.** Copy them
exactly (commas, quoting, empty fields, day-name spelling, and case all matter).

**12-column layout (through 2023) — quoted CSV, abbreviated day, header present.**
Example from `2012schedule.csv` (the season game-number fields, columns 6 & 9,
are *unquoted* integers):

```
Date,Num,Day,Visitor,League,Game,Home,League,Game,Day/Night,Postponed,Makeup
"20120328","0","Wed","SEA","AL",1,"OAK","AL",1,"N","",""
"20120410","0","Tue","CHA","AL",5,"CLE","AL",5,"N","Rain","20120507"
"20120420","0","Fri","TEX","AL",14,"DET","AL",14,"N","Rain","20120421"
```

Field order (12): `Date, Num, Day, Visitor, Vis-League, Vis-GameNo, Home,
Home-League, Home-GameNo, Day/Night, Postponed, Makeup`. Postponed at index 10,
Makeup at index 11 — the current parser is correct here.

**13-column layout (2024+) — UNquoted CSV, full day name, lowercase Day/Night, a
new `Location` column at index 10.** Example from `2024schedule.csv`:

```
Date,Num,Day,Visitor,League,Game,Home,League,Game,Day/Night,Location,Postponed,Makeup
20240320,0,Wednesday,LAN,NL,1,SDN,NL,1,n,SEO01,,
20240321,0,Thursday,SDN,NL,2,LAN,NL,2,n,SEO01,,
20240328,0,Thursday,MIL,NL,1,NYN,NL,1,d,NYC20,Rain,20240329
20240328,0,Thursday,ANA,AL,1,BAL,AL,1,d,BAL12,,
```

Field order (13): `... Day/Night, Location, Postponed, Makeup`. **Postponed is
now index 11, Makeup index 12.** `Location` (index 10) is a Retrosheet park code
(`SEO01` = the Seoul Series at Gocheok Sky Dome, `NYC20` = Citi Field, `BAL12` =
Camden Yards). The `MIL@NYN` row is the target postponement case: `Location=NYC20,
Postponed=Rain, Makeup=20240329`. The current parser mis-reads index 10 (`NYC20`)
as *postponed* and index 11 (`Rain`) as *makeup* (which then fails the 8-digit
check → `None`), so **every 2024 row looks cancelled** and the season is destroyed.

**2020 two-member ZIP.** `2020SKED.zip` contains two members —
`2020sched-orig.csv` (the pre-pandemic 162-game original) and `2020schedule.csv`
(the played 60-game slate). Both are 12-column quoted files. `pick_schedule_member`
must select `2020schedule.csv` (the non-`orig` one). First played row:
`"20200723","0","Thu","NYA","AL",1,"WAS","NL",1,"n","",""`.

## Design

### Fixture conventions

- New committed fixtures live under `tests/fixtures/schedules/` as **plain-text
  files** holding the verbatim excerpts above (e.g. `2012_head.csv`,
  `2024_head.csv`) — reviewable in a diff, no binary blobs. Keep each to ~5–8
  rows: enough to cover header + normal game + doubleheader + postponed-with-makeup
  + cancelled + (for 2024) a Location-bearing Seoul row.
- ZIP-shaped fixtures (2020 two-member case) are **constructed in-process** with
  `zipfile` from two member strings — no committed `.zip`. This keeps the tree
  text-only and lets `parse_zip_bytes` / `pick_schedule_member` be tested against
  real member names.
- The historical-season integration fixture is a **tiny SQLite built in-process**
  by a shared helper (see below), not a committed `.sqlite`.

### Reusable helpers this spec introduces

1. **`tests/support/mini_lahman.py`** — a builder that constructs a minimal but
   *valid* Lahman+Schedules SQLite in a `tmp_path` (or `:memory:`): `Teams` (incl.
   `teamIDretro`, `lgID`, `divID`, `name`, `BPF`, `PPF`, `G`), `People`, `Batting`,
   and `Schedules`. Parameterized by (year, team list with retro↔lahman ids and
   league/division, games). Enough that `build_historical_season` runs end-to-end.
   One helper, reused by the integration test and the invariant test.
2. **`tests/support/season_invariants.py`** — `assert_season_invariants(state, *,
   raw_row_count, lahman_games_by_team, min_league_size, min_retention=0.8,
   min_team_games=40)` raising `AssertionError` **naming the offending numbers**
   when a built `SeasonState` doesn't look like a real season. This is the
   throwaway QA harness made permanent. Checks:
   - **day == list index** for every `ScheduledGame` (`game.day == index`);
   - **game_id contiguous** from 0 in play order (`ids == list(range(len(ids)))`);
   - **league size** `len(state.teams) >= min_league_size`;
   - **retention** played games ≥ `min_retention × raw_row_count`;
   - **per-team games** each team's scheduled-game count ≥ `min_team_games`, and —
     when `lahman_games_by_team` is supplied — within a small band of Lahman
     `Teams.G` (use a band, **not** equality: real per-team totals sit within
     ~1–3 of Lahman G because of ties/replays; a 1927 team plays 153–154 vs G).

   Verified healthy baselines (from FRE-149, for choosing bands/thresholds): 1927
   actual → 16 teams, 174 days, 1227 of 1232 raw rows retained (99.6%), per-team
   153–154 games; a modern year → 30 teams, ~2430 games. The corrupted 2024 cache
   retained 1 of 2430 rows (0.04%) with a 2-team "league" — the harness must flag
   that loudly.

### Test additions by issue

**Issue A (FRE-157) — real-format parser/ingest fixtures (both layouts + 2020 ZIP).**
Rewrite/extend the parser tests in `tests/test_schedule_data.py` (and/or a new
`tests/test_schedule_formats.py`) to exercise the committed real-format fixtures:
- 12-column (`2012_head.csv`): postponed/makeup land in the right columns
  (`Rain`/`20120507`), doubleheaders, cancelled-vs-made-up.
- 13-column (`2024_head.csv`): **Postponed at index 11, Makeup at index 12**; the
  `MIL@NYN` row parses to `postponed="Rain", makeup_date=20240329`; the Seoul row
  (`LAN@SDN … SEO01`) parses as a *played* game (not cancelled) with the park code
  **not** leaking into `postponed`. This assertion **fails on today's fixed-index
  parser and passes once FRE-147 lands** — hence Issue A is blocked by FRE-147.
- 2020: build an in-process ZIP with members `2020sched-orig.csv` +
  `2020schedule.csv`; assert `pick_schedule_member` / `parse_zip_bytes` select the
  played file and yield sane rows.

**Issue B (FRE-158) — runnable end-to-end integration test + strong invariants.**
- Add `tests/support/mini_lahman.py` and `tests/support/season_invariants.py`.
- A test that builds an 8-team (≥ `min_league_size`) single- or double-round-robin
  season via the helper, runs `build_historical_season`, and asserts
  `assert_season_invariants(...)`. This **always runs** (no `pytest.skip`), closing
  the "integration tests never execute" gap with a committed offline dataset.
- Include one Retrosheet-id ≠ Lahman-id team in the fixture (e.g. a team with
  `teamID='LAA', teamIDretro='ANA'`) so the join is exercised inside the build.
- A **negative** test: feed the harness a degenerate 2-team / 1-game season (the
  exact 2024-cache shape) and assert `assert_season_invariants` raises with a
  message naming the retention/league-size numbers. This is the check that would
  have caught FRE-149's degenerate league.
- Strengthen the existing guarded real-DB tests (`TestBuildHistoricalSeasonDB` in
  `tests/test_season_historical.py`, `TestScheduleIntegration` in
  `tests/test_schedule_data.py`): replace the weak `len(state.teams) >= 2` with
  `assert_season_invariants`, and make the skip **loud** — emit a
  warning (`warnings.warn` / `pytest` warning) when the real DB or its schedule
  data is absent, so a skipped integration run is visible in the summary rather
  than indistinguishable from a pass.

**Issue C (FRE-159) — Retrosheet→Lahman join coverage across the real alias eras.**
Unit tests for `retro_to_lahman_team` against a `Teams` fixture that **includes
`teamIDretro`**, covering the real franchise divergences (from FRE-154's
authoritative six-mapping table) with **year-scoping**:
- `ANA` → `LAA` for 2005+ (fixture row `2019: teamID=LAA, teamIDretro=ANA`), and
  `ANA` → `ANA` for 2004 (fixture row `2004: teamID=ANA, teamIDretro=ANA`) — the
  same Retrosheet id resolving differently by year.
- `MIL` → `ML4` for 1970–1997 (`1994: teamID=ML4, teamIDretro=MIL`) and
  `MIL` → `MIL` for a modern year (`2019: teamID=MIL, teamIDretro=MIL`).
- one pre-war divergence, `WSN` → `WAS` (`1899: teamID=WAS, teamIDretro=WSN`), or
  the exact-match pre-war control `WS1` → `WS1` (`1927`).
- exact-match controls (`NYA`→`NYA`) and unresolved (`ZZZ`→`None`, wrong-year).

These assert the **column-present** path (a fresh/rebuilt DB) and are green on
today's code. The **column-absent** stale-DB path (where FRE-154's alias table
becomes the resolver) is FRE-154's own `risk:high` regression surface and is **not**
re-asserted here (see Non-goals).

## Open questions

None require a human. Thresholds/bands for the invariant harness are grounded in
FRE-149's verified baselines (above); the implementer may tune the exact band
width so real years pass, as long as the degenerate-league negative test still
fails the harness.

## Issue breakdown

| Issue | Title | Depends on | Risk |
| --- | --- | --- | --- |
| FRE-157 | Real-format Retrosheet schedule fixtures + both-layout parser tests | FRE-147 | low |
| FRE-158 | Runnable historical-season integration test + strong season-invariant harness | — | low |
| FRE-159 | Retrosheet→Lahman join tests across the real alias eras (`teamIDretro`-present) | — | low |
