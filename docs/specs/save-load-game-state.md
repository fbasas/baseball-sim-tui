# Spec: Save / load game state

**Source issue:** FRE-19 · **Date:** 2026-07-07 · **Status:** active

## Goal

Let the player save an in-progress game (and, in series mode, an in-progress
best-of-N series) to disk and resume it later exactly where they left off —
same inning, score, base runners, lineups, box score, pitcher fatigue, and (in
a series) standings and pitcher rest. Resume is **deterministic**: the first
at-bat after loading produces the same outcome it would have if the game had
never been saved, because the simulation RNG's internal state is captured, not
just its seed. This is also the practical prerequisite for **Season mode**
(FRE-15) — a season is unplayable without cross-game persistence.

## Non-goals

- **No reconstruction of the play-by-play scroll-back.** The interactive game
  renders narrative straight to the `PlayByPlayLog` widget as formatted strings
  (`game_screen.py::_log_play`, via `narrative.py` random text); there is **no
  structured play-log data model** in the interactive path. On resume the play
  log starts fresh with a "resumed game" marker. The **box score is fully
  preserved** (that is the accumulator that matters); the narrative history is
  not. Reconstructing it would mean either storing every play's text or
  replaying from the start — both are out of scope and would break issue sizing.
- **No preservation of purely-cosmetic narrative streak counters.** The streak
  trackers used only for flavor callouts — `_player_hit_counts` and
  `_pitcher_consecutive_retired` (`game_screen.py:137-138`) — reset on resume.
  Everything that affects the linescore / box score IS preserved.
- **No save-format migration engine.** Saves carry an integer `schema_version`.
  A save whose version does not match the current code is **rejected with a
  clear error**, never silently coerced. Writing migrations for old saves is a
  future concern.
- **No cloud / multi-device sync, no autosave, no save thumbnails/screenshots.**
  Saves are local JSON files under `data/saves/`.
- **No editing of a save file as a supported surface.** Files are JSON and
  human-readable, but hand-editing is unsupported.
- **No new serialization dependency.** Persistence uses stdlib `json` + per
  dataclass `to_dict`/`from_dict`, exactly like the two existing precedents
  (`RestLedger`, `TeamRoleCard`). No pydantic / msgpack / pickle.
- **No mid-play saving.** Saving is only offered at at-bat boundaries (the clean
  state between `_advance_one()` calls) and at end-of-game, never mid-resolution.

## Background — where the state actually lives (audited 2026-07-07)

This feature's difficulty is entirely in knowing *what* to capture. The engine
is almost fully immutable/functional, but the game's mutable state is scattered
across three layers, and the box score / play log are **not in the engine at
all**. The authoritative findings:

### The state is in three places, not one

1. **`GameState`** (`src/game/state.py:26`, `@dataclass(frozen=True)`) — the
   canonical per-play snapshot: `inning`, `half` (`InningHalf` enum), `outs`,
   `base_state` (`BaseState`, `src/simulation/game_state.py:12`), `away_score`,
   `home_score`, `away_batting_index`, `home_batting_index`, `is_complete`,
   `away_pitcher_id`, `home_pitcher_id`, and `away_pitcher_fatigue` /
   `home_pitcher_fatigue` (`FatigueState`, `src/game/fatigue.py:41`, frozen).
   All scalars/strings/enums/simple nested dataclasses — clean to serialize.

2. **`SubstitutionManager`** (`src/game/substitutions.py:59`, a *plain mutable*
   object, shared between `GameScreen.sub_manager` and `engine.sub_manager`):
   `removed_players: set[str]`, `substitution_history: list[SubstitutionRecord]`
   (frozen dataclass carrying `Position` enums + `SubstitutionType` enum),
   `away_dh_active: bool`, `home_dh_active: bool`. Enforces the no-re-entry rule
   and DH forfeiture — must survive a reload or those invariants break.

