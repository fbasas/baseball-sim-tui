---
phase: 06-substitution-wiring-fixes
plan: 02
subsystem: substitutions
tags: [substitutions, dh-forfeiture, engine, mlb-rules, audit-gap]
requires:
  - src/game/substitutions.py::SubstitutionManager.record_substitution
  - src/game/substitutions.py::SubstitutionRecord.dh_forfeited
provides:
  - src/game/substitutions.py::SubstitutionManager.would_forfeit_dh (extended)
  - src/game/engine.py::GameEngine.make_substitution (DH-aware)
affects:
  - src/game/substitutions.py
  - src/game/engine.py
  - tests/test_substitutions.py
  - tests/test_game_engine.py
tech_stack:
  added: []
  patterns:
    - Sentinel class identity check (`old_position is DesignatedHitter`) rather than instance
    - Capture-before-mutate for slot.position (engine.py:make_substitution)
    - Regex-based static check that the buggy isinstance(x, type(Position)) cannot return
key_files:
  created: []
  modified:
    - src/game/substitutions.py
    - src/game/engine.py
    - tests/test_substitutions.py
    - tests/test_game_engine.py
decisions:
  - "would_forfeit_dh keeps backward-compat: old_position defaults to None so callers without lineup context (existing test_would_forfeit_dh_for_pitcher_entering_lineup) still work via Path 1."
  - "Path 1 (pitching change) tightened: only forfeits when position_change is a Position member OTHER THAN Position.PITCHER. A plain PITCHER -> PITCHER swap no longer forfeits — the previous behaviour was a bug masked because no caller ever set dh_forfeited=True anyway."
  - "DesignatedHitter is checked via class identity (`is DesignatedHitter`), not isinstance — it is a sentinel CLASS not an enum member, per src/game/positions.py:77-92."
  - "SubstitutionRecord.old_position keeps its declared type Optional[Position]: when the slot held the DH sentinel, we record None (the sentinel is not a Position member). The forfeit signal is carried by the dh_forfeited boolean instead."
  - "engine.py:make_substitution derives is_away_team from state.half — matches the record_substitution logic on the other end of the API and removes the need for callers to pass yet another flag (the existing is_away_team parameter is kept for the validate_* calls but is_NOT_ relied on for forfeiture team selection, which keeps the two ends symmetric)."
metrics:
  duration: "~10 minutes"
  tasks_completed: 2
  files_modified: 4
  tests_added: 10
  date_completed: "2026-05-22"
---

# Phase 06 Plan 02: DH Forfeiture Wiring Summary

Closes audit gap 6 (SUBS-03): `SubstitutionRecord.dh_forfeited` and `SubstitutionManager.would_forfeit_dh` existed since Phase 04 but were dead code — no caller ever evaluated `would_forfeit_dh` before constructing the record, and both branches of `GameEngine.make_substitution` hardcoded `dh_forfeited=False`. After this plan, the engine detects both MLB-defined DH-forfeiture paths and stamps the flag on the record, which causes `record_substitution` to flip the correct team's `dh_active` flag.

## What Changed

### 1. `SubstitutionManager.would_forfeit_dh` — extended with `old_position`

Signature: `(is_away_team, sub_type, position_change=None, old_position=None) -> bool`

Two trigger paths now recognised:

| Path | Trigger | Example |
|------|---------|---------|
| **1 — Pitcher takes field slot** | `sub_type == PITCHING_CHANGE` AND `isinstance(position_change, Position)` AND `position_change is not Position.PITCHER` | Double switch: pitcher comes in at first base |
| **2 — DH takes field slot** | `old_position is DesignatedHitter` AND `isinstance(position_change, Position)` | Manager moves DH from batting-only role into LF |

Both paths short-circuit if the team's DH is already inactive.

**Behavioural changes from previous version:**
- A plain `PITCHER -> PITCHER` change no longer trips Path 1 (the old code triggered on *any* non-None `position_change`, including `Position.PITCHER`, which was wrong). This was dead behaviour previously because nobody read the return value; now that engine.py reads it, the predicate had to be correct.
- `DesignatedHitter` sentinel class is recognised via identity (`is DesignatedHitter`), matching the project's convention from `src/game/positions.py:84-86`.

