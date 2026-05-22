---
phase: 06-substitution-wiring-fixes
plan: 03
subsystem: tui-substitution
tags: [tui, substitution-menu, pinch-hitter, validation, replay, wiring, dh-forfeiture]
requires:
  - src/tui/screens/substitution_menu.py::SubstitutionMenu
  - src/tui/screens/game_screen.py::GameScreen._handle_substitution
  - src/game/engine.py::GameEngine.make_substitution (post-Plan-02)
  - src/game/substitutions.py::SubstitutionManager
provides:
  - src/tui/screens/substitution_menu.py rendered #batter-list
  - src/tui/screens/game_screen.py::GameScreen._is_away_team_for_substitution
  - src/tui/screens/game_screen.py::GameScreen._reset_sub_manager
  - tests/test_game_screen_substitutions.py (7 tests)
  - tests/test_game_engine.py::TestDHForfeitureReachability (2 tests)
affects:
  - src/tui/screens/substitution_menu.py
  - src/tui/screens/game_screen.py
  - tests/test_game_screen_substitutions.py
  - tests/test_game_engine.py
tech_stack:
  added: []
  patterns:
    - One-seam state mutation through engine.make_substitution (TUI is pure presentation)
    - Pure-Python testability via unbound method + SimpleNamespace mock (Textual-free)
    - Most-recent-selection disambiguation for multi-list confirm dispatch
key_files:
  created:
    - tests/test_game_screen_substitutions.py
  modified:
    - src/tui/screens/substitution_menu.py
    - src/tui/screens/game_screen.py
    - tests/test_game_engine.py
decisions:
  - "Engine owns substitution state mutation. TUI _handle_substitution is presentation-only after engine.make_substitution returns — no dataclass_replace of pitcher_id, no direct SubstitutionRecord construction, no manual lineup slot mutation."
  - "Helper _is_away_team_for_substitution(sub_type, half) replaces inline 4-branch conditional. Pure function of args, raises ValueError on unknown sub_type. Tested as unbound method (self=None) so it works without a Textual App context."
  - "Helper _reset_sub_manager() is the single seam for replay reset. Constructs fresh SubstitutionManager AND rewires self.engine.sub_manager. Tested via SimpleNamespace mock."
  - "Auto-pick-first-pitcher fallback REMOVED from SubstitutionMenu (intentional UX change beyond audit gap 3). Confirming with nothing selected now dismisses with None instead of silently substituting the first reliever."
  - "Most-recent-selection wins when both a pitcher and a batter are selected in the menu (tracked via self._last_selection)."
  - "DH-forfeiture defensive-replacement TUI selector DEFERRED to a future phase (option (a) from PLAN revision). Engine-API reachability proven via tests/test_game_engine.py::TestDHForfeitureReachability; the deferral note is pinned in the test class docstring."
metrics:
  duration: "~12 minutes"
  tasks_completed: 3
  files_modified: 3
  files_created: 1
  tests_added: 9
  date_completed: "2026-05-22"
---

# Phase 06 Plan 03: TUI Substitution Wiring Summary

Closes the three TUI-side audit gaps that survived Plans 01 and 02:

- **Gap 3 (SUBS-02):** SubstitutionMenu.compose() only yielded pitcher widgets; the batters list was constructed by GameScreen but never rendered. Fixed.
- **Gap 5 (SUBS-03):** GameScreen._handle_substitution mutated state and lineup directly and called sub_manager.record_substitution(), bypassing engine validation. Now routes through GameEngine.make_substitution at a single seam.
- **Gap 4 (SUBS-03):** GameScreen._reset_game left the stale SubstitutionManager attached so removed players carried into replayed games. Now reset via an extracted `_reset_sub_manager` helper that also rewires the engine.

Plus a deliberate UX improvement (removal of the auto-pick-first-pitcher fallback) and an engine-API reachability test for DH forfeiture (since the TUI does not yet expose a defensive-replacement selector).

## What Changed

### 1. `src/tui/screens/substitution_menu.py` — batter list rendered, fallback removed