3. **The box-score accumulators live as loose instance fields on the TUI
   `GameScreen`** (`src/tui/screens/game_screen.py`), **not in the engine**:
   `_batting_lines: Dict[str, Dict[str,int]]` (`:141`, per player
   `AB/R/H/RBI/BB/K`), `_pitching_lines: Dict[str, Dict[str,int]]` (`:142`, per
   pitcher `outs/H/R/ER/BB/K`), `_pitcher_teams: Dict[str,str]` (`:143`),
   `away_hits`/`home_hits` (`:132-133`), `_inning_scores: List[Tuple[int,int]]`
   (`:144`), `_away_errors`/`_home_errors` (`:146-147`),
   `_current_inning_away_runs`/`_current_inning_home_runs` (`:147-148`),
   `_current_half_inning: Tuple[int, InningHalf]` (`:134`). These are populated
   in `_log_play` (`:797-834`) and reset by `_reset_tracking` (`:978`). **To
   save a game you must capture these `GameScreen` fields separately from
   `game_state`.** (The batch/headless `simulate_game` and AI-vs-AI `play_ai_game`
   paths keep their own `play_log`/accumulators, but the interactive owner is
   `GameScreen`.)

### Teams re-hydrate from `(team_id, year)` — do NOT serialize rosters

`Team.load_from_repository(repo, team_id, year)` (`src/game/team.py:205`) is a
deterministic function of `(team_id, year)` against `data/lahman.sqlite`: same
DB ⇒ byte-identical `info/roster/batting_stats/pitching_stats`
(`PlayerInfo`/`BattingStats`/`PitchingStats`/`TeamSeason` in
`src/data/models.py` are small immutable stat lines). So a save stores the two
teams' **`(team_id, year)` identifiers**, not their rosters, and reloads them on
open. **But** the *mutable overlay* on top of the static roster IS game state
and must be saved:

- **`Team.lineup`** (`team.py:203`, a `Lineup` of 9 `LineupSlot`s +
  `starting_pitcher_id`) is set after load and **mutated in place** during the
  game — `Team.update_lineup_slot` (`team.py:289`) rewrites slots for pinch
  hitters, and `ai_pregame` sets the AI side's lineup. Manual pregame edits
  (the FRE-8 lineup editor, `LineupPlan`) and in-game substitutions are *not*
  recoverable from `(team_id, year)`. **The current lineup (batting-order player
  IDs + positions + starting pitcher) must be saved.**
- **Gotcha:** `LineupSlot.position` is `Union[Position, type]` where the DH is
  the **`DesignatedHitter` class object itself** (`src/game/positions.py:77`), a
  sentinel, not an instance — and `Position` is an `IntEnum`. Neither is
  directly JSON-serializable. The manager/series layer already sidesteps this by
  using string abbreviations everywhere (`roles.py::POSITION_ABBREVS`:
  `"C","1B",…,"DH"`). **Serialize positions as those abbreviation strings** and
  map back on load.

### The RNG must capture generator state, not just the seed

`SimulationRNG` (`src/simulation/rng.py:13`) wraps `np.random.default_rng(seed)`.
It stores `seed` and an audit `history`, but **the running generator state after
N draws lives inside the numpy `BitGenerator`, not in `seed`.** The interactive
game is currently **unseeded** (system entropy — `GameScreen` never calls
`reset_rng`), so there is no seed to reproduce it from anyway. For deterministic
mid-game resume, capture `rng.rng.bit_generator.state` — a plain
JSON-serializable dict (PCG64 state is ints) — and restore it by assigning it
back to `rng.rng.bit_generator.state` on load. This works regardless of seed, so
**no change to seeding the interactive game is required.** The unbounded
`history` audit trail is NOT persisted (it is debug-only and would bloat saves).

### Series / cross-game state (series mode only)

Cross-game state is held by `SeriesController` (`src/series/controller.py:22`):
`state: SeriesState` (`src/series/state.py:27` — `best_of` + `results:
List[GameRecord]`; all wins/standings/current-game/day are `@property`s derived
from `results`), plus `away_ledger` / `home_ledger` (`RestLedger`,
`src/manager/rest.py:31` — `outings: Dict[str, Dict[int,int]]` pitcher→day→BF,
governs rest availability in later games). **`RestLedger` already has
`to_dict`/`from_dict`** (`rest.py:102`). `SeriesState`/`GameRecord` do not yet.
Fatigue does **not** carry across games; the manager (`ManagerAI`) is stateless
and reconstructs from its `TeamRoleCard` (`data/roles/<TEAMID>-<YEAR>.json`, via
`load_manager_for_team`) — nothing to save there.

### Non-serializable objects that must be re-created, never stored

Open SQLite connection (`GameScreen.repo: LahmanRepository`), the numpy
`Generator`, Textual runtime objects (widgets, `Screen`, `_fast_forward_timer:
Timer`), the `_on_game_complete: Callable` series callback, and the large
mutated `Team` objects. All are rebuilt on load from saved primitives +
`(team_id, year)`.