### 2. `GameEngine.make_substitution` — wires the predicate, fixes the buggy isinstance

Both branches now call `sub_manager.would_forfeit_dh(...)` BEFORE constructing the `SubstitutionRecord` and pass the result into the record's `dh_forfeited` field.

| Branch | old_position passed to predicate |
|--------|----------------------------------|
| Pitching change (`is_pitching_change=True`) | `Position.PITCHER` (the outgoing player is by definition a pitcher) |
| Position player (`is_pitching_change=False`) | `team.lineup.slots[slot_index].position`, captured BEFORE `team.update_lineup_slot` mutates the slot |

The team that forfeits is determined from `state.half` (TOP → away, BOTTOM → home), the same logic `record_substitution` uses on the other side of the API.

**Pre-existing bugs deleted:**
- Line 229 of engine.py used `isinstance(new_position, type(Position))`. `type(Position)` is `EnumType` (the metaclass), not `Position`. The check would only return True if `new_position` were the `Position` class itself, never a `Position` member. The buggy line and its mirror at 230 (mirror in the pitching-change branch) are now gone — replaced with proper `isinstance(x, Position)` and explicit `Position.PITCHER` literals.
- Line 263 read `team.lineup.slots[slot_index].position` AFTER `team.update_lineup_slot` had already overwritten the slot — capturing the NEW position, not the old one. Fixed by capturing `old_slot_position` BEFORE the mutation.
- The static check `test_old_position_derivation_no_longer_buggy` regex-scans `engine.py` to prevent regression — if anyone reintroduces `isinstance(x, type(Position))`, the test fails immediately.

## Test Coverage Added

**`tests/test_substitutions.py` (+5 tests)** — predicate-level paths:
- `test_would_forfeit_dh_for_dh_taking_field_position`: Path 2 fires (DH -> LF).
- `test_would_forfeit_dh_pitcher_to_pitcher_does_not_forfeit`: Path 1 rejects benign change.
- `test_would_forfeit_dh_dh_to_dh_does_not_forfeit`: DH-stays-as-DH no-op.
- `test_would_forfeit_dh_pitcher_to_field_position_still_works`: Path 1 fires (with explicit old_position=PITCHER).
- `test_would_forfeit_dh_returns_false_when_dh_inactive_with_new_signature`: inactive-guard works with the new keyword arg.

**`tests/test_game_engine.py::TestMakeSubstitutionForfeitsDH` (+5 tests)** — engine-level wiring:
- `test_pitcher_to_field_position_forfeits_dh`: position-player branch correctly flips `home_dh_active` and stamps `dh_forfeited=True` on the record when the DH slot is moved to FIRST_BASE.
- `test_plain_pitching_change_does_not_forfeit`: pitching branch passes through with `dh_forfeited=False`, both dh_active flags stay True, and `record.new_position` is `None` (the actual argument, not the buggy literal `Position.PITCHER`).
- `test_pinch_hitter_for_dh_no_forfeit`: pinch hitter for the DH staying as DH does not forfeit.
- `test_inning_half_determines_team_forfeited`: TOP -> away; BOTTOM -> home.
- `test_old_position_derivation_no_longer_buggy`: regex-based static check that `isinstance(x, type(Position))` is gone from `src/game/engine.py`.

A helper `_make_team_with_dh(extra_player_ids=...)` in `tests/test_game_engine.py` builds a minimal Team whose slot 8 holds the DH and pads `batting_stats` with any incoming substitute IDs so `update_lineup_slot` succeeds.

## Verification Output

```
$ python3 -m pytest tests/test_substitutions.py -v
============================== 21 passed in 0.12s ==============================

$ python3 -m pytest tests/test_game_engine.py::TestMakeSubstitutionForfeitsDH -v
============================== 5 passed in 0.12s ===============================

$ python3 -m pytest tests/ -q
======================= 297 passed, 25 skipped in 0.84s ========================

$ grep -n "would_forfeit_dh" src/game/engine.py
275:                dh_forfeited_flag = self.sub_manager.would_forfeit_dh(
315:            # class; we pass it through to would_forfeit_dh unchanged.
318:            # Detect DH forfeiture BEFORE we touch the lineup. would_forfeit_dh
323:                dh_forfeited_flag = self.sub_manager.would_forfeit_dh(

$ grep -n "isinstance(new_position, type(Position))" src/game/engine.py || echo "PASS"
PASS
```