- `compose()` now yields a SECOND `VerticalScroll` with `id="batter-list"` containing `PlayerListItem` widgets keyed `id=f"b-{pid}"` (matching the existing `on_player_selected` prefix discrimination at `b-` vs `p-`).
- A labelled section `"[bold]Available Pinch Hitters:[/bold]"` mirrors the existing reliever label.
- **CSS sizing:** `#sub-menu-container` height bumped 20 → 26 (programmatic check requires ≥24); `#pitcher-list` height reduced 10 → 8; new `#batter-list` rule at height 8 to fit both lists without clipping.
- **Confirm dispatch:** Extracted `_resolve_confirm_choice()` resolves `(sub_type, out_id, in_id)` from the two selection slots. Both `on_button_pressed` and `action_confirm` call it. Rules:
  - Pitcher selected & no batter → `pitching_change`
  - Batter selected & no pitcher → `pinch_hitter`
  - Both selected → most-recent wins (tracked via new `self._last_selection`)
  - Nothing selected → return `None` (NO auto-fallback)
- **UX change (intentional, beyond audit scope):** The auto-pick-first-pitcher fallback that previously triggered when Confirm was pressed with nothing selected has been **removed**. The old behavior masked selection failures and produced phantom substitutions — the new behavior dismisses without making a substitution. Documented in PLAN.md and in this summary.

### 2. `src/tui/screens/game_screen.py` — engine routing + replay reset

- **Engine wiring:** `_finalize_game_setup` now constructs `GameEngine(substitution_manager=self.sub_manager)` so engine validation runs against the screen's manager and engine-recorded substitutions update the same set the menu reads from.
- **New helper:** `_is_away_team_for_substitution(sub_type, half) -> bool`. Pure function of its arguments; raises `ValueError` on unknown sub_type.

  | sub_type          | half   | returns | reason                                         |
  | ----------------- | ------ | ------- | ---------------------------------------------- |
  | `pitching_change` | TOP    | False   | Home team fielding → home makes the sub       |
  | `pitching_change` | BOTTOM | True    | Away team fielding → away makes the sub       |
  | `pinch_hitter`    | TOP    | True    | Away team batting → away makes the sub        |
  | `pinch_hitter`    | BOTTOM | False   | Home team batting → home makes the sub        |

- **New helper:** `_reset_sub_manager()` — constructs a fresh `SubstitutionManager()` AND rewires `self.engine.sub_manager` to it. Defensive against `self.engine is None` (pre-finalize edge case).
- **`_reset_game()` calls `_reset_sub_manager()`** so Replay/New Game produces a clean substitution state.
- **`_handle_substitution()` body replaced.** All the duplicated logic (pitcher dataclass_replace, manual SubstitutionRecord construction, manual `record_substitution` calls, manual `lineup.slots` mutation) is gone. The new body:

  ```python
  try:
      new_state, _modified_team = self.engine.make_substitution(
          state=state,
          team=target_team,
          is_away_team=self._is_away_team_for_substitution(sub_type, state.half),
          player_out_id=player_out_id,
          player_in_id=player_in_id,
          new_position=None if sub_type == "pinch_hitter" else Position.PITCHER,
          is_pitching_change=(sub_type == "pitching_change"),
      )
  except ValueError as e:
      log.add_play(f"[bold red]Invalid substitution: {e}[/bold red]")
      return
  self.game_state = new_state
  ```

  Below this, narrative logging (`generate_substitution_text`, `generate_pinch_hitter_text`), `_pitcher_consecutive_retired` reset, and `_update_lineup_cards()` remain — they are pure presentation.
- **Unused imports removed:** `dataclass_replace`, `FatigueState`, `update_fatigue_state`, `SubstitutionRecord`, `SubstitutionType` (all owned by the engine now).

### 3. `tests/test_game_screen_substitutions.py` (NEW — 7 tests)

Pure-Python tests, no Textual App required:

- 4 tests for `_is_away_team_for_substitution` — one per `(sub_type, half)` combo (called as unbound method with `self=None`).
- 1 test for the `ValueError` raised on unknown sub_type.
- 1 test for `_reset_sub_manager` — creates a `SubstitutionManager`, marks a player removed, captures `id()`, calls reset via `SimpleNamespace` mock, asserts new instance + player available again + engine rewired (`engine.sub_manager is mock_self.sub_manager`).
- 1 defensive test: `_reset_sub_manager` with `engine=None` does not crash.

### 4. `tests/test_game_engine.py::TestDHForfeitureReachability` (NEW — 2 tests)

Engine-API reachability for DH forfeiture, since the TUI does not yet expose a defensive-replacement selector:

- `test_dh_forfeiture_via_engine_api`: DH-takes-FIRST_BASE substitution through `engine.make_substitution` flips `home_dh_active` to False and stamps `dh_forfeited=True` on the `SubstitutionRecord`. Structurally a duplicate of Plan 02's `TestMakeSubstitutionForfeitsDH::test_pitcher_to_field_position_forfeits_dh` — intentional, because Plan 02 proves engine isolation while this proves wiring is still reachable in Plan 03's TUI-scoped context.
- `test_no_tui_trigger_documented`: Pins the class docstring's deferral note in a test assertion so the documentation cannot be silently deleted.

## Why Two Intentional Changes Beyond Audit Scope

**(1) DH-forfeiture defensive-replacement UI deferred.** The substitution menu in Plan 03 exposes two sub-types: `pitching_change` (PITCHER → PITCHER) and `pinch_hitter` (batter → batter). Neither triggers DH forfeiture through user interaction. Adding a third defensive-replacement selector would have brought its own UX/CSS/keybindings burden and would have widened the human-verify checkpoint scope. Per the PLAN revision, option (a) was chosen: defer the TUI selector + prove engine-API reachability via test. The deferral is documented in:

- `06-03-PLAN.md` objective (Disposition note)
- `tests/test_game_engine.py::TestDHForfeitureReachability` class docstring
- This summary

**(2) Auto-pick-first-pitcher fallback removed.** The old `SubstitutionMenu.action_confirm` (and `on_button_pressed` for the Confirm button) would loop through `self._pitchers` to find the first available pitcher when no selection had been made — silently committing a substitution the user did not request. This masked selection failures (a misclick, a focus issue, or a not-yet-clicked state would all turn into an unintended pitching change). The new behavior dismisses with `None` when nothing is selected, so confirming-by-mistake is a no-op.

## Test Coverage

```
$ python3 -m pytest tests/test_game_screen_substitutions.py -x -v
======================== 7 passed in 0.23s ========================

$ python3 -m pytest tests/test_game_engine.py::TestDHForfeitureReachability -x -v
======================== 2 passed in 0.17s ========================

$ python3 -m pytest tests/ -q
======================== 331 passed in 0.91s ========================
```

Baseline at start of Plan 03: 322 passed (after Plans 01+02). After Plan 03: **331 passed** — +9 new tests, 0 regressions.

## Verification Output (from plan acceptance commands)

```
$ grep -n "self.engine.make_substitution\|self.sub_manager = SubstitutionManager" src/tui/screens/game_screen.py
69:        self.sub_manager = SubstitutionManager()
668:        self.sub_manager = SubstitutionManager()
848:            new_state, _modified_team = self.engine.make_substitution(

$ grep -E "sub_manager\.record_substitution" src/tui/screens/game_screen.py | grep -vE "^\s*#" || echo PASS
PASS

$ grep -n "_is_away_team_for_substitution\|_reset_sub_manager" src/tui/screens/game_screen.py
650:        self._reset_sub_manager()       # call site (inside _reset_game)
660:    def _reset_sub_manager(self) -> None:    # definition
672:    def _is_away_team_for_substitution(     # definition
851:                is_away_team=self._is_away_team_for_substitution(sub_type, state.half),   # call site

$ python3 -c "import re; src = open('src/tui/screens/substitution_menu.py').read(); m = re.search(r'#sub-menu-container\s*\{[^}]*height:\s*(\d+)', src); assert m and int(m.group(1)) >= 24"
PASS: container height ok: 26
```

## Deviations from Plan

**None — plan executed exactly as written.** Three presentational notes worth flagging for any future reader:

1. The helpers `_is_away_team_for_substitution` and `_reset_sub_manager` were placed as methods on `GameScreen` (the plan offered "method OR module-level helper, either is fine"). Method placement keeps related class state contained.
2. A small additional defensive test (`test_reset_sub_manager_with_no_engine_does_not_crash`) was added on top of the plan's required 5 in `tests/test_game_screen_substitutions.py` — it pins the `if self.engine is not None` guard that prevents a crash when `_reset_game` somehow runs before `_finalize_game_setup`. The plan was silent on the pre-finalize edge case; the test is cheap and documents the guard.
3. `_resolve_confirm_choice` was extracted as a private helper in `SubstitutionMenu` rather than duplicating the confirm logic across `on_button_pressed` and `action_confirm`. The plan's wording ("In on_button_pressed and action_confirm, replace the pitcher-only auto-confirm logic so that...") allows this; the extraction keeps the resolve rule documented in one place.

## Files Touched

