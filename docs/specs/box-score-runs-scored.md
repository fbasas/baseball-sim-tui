# Spec: Box score — credit runs scored (R) to batters

**Source issue:** FRE-5 · **Date:** 2026-07-06 · **Status:** active

## Goal

The end-of-game box score's batting table has an `R` (runs scored) column that is
always `0` for every player, and the summed `TOTALS` row is therefore `0` as well.
Individual runs are never credited to the players who scored them. This spec fixes
that so each batter's `R` reflects the number of times that player crossed the plate,
and the per-team `TOTALS['R']` equals the team's final run total shown on the
linescore.

## Non-goals

- No change to how runs are *scored* or *counted* by the simulation — the run totals
  on the linescore (`state.away_score` / `state.home_score`) are already correct and
  must not change.
- No change to RBI, AB, H, BB, K, or any pitching stat accumulation.
- No new box-score columns, formatting changes, or UI layout work.
- No change to the advancement matrices or the meaning of `runners_scored`.
- No refactor of `_log_play` beyond adding the R-crediting; keep it a minimal,
  targeted fix.

## Design

### Where the data already is

The scoring player IDs are already computed and already reach the game screen — the
only missing step is consuming them.

- `src/simulation/advancement.py::advance_runners` returns an
  `AdvancementResult` (defined in `src/simulation/game_state.py`) whose
  `runners_scored: List[str]` field holds the **player IDs of everyone who scored on
  the play**, in scoring order. This includes the batter when the batter reaches home
  (home run, or `batter_destination == 4` via the no-passing runner resolution in
  `_resolve_runner_ids`). `len(runners_scored) == runs_scored` by construction.
- `src/simulation/engine.py::AtBatResult` carries that result as
  `result.advancement`, with `result.runs_scored` exposed as a convenience property
  (`= result.advancement.runs_scored`). So `result.advancement.runners_scored` is
  available wherever `AtBatResult` is.

### Where the bug is

`src/tui/screens/game_screen.py::_log_play(self, result, team, player_id)`
(around line 725) accumulates box-score stats into `self._batting_lines`
(a `Dict[str, Dict[str, int]]` keyed by player_id, each line
`{"AB", "R", "H", "RBI", "BB", "K"}`). It credits the **batter's** RBI
(`bl["RBI"] += result.runs_scored`) and increments the pitcher's `R`
(runs allowed, `pl["R"] += result.runs_scored`), but it **never increments any
batter's `R` (runs scored)**. `R` is set to 0 at init in `_init_stat_lines`
(around line 274) and never touched again on the batting side.

The `TOTALS` row in `box_score_screen.py::_build_batting_table` (around line 192)
is computed by summing each player's `R`, so it is 0 too. Fixing the per-player R
automatically fixes the TOTALS row — there is no separate totals bug.

### The fix

In `_log_play`, after (or alongside) the existing batting-line accumulation, credit
each scoring player one run:

```python
for scorer_id in result.advancement.runners_scored:
    line = self._batting_lines.setdefault(
        scorer_id, {"AB": 0, "R": 0, "H": 0, "RBI": 0, "BB": 0, "K": 0}
    )
    line["R"] += 1
```

Notes / constraints for the implementer:

- **Credit the scorers, not the batter.** The runs go to the players named in
  `runners_scored`, which is generally *not* the current batter (it's the runners who
  came around). On a home run the batter *is* in the list and is correctly credited
  once. Do **not** add `result.runs_scored` to the batter's `R` — that is the classic
  RBI-vs-R confusion and would be wrong.
- **All scorers belong to the batting team.** Only the offense's runners can score,
  so every ID in `runners_scored` has (or should have) a batting line on the batting
  team. `_init_stat_lines` pre-seeds a line for every lineup player of both teams;
  use `setdefault` (as above) as a defensive guard for pinch-runners / any ID not
  pre-seeded, mirroring the existing defensive `setdefault`-style guard already used
  for the batter's line at ~line 801.
- **Reset path:** the R credit lives entirely in `_batting_lines`, which is already
  cleared on replay/new-game (the `self._batting_lines = {}` resets around lines
  991–992). No extra reset work needed.
- Keep the change surgical — a few lines in `_log_play`. Do not thread a new field
  through `AtBatResult`; the data is already on `result.advancement`.

### Invariant to verify

After a full simulated game, for each team:

```
sum(line["R"] for line in that team's batting lines) == team's final score
```

(Every run is scored by exactly one batter, so per-team R must sum to the run total
on the linescore.) This is the strongest end-to-end check and should anchor the test.

### Tests

`tests/test_box_score.py` is the home for box-score stat tests. Its existing style is
two-fold and both styles are acceptable here:

1. **Pure-logic tests** that replicate the accumulation rule on a plain dict — add one
   asserting that iterating a sample `runners_scored` list credits `R` to each named
   player exactly once (and that a batter appearing in the list, as on a HR, gets
   exactly one R).
2. Prefer to also add a **behavioral test that exercises the real crediting path** so
   the fix can't silently regress — e.g. construct an `AtBatResult` with a known
   `AdvancementResult(runners_scored=[...])` and drive the accumulation, or simulate a
   short game and assert the `sum(R) == final score` invariant above. If instantiating
   `GameScreen` in a headless test proves impractical, factor the R-crediting into a
   small helper that both `_log_play` and the test can call, rather than dropping the
   behavioral coverage. Check `tests/test_game_screen_substitutions.py` for the
   existing pattern for testing GameScreen-adjacent logic before choosing an approach.

The PR must include test changes (per FACTORY.md); a green existing suite plus the new
assertions is the bar.

## Definition of done

- Each batter's box-score `R` equals the number of times that player scored in the
  game; the per-team batting `TOTALS['R']` equals that team's final run total.
- Home-run and inside-the-park cases credit the batter exactly one R (no double count,
  no RBI/R confusion).
- New test(s) in `tests/test_box_score.py` cover R-crediting, including the
  `sum(R) == final score` invariant or an equivalent behavioral check; full test suite
  green.
- No change to run totals, RBI, or any other stat.

## Open questions

None — the fix is fully specified by the existing code. No human checkpoint required.

## Issue breakdown

| Issue | Title | Depends on | Risk |
| --- | --- | --- | --- |
| FRE-5 child | Credit runs scored (R) to batters in the box score | — | — |