Baseline at start of plan: 292 passed (after Plan 01 added 5 prior tests on top of the pre-Phase-6 287). After Plan 02: **297 passed, 25 skipped** — +5 substitution tests + 5 engine tests = +10 new tests, 0 regressions.

## Deviations from Plan

**None — plan executed exactly as written.** Three minor presentational choices worth flagging for any future reader:

1. `SubstitutionRecord.old_position` for the position-player branch is recorded as `None` when the slot held the `DesignatedHitter` sentinel, because the field is typed `Optional[Position]` and the sentinel is not a `Position` member. The forfeit signal travels via the `dh_forfeited` boolean. This matches what the plan implicitly requested (the plan said "pass `old_position=old_slot_position if isinstance(old_slot_position, Position) else None`").
2. `SubstitutionRecord.new_position` for the pitching-change branch is set to the literal value of the `new_position` argument when it is a `Position` member, else `None`. The plan's wording ("pass the actual `new_position` argument") could be read as "pass it raw"; passing it raw would have allowed `DesignatedHitter` (a class) into a field typed `Optional[Position]`, which is type-incorrect. The `isinstance(new_position, Position)` guard is the minimum coercion needed to honour the field's declared type.
3. The engine-side `is_away_team` parameter is kept (used for the `validate_*` calls) but the team-for-forfeiture is re-derived locally from `state.half` to ensure the same logic both ends of the API use. The plan and the implementation are consistent on this point; calling it out only because the redundancy is intentional, not an oversight.

## Files Touched

| File | Change |
|------|--------|
| `src/game/substitutions.py` | `would_forfeit_dh` extended with `old_position` param; Path 1 tightened to reject PITCHER -> PITCHER; Path 2 added for DH-takes-field. Docstring rewritten. |
| `src/game/engine.py` | Both branches of `make_substitution` now call `would_forfeit_dh` and stamp `dh_forfeited` on the record. Two buggy `isinstance(new_position, type(Position))` checks deleted and replaced with `isinstance(x, Position)`. Position-player branch captures `old_slot_position` BEFORE the mutation. |
| `tests/test_substitutions.py` | +5 predicate tests covering both forfeiture paths and the non-trigger cases. |
| `tests/test_game_engine.py` | +5 engine-level tests in `TestMakeSubstitutionForfeitsDH` plus `_make_team_with_dh` helper. |

## Commits

- `0ee1142` test(06-02): add failing tests for would_forfeit_dh old_position signature (RED)
- `755780c` feat(06-02): extend would_forfeit_dh with old_position parameter (GREEN)
- `5373e0c` test(06-02): add failing tests for make_substitution DH-forfeiture wiring (RED)
- `d70c9be` feat(06-02): wire DH forfeiture detection into make_substitution (GREEN)

## Success Criteria

- [x] DH-takes-field substitutions correctly forfeit the DH for the substituting team
- [x] Pitcher-to-field-position substitutions (double switch) correctly forfeit the DH
- [x] Plain pitching changes (PITCHER -> PITCHER) and pinch hitters for DH (DH -> DH) do NOT forfeit
- [x] Pre-existing `isinstance(new_position, type(Position))` bug is removed (static regex check)
- [x] All existing tests still pass (297 passed, 25 skipped); no public signatures broken

## Self-Check: PASSED

- `src/game/substitutions.py` modified — FOUND
- `src/game/engine.py` modified — FOUND
- `tests/test_substitutions.py` extended — FOUND
- `tests/test_game_engine.py` extended — FOUND
- Commit `0ee1142` (RED Task 1) — FOUND
- Commit `755780c` (GREEN Task 1) — FOUND
- Commit `5373e0c` (RED Task 2) — FOUND
- Commit `d70c9be` (GREEN Task 2) — FOUND
- Full suite green (297/297 passing, +10 new, 0 regressions) — VERIFIED
- Buggy `isinstance(x, type(Position))` gone from engine.py — VERIFIED
- `would_forfeit_dh(` appears at two call sites inside `make_substitution` — VERIFIED