### TUI hook points

- **No title/main-menu screen exists.** `BaseballSimApp` (`src/tui/app.py:29`)
  composes only a `Header`; the first thing the user sees is the **GAME MODE
  `ChoiceScreen`** pushed by `SetupFlow._select_mode` (`setup_flow.py:98`). The
  new-game sequence is `ChoiceScreen`(mode) → `ChoiceScreen`(control) →
  `TeamSelectScreen`×2 → `PitcherSelectScreen`×(human sides) → `GameScreen`.
- **End-of-game screen is `BoxScoreScreen`** (`r`/`n`/`q`). (`EndGameMenu` was
  removed in FRE-7.)
- **`GameScreen` owns the live game** and holds everything a save reads:
  `game_state` (reactive), `engine`, `away_team`/`home_team`, `sub_manager`,
  `_away_ctx`/`_home_ctx`, and all the box-score fields above. App level holds
  `series`, `config` (`GameConfig`, frozen), teams, and contexts (`app.py`).
- **Bindings pattern:** class-level `BINDINGS = [Binding("key","action_name",
  "Label")]` + `def action_<name>(self)`; a `Footer()` auto-shows new bindings.
  `GameScreen.BINDINGS` already has `space/enter/f/s/q` (`game_screen.py:58`).
- **`data/` is the established gitignored home for local artifacts**, with a
  load precedent in `data/roles/<TEAMID>-<YEAR>.json`. Saves go under
  **`data/saves/`** (added to `.gitignore` by this work).

### Testing idioms (house style — the DoD must match these)

- **pytest**, plain `assert`, `pytest.raises(match=...)`, `parametrize`.
- **Serialization round-trip tests** with synthetic dataclasses and **no DB**,
  mirroring `TestRestLedgerSerialization.test_round_trip`
  (`tests/test_rest_and_series.py`) and the `make_batting_stats` / `make_lineup`
  / `_make_team_with_two_pitchers` factories in `tests/test_game_engine.py`.
- **DB-backed integration tests are guarded**: `if not _DB_PATH.exists():
  pytest.skip("lahman.sqlite not found - run build_lahman_db.py first")`, then
  `Team.load_from_repository(repo, "NYA", 1927)` inside `with
  LahmanRepository(...)` (`tests/test_game_screen_substitutions.py`).
- **Screens are tested WITHOUT Textual `Pilot`/`run_test()`** — as unbound
  methods driven with a `types.SimpleNamespace` mock-`self` plus lambda-bound
  real helpers and stub widgets (`tests/test_game_screen_substitutions.py`).
  Save/load screen logic follows this mock-`self` idiom, not `Pilot`.

## Design

### On-disk format

A single top-level JSON object per save file, `data/saves/<name>.json`, written
with `json.dumps(..., indent=2)` (matching `roles.py`). Shape:

```jsonc
{
  "schema_version": 1,
  "kind": "single",              // "single" | "series"
  "created_at": "<ISO-8601 UTC>",
  "label": "1927 NYA @ 2016 CHN — T7, 3-2",   // human-readable, for the load list
  "game": { ...GameSnapshot... },             // present for both kinds
  "series": { ...SeriesSnapshot... }          // present only when kind == "series"
}
```

`GameSnapshot` (new `@dataclass` in `src/game/persistence.py`) composes the
audited pieces:

```
GameSnapshot:
  config:        GameConfig fields (mode, control) as a dict
  away_ref:      {team_id, year}          # re-hydrate via Team.load_from_repository
  home_ref:      {team_id, year}
  away_lineup:   [{player_id, position_abbrev, ...}] + starting_pitcher_id
  home_lineup:   [ ... ]                  # positions as "C","1B",…,"DH" strings
  game_state:    GameState.to_dict()      # incl. base_state + two FatigueStates
  substitutions: SubstitutionManager.to_dict()  # removed_players, history, dh flags
  box_score:     { batting_lines, pitching_lines, pitcher_teams, away_hits,
                   home_hits, inning_scores, away_errors, home_errors,
                   current_inning_away_runs, current_inning_home_runs,
                   current_half_inning }        # the GameScreen accumulators
  rng:           { seed, bit_generator_state } # numpy generator state dict
```

`SeriesSnapshot`: `{ best_of, results: [GameRecord…], current_game_number,
away_ledger: RestLedger.to_dict(), home_ledger: RestLedger.to_dict() }`.

### Serialization ownership

