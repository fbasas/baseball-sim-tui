# Spec: Manual lineup editor (batting order & positions)

**Source issue:** FRE-8 · **Date:** 2026-07-06 · **Status:** active

## Goal

Give the human manager a pre-game screen to review and edit the auto-generated
lineup before the game starts: reorder the batting order, reassign defensive
positions, and swap in a different starter from the roster. The auto-generated
lineup (`build_lineup()`) remains the default, so the current fast path — accept
the auto lineup and play — is unchanged. Delivers requirement LINE-01 (flagged
partial in the v1.0 milestone audit).

## Non-goals

- **No between-series-game editing.** The editor appears only in the initial
  pregame `SetupFlow`. In best-of-N series, games 2+ rebuild the auto lineup
  (only the starter is re-picked between games, as today). Per-game editing is a
  possible follow-up, explicitly out of scope here.
- **No DH ⇄ pitcher-bats (NL-style) toggle.** The built lineup uses the DH
  (8 fielders + DH), and every edit operation preserves that invariant. Choosing
  a batting pitcher / removing the DH is out of scope.
- **No AI-side editing.** AI-managed dugouts pick their own lineup via
  `ai_pregame` and are never shown the editor.
- **No new bench/roster construction UI.** Substitution is limited to swapping a
  lineup slot for a roster player who has batting stats and isn't already in the
  lineup or the starting pitcher.
- **No mid-game lineup editing.** In-game changes remain the existing
  substitution menu.

## Background — how lineups are built today

- `build_lineup(team, repo, pitcher_id)` (`src/game/lineup_builder.py`) sets
  `team.lineup` to a `Lineup` (`src/game/team.py`): 9 `LineupSlot`s
  (`player_id`, `position`, `batting_stats`) plus `starting_pitcher_id`. It uses
  DH (8 `Position` values + `DesignatedHitter`). `Lineup.__post_init__` validates
  exactly 9 slots and exactly the 8 non-pitcher fielding positions (+ DH).
- Pregame selection runs in `SetupFlow` (`src/tui/setup_flow.py`):
  mode → control → away team → home team → **starting pitcher for each
  human-managed side** → `on_complete(away_team, home_team, away_pitcher_id,
  home_pitcher_id, config)`. AI sides pass `None` for their pitcher.
- `BaseballSimApp._on_setup_complete` (`src/tui/app.py`) stores the matchup and
  pushes `GameScreen`. **Lineups are NOT built in the setup flow** — they are
  built inside `GameScreen._build_lineups()` (`src/tui/screens/game_screen.py`),
  which is called both at game start (`_finalize_game_setup`) **and on replay**
  (`_reset_game`). For a human side it calls `build_lineup(team, repo,
  pitcher_id)`; for an AI side it calls `ai_pregame(...)` with a heuristic
  fallback.
- **Critical constraint (replay):** `_reset_game` deliberately re-runs
  `_build_lineups()` from scratch to *undo* in-place pinch-hitter mutations of
  `team.lineup.slots` and restore the starting pitcher. Therefore a manual lineup
  **must not** be applied by mutating `team.lineup` once and hoping it survives —
  in-game substitutions would leak into a replay. The manual lineup must be
  stored as **replay-safe data** (a plan) and re-applied fresh on every
  `_build_lineups()` call.

## Design

### The `LineupPlan` — replay-safe manual lineup as data

Introduce a small immutable value object that fully describes a lineup as plain
data, so it can be regenerated into a fresh `Lineup` on every build:

```python
@dataclass(frozen=True)
class LineupPlan:
    batting_order: Tuple[str, ...]                 # 9 player_ids, leadoff first
    positions: Mapping[str, Union[Position, type]]  # player_id -> Position | DesignatedHitter
    starting_pitcher_id: str
```

