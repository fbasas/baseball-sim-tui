# Spec: Global quit key across the pregame setup flow

**Source issue:** FRE-102 · **Date:** 2026-07-10 · **Status:** active

## Goal

Give the player a single, always-available way to **quit the app** from anywhere
in the pregame setup flow. Today, once you leave the main GAME MODE menu, you are
locked into the setup chain until the game actually starts. Pressing `q` on any
pregame screen should exit the app cleanly, matching the `q → quit` that already
exists on the in-game `GameScreen`.

## Background — why the player is "locked in"

`SetupFlow` (`src/tui/setup_flow.py`) pushes a chain of modal screens over the
app's base screen:

```
GAME MODE (ChoiceScreen, allow_quit=True)   ← q quits here today (FRE-98/99)
  └─ MANAGER CONTROL (ChoiceScreen, allow_quit=False)
       └─ AWAY TEAM (TeamSelectScreen)
            └─ HOME TEAM (TeamSelectScreen)
                 └─ STARTING PITCHER ×(human sides) (PitcherSelectScreen)
                      └─ LINEUP EDIT ×(human sides) (LineupEditScreen)
                           └─ GameScreen  ← q quits here today
```

FRE-98/FRE-99 added an opt-in `q → quit` to the **GAME MODE** menu only. Every
screen *after* it has no quit. Worse, on most of them `Esc` does **not** go back —
it picks a default and moves the flow *forward*:

- **MANAGER CONTROL** `ChoiceScreen`: `Esc` → `action_use_default` → dismisses the
  default id (`home_ai`), which advances into team selection. Its `q` binding is
  gated off (`allow_quit=False`).
- **PitcherSelectScreen**: `Esc` → `action_use_default` → advances to lineup edit.
- **LineupEditScreen**: `Esc` → `action_cancel` → dismisses `None` = "accept the
  auto lineup", which advances to the next side / into the game.
- Only **TeamSelectScreen** `Esc` steps back a phase (and cancels from the decade
  phase).

So after an accidental "single game" pick there is effectively no way back to the
menu and no way to quit until `GameScreen` appears. This is the bug.

## Non-goals

- **Not changing any existing key's behavior.** `Esc`-picks-default / `Esc`-back,
  `Enter`-selects, and every screen that *already* binds `q` keep their exact
  current behavior. This spec only adds a quit where there is none.
- **No "return to main menu" semantics.** The issue asks for a *quit key*. `q`
  exits the app (like `GameScreen`'s `q`), it does not unwind the flow back to the
  mode menu. (Unwinding each setup screen back to the menu is a larger, separate
  UX change and is out of scope.)
- **No confirmation dialog.** The pregame flow has no persisted or in-game state to
  protect — a half-built lineup is discardable — so quitting is immediate. (This
  matches the FRE-98 decision for the main menu.)
- **No changes to in-game / post-game / hub / season screens.** `GameScreen`,
  `SeasonHubScreen`, `BoxScoreScreen`, `SeriesStatusScreen`, and the GAME MODE
  `ChoiceScreen` all already bind their own `q`; those bindings shadow the new
  app-level one and are left untouched.

## Design

Add the quit binding **once, at the `App` level** on `BaseballSimApp`
(`src/tui/app.py`), rather than per-screen. Textual resolves key bindings from the
focused widget up through the current screen to the app; a screen that binds `q`
itself shadows the app binding, and a key that no screen/widget consumes falls
through to the app. This makes one app-level binding a genuinely global quit that
automatically covers every "locked-in" screen without touching each one.

### 1. App-level binding + explicit action

In `BaseballSimApp` (`src/tui/app.py`):

```python
from textual.binding import Binding
...
class BaseballSimApp(App):
    ...
    BINDINGS = [
        Binding("q", "quit", "Quit"),
    ]

    def action_quit(self) -> None:
        """Global quit: exit the app from any screen that doesn't handle `q`.

        Screens that bind their own `q` (GameScreen, SeasonHubScreen, the GAME
        MODE ChoiceScreen, etc.) shadow this; on every pregame setup screen that
        doesn't, `q` falls through to here and exits cleanly.
        """
        self.exit()
```

Define `action_quit` explicitly (rather than relying on Textual's default
`App.action_quit`) so the behavior is unambiguous and matches `GameScreen`'s
`self.app.exit()`. `BaseballSimApp` has no existing `BINDINGS` today — add the
attribute.

### 2. Why this reaches the locked-in screens (verified in Textual 7.4.0)

The installed/pinned Textual behaviors this design relies on were confirmed
empirically on this repo's `venv` (Textual **7.4.0**; `requirements.txt` pins
`textual>=0.85.0`):