| File | Change |
|------|--------|
| `src/tui/screens/substitution_menu.py` | Render `#batter-list` VerticalScroll with PlayerListItem widgets keyed `b-{pid}`. CSS: container 20 → 26, pitcher-list 10 → 8, batter-list new at 8. Extract `_resolve_confirm_choice`, remove auto-pick-first fallback. Track `_last_selection`. |
| `src/tui/screens/game_screen.py` | Wire `GameEngine(substitution_manager=self.sub_manager)`. Add `_is_away_team_for_substitution` and `_reset_sub_manager` helpers. Route `_handle_substitution` through `engine.make_substitution` and surface ValueErrors to the play log. Call `_reset_sub_manager()` from `_reset_game()`. Remove unused imports. |
| `tests/test_game_screen_substitutions.py` | NEW: 7 tests covering helper truth tables + replay reset semantics (Textual-free via unbound method + SimpleNamespace mock). |
| `tests/test_game_engine.py` | Add `TestDHForfeitureReachability` class (2 tests) proving engine-API reachability and pinning the TUI-deferral note. |

## Commits

- `2c931de` feat(06-03): render batter list in SubstitutionMenu with non-clipping sizing
- `2eb0dbe` feat(06-03): route TUI substitutions through engine + reset on replay
- `db99107` test(06-03): document DH-forfeiture engine reachability + TUI deferral

## Success Criteria

- [x] Substitution menu renders both relievers and pinch hitters without clipping (container height 26 ≥ 24)
- [x] All substitutions route through `GameEngine.make_substitution` via `_is_away_team_for_substitution` helper (verified: grep shows the call site; no `sub_manager.record_substitution` left in the TUI layer)
- [x] `_reset_game` produces a fresh `SubstitutionManager` via `_reset_sub_manager` helper (verified: 2 `self.sub_manager = SubstitutionManager()` lines + unit test asserting `id()` changes and engine is rewired)
- [x] DH forfeiture is provably reachable via engine-API test (`TestDHForfeitureReachability::test_dh_forfeiture_via_engine_api` passes); TUI defensive-replacement selector explicitly documented as deferred
- [x] Existing pytest suite still passes; new test file adds 7 unit tests; `tests/test_game_engine.py` gains 2 reachability tests (331 passed total, 0 regressions)
- [ ] **Human verifies the six end-to-end scenarios (Task 4 — PENDING; the human-verify checkpoint is awaiting the user's manual TUI run per `<how-to-verify>` in 06-03-PLAN.md)**

## Human Verification Status: PENDING

Task 4 is a `checkpoint:human-verify` gate. The engineer must run `python -m src.tui.app` (or `./play.sh`) and walk through the six scenarios in `06-03-PLAN.md` Task 4 `<how-to-verify>`:

1. **Pinch hitter visibility (Gap 3 / SUBS-02)** — both lists appear without clipping; selecting a bench batter and pressing C dismisses with a pinch_hitter sub.
2. **Pitching change effects sim (SUBS-01)** — fatigue resets to 0%, displayed pitcher name updates, subsequent plays use the new pitcher's name.
3. **No-reentry validation (Gap 5 / SUBS-03)** — already-removed player shows grayed with "(Used)".
4. **Replay resets substitutions (Gap 4 / SUBS-03)** — after Replay from the end-game menu, previously-removed players are no longer grayed.
5. **Auto-pick fallback removed** — pressing C with nothing selected makes NO substitution (no play-log narrative, no state change).
6. **No regressions** — boxscore, situation widget, play log, lineup cards, fast-forward, end-of-game box score all still render correctly.

The orchestrator will update this section after the user types `approved`.

## Self-Check: PASSED

- `src/tui/screens/substitution_menu.py` modified — FOUND
- `src/tui/screens/game_screen.py` modified — FOUND
- `tests/test_game_screen_substitutions.py` created — FOUND
- `tests/test_game_engine.py` extended — FOUND
- Commit `2c931de` (Task 1) — FOUND
- Commit `2eb0dbe` (Task 2) — FOUND
- Commit `db99107` (Task 3) — FOUND
- Full suite green (331 passed, +9 new, 0 regressions) — VERIFIED
- No `sub_manager.record_substitution` calls remain in TUI — VERIFIED
- CSS container height = 26 (≥24 required) — VERIFIED
- `_is_away_team_for_substitution` defined + called — VERIFIED
- `_reset_sub_manager` defined + called from `_reset_game` — VERIFIED
- Auto-pick-first-pitcher fallback removed from substitution_menu.py — VERIFIED
- Task 4 (human verification) PENDING — orchestrator to update after user runs scenarios