- `lineup_to_plan(lineup) -> LineupPlan` — snapshot a `Lineup`.
- `apply_plan(team, plan) -> None` — set `team.lineup = create_lineup(team,
  list(plan.batting_order), dict(plan.positions), plan.starting_pitcher_id)`.
  This is a thin wrapper over the existing `create_lineup`, which already
  validates fully, so applying a plan is atomic and replay-safe (a fresh
  `Lineup`, no leaked subs).

### Edit operations (pure logic, always leave a valid lineup)

All operations act on a `Lineup` (the editor works on a scratch copy) and are
atomic: on any invalid request they raise `ValueError` and leave the lineup
unchanged. Each guarantees the result still passes `Lineup` validation (9 unique
players, exactly the 8 fielding positions + DH, pitcher tracked separately).

1. **Reorder** — `swap_batting_slots(lineup, i, j)`: exchange slots `i` and `j`
   in `lineup.slots`. Each player keeps their defensive position; only batting
   order changes. (The editor's "move up/down" is a swap of adjacent slots.)
2. **Swap positions** — `swap_positions(lineup, i, j)`: exchange the `position`
   fields of slots `i` and `j` (players and batting order unchanged). Swapping
   two players' positions always keeps the position set complete, so the result
   is always legal — including when one of the two is the DH.
3. **Substitute** — `substitute_slot(team, lineup, slot_index, new_player_id)`:
   replace the player in `slot_index` with `new_player_id`, keeping that slot's
   position and batting-order index. Guards: `new_player_id` must have batting
   stats (`team.batting_stats`), must not already appear in the lineup, and must
   not be the `starting_pitcher_id`. (This is the hardened form of the existing
   `Team.update_lineup_slot`, which lacks the duplicate-player guard.)

Bounds: any out-of-range slot index raises `ValueError`.

### Module layout

- **New:** `src/game/lineup_edit.py` — `LineupPlan`, `lineup_to_plan`,
  `apply_plan`, `swap_batting_slots`, `swap_positions`, `substitute_slot`.
  Pure logic; no Textual import. (Kept separate from `lineup_builder.py` so the
  builder stays focused on construction.)
- **New:** `src/tui/screens/lineup_edit_screen.py` — `LineupEditScreen` modal.
- **Changed:** `src/tui/setup_flow.py`, `src/tui/app.py`,
  `src/tui/screens/game_screen.py` — wire the editor in and consume the plan.

### The `LineupEditScreen` modal

A `ModalScreen[Optional[LineupPlan]]` matching the look and keyboard-first feel
of `PitcherSelectScreen` / `SubstitutionMenu` (same gold/green theme, in-dialog
hint line, no buttons). It receives the team, its freshly built auto `Lineup`,
and the repo (for the bench list / stats). It edits a **scratch copy** of the
lineup via the pure ops above, and on confirm dismisses with a `LineupPlan`
snapshot of the edited lineup; on cancel it dismisses with `None` (meaning "use
the auto lineup unchanged").

Display: 9 rows — batting-order number, player name, position abbrev, and a
slash line (AVG/OBP/SLG) — with the selected slot highlighted; plus a bench list
(roster batters with stats, excluding those already in the lineup and the
starting pitcher) shown when substituting.

Target interaction model (keyboard-first; an implementer may substitute an
equivalently simple scheme **only if** all three edit types + reset + confirm +
cancel remain reachable and unit-tested):

| Key | Action |
| --- | --- |
| `↑` / `↓` | Move selection between the 9 batting slots |
| `Shift+↑` / `Shift+↓` (or `,` / `.`) | Move selected batter up/down in the order (reorder) |
| `p` | Position-swap: press on one slot to mark it, then `p` on a second slot swaps their positions (`Esc` clears a pending mark) |
| `s` | Open the bench list for the selected slot; `↑/↓` + `Enter` picks the replacement (substitute) |
| `r` | Reset to the auto lineup (`build_lineup`) |
| `Enter` | Confirm — dismiss with the edited `LineupPlan` |
| `Esc` | Cancel — dismiss with `None` (use auto lineup) |

**Testability requirement:** as with `test_game_screen_substitutions.py`, this
project tests TUI logic by exercising extracted helper methods directly, without
spinning up a Textual `App` (no pilot). Keep every edit action in a plain method
that mutates the screen's scratch `Lineup` (delegating to `src/game/lineup_edit.py`)
and can be called on a screen instance built with a constructed/mock team. Unit
tests must cover each edit type, reset, and that confirm yields a plan reflecting
the edits while cancel yields `None`.

### Wiring into the pregame flow

1. **`SetupFlow`** — after a human side's starting pitcher is chosen
   (`_select_pitcher` → `on_pitcher_chosen`), build the auto lineup
   (`build_lineup(team, repo, pitcher_id=pid)`) and push `LineupEditScreen`.
   Capture the result: a `LineupPlan` (edited) or `None` (accept auto). Store
   per side and pass both through to completion. Extend the `on_complete`
   signature to carry them, e.g.:
   `on_complete(away_team, home_team, away_pitcher_id, home_pitcher_id,
   away_plan, home_plan, config)` where each `*_plan` is `Optional[LineupPlan]`
   (`None` for AI sides and for accept-auto). Preserve existing back-out
   behavior; the editor is not shown for AI sides.
2. **`BaseballSimApp`** — store `away_plan` / `home_plan` from
   `_on_setup_complete` and pass them into the first `GameScreen`
   (`_push_game`). For series games 2+ (`_start_next_series_game`), pass **no**
   plans (auto lineup), consistent with the non-goal. The initial game uses the
   plans; later games do not.
3. **`GameScreen`** — accept `away_plan` / `home_plan` (`Optional[LineupPlan]`,
   default `None`) in the constructor. In `_build_lineups`, for a human side:
   **if a plan is present, `apply_plan(team, plan)`** (fresh `Lineup` each call —
   works for both the initial build and replay, undoing any in-game subs); else
   `build_lineup(...)` exactly as today. AI sides are unchanged. Because the plan
   is re-applied from data on every `_build_lineups()`, `_reset_game` (replay)
   correctly restores the manual lineup with subs undone.

### Flow diagram

```
SetupFlow: mode → control → away team → home team
   → [human away] pick starter → build auto lineup → LineupEditScreen → away_plan?
   → [human home] pick starter → build auto lineup → LineupEditScreen → home_plan?
   → on_complete(..., away_plan, home_plan, config)
App: store plans → GameScreen(game 1, away_plan, home_plan)
   GameScreen._build_lineups(): human side w/ plan → apply_plan (replay-safe)
                                human side no plan  → build_lineup
                                AI side             → ai_pregame (unchanged)
Series game 2+: _start_next_series_game → GameScreen(no plans) → auto lineups
```

## Open questions

None require a human checkpoint. The interaction model has a concrete, testable
default derived from the existing modals (above); an implementer may refine the
exact keys within the stated constraint. Between-series editing and the NL/DH
toggle are deliberate non-goals (candidate follow-ups), not blockers.

## Issue breakdown

| Issue | Title | Depends on | Risk |
| --- | --- | --- | --- |
| FRE-8·1 | Lineup editing model layer (`LineupPlan` + edit ops) | — | — |
| FRE-8·2 | `LineupEditScreen` modal | FRE-8·1 | — |
| FRE-8·3 | Wire the lineup editor into the pregame flow | FRE-8·1, FRE-8·2 | — |

Sizing: each issue is one concept, well under 400 lines / 10 files. Issue 1 adds
a tested module unused by the app; Issue 2 adds a tested screen unused until
wired; Issue 3 wires them and keeps the fast path, series mode, and replay
working. None touch external services, auth, or persistent data, so none are
`risk:high`; the DoD for each is provable by the existing pytest suite (no live
TUI driving required).