- A focused `OptionList` (the widget inside every setup modal) does **not**
  type-ahead-consume `q`; the key bubbles up past it. (Same fact FRE-98 relied on.)
- A screen-level binding disabled via `check_action` returning `None` (exactly the
  MANAGER CONTROL `ChoiceScreen`, `allow_quit=False`) **falls through** to the
  app-level `q` binding, which then fires.
- Both hold when the current screen is a `ModalScreen` (all setup screens are
  `ModalScreen`).

Net effect per screen:

| Screen | Binds `q`? | Result of `q` |
| --- | --- | --- |
| GAME MODE `ChoiceScreen` (`allow_quit=True`) | yes (screen) | unchanged — `dismiss(None)` → `on_cancel` → `exit` |
| MANAGER CONTROL `ChoiceScreen` (`allow_quit=False`) | bound but gated off | **falls through → app `action_quit` → exit** |
| `TeamSelectScreen` (away/home) | no | **app `action_quit` → exit** |
| `PitcherSelectScreen` | no | **app `action_quit` → exit** |
| `LineupEditScreen` | no | **app `action_quit` → exit** |
| `SaveSelectScreen`, `SubstitutionMenu` | no | **app `action_quit` → exit** (also now quit-able; desirable) |
| base app screen (between modals) | no | **app `action_quit` → exit** |
| `GameScreen` / `SeasonHubScreen` / `BoxScoreScreen` / `SeriesStatusScreen` | yes (screen) | unchanged |

There are **no `Input`/`TextArea` widgets anywhere in the app** (the UI is entirely
list-driven), so a bare `q` cannot collide with text entry.

### 3. Discoverability — advertise `q` in the setup screens' hint lines

The player filed this because they didn't know how to get out, so the fix must be
visible. Each dead-end setup screen shows a static hint `Label` inside its modal.
Append a quit affordance to the three screens that own a `_HINT` constant and were
locked-in, matching the existing markup style (`[#d4a843]key[/] label`, joined by
three spaces):

- **`TeamSelectScreen._HINT`** — currently
  `↑/↓ navigate   Enter select   Esc back` → append `   [#d4a843]q[/] quit`.
- **`PitcherSelectScreen._HINT`** — currently
  `↑/↓ navigate   Enter select   Esc use default ★` → append `   [#d4a843]q[/] quit`.
- **`LineupEditScreen`** — append `   [#d4a843]q[/] quit` to its main controls hint
  (the one shown when the bench is closed; **do not** alter the `_BENCH_HINT` shown
  while substituting). Inspect the file to confirm the exact hint constant/label
  name before editing.

**Leave the MANAGER CONTROL `ChoiceScreen` hint unchanged.** `ChoiceScreen`'s hint
is tied to its `allow_quit` flag (FRE-98/99), and setting `allow_quit=True` on the
control screen would re-route its `q` to `dismiss(None)` → *back to the mode menu*
rather than *quit the app* — the wrong behavior. Rather than re-couple that generic
screen, the control question keeps its current hint; `q` still works there
functionally (falls through to the app). This is a deliberate, minor inconsistency,
noted so the implementer doesn't "fix" it by flipping `allow_quit`.

### Landmines for the implementer

