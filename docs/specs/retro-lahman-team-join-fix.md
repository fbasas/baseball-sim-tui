# Spec: Robust Retrosheet→Lahman team-id resolution (stale-DB self-heal)

**Source issue:** FRE-148 · **Date:** 2026-07-16 · **Status:** active

## Goal

Make historical-season team resolution work on a Lahman database that predates
the `teamIDretro` column, so historical seasons build for every supported year
instead of being blocked by "unresolved Retrosheet id" errors. Today `ANA` fails
for every season 2005+ (Retrosheet keeps `ANA`; Lahman's `teamID` became `LAA`)
and `MIL` fails 1970–1997 (Lahman `ML4`); combined with the 2024/2025 parse bug
(FRE-147) no season 1970–2025 is playable except 1998–2004. This delivers the fix
for the join half: a stale DB resolves those franchises correctly with no rebuild,
and any residual failure produces an actionable, persistent error instead of a
12-second toast that vanishes.

## Background — how the join works today (from ADR-001)

Retrosheet schedule files use a team id per game (`vis_team` / `home_team`, e.g.
`ANA`). Lahman rosters/stats are keyed by `teamID` (e.g. `LAA`). The bridge is the
Lahman `Teams.teamIDretro` column: for a given `(yearID)`, the row whose
`teamIDretro` equals the schedule's Retrosheet id gives the Lahman `teamID`.
`LahmanRepository.retro_to_lahman_team(retro_id, year)` (src/data/lahman.py)
resolves in two steps:

1. **`teamIDretro` column** — `SELECT teamID FROM Teams WHERE yearID=? AND
   teamIDretro=?`. On `sqlite3.OperationalError` (column absent) it silently
   swallows the error and falls through to step 2.
2. **Exact match** — `SELECT teamID FROM Teams WHERE yearID=? AND teamID=?`.
   Correct only when the Retrosheet id equals the Lahman `teamID` (most teams).

ADR-001 verified empirically that **step 1 alone covers every era** (zero
unresolved ids across 1927/1969/1981/1994/2016/2020). So the *only* defect is that
the shipped `data/lahman.sqlite` was built before `teamIDretro` was added to
`scripts/build_lahman_db.py`'s Teams column list; a rebuild would fix it, but
nothing prompts one and the exact-match fallback degrades silently.

## Design

### Why not `ALTER TABLE … ADD COLUMN` + backfill (the issue's suggested fix)

The issue suggests self-healing by adding the column and backfilling it "from the
Lahman CSV zip already in `data/`". That premise doesn't hold here:

- **`data/` is gitignored and empty in the repo** (`data/*.zip`, `data/*.sqlite`
  are ignored; only `.gitkeep` is tracked). `build_lahman_db.py` downloads the
  CSV zip into memory and never writes it to disk, so there is normally **no zip
  on disk** to backfill from, and the CSV host (`seanlahman.com`) is not reliably
  reachable.
- So the only *guaranteed-present* backfill source is data committed to the repo.
  Given that, writing it into the user's DB (an `ALTER` + row updates on open,
  with the thread-affine-connection and read-only-DB hazards that implies) buys
  nothing over consulting the committed data directly at resolve time.

**Decision:** keep `teamIDretro` as the primary join (unchanged for fresh /
jknecht-built DBs), and add a **committed, year-scoped Retrosheet→Lahman alias
table** as a read-only third resolution step. No DB mutation, smallest blast
radius, fully offline and testable. This is ADR-001's rejected "franchise-level
map" made **year-scoped** (ADR-001 rejected only the *year-agnostic* form).

### The alias table — authoritative and complete (through 2021)

Derived from Lahman's own `Teams` data (`teamIDretro` column): the set of
`(yearID, teamID)` where `teamIDretro != teamID` is exactly the set the
exact-match fallback fails on. Computed from the full Lahman `Teams.csv`
(1871–2021), that set is only **six** distinct franchise mappings:

| Retrosheet id (`teamIDretro`) | Lahman `teamID` | Years |
| --- | --- | --- |
| `CN4` | `CN1` | 1880 |
| `BL5` | `BL2` | 1882 |
| `WSN` | `WAS` | 1892–1899 |
| `MLN` | `ML1` | 1953–1965 |
| `MIL` | `ML4` | 1970–1997 |
| `ANA` | `LAA` | 2005–present |

