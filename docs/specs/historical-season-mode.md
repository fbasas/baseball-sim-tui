# Spec: Historical season mode

**Source issue:** FRE-115 · **Date:** 2026-07-15 · **Status:** active

## Goal

Add a **historical season** mode: pick a year, and play a full-league season of
**every team that played that year**, on the **actual historical schedule** —
the real day-by-day slate of matchups from that season, sourced from Retrosheet
schedule data. The user manages one team (or watches as commissioner); every
game is simulated by the engine, so the *schedule* is history but the *results*
are freshly played. This is the "whole league of year Y" preset the round-robin
[season mode](./season-mode.md) explicitly deferred ("`get_teams_for_year`
makes a 'whole league of year Y' preset easy later; out of scope now").

It **reuses the entire `src/season/` engine** — `SeasonState` (standings,
current-day, champion), `SeasonStats` (leaders), `SeasonController` (day-by-day
headless sim + interactive user games + rest ledgers), `SeasonHubScreen`, and
`kind == "season"` save/resume. The genuinely new work is: (1) a **schedule
data source** (Retrosheet schedule files → local DB), (2) a **historical
schedule builder** that turns that data into the same `List[SeasonDay]` the
engine already consumes, (3) **league/division-grouped standings** (a 16–30-team
mixed AL/NL league is not one round-robin table), and (4) a **year-based setup
flow** replacing the league-builder loop.

## Non-goals

- **No new simulation engine.** Historical games are simmed by the existing
  `play_ai_game` / `GameScreen` exactly as round-robin season games are. Only
  the schedule and league composition are historical.
- **No result replay.** We replay the *schedule* (who plays whom, on which day),
  not historical outcomes. A game the 1927 Yankees won 6–3 is re-simmed and may
  end any way. (Replaying literal box scores would defeat the product.)
- **No World Series / postseason bracket.** The season ends at the end of the
  regular-season schedule. Standings are grouped by league (and division from
  1969 on); the headline "champion" is the best overall regular-season record,
  with per-league pennant winners shown. A postseason bracket is a follow-up.
- **No generated schedule in the first cut.** The issue notes the mode "may also
  use a completely generated schedule, based on the historical schedule from
  that year." That is built as a **secondary variant** (Part 5) on top of the
  historical-replay core (Parts 1–4), not before it.
- **No roster/transaction fidelity.** Rosters are the full Lahman season roster
  per team (as round-robin season already does); no mid-season call-ups, trades,
  or day-accurate active rosters. A player traded mid-year appears on his
  summed-stats team (existing `get_batting_stats`/`get_pitching_stats` behavior).
- **No schema-version bump.** Historical seasons persist through the *existing*
  `kind == "season"` `SeasonSnapshot` unchanged (see "Persistence"). Round-robin
  and historical seasons are the same on disk; `SCHEMA_VERSION` stays 1.
- **No round-robin regressions.** The existing 4/6/8-team round-robin season and
  every other mode must behave exactly as today. Historical mode is a fourth
  top-level mode beside single / series / season.
- **No parallel/multiprocess sim.** As in round-robin season: `play_ai_game`
  runs a game in well under a second; sim-ahead runs on a Textual worker with a
  progress line. A full modern season is large (see "Scale") — this is a
  documented cost, not a reason to parallelize now.

## Background — the data gap

The engine is season-ready; the **data** is the missing piece.

- **Lahman has no schedule.** `data/lahman.sqlite` (built by
  `scripts/build_lahman_db.py`) has People / Batting / Pitching / Appearances /
  Teams — rosters, stats, park factors, league/division — but **no game-level
  schedule**. `LahmanRepository.get_teams_for_year(year)` already returns every
  team of a year; there is nothing that returns *who played whom on which day*.
- **The schedule lives in Retrosheet** ("scoresheet data"). Retrosheet
  publishes a per-year **schedule file** giving the exact day-by-day slate. This
  spec bakes in the format (below) so implementers need no web access.

### Retrosheet schedule files (verified 2026-07-15)

- **URL pattern:** `https://www.retrosheet.org/schedule/YYYYSKED.zip` — one ZIP
  per year. Coverage **1877–2026** (no 1876). Each ZIP contains a comma-
  delimited text file (e.g. `2016SKED.TXT`). **Special case:** the 2020 ZIP
  holds two files — `2020orig.txt` (pre-pandemic) and `2020rev.txt` (the played
  60-game schedule); use the `rev` file for 2020.
- **Record layout — 12 comma-separated fields, no header:**
  1. **Date** — `yyyymmdd`
  2. **Game number** — `0` single game · `1` first game of a doubleheader ·
     `2` second game of a doubleheader
  3. **Day of week** — `Sun`…`Sat`
  4. **Visiting team** — Retrosheet team id (e.g. `NYA`)
  5. **Visiting league** — `AL` / `NL` / `AA` / `FL` / …
  6. Season game number for the visiting team
  7. **Home team** — Retrosheet team id
  8. **Home league**
  9. Season game number for the home team
  10. **Time of day** — `D` day · `N` night · `A` afternoon · `E` twilight
  11. **Postponement / cancellation indicator** — non-empty when the game was
      *not* played as scheduled (multiple phrases separated by `;`)
  12. **Makeup date** — `yyyymmdd` if the postponed game was replayed later
      (else empty)

  Source: <https://www.retrosheet.org/schedule/> and the field notes on that
  page. **Required attribution** (must appear in-product — see "Attribution"):
  > The information used here was obtained free of charge from and is
  > copyrighted by Retrosheet. Interested parties may contact Retrosheet at
  > "www.retrosheet.org".

### Retrosheet ↔ Lahman team-id join

Retrosheet team ids in the schedule are **not always equal to Lahman `teamID`**
(the id used to look up rosters/stats/park factors). Lahman's `Teams` table
carries a **`teamIDretro`** column that maps Lahman `teamID` ↔ Retrosheet id.
The current `build_lahman_db.py` Teams import does **not** include `teamIDretro`
— Part 1 adds it. The builder resolves each schedule row's Retrosheet ids to
Lahman `teamID`s via `teamIDretro` (falling back to an exact `teamID` match,
which is correct for most modern teams), then keys everything by the engine's
`"{team_id}-{year}"` convention.

## Design

### Data flow (end to end)

```
Retrosheet YYYYSKED.zip ──build_schedule_db.py──▶ Schedules table (in lahman.sqlite)
                                                        │
Lahman Teams (teamIDretro, lgID, divID) ◀──────────────┤ get_schedule(year)
                                                        ▼
                        src/season/historical.build_historical_season(repo, year, user_team_key)
                                                        │  (retro id → lahman key,
                                                        │   group games by date,
                                                        │   handle DH / postponed / makeup)
                                                        ▼
        LeagueTeam[] (all teams that year, with league+division)  +  schedule: List[SeasonDay]
                                                        ▼
                     SeasonState (prebuilt schedule, games_per_opponent=None)
                                                        ▼
        HistoricalSeasonSetupFlow ── role-card pass (all teams) ──▶ SeasonController ──▶ SeasonHubScreen
                                                        ▲                                     │
                                                        └──────── existing engine (unchanged) ┘
```

Everything from `SeasonState` rightward is **existing season-mode machinery**.
The new modules are the two upstream boxes (data ingest + builder), the model
tweaks that let `SeasonState` accept a prebuilt schedule and carry league/
division, grouped standings, and the year-based setup flow.

### Part 1 — Schedule data ingestion (`risk:high`)

The research-spike-and-foundation issue. Deliverables:

- **`scripts/build_schedule_db.py`** — mirrors `build_lahman_db.py`'s shape
  (argparse, download-with-timeout, idempotent). Downloads
  `https://www.retrosheet.org/schedule/YYYYSKED.zip` for a requested year (or a
  year range / list), parses the 12-field records, and populates a **`Schedules`
  table** in the existing `data/lahman.sqlite` (`CREATE TABLE IF NOT EXISTS`;
  clear+reinsert per year so re-runs are idempotent). Columns:
  `year, date (yyyymmdd int or text), game_num, dow, vis_team, vis_league,
  home_team, home_league, time_of_day, postponed (text, nullable), makeup_date
  (nullable)`. Index on `(year)`. **2020:** read `2020rev.txt`.
- **`teamIDretro` added to `build_lahman_db.py`'s Teams column list** so a rebuilt
  `lahman.sqlite` carries the join key. (Existing DBs must be rebuilt to get the
  column; document this in the script/README.)
- **`LahmanRepository` methods:**
  - `get_schedule(year) -> List[ScheduleRow]` — all schedule rows for a year,
    ordered by `(date, game_num)`. `ScheduleRow` is a small dataclass in
    `src/data/models.py`.
  - `retro_to_lahman_team(retro_id, year) -> Optional[str]` — resolve a
    Retrosheet id to a Lahman `teamID` for that year via `teamIDretro`, falling
    back to `teamID == retro_id`; `None` if unresolved.
  - `has_schedule(year) -> bool` — whether the `Schedules` table has rows for
    the year (drives which years the setup flow offers).
- **ADR** `docs/adr/NNN-historical-schedule-data.md` — the **research-spike
  writeup**: the schedule format, the retro↔lahman join, and an **empirical
  characterization of schedule structure across eras**, produced by actually
  downloading and parsing a sample of years spanning the variation:
  - a modern 30-team, 162-game season (e.g. **2016**),
  - the **division era** boundary (e.g. **1969**, first divisions),
  - a **pre-division two-league** season (e.g. **1927**, 16 teams, 154 games),
  - an **anomaly** (e.g. **2020** revised 60-game, and note **1981** split
    season / **1994** strike as known short/irregular seasons).
  Record, per sampled year: team count, games/team, doubleheader count,
  postponed-without-makeup count, and any team ids that fail the retro→lahman
  join. These findings set the builder's expectations (Part 2).
- **DoD:** the script populates `Schedules` for at least the sampled years;
  `get_schedule`/`retro_to_lahman_team`/`has_schedule` are covered by tests
  (unit tests parse fixture rows; DB-backed assertions **guarded with
  `pytest.skip` when `data/lahman.sqlite`/schedule data is absent**, matching
  house style); the ADR is committed. No UI in this part.

### Part 2 — Historical schedule builder + model support

New module **`src/season/historical.py`**:

- `build_historical_season(repo, year, user_team_key=None) -> SeasonState`
  (plus whatever the setup flow needs — see below). Steps:
  1. `rows = repo.get_schedule(year)`; error clearly if empty
     (`ValueError("no schedule data for {year}")`).
  2. **Drop games not actually played:** a row with a non-empty postponement
     indicator **and no makeup date** is a cancelled game → excluded. A
     postponed row **with** a makeup date is **moved to the makeup date** (its
     effective play date becomes field 12). Rows with an empty postponement
     field play on field 1's date. (Document this rule; the ADR's
     postponed/makeup counts validate it.)
  3. **Resolve teams:** map each row's `vis_team`/`home_team` Retrosheet ids to
     Lahman keys via `repo.retro_to_lahman_team`. Collect the set of team keys
     appearing in the (played) schedule → the league. An id that fails to
     resolve, or a team-season whose roster won't load, is collected and
     reported; **season build fails with a named error** listing the problem
     teams (season mode's blocking precedent — a faithful league loads cleanly
     for supported years).
  4. **Group by day:** sort played rows by `(effective_date, game_num)`; each
     **distinct effective calendar date** becomes one `SeasonDay` (position =
     season-day ordinal, used by the hub's "Day X of Y"). A **doubleheader**
     (two rows, same teams, same date, game_num 1 & 2) yields two
     `ScheduledGame`s on the same day. Assign `ScheduledGame.game_id`
     sequentially in `(date, game_num)` order and `ScheduledGame.day = ordinal`
     (list position), matching the round-robin invariant `day == list index`.
     Home/away from fields 7/4.
  5. Build `LeagueTeam`s for every league team, populated with **league** and
     **division** (see model change) from `repo.get_team_season`.
  6. Return a `SeasonState` built from the prebuilt schedule (not
     `generate_schedule`).

**Model changes (small, back-compatible):**

- `SeasonState.games_per_opponent: Optional[int]` (was `int`) — historical
  seasons pass `None` (the field is round-robin-only; only used for
  round-robin regeneration/display). `to_dict`/`from_dict` pass it through
  unchanged; existing saves (an int) still load.
- New constructor path **`SeasonState.from_schedule(teams, schedule,
  user_team_key=None)`** that stores a prebuilt schedule directly and runs the
  existing `__post_init__` validation (duplicate teams, user-team membership)
  **without** the round-robin size/games checks in `generate_schedule`. (The
  dataclass already accepts `schedule` directly; this is a thin classmethod.)
- `LeagueTeam` gains optional **`league: Optional[str] = None`** and
  **`division: Optional[str] = None`** (default `None` keeps round-robin
  `LeagueTeam`s and their `to_dict`/`from_dict` unchanged; new keys read as
  `None` when absent on load). `get_team_season` is extended to also return
  `divID` (add `division` to `TeamSeason`).

**Modeling note (rest across off-days):** day index = *season-day ordinal*
(a distinct played date), so pitcher rest via `RestLedger` is measured in
**league game-days**, not calendar days — identical to the round-robin model
(`day == list position`). Off-days therefore don't add rest. This is a
deliberate simplification consistent with existing season mode; a calendar-
offset refinement (`ScheduledGame.day` = days-since-opening) is possible later
without touching the iteration code, since the controller keys rest off
`ScheduledGame.day` while iterating by list position.

**DoD:** builder produces a valid `SeasonState` for a fixture schedule (unit
test with synthetic rows covering a doubleheader, a postponed-no-makeup drop,
and a makeup move); DB-backed integration test for one real year guarded with
`pytest.skip`; `SeasonState.from_schedule` + `Optional` game count +
`LeagueTeam` league/division round-trip through `to_dict`/`from_dict`. No UI.

### Part 3 — League/division-grouped standings

A 16–30-team mixed-league season needs standings **grouped by league, then
division** (divisions exist 1969→; pre-1969 `divID` is empty ⇒ one group per
league). Model + display:

- **Model:** add `SeasonState.standings_by_group() -> List[StandingsGroup]`
  where `StandingsGroup` is `{league, division, rows: List[StandingsRow]}`,
  each group's rows sorted by the **existing** standings ordering (Pct → run
  diff → key) and GB computed **within the group**. Grouping keys come from the
  `LeagueTeam.league`/`division` set at build; a team with `division=None`
  groups under its league only. The flat `standings` property is unchanged (and
  still used by round-robin seasons and overall ranking).