Each type owns its own `to_dict`/`from_dict`, matching the `RestLedger` /
`TeamRoleCard` precedent. New serialization is added to: `GameState` (+
`BaseState`, `FatigueState`), `SubstitutionManager` (+ `SubstitutionRecord`,
with `Position`/`SubstitutionType` enums encoded by name/abbrev and
`DesignatedHitter` as `"DH"`), `Lineup`/`LineupSlot`, `SeriesState`/`GameRecord`,
and a `SimulationRNG` `get_state()`/`set_state()` pair over
`bit_generator.state`. `persistence.py` provides the `GameSnapshot` /
`SeriesSnapshot` / `SaveFile` wrappers and `save_game(path)` / `load_game(path)`.

### Restore path (the hard part — replay-safe, mirrors FRE-8)

Constructing a fresh `GameScreen` runs `_finalize_game_setup` →
`_build_lineups()` + `_reset_tracking()`, which **rebuild lineups from scratch
and zero the accumulators** — exactly what we must NOT do when restoring. This
is the same replay hazard the manual-lineup-editor spec calls out
(`_reset_game` deliberately rebuilds lineups to undo in-place pinch-hit
mutations). Therefore restore must **bypass the fresh-setup rebuild** and inject
saved state instead: re-hydrate both teams from `(team_id, year)`, apply the
saved `Lineup` (not `build_lineup`), assign the restored `GameState`, replace
`sub_manager` with the restored one (shared into the engine), restore every
box-score accumulator field, and set `engine.sim.rng.bit_generator.state`.
Determinism is the acceptance bar: the next `_advance_one()` after restore must
equal the next `_advance_one()` of the un-saved control game.

### UI flow

- **Save:** in-game `Binding("ctrl+s","save_game","Save")` on `GameScreen`
  (and, in series mode, offered between games). `action_save_game` builds a
  `GameSnapshot`/`SaveFile` from the live screen + app state, writes
  `data/saves/<timestamped>.json`, and flashes a confirmation via
  `self.notify(...)`. Saving is only reachable at at-bat boundaries.
- **Load / Resume:** a **"Load saved game"** entry added to the first screen
  (into `_MODE_CHOICES`, handled in `SetupFlow._select_mode`). Choosing it
  pushes a **`SaveSelectScreen`** (built on the reusable `ChoiceScreen` /
  `OptionList`) listing `data/saves/*.json` by their `label` + `created_at`;
  selecting one loads the `SaveFile`, reconstructs the game (single) or series,
  and pushes the restored `GameScreen`. Empty-saves and unreadable/wrong-version
  files are handled with a visible message, never a crash.

### Error handling

- Wrong `schema_version` → refuse with a clear message.
- `(team_id, year)` not present in the loader's local `data/lahman.sqlite` (the
  DB is machine-local and rebuildable, not version-pinned) → **fail loudly**
  ("this save references NYA 1927, which isn't in your local database"), never
  silently load different stats.
- Corrupt/unparseable JSON → caught, surfaced in the load screen, file skipped.

## Open questions

None require a human checkpoint. Product-taste decisions were resolved in-spec
with conservative defaults (timestamped multi-file saves rather than slot
management; deterministic RNG resume; play-log history treated as a non-goal;
no migration engine). If the human wants a different save-slot UX or wants the
narrative history preserved, that is a follow-up, not a blocker. The risk:high
issues route through `Verify` for live DoD proof after merge.

## Issue breakdown

Single-game save/resume ships end-to-end across issues 1–5 (each leaves the app
working and merged); issue 6 extends it to series mode (the true Season-mode
prerequisite). Positions/enums, RNG state, and the restore/replay path are the
correctness-sensitive pieces and are flagged `risk:high`.

| # | Title | Depends on | Risk |
| --- | --- | --- | --- |
| 1 | Serialization primitives for core game dataclasses (`to_dict`/`from_dict` + RNG state) | — | — |
| 2 | `SaveFile`/`GameSnapshot` bundle + JSON save/load to `data/saves/` (single game) | 1 | high |
| 3 | Save action: capture a save from the live `GameScreen` (Ctrl+S) | 2 | — |
| 4 | Restore path: reconstruct a `GameScreen` from a `GameSnapshot` (deterministic, replay-safe) | 2 | high |
| 5 | Load/Resume UI: "Load saved game" entry + `SaveSelectScreen` | 4 | — |
| 6 | Extend save/resume to series mode (`SeriesSnapshot`, standings + rest carryover) | 4, 5 | high |
