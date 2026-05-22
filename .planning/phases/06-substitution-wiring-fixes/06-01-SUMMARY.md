---
phase: 06-substitution-wiring-fixes
plan: 01
subsystem: game-engine
tags: [engine, fatigue, pitching-change, simulation, tui, audit-gap]
requires:
  - src/game/engine.py::apply_fatigue_modifier
  - src/game/state.py::GameState.current_pitcher_id
  - src/game/state.py::GameState.current_pitcher_fatigue
provides:
  - src/game/engine.py::resolve_pitcher_stats
  - simulate_half_inning per-AB fatigue application
  - GameScreen.advance_game honors GameState pitcher + fatigue
affects:
  - src/game/engine.py
  - src/tui/screens/game_screen.py
  - tests/test_game_engine.py
tech_stack:
  added: []
  patterns:
    - module-level helper for shared TUI/engine lookup
    - duplicated fatigue formula across two call sites (intentional, for signature stability)
    - static AST-style slice test (regex-based) for hot-path enforcement
key_files:
  created: []
  modified:
    - src/game/engine.py
    - src/tui/screens/game_screen.py
    - tests/test_game_engine.py
decisions:
  - "resolve_pitcher_stats lives at module scope in engine.py (not on GameEngine class) — it is a pure lookup, no engine state needed, and the TUI imports it directly."
  - "simulate_half_inning keeps its (state, lineup, pitching_stats, park_factor) signature; fatigue is applied inline per iteration instead of refactoring callers."
  - "Fatigue formula (hits *= 1+f*0.5, walks *= 1+f*0.3, HRs *= 1+f*0.4) is intentionally duplicated across resolve_pitcher_stats and simulate_half_inning's per-AB loop — both code paths exist for stability and DRYing them would require a signature change."
  - "Static slice test (TestAdvanceGamePitcherLookup) over a Textual-touched module replaces a runtime widget test — proves the wiring without spinning up an App."
metrics:
  duration: "~5 minutes"
  tasks_completed: 2
  files_modified: 3
  tests_added: 7
  date_completed: "2026-05-22"
---

# Phase 06 Plan 01: Pitching-change & Fatigue Hot-Path Wiring Summary

Closes audit gaps 1 and 2 (SUBS-01): after this plan the TUI's per-at-bat simulation actually uses the current pitcher recorded in GameState (not the lineup's frozen `starting_pitcher_id`) and the pitching stats are fatigue-modified before each call to `simulate_at_bat`. Substitutions and pitcher tiredness now produce measurable changes in outcomes.

## What Changed

1. **New helper: `resolve_pitcher_stats(state, pitching_team)` in `src/game/engine.py`**
   - Reads `state.current_pitcher_id` (the home/away pitcher depending on `state.half`), falling back to `pitching_team.lineup.starting_pitcher_id` only when GameState has no pitcher set (pre-finalize edge case).
   - Looks up the team's PitchingStats by that id.
   - Applies the existing `apply_fatigue_modifier` using `state.current_pitcher_fatigue.current_fatigue`.
   - Returns `(pitcher_id, fatigue_modified_stats)`.

2. **`GameScreen.advance_game` rewired (the actual user-visible bug)**
   - `from src.game.engine import resolve_pitcher_stats` added to the imports.
   - The three lines that read `pitching_team.lineup.starting_pitcher_id` and indexed into `pitching_team.pitching_stats` are replaced with a single call to the helper.
   - Result: when the user makes a pitching change via the substitution menu (which already writes to `home_pitcher_id` / `away_pitcher_id` and resets `*_pitcher_fatigue`), the *very next* at-bat actually uses the reliever's stats.

3. **`GameEngine.simulate_half_inning` applies fatigue per iteration**
   - Inside the `while current_state.outs < 3` loop, `apply_fatigue_modifier(pitching_stats, current_state.current_pitcher_fatigue.current_fatigue)` is now called once per AB to produce `ab_pitching_stats`, which is what gets passed to `self.sim.simulate_at_bat`.
   - Fatigue is read from `current_state` (not entry-time `state`) because `_apply_result` increments fatigue after each AB and the loop reuses `current_state`.
   - Public signature unchanged (`state, batting_lineup, pitching_stats, park_factor`).

## Why a Helper Instead of Just Fixing `simulate_half_inning`

`GameScreen.advance_game` calls `self.engine.sim.simulate_at_bat(...)` directly and never enters `simulate_half_inning` — only the orphaned `simulate_game()` (per `v1.0-MILESTONE-AUDIT.md`) calls `simulate_half_inning`. Fixing fatigue inside `simulate_half_inning` alone would close the audit gap in *test-only code* while the user-visible bug stayed broken. Extracting a shared helper and calling it from the TUI hot path closes the real gap.

## Intentional Duplication Note (read before changing the fatigue formula)

The fatigue formula lives in **two** call sites:

1. `resolve_pitcher_stats` (used by `GameScreen.advance_game` — the TUI hot path)
2. `GameEngine.simulate_half_inning` per-AB loop (used by the orphaned `simulate_game()` and by any future caller of the engine that still uses `pitching_stats` directly)

A code comment above each call site flags this duplication. The tradeoff is signature stability over DRY: making `simulate_half_inning` take a `Team` would ripple into every test fixture and `simulate_game()` itself. Test coverage protects the seam: a formula change that touches only one call site will break at least one of `TestResolvePitcherStats::test_applies_fatigue_modifier` or `TestFatigueEffectsSim::test_fatigue_modifier_called_inside_simulate_half_inning`.

