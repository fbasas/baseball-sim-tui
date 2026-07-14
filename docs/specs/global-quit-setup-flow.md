# Spec: Global quit key across the pregame setup flow

**Source issue:** FRE-102 · **Date:** 2026-07-10 · **Revised:** 2026-07-14 · **Status:** active

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
  gated off (`allow_quit=False`), so `q` does nothing here today.
- **PitcherSelectScreen**: `Esc` → `action_use_default` → advances to lineup edit.
- **LineupEditScreen**: `Esc` → `action_cancel` → dismisses `None` = "accept the
  auto lineup", which advances to the next side / into the game.
- Only **TeamSelectScreen** `Esc` steps back a phase (and cancels from the decade
  phase).

So after an accidental "single game" pick there is effectively no way back to the
menu and no way to quit until `GameScreen` appears. This is the bug. Note that
MANAGER CONTROL is the **first** locked-in screen — it is exactly where the player
lands after the accidental mode pick FRE-102 describes.

## ⛔ Why the original app-level design was scrapped (read this first)

The **first** version of this spec (2026-07-10) proposed adding the quit binding
*once, at the `App` level* on `BaseballSimApp`, on the theory that Textual lets a
key no screen consumes "fall through" to the App's `BINDINGS`. **That premise is
false for this app**, and the implementer proved it empirically on the repo's
pinned Textual **7.4.0** *and* on 8.1.1 (same result), confirmed in the Textual
source:

- Every setup screen is a `ModalScreen`. `textual/screen.py::_modal_binding_chain`
  **truncates the binding chain at the last modal node, excluding the App**
  (`return binding_chain[:index]` once `node.is_modal`).
- `textual/app.py::_check_bindings` dispatches a non-priority key via
  `self.screen._modal_binding_chain`, so under a modal the App's `BINDINGS` are
  **never consulted**. `ModalScreen`'s own docstring: *"A screen with bindings
  that take precedence over the App's key bindings."*
- The GAME MODE `q` works today **only** because `ChoiceScreen` binds its *own*
  screen-level `q` (inside the modal chain) — it is **not** App fall-through.

Rejected alternatives to make an app-level binding reach modals, and why:

