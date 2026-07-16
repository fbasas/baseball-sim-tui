# Spec: Historical-season shape validation (block degenerate leagues before launch)

**Source issue:** FRE-149 · **Date:** 2026-07-16 · **Status:** active

## Goal

Make `build_historical_season` **refuse to build a degenerate season** — one that,
after the postponed/makeup filter, has lost entire teams or the great majority of
its games — and instead raise an **actionable, numeric** error naming what looks
wrong ("the 2024 schedule has 2430 raw rows but only 1 playable game — the
schedule data looks corrupt; re-fetch it"). Today the builder trusts whatever
survives the filter: with the corrupted 2024 cache
([FRE-147](https://linear.app/fred-basas/issue/FRE-147/schedule-ingest-misparses-2024-retrosheet-files-new-13-column-format))
it walked the user through a full setup and landed on a **"Day 1 of 1", 2-team**
"season" with complete confidence. The done vision: any future data problem
(format drift, partial ingest, truncated download that still yields *some* rows)
produces a diagnosable, blocking error at build time — the same blocking
precedent season mode already applies to unresolved teams ("a faithful league
loads cleanly") — rather than a quietly absurd season.

This is **defense-in-depth** independent of the parser fix (FRE-147). FRE-147
removes *this* trigger; this spec guards against the *class* of trigger.

## Non-goals

- **No parser / cache / ingest changes.** The 2024 13-column parse fix and the
  stale-cache repair are FRE-147; the Retrosheet→Lahman join is FRE-154/155.
  This spec adds a **shape check on the builder's own output** and nothing else.
- **No new setup-flow UI.** The new error is a `ValueError` subclass, so the
  **existing** `historical_setup_flow.py::_build_league` `except ValueError`
  branch already catches it, shows its message, and returns to the year picker —
  no setup-flow source change is required or in scope. Giving the degenerate case
  the *persistent* (non-auto-dismiss) treatment that
  [FRE-155](https://linear.app/fred-basas/issue/FRE-155) gives the
  unresolved-team case is a **possible follow-up**, deliberately left out here so
  the two issues do not edit the same method in parallel.
- **No change to the existing failure paths.** The `no schedule data` /
  `no played games` `ValueError`s and the `HistoricalSeasonError`
  (unresolved/unloadable team) path are unchanged. The shape check is a new,
  additional gate.
- **No absolute league-size floor, no exact-equality-with-Lahman check.** Both
  would misfire (see Design): a hard `len(league) >= 8` rejects the real 6-team
  1877/1878 NL; exact per-team equality with Lahman `Teams.G` is too strict
  (ties/replays put real per-team totals 1–3 off Lahman). All bounds are **bands
  relative to the year's own raw data**, not absolutes, except one deliberately
  loose per-team floor (justified below).
- **No round-robin / generated-variant behavior change** beyond the shape gate
  also applying to generated seasons (which build on the actual builder).

## Background — the exact defect

`build_historical_season(repo, year, ...)` in `src/season/historical.py`:

1. `rows = repo.get_schedule(year)` — **every** scheduled row (played, postponed,
   cancelled). Call this the **raw** slate.
2. Filters to `played` = rows that are not cancelled (postponed-with-no-makeup is
   dropped; makeups move to their makeup date) — see `_effective_date`.
3. Resolves each played row's Retrosheet ids to Lahman teams, loads season+roster
   (unresolved/unloadable → `HistoricalSeasonError`).
4. Groups `played` into `SeasonDay`s (day ordinal == list index).
5. Builds one `LeagueTeam` per resolved team.
6. `SeasonState.from_schedule(...)` — **skips** the round-robin size/games checks.

Nothing between steps 2 and 6 asks "does this look like a real season?". With the
corrupt 2024 cache, step 2 left **1 game between 2 teams** out of **2430 raw
rows**, every downstream step succeeded, and the app presented it as a full
historical season.

### Verified era baselines (bake these into the thresholds)

From ADR `docs/adr/001-historical-schedule-data.md` (sample parsed 2026-07-15)
and web-verified season lengths (2026-07-16). "Retained" = played ÷ raw rows;
"per-team" = games actually played per team.

| Year | Kind | Teams | Per-team (played) | Retained | Note |
| ---- | ---- | ----- | ----------------- | -------- | ---- |
| 1877 / 1878 | earliest NL | **6** | ~60 (shortest real seasons) | ~high | smallest real league; ~60 g/team |
| 1927 | clean 16-team | 16 | 153–154 | **1227/1232 ≈ 99.6%** | 5 cancelled |
| 1969 | 24-team | 24 | 160–162 | high | 3 cancelled |
| 2016 | modern 30-team | 30 | 161–162 | high | 2 cancelled |
| 2020 | COVID short | 30 | **57–60** | high | 5 cancelled |
| 1981 | strike (split) | 26 | 103–111 | **≈ 66%** | 713 cancelled |
| 1994 | strike (short) | 28 | 112–118 | **≈ 71%** | 659 cancelled |
| 2024 (corrupt cache) | **degenerate** | **2** | **~1** | **1/2430 ≈ 0.04%** | the bug |

Takeaways that set the bounds:
- **Smallest real league is 6 (1877/1878), not 8** — no absolute league-size floor.
- **Real seasons never drop below ~66% retained** (the strike years are the
  floor); the degenerate case is ~0.04%. A retention band with a wide gap between
  these is safe.
- **Smallest real per-team count is ~57–60** (1877, 2020). The degenerate case is
  ~1. A per-team floor anywhere in the 40s cleanly separates them and additionally
  catches a **truncated modern download** (~25 g/team from a partial file — the
  issue's stated concern).
- **Per-team totals sit within 1–3 of Lahman `Teams.G`** (ties/replays) → use
  bands, never equality.

## Design

Add a single shape gate, `_validate_season_shape`, called inside
`build_historical_season` **right after the `played` slate is assembled** (after
the existing `if not played: raise ValueError` block, before team resolution — it
needs only raw Retrosheet ids and row counts, so it runs before the more
expensive resolution/roster loads and its data-corruption message takes
precedence over any incidental downstream failure).

### The three checks (all era-safe)

Let `raw = rows`, `played = the filtered list`. Team sets use **raw Retrosheet
ids** directly (no Lahman resolution needed):

- `raw_teams  = { r.vis_team, r.home_team  for r in raw }`
- `played_teams = { r.vis_team, r.home_team for (_date, r) in played }`
  (`played_teams ⊆ raw_teams` always).

1. **No whole team vanishes** — `played_teams == raw_teams`. A real season never
   cancels *every* game a team plays; if a team appears only in cancelled rows the
   slate is corrupt. Self-relative → era-safe (6-team 1877 and 30-team 2024
   alike). Catches 2024 (2 played vs 30 raw).

2. **Game retention** — `len(played) / len(raw) >= MIN_GAME_RETENTION`
   (`MIN_GAME_RETENTION = 0.5`). Clean years ≈ 0.99, strike years ≈ 0.66–0.71 →
   pass with margin; 2024 ≈ 0.0004 → fails decisively. Self-relative → era-safe.
   This is the headline "lost most of its games" check.

3. **Minimum per-team played games** —
   `min over played_teams of (appearances in played) >= MIN_GAMES_PER_TEAM`
   (`MIN_GAMES_PER_TEAM = 40`). Every real season in coverage plays ≥ ~57/team;
   40 clears them all with margin, catches the degenerate ~1/team **and** a
   truncated partial-ingest (~25/team) where checks 1–2 might pass because the
   *raw* file itself is small/truncated. This is the one **absolute** floor;
   chosen at 40 to catch truncated modern data per the issue's "truncated
   download that still yields some rows" concern. Documented trade-off: it can
   reject the most extreme 19th-century **folded-franchise** curiosities (e.g. a
   handful of 1884 Union Association teams that played < 40 games before
   disbanding). That is acceptable — the error is actionable and the user can
   pick another year — and the floor is a **named module constant**, a one-line
   change if those seasons are ever wanted (a follow-up, not this issue).

Run the checks in order; **collect every failed check's reason** and raise once
(mirroring how `HistoricalSeasonError` collects `problem_teams`), so the message
is maximally diagnostic when several fire at once (2024 trips all three).

### The exception

```python
class DegenerateHistoricalSeasonError(ValueError):
    """The built season is structurally implausible (corrupt/partial schedule).

    Distinct from HistoricalSeasonError (which is a per-team resolve/load
    failure): here the teams resolve fine but the surviving slate is degenerate
    — entire teams missing, most games gone, or too few games per team. NOT a
    subclass of HistoricalSeasonError, so the setup flow's team-oriented handler
    does not mis-handle it; it IS a ValueError, so the flow's existing
    `except ValueError` branch surfaces it and returns to the year picker.
    """
    def __init__(self, year, raw_rows, played_games, reasons):
        self.year = year
        self.raw_rows = raw_rows
        self.played_games = played_games
        self.reasons = list(reasons)
        super().__init__(
            f"The {year} schedule looks corrupt: {raw_rows} scheduled row(s) "
            f"but only {played_games} playable game(s) — "
            f"{'; '.join(self.reasons)}. Re-fetch the schedule data."
        )
```

The message always leads with the `raw_rows → played_games` headline the issue
asked for, then the specific failed check(s). Example reasons:
- `"entire teams are missing (30 teams scheduled, only 2 play)"`
- `"only 0% of scheduled games survived (needs >= 50%)"`
- `"the OAK slate has just 1 game (needs >= 40 per team)"`

### Wiring into the builder

- Add module constants `MIN_GAME_RETENTION = 0.5` and `MIN_GAMES_PER_TEAM = 40`
  with a comment citing the era table above.
- Add keyword-only `validate: bool = True` to **both** `build_historical_season`
  and `build_generated_historical_season`. The generated builder threads its
  `validate` into its `build_historical_season(...)` call (validation runs on the
  real played slate before the shuffle — same games, so the shuffled schedule
  needs no separate check).
- In `build_historical_season`, when `validate`, call
  `_validate_season_shape(year, rows, played)` immediately after the
  `if not played` guard.
- Update the builders' docstring `Raises:` sections to list
  `DegenerateHistoricalSeasonError`.

**Why the `validate` flag:** the existing structural unit tests in
`tests/test_season_historical.py` use a deliberately tiny 4-team `standard_schedule()`
(~3 games/team) to exercise day-grouping, doubleheaders, makeups, and game-id
ordering. That fixture is *supposed* to be degenerate — it would trip every shape
check. Those tests must pass `validate=False` so they keep testing structure in
isolation; the new shape tests use realistic synthetic slates (or explicit
corrupt ones) with the default `validate=True`. Production's only caller
(`historical_setup_flow.py`) uses the default.

### End-to-end path (no setup-flow change)

`historical_setup_flow.py::_build_league` already wraps the build in
`try/except HistoricalSeasonError / except ValueError`. `DegenerateHistoricalSeasonError`
is a `ValueError` (and *not* a `HistoricalSeasonError`), so it falls to the
existing `except ValueError` branch, which does `self._app.notify(str(exc), ...)`
and calls `self._select_year()` — exactly the desired behavior (actionable toast
naming the numbers, back to the picker). The generated path routes identically.
No source edit to the setup flow is required for this issue.

## Open questions

None requiring a human. Product-taste calls are resolved in-spec from the ADR era
survey + web-verified season lengths:
- **Thresholds** — `MIN_GAME_RETENTION = 0.5`, `MIN_GAMES_PER_TEAM = 40`, strict
  team retention; justified above and tunable as named constants.
- **Folded-franchise 19th-century seasons** — may be rejected by the per-team
  floor; accepted trade-off, follow-up if ever wanted (not a blocker).

## Issue breakdown

Atomic — a single implementer session. The source issue **FRE-149 is repurposed
as this implementer issue** (`Spec → Ready`); no child issues.

| # | Title | Depends on | Risk |
| --- | --- | --- | --- |
| FRE-149 | Shape-validate the built historical season; block degenerate leagues | — | — |

**Definition of done**
- `build_historical_season` raises `DegenerateHistoricalSeasonError` (numeric,
  actionable message naming raw rows, playable games, and the failed check[s])
  when the played slate (a) loses an entire team, (b) retains < 50% of raw rows,
  or (c) leaves any team < 40 games — collecting all failing reasons.
- A synthetic corrupt slate mirroring the 2024 bug (many raw rows, ~1 playable
  game, teams vanished) is rejected with a message that includes the raw-row and
  playable-game counts.
- Realistic synthetic slates that mimic the verified baselines pass validation:
  a clean full slate, a strike-year-like ~66% retention, a ~60-game short season,
  and a **6-team** league (proves no absolute league-size floor).
- `build_generated_historical_season` inherits the gate (validates the real slate
  before shuffling); its existing generated tests stay green.
- Existing structural builder tests pass `validate=False` and remain green; the
  `no schedule data` / `no played games` / `HistoricalSeasonError` paths are
  unchanged.
- Setup flow is unchanged: a comment or a light test confirms the existing
  `except ValueError` branch surfaces the new error and returns to the year picker
  (no source edit to `historical_setup_flow.py`).
- Tests are DB-free (`FakeRepo`, mock-self house style). PR body notes coverage.

Not `risk:high`: a pure model-layer validation function, fully unit-testable with
no external service, integration, or data mutation (contrast FRE-154, which is
`risk:high` for touching DB resolution). The correctness hazard — a mis-tuned
threshold clipping a real season — is covered by the boundary tests above, not by
live verification.