**If you change the formula** (`hits *= 1 + fatigue*0.5`, `walks *= 1 + fatigue*0.3`, `home_runs *= 1 + fatigue*0.4`), update BOTH:
- `src/game/engine.py::apply_fatigue_modifier` (the single shared implementation), and
- both call-site test assertions (`TestResolvePitcherStats::test_applies_fatigue_modifier` plus `TestFatigueEffectsSim::test_fatigue_modifier_called_inside_simulate_half_inning`).

## Test Coverage Added

**`TestResolvePitcherStats` (4 tests)** — exercise the helper directly:
- `test_returns_state_pitcher_id_not_lineup_starter`: lineup starter ≠ state pitcher → helper returns state pitcher.
- `test_applies_fatigue_modifier`: with `current_fatigue=0.8`, returned `hits_allowed = int(base * 1.4)`, walks = `int(base * 1.24)`, HRs = `int(base * 1.32)`; with `0.0`, unchanged.
- `test_resolves_per_inning_half`: TOP → `home_pitcher_id`, BOTTOM → `away_pitcher_id`.
- `test_falls_back_to_starting_pitcher_if_state_pitcher_none`: pre-finalize fallback returns lineup starter.

**`TestFatigueEffectsSim` (2 tests)** — `simulate_half_inning` path:
- `test_fatigue_modifier_called_inside_simulate_half_inning`: monkey-patches `SimulationEngine.simulate_at_bat`, asserts the first captured `pitching_stats` reflects entry-time fatigue 0.8 (fatigue updates AFTER the AB).
- `test_zero_fatigue_passes_stats_unchanged`: with fatigue 0.0, captured stats equal base.

**`TestAdvanceGamePitcherLookup` (1 test)** — static slice over the TUI hot path:
- `test_helper_replaces_starting_pitcher_id_in_advance_game`: regex-extracts `GameScreen.advance_game`'s body (start at the `def` line, stop at the next sibling `    def `) and asserts the body contains `resolve_pitcher_stats` and does NOT contain `starting_pitcher_id`. This catches future regressions without needing a Textual harness, and the slice scope leaves the four legitimate uses (lines 181, 182, 202, 722) outside the assertion.

## Verification Output (from plan acceptance commands)

```
$ python3 -m pytest tests/test_game_engine.py
============================== 26 passed in 0.16s ==============================

$ python3 -m pytest tests/
======================= 287 passed, 25 skipped in 0.82s ========================

$ grep -n "def resolve_pitcher_stats" src/game/engine.py
60:def resolve_pitcher_stats(

$ awk '/def simulate_half_inning/{flag=1;next} flag && (/^def [a-zA-Z_]/ || /^class /){exit} flag' src/game/engine.py | grep -q apply_fatigue_modifier && echo OK
OK

$ awk '/def advance_game/{flag=1;next} flag && /^    def /{exit} flag' src/tui/screens/game_screen.py | grep -q resolve_pitcher_stats && echo OK
OK

$ awk '/def advance_game/{flag=1;next} flag && /^    def /{exit} flag' src/tui/screens/game_screen.py | grep -c starting_pitcher_id
0
```

Full suite: **287 passed, 25 skipped** (baseline was 280 passed; +7 new tests, 0 regressions).

## Deviations from Plan

None — plan executed exactly as written. Minor presentational note: the plan referenced "line 720" for the legitimate reliever-list filter; in the current file it's at line 722 (the surrounding edit shifted lines slightly). The four "untouched" callsites listed in the plan (181, 182, 202, 720) are all preserved (now at 181, 182, 202, 722).

## Files Touched

| File | Change |
|------|--------|
| `src/game/engine.py` | Added `resolve_pitcher_stats` (module level). `simulate_half_inning` now calls `apply_fatigue_modifier` per AB using `current_state.current_pitcher_fatigue`. |
| `src/tui/screens/game_screen.py` | Import `resolve_pitcher_stats`. Replaced 3 lines in `advance_game` with a single helper call. No other call sites touched. |
| `tests/test_game_engine.py` | +7 tests across 3 new classes: `TestResolvePitcherStats`, `TestFatigueEffectsSim`, `TestAdvanceGamePitcherLookup`. |

## Commits

- `2f4cedb` test(06-01): add failing tests for resolve_pitcher_stats and fatigue-in-simulate-half-inning (RED)
- `3c8ec5a` feat(06-01): add resolve_pitcher_stats helper and apply fatigue inside simulate_half_inning (GREEN)
- `a9ea301` test(06-01): add failing test for advance_game using resolve_pitcher_stats (RED)
- `b937523` feat(06-01): wire resolve_pitcher_stats into GameScreen.advance_game (GREEN)

## Success Criteria

- [x] After a pitching change recorded into GameState, the very next at-bat through the TUI hot path uses the new pitcher's stats (proven by `TestResolvePitcherStats` covering the helper that `advance_game` calls).
- [x] Fatigue modifier applied to pitching stats before each `simulate_at_bat` in BOTH `advance_game` (via `resolve_pitcher_stats`) and `simulate_half_inning` (direct).
- [x] Two fatigue call sites documented as duplicates; both covered by tests so formula drift breaks at least one.
- [x] All new and existing tests pass (287 passed, 25 skipped).
- [x] No public API signatures changed.

## Self-Check: PASSED