- **Champion / pennants:** keep `SeasonState.champion` as the best overall
  record (the headline). Add `pennant_winners() -> Dict[str, str]` (best record
  per league) for the summary. No cross-league tiebreak beyond the existing
  Pct → head-to-head → run-diff.
- **Hub display:** `SeasonHubScreen` renders **grouped** standings when the
  season has grouping (any `LeagueTeam.league` set), otherwise the current
  single table (round-robin unaffected). The end-of-season summary shows pennant
  winners plus the overall champion line. Today's-slate and leaders rendering
  are unchanged (leaders are already league-wide via `SeasonStats`).

**DoD:** `standings_by_group`/`pennant_winners` unit-tested (a 1969-style
two-league-two-division synthetic league and a pre-division two-league one);
hub renders grouped standings for a historical season and the unchanged single
table for a round-robin season (screen tested without `Pilot`, house style).
Depends on Part 2's `LeagueTeam` league/division.

### Part 4 — Historical setup flow + wiring (`risk:high`)

Makes historical mode **playable end to end**, reusing the season play/sim/save
infrastructure wholesale.

- **Mode menu:** add `("historical", "Historical season — a real year's full
  league on its actual schedule")` to `setup_flow._MODE_CHOICES`, dispatched via
  a new `on_historical` callback (mirrors the existing `on_season` seam;
  optional so it can be disabled).