Verified properties (checked against the full Lahman `Teams.csv`):

- **No collisions.** In no year does a wrong team's `teamID` equal a divergent
  Retrosheet id, so exact-match-first can never return the wrong team — the alias
  table is a safe *last* step.
- **No ambiguity.** No year has two teams sharing a `teamIDretro`, so
  `(retro_id, year)` → `teamID` is a function.
- This matches FRE-148's empirical finding exactly (only `ANA` 2005+ and `MIL`
  1970–1997 fail in the modern era).

`ANA`→`LAA` is extended **through the schedule max year (2026)** because the
Angels remain `LAA` in Lahman (the source CSV merely stops at 2021). **Out of
scope:** any *new* divergence in 2022+ — in particular the Athletics' 2024/2025
relocation, whose Retrosheet id is not yet known here. That belongs with the
2024/2025 work in **FRE-147** and is tracked as a follow-up (see Issue breakdown).

### Resolution order (final)

`retro_to_lahman_team(retro_id, year)`:

1. `teamIDretro` column (existing; unchanged — fresh/jknecht DBs stop here).
2. Exact `teamID == retro_id` (existing; unchanged).
3. **New:** committed alias table lookup `(retro_id, year) → teamID`.
4. `None` (unresolved).

### Actionable error on residual failure

When resolution still yields `None` (or a resolved team's record/roster won't
load), `build_historical_season` raises `HistoricalSeasonError` and the setup
flow (`src/tui/historical_setup_flow.py::_build_league`) shows a 12-second toast
that then vanishes, stranding the user at the year picker with no explanation.
Replace that, for the **unresolved-Retrosheet-id** case, with a **persistent,
actionable** message naming the remediation: the database likely predates schedule
support and should be rebuilt with `python scripts/build_lahman_db.py`. "Persistent"
= it must remain visible until the user dismisses/acts, not auto-dismiss after a
few seconds (implementer chooses the mechanism: a sticky notification, an inline
year-picker label, or a modal). This is a defense-in-depth safety net; with the
alias table, supported historical years should not reach it.

## Non-goals

- **No DB migration / `ALTER TABLE` / write to the user's DB.** Resolution stays
  read-only (see rationale above).
- **No change to `build_lahman_db.py`.** Fresh builds already include
  `teamIDretro`; this spec fixes *stale* DBs at runtime.
- **No 2024/2025 schedule parse fix.** That is FRE-147; the two are independent
  and stack.
- **No 2022+ divergence coverage** beyond continuing `ANA`→`LAA` (see follow-up).
- **No re-offering / hiding of irregular strike years.** 1981/1994 are in scope as
  verification targets (they build once the join works, per the source issue);
  whether to *flag* them in the picker is a separate product question, untouched
  here.

## Open questions

None requiring a human checkpoint. The backfill approach, alias-table source, and
error-surfacing mechanism are technical decisions made above; the product
questions (which years to offer, strike-year handling) were already settled by the
source issue and ADR-001.

## Verification (definition of done for the epic)

On a Lahman DB **without** a `teamIDretro` column (a stale DB), `retro_to_lahman_team`
must resolve `ANA`→`LAA` for 2012/2016/2019 and `MIL`→`ML4` for 1994, and
`build_historical_season(repo, year)` must succeed for **1927, 1969, 1981, 1994,
2012, 2016, 2019** (all confirmed by the source issue to parse and resolve cleanly
once the join works). A DB *with* the column must behave exactly as before. This is
the live proof the Verifier runs (this epic's core issue is `risk:high`).

## Issue breakdown

| Issue | Title | Depends on | Risk |
| --- | --- | --- | --- |
| FRE-154 | Year-scoped Retrosheet→Lahman alias table so stale DBs resolve ANA/MIL/etc. | — | high |
| FRE-155 | Persistent, actionable error when a historical team can't resolve | — | — |
| FRE-156 | Extend/regenerate the retro→Lahman alias table for 2022+ (incl. Athletics relocation) | FRE-147, FRE-154 | — |