- **Do not touch `ChoiceScreen` or `SetupFlow._select_control`.** The global quit is
  purely additive at the app level. Flipping the control screen's `allow_quit`
  would change its `q` to *return to menu*, not *quit* — that is explicitly wrong.
- `GameScreen.action_quit` calls `self.app.exit()` and also stops a fast-forward
  timer; that path is unrelated and unchanged. The new app `action_quit` is only
  reached on screens without their own `q`, none of which run a timer.
- Keep the binding tuple name `"quit"`/`action_quit` consistent so Textual resolves
  it against the app namespace.

## Open questions

None. The one judgment call — *quit the app* vs *return to the mode menu* — is
resolved by the issue title ("global quit key") and the existing `GameScreen`
convention (`q` = exit app).

## Testing

No CI — the local `pytest` suite is the gate. Use the repo's DB-free house idioms
(`tests/test_choice_screen.py` for mock-`self`/`SimpleNamespace` + captured
`dismiss`/`exit`; in-process `Pilot` via `app.run_test()` where a running app is
needed). The full-app Pilot path needs the Lahman DB (gitignored, absent in a fresh
worktree) because `BaseballSimApp.on_mount` opens `LahmanRepository`; the tests
below are all **DB-free** and are sufficient for the definition of done. If a
full-app Pilot smoke is desired, symlink `data/lahman.sqlite` read-only per the
repo convention and `pytest.skip` when absent — but do not make it the gate.

Add `tests/test_global_quit.py` covering:

1. **App action exits.** `BaseballSimApp.action_quit` calls `self.exit()` — drive it
   with a `SimpleNamespace` (or a subclass) capturing `exit()`; assert `exit` was
   called once with no args.
2. **App binds `q → quit`.** Assert `("q", "quit")` is among
   `BaseballSimApp.BINDINGS` (read `.key` / `.action` off the `Binding`s) so the
   global affordance can't silently regress.
3. **Setup screens don't shadow `q`.** For `TeamSelectScreen`,
   `PitcherSelectScreen`, and `LineupEditScreen`, assert `"q"` is **not** in their
   class `BINDINGS` keys — proving `q` falls through to the app. (A screen that
   later adds its own `q` would trip this and force a conscious decision.)
4. **Fall-through, live (Pilot, DB-free).** Build a minimal `App` subclass of the
   *same shape* — app-level `Binding("q", "quit")` + `action_quit` that records a
   flag — push a bare `ModalScreen` containing a focused `OptionList` and (to mirror
   the control screen) a `q` binding gated off via `check_action` returning `None`;
   `await pilot.press("q")`; assert the app's quit flag fired. This locks in the
   Textual fall-through behavior the whole design rests on, without the Lahman DB.
   (This mirrors the empirical check done while writing this spec.)
5. **Hint advertises quit.** Assert each edited `_HINT` string contains a `q`/quit
   affordance (read the constant directly; no app needed) and still contains its
   original navigate/select text. For `LineupEditScreen`, also assert the
   **bench** hint is unchanged.

## Definition of done

- Pressing `q` on **any** pregame setup screen — MANAGER CONTROL, AWAY/HOME TEAM,
  STARTING PITCHER, LINEUP EDIT — exits the app cleanly.
- The GAME MODE menu's `q` and every existing screen-level `q` (GameScreen,
  SeasonHubScreen, BoxScoreScreen, SeriesStatusScreen) behave exactly as before.
- No other key's behavior changes anywhere (`Esc`/`Enter` unchanged).
- `TeamSelectScreen`, `PitcherSelectScreen`, and `LineupEditScreen` hint lines
  advertise `q` to quit; `LineupEditScreen`'s bench-substitution hint is unchanged.
- New `tests/test_global_quit.py` passes and the full `pytest` suite is green.

## Issue breakdown

| Issue | Title | Depends on | Risk |
| --- | --- | --- | --- |
| FRE-102-a | Add an app-level global `q → quit` binding; advertise it on the setup screens | — | — |
</content>
</invoke>