- **`HistoricalSeasonSetupFlow`** (new module, same modal-chain style as
  `SeasonSetupFlow`):
  1. **Year picker** — a `ChoiceScreen` (or `TeamSelectScreen`-style list) over
     years for which `repo.has_schedule(year)` is true (intersect
     `get_available_years()` with schedule availability). Backing out returns to
     the mode menu.
  2. Build the season via `build_historical_season(repo, year)` (no user team
     yet) to discover the league; a build failure (unresolved/​unloadable teams)
     is reported by name and returns to the year picker.
  3. **Your team** — a `ChoiceScreen` over every league team (labelled
     `"{year} {team_name}"`) plus a **"Watch-only (commissioner)"** option
     (`user_team_key = None`).
  4. **Role-card pass** — build any missing `data/roles/<TEAM>-<YEAR>.json` for
     **all league teams** (up to 30). **Reuse** `SeasonSetupFlow`'s role-card
     machinery — extract the DB-gather-on-main-thread + worker-build +
     progress/blocking logic into a shared helper both flows call (keeps the
     documented sqlite-thread-affinity fix in one place). A team whose card
     can't be built blocks the season, named, as in season mode.
  5. Construct the `SeasonController` (teams + contexts + the historical
     `SeasonState`) and hand it to the app via `on_complete` — the app pushes
     `SeasonHubScreen` through the **existing** `_on_season_ready` path (stamp
     `GameConfig(mode="season")` so mid-game Ctrl+S saves as `kind ==
     "season"`).