| App-level attempt | Result |
| --- | --- |
| `Binding("q", "quit")` (non-priority — the old design) | **Does nothing** on any setup screen. Feature simply doesn't work. |
| `Binding("q", "quit", priority=True)` | Works on setup screens, but the priority pass checks the **App first**, so it **pre-empts every screen that binds its own `q`** — a real regression **including data loss**: `SeasonHubScreen`'s `q → action_quit_to_menu` runs the unsaved-season save prompt; a priority app-quit would bypass it and drop unsaved progress. (`BoxScoreScreen`/`SeriesStatusScreen` `q → dismiss("quit")` and GAME MODE `q → dismiss(None)` likewise bypassed.) |
| App-level `on_key` handler | Bubbles **even when a screen already handled `q`**, so it double-acts (exits on top of `GameScreen`'s own quit). Not usable. |

There is no app-level construct that fires *only* for modal-unhandled keys. So the
design below is **per-screen**, matching the idiom `GameScreen` already uses.

## Non-goals

- **Not changing any existing key's behavior.** `Esc`-picks-default / `Esc`-back,
  `Enter`-selects, and every screen that *already* binds `q` (`GameScreen`,
  `SeasonHubScreen`, `BoxScoreScreen`, `SeriesStatusScreen`, and the **GAME MODE**
  `ChoiceScreen`) keep their exact current behavior. This spec only *adds* a quit
  where there is none. In particular the GAME MODE menu's `q` path
  (`dismiss(None)` → `on_mode_chosen(None)` → `on_cancel = app.exit`) is left
  byte-for-byte unchanged.
- **No "return to main menu" semantics.** The issue asks for a *quit key*. `q`
  exits the app (like `GameScreen`'s `q`); it does not unwind the flow back to the
  mode menu. (Unwinding each setup screen back to the menu is a larger, separate
  UX change and is out of scope.)
- **No confirmation dialog.** The pregame flow has no persisted or in-game state to
  protect — a half-built lineup is discardable — so quitting is immediate. (Matches
  the FRE-98 decision for the main menu.)
- **No app-level `BINDINGS` on `BaseballSimApp`.** The corrected design is purely
  per-screen; `src/tui/app.py` is **not** touched.
- **No changes to in-game / post-game / hub / season screens**, nor to
  `SaveSelectScreen` / `SubstitutionMenu` (those are not part of the locked-in
  pregame trap; leaving them out keeps the change minimal and its risk contained).

## Design

Add a quit binding **on each locked-in setup screen**, resolving inside that
screen's own modal chain — the same idiom `GameScreen` uses
(`Binding("q", "quit", "Quit")` + `action_quit` → `self.app.exit()`). There are two
shapes of screen to cover.

### 1. The three list screens — `TeamSelectScreen`, `PitcherSelectScreen`, `LineupEditScreen`

These three are `ModalScreen` subclasses that **do not bind `q` today** (`q` is
unused in all three — no key conflict). On each, add:

```python
from textual.binding import Binding   # already imported in all three
...
    BINDINGS = [
        ...existing bindings...,
        Binding("q", "quit", "Quit"),
    ]

    def action_quit(self) -> None:
        """Quit the app from this locked-in pregame setup screen."""
        self.app.exit()
```

- **`TeamSelectScreen`** (`src/tui/screens/team_select_screen.py`) — used for both
  AWAY and HOME team. Add the binding + `action_quit`. Its existing bindings are
  `up`/`down`/`enter` (priority) and `escape` → `back`; none is `q`. Leave `Esc`'s
  step-back behavior untouched.
- **`PitcherSelectScreen`** (`src/tui/screens/pitcher_select_screen.py`) — add the
  binding + `action_quit`. Existing: `enter` (priority), `escape` → `use_default`.
- **`LineupEditScreen`** (`src/tui/screens/lineup_edit_screen.py`) — add the
  binding + `action_quit`. Existing bindings include `p`, `s`, `r`, `,`/`.`,
  shift+arrows, `enter` (priority), `escape` → `cancel`; **none is `q`.** The
  lineup screen is the most key-dense — double-check no future `q` sneaks in.

`q` fired on any of these resolves against the screen's own namespace inside the
modal chain, so it works regardless of Textual's app-fall-through truncation, and
it cannot pre-empt any other screen's `q` (each binding is local to its screen).
Confirmed working on Textual 7.4.0 and 8.1.1.

### 2. MANAGER CONTROL — `ChoiceScreen` gets an opt-in *true-exit* quit

MANAGER CONTROL is a `ChoiceScreen` constructed with the default `allow_quit=False`
(`src/tui/setup_flow.py::_select_control`). `ChoiceScreen` is a **generic, reused**
screen: it is also the GAME MODE menu (`allow_quit=True`). We must give MANAGER
CONTROL a `q → quit` **without** disturbing GAME MODE, and the subtlety is what
`q` should *do*:

- `ChoiceScreen.action_quit` today calls `self.dismiss(None)`. For **GAME MODE**
  that routes to `on_mode_chosen(None)` → `on_cancel` (= `app.exit`) → the app
  exits. Correct.
- For **MANAGER CONTROL**, `dismiss(None)` routes to `on_control_chosen(None)` →
  `self._select_mode()` = **go back to the mode menu**, *not* quit. (That path is
  currently unreachable, since `q` is gated off there.) So simply flipping
  `allow_quit=True` on the control screen would make its `q` mean "return to
  menu" — the **wrong** behavior, and inconsistent with `q = exit` everywhere else.

**Chosen fix (option (b) from the implementer's handback):** add a second,
independent opt-in to `ChoiceScreen` that makes `q` exit the app *directly* (the
`GameScreen` idiom), distinct from the existing `dismiss(None)` cancel-quit. Only
MANAGER CONTROL opts into it.

Add a `quit_exits_app: bool = False` constructor parameter to `ChoiceScreen`
(`src/tui/screens/choice_screen.py`) and thread it through the three places that
already read `allow_quit`:

```python
def __init__(self, ..., allow_quit: bool = False,
             quit_exits_app: bool = False, **kwargs) -> None:
    ...
    self._allow_quit = allow_quit
    self._quit_exits_app = quit_exits_app

@property
def _quit_enabled(self) -> bool:
    """`q` is active (and advertised) under either opt-in."""
    return self._allow_quit or self._quit_exits_app

def check_action(self, action, parameters):
    if action == "quit":
        return True if self._quit_enabled else None
    return True

@property
def _hint_text(self) -> str:
    return self._HINT + self._QUIT_HINT if self._quit_enabled else self._HINT

def action_quit(self) -> None:
    if self._quit_exits_app:
        self.app.exit()          # MANAGER CONTROL: true direct quit
    else:
        self.dismiss(None)       # GAME MODE: unchanged cancel-quit path
```

Then in `setup_flow.py::_select_control`, construct the control `ChoiceScreen` with
`quit_exits_app=True` (leave `allow_quit` at its default `False`):

```python
ChoiceScreen(
    title="⚾ MANAGER CONTROL",
    prompt="Who manages the dugouts?",
    choices=_CONTROL_CHOICES,
    default_id="home_ai",
    quit_exits_app=True,
),
```

**Invariants this preserves (must all hold):**

- **GAME MODE is byte-for-byte unchanged.** It passes `allow_quit=True` and does
  *not* pass `quit_exits_app`, so `_quit_exits_app` is `False` → `action_quit`
  still calls `self.dismiss(None)` → same exit path as today. `_quit_enabled` is
  `True` (via `allow_quit`), so its hint and `check_action` gating are identical.
- **A plain `ChoiceScreen`** (neither flag) is entirely unaffected: `q` gated off,
  hint has no quit affordance — same as today.
- **`allow_quit` semantics are not overloaded.** `dismiss(None)` vs `app.exit()` is
  a genuinely different action, so it earns its own flag rather than a magic value
  of `allow_quit`.

### 3. Discoverability — advertise `q` in the setup screens' hint lines

The player filed this because they didn't know how to get out, so the fix must be
visible. Append a quit affordance matching the existing markup (`[#d4a843]key[/]
label`, joined by three spaces) — `   [#d4a843]q[/] quit`:

- **`TeamSelectScreen._HINT`** — currently
  `[#d4a843]↑/↓[/] navigate   [#d4a843]Enter[/] select   [#d4a843]Esc[/] back`
  → append `   [#d4a843]q[/] quit`.
- **`PitcherSelectScreen._HINT`** — currently ends `[#d4a843]Esc[/] use default
  [#d4a843]★[/]` → append `   [#d4a843]q[/] quit`.
- **`LineupEditScreen`** — append `   [#d4a843]q[/] quit` to its **main controls**
  hint `_HINT` (the two-line one shown when the bench is closed; append to the end
  of the second line). **Do not** alter `_BENCH_HINT`, the hint shown while the
  bench substitution list is open.
- **MANAGER CONTROL** — its hint is **automatic**: `_hint_text` now returns
  `_HINT + _QUIT_HINT` because `_quit_enabled` is `True`. No manual hint edit; do
  not hard-code a control-screen hint. (This is a nice side effect of option (b):
  MANAGER CONTROL both quits *and* advertises it, closing the discoverability gap
  the old spec had to accept.)

### Landmines for the implementer

- **`q` is unused on all three list screens** — verified against origin/main. Each
  new binding is local to its screen, so it shadows nothing elsewhere; the test in
  §Testing that asserts `q` *is* present will catch accidental removal.
- **Do not touch `BaseballSimApp` / `src/tui/app.py`.** No app-level binding. The
  whole point of the re-spec is that the app-level approach does not work.
- **Do not change GAME MODE.** Don't pass `quit_exits_app` to the GAME MODE
  `ChoiceScreen`, and don't change `_select_mode`. GAME MODE keeps `allow_quit=True`
  and the `dismiss(None)` cancel-quit path.
- **`LineupEditScreen` hint is two lines and swaps to `_BENCH_HINT` at runtime.**
  Append `q` only to `_HINT`; the bench hint must read exactly as before.
- **`GameScreen.action_quit` also stops a fast-forward timer** — that path is
  unrelated and unchanged. The new setup-screen `action_quit`s run no timer, so a
  bare `self.app.exit()` is correct for them (mirror `GameScreen` minus the timer).
- Keep the binding action name `"quit"` / method `action_quit` consistent so
  Textual resolves it against each screen's namespace.

## Open questions

None. The MANAGER CONTROL mechanism (the one decision the implementer left to the
Planner) is resolved above as option (b). The *quit-app vs return-to-menu* question
is settled by the issue title ("global quit key") and the `GameScreen` convention
(`q` = exit app).

## Testing

No CI — the local `pytest` suite is the gate. Use the repo's DB-free house idioms
(`tests/test_choice_screen.py` for `SimpleNamespace`-as-`self` + captured
`dismiss`/`exit` and a `FakeApp` recording `push_screen`; in-process `Pilot` via
`app.run_test()` only where a running app is needed). The full-app Pilot path needs
the Lahman DB (gitignored, absent in a fresh worktree) because
`BaseballSimApp.on_mount` opens `LahmanRepository`; the tests below are all
**DB-free** and are sufficient for the definition of done.

Add `tests/test_global_quit.py` covering:

1. **Each list screen exits the app.** For `TeamSelectScreen`,
   `PitcherSelectScreen`, and `LineupEditScreen`: drive `action_quit` with a
   `SimpleNamespace`/stub `self` whose `.app` captures `exit()`; assert `exit` was
   called once with no args. (Mirror `test_choice_screen`'s `SimpleNamespace`-as-`self`
   idiom — bind the unbound `Screen.action_quit` to a stub `self`; do **not**
   construct the real screens if that needs a DB/repo.)
2. **Each list screen binds `q → quit`.** Assert `("q", "quit")` is among each of
   `TeamSelectScreen.BINDINGS`, `PitcherSelectScreen.BINDINGS`,
   `LineupEditScreen.BINDINGS` (read `.key` / `.action` off the `Binding`s). This
   is the affordance that must not silently regress. **Note this inverts the old
   spec's test** (which asserted `q` was *absent* to prove app fall-through);
   fall-through is dead, so `q` must now be *present* on each screen.
3. **`ChoiceScreen` true-exit opt-in.**
   - With `quit_exits_app=True`: `action_quit` calls `self.app.exit()` (once, no
     args) and does **not** call `dismiss`; `check_action("quit", ())` returns
     `True`; `_hint_text` contains the quit affordance.
   - With `allow_quit=True` (GAME MODE, default `quit_exits_app=False`):
     `action_quit` calls `self.dismiss(None)` and does **not** call `app.exit`
     (regression guard on GAME MODE); `check_action("quit", ())` is `True`.
   - Plain `ChoiceScreen` (neither flag): `check_action("quit", ())` is `None` and
     `_hint_text` has no quit affordance.
4. **`_select_control` opts into true-exit.** Drive `SetupFlow._select_control`
   over the `FakeApp` (as `test_choice_screen` does) and assert the pushed
   `ChoiceScreen` has `_quit_exits_app is True` and `_allow_quit is False`. Assert
   `_select_mode`'s pushed screen still has `_allow_quit is True` and
   `_quit_exits_app is False` (GAME MODE untouched).
5. **Per-screen binding works under a modal, live (Pilot, DB-free).** Build a
   minimal `App` subclass with **no** app-level `q` binding, push a bare
   `ModalScreen` that binds its own `Binding("q", "quit")` + `action_quit` setting a
   flag, containing a focused `OptionList`; `await pilot.press("q")`; assert the
   flag fired — proving the per-screen binding resolves inside the modal chain. (A
   companion assertion that a modal *without* a `q` binding does **not** reach an
   app-level `q` binding is optional but nails down why the app-level design was
   dropped.)
6. **Hints advertise quit.** Assert each of `TeamSelectScreen._HINT`,
   `PitcherSelectScreen._HINT`, and `LineupEditScreen._HINT` contains a `q`/quit
   affordance and still contains its original navigate/select text; assert
   `LineupEditScreen._BENCH_HINT` is unchanged (no `q`). For MANAGER CONTROL, assert
   a `ChoiceScreen(..., quit_exits_app=True)._hint_text` contains the quit
   affordance (the auto-hint path).

## Definition of done

- Pressing `q` on **any** pregame setup screen — MANAGER CONTROL, AWAY/HOME TEAM,
  STARTING PITCHER, LINEUP EDIT — exits the app cleanly.
- The GAME MODE menu's `q` and every existing screen-level `q` (`GameScreen`,
  `SeasonHubScreen`, `BoxScoreScreen`, `SeriesStatusScreen`) behave exactly as
  before; `SeasonHubScreen`'s unsaved-season save prompt is **not** bypassed.
- No other key's behavior changes anywhere (`Esc`/`Enter` unchanged); `src/tui/app.py`
  is untouched.
- `TeamSelectScreen`, `PitcherSelectScreen`, `LineupEditScreen`, and MANAGER
  CONTROL all advertise `q` to quit; `LineupEditScreen`'s bench-substitution hint
  is unchanged.
- New `tests/test_global_quit.py` passes and the full `pytest` suite is green.

## Issue breakdown

| Issue | Title | Depends on | Risk |
| --- | --- | --- | --- |
| FRE-103 | Add per-screen `q → quit` to the pregame setup screens (incl. MANAGER CONTROL); advertise it | — | — |