- **No per-game changes:** interactive user games, sim-day, sim-ahead, and the
  end-of-season summary all run through the existing `SeasonController` /
  `SeasonHubScreen` code. Sim-ahead's bounded options ("to my next game / 7
  days / to end of season") already exist and matter more here (see "Scale").

**DoD:** picking Historical → a year → a team (and watch-only) starts a season
whose hub shows the real league on grouped standings; the user can play/sim a
game and sim a day; a watch-only season can sim to completion and show the
summary with pennant winners. Setup-flow logic tested without `Pilot`
(mock-`self` house style); the shared role-card helper keeps season mode's tests
green. `risk:high` (integration + external data → routes through `Verify`).

### Part 5 — Generated-schedule variant (secondary; the "may also")

On top of Parts 1–4: a **generated** schedule that preserves the *structure* of
a year's real schedule (per-team game count, home/away balance, and
intra-/inter-division opponent weighting) but shuffles the actual day-by-day
matchup order — a "what if this league replayed a fresh season" option. At the
year picker (or a follow-on toggle), the user chooses **actual** vs **generated**
schedule; generated builds a schedule from the same league + the year's
structural parameters (derived from `get_schedule`) rather than the literal
rows. Reuses everything downstream. Lower priority than the replay core; a
`ChoiceScreen` toggle and a `src/season/historical.py` generator function.

**DoD:** choosing "generated" for a year produces a valid full-league
`SeasonState` with the same per-team game count as the real season, verified in
a DB-guarded test; the flat + grouped standings and save/resume all work.

### Persistence & save/resume (no new work)

Historical seasons persist through the **existing** `kind == "season"`
`SeasonSnapshot` with **no changes**: it serializes the whole `SeasonState`
(including the prebuilt `schedule`, `games_per_opponent=None`, and the
league/division-bearing `LeagueTeam`s) plus `SeasonStats` and the rest ledgers.
`src.season.rehydrate.rehydrate_season_teams` reloads every team by key on
resume (30 loads for a modern season — slower but correct) and rebuilds any
missing role card in-process, exactly as it does for a round-robin season. The
only requirement is that the Part 2 model changes round-trip (they do: optional
game count and optional `LeagueTeam` fields). Verify old round-robin saves still
load unchanged.

### Attribution

Because the product ships Retrosheet-derived data, the required Retrosheet
notice (quoted in "Background") must appear in-product — add it to the app's
about/credits surface (or README + a visible setup/help line). Track it as part
of Part 1's DoD so it lands with the data.

### Scale (documented cost, not a blocker)

A full modern season is large: 30 teams × 162 games ≈ **2,430 games**; 1927 is
16 × 154 ÷ 2 ≈ 1,232. The user interactively plays only their own team's ~162;
the rest sim headlessly (well under a second each). A watch-only sim-to-end of a
modern season is thousands of headless games — **minutes** on the Textual worker
with the existing progress line. This is acceptable and spread across sessions;
the bounded sim-ahead options ("to my next game / 7 days") keep any single
action short. No parallelism now (non-goal). If, after the human tries it, a
hard league-size cap or faster bulk-sim is wanted, that is a tuning follow-up.

## Open questions

No blocking human checkpoints. Product-taste calls are resolved in-spec with
defaults consistent with the product's cross-era identity and the existing
[season spec](./season-mode.md)'s precedent (which likewise resolved everything
in-spec):

- **Replay vs generated schedule** — the issue offers both ("may also use a
  completely generated schedule"). Resolved: **actual historical replay is the
  core (Parts 1–4); generated is a secondary variant (Part 5)** built on top,
  not a blocker.
- **Postseason** — no World Series bracket; the regular-season schedule ends the
  season, with grouped standings + per-league pennant winners + an overall
  champion headline. A postseason bracket is a natural follow-up.
- **Rest across off-days** — rest measured in league game-days (matches existing
  model); calendar-accurate rest noted as a future refinement.
- **League-size / sim-time** — all data years supported; full-league sim cost
  documented and mitigated by bounded sim-ahead, not capped.

If the human wants a postseason, generated-first, calendar-accurate rest, or a
size cap, those are follow-up issues — not reasons to block the replay core. The
`risk:high` issues route through `Verify` for live DoD proof after merge.

## Issue breakdown

Parts 1–2 are the data + model foundation; the mode becomes playable at Part 4;
Part 5 adds the generated variant. Each part leaves the app working and merged.
The data ingest (1) and the integration/wiring (4) are the correctness- and
external-data-sensitive pieces and are flagged `risk:high`.

| # | Title | Depends on | Risk |
| --- | --- | --- | --- |
| 1 | Schedule data ingestion: Retrosheet `Schedules` table, `teamIDretro` join, repo methods, structure ADR | — | high |
| 2 | Historical schedule builder (`src/season/historical.py`) + `SeasonState.from_schedule` / optional game count / `LeagueTeam` league+division | 1 | — |
| 3 | League/division-grouped standings + pennant winners (model + hub) | 2 | — |
| 4 | Historical setup flow + mode wiring + full-league role-card pass (end-to-end playable) | 2, 3 | high |
| 5 | Generated-schedule variant (secondary "may also") | 2 | — |
</content>
