# Spec: Quit from the main (game-mode) menu

**Source issue:** FRE-98 · **Date:** 2026-07-10 · **Status:** active

## Goal

Give the player a way to quit the app from the main menu with the `q` key. The
"main menu" is the **GAME MODE** `ChoiceScreen` that `SetupFlow._select_mode`
pushes at startup (Single game / Best-of-N series / Season / Load saved game).
Today there is no way to exit from it: Esc picks the default ("single game") and
`ChoiceScreen` never dismisses `None`, so the app's `on_cancel=self.exit` path is
unreachable. Pressing `q` at the main menu should exit the app cleanly.

## Non-goals

- **No new quit affordance anywhere else.** Only the game-mode menu gets `q`. The
  manager-control question (`_select_control`) uses the *same* `ChoiceScreen` class
  but must keep its current behavior — no `q` binding, no visible quit hint.
- Do **not** change the Esc-picks-default or Enter-selects behavior of any
  `ChoiceScreen`. `q` is an *additional* key on the mode menu, not a replacement.
- No confirmation dialog on quit. The main menu has no unsaved state to protect;
  quitting is immediate. (In-game and hub quit-with-save prompts are unrelated and
  untouched.)
- No changes to season/series/in-game screens — those already have their own quit
  bindings (`season_hub_screen.py`, `game_screen.py`, etc.).

## Design

`ChoiceScreen` (`src/tui/screens/choice_screen.py`) is a generic modal reused for
both the game-mode menu and the manager-control question. Make the quit key
**opt-in per instance** so only the mode menu gets it.

**1. Opt-in constructor flag.** Add `allow_quit: bool = False` to
`ChoiceScreen.__init__`, stored as `self._allow_quit`.

**2. Declare the binding, gate it with `check_action`.** Add
`Binding("q", "quit", "Quit")` to the class `BINDINGS`, and gate it with a
`check_action` override — the exact pattern already used in
`src/tui/screens/season_hub_screen.py` (see its `check_action`, which returns
`None` to hide *and* disable a binding and `True` to enable it):

```python
def check_action(self, action: str, parameters: tuple) -> Optional[bool]:
    if action == "quit":
        return True if self._allow_quit else None
    return True
```

Returning `None` when `allow_quit` is False both disables the key and keeps it out
of any footer (Textual convention), so the control question is unaffected.

**3. The action dismisses `None`, reusing the existing cancel path.**

```python
def action_quit(self) -> None:
    self.dismiss(None)
```

For the mode menu, dismissing `None` flows into `on_mode_chosen(None)` →
`self._on_cancel()` → the app's `on_cancel=self.exit`, which exits Textual. Do
**not** call `self.app.exit()` directly — routing through `dismiss(None)` keeps
`ChoiceScreen` generic and reuses the wiring the flow already owns. (The control
question's `None` path calls `_select_mode` and is never reached because `q` is
gated off there.)

**4. Show the affordance in the hint line.** `ChoiceScreen` is a `ModalScreen`
with **no Footer** — the only visible key hint is the static `#choice-hint`
`Label` (`_HINT`). Because it is static, it must be made conditional so the mode
menu shows the quit hint and other `ChoiceScreen`s do not. Build the hint in
`compose` from `self._allow_quit`, e.g. append
`"   [#d4a843]q[/] quit"` to the existing hint string only when `allow_quit` is
True. Keep the existing markup style (`↑/↓ navigate   Enter select   Esc default`).

**5. Enable it for the mode menu only.** In `src/tui/setup_flow.py`,
`_select_mode`, pass `allow_quit=True` to the `ChoiceScreen(...)` constructor. Do
**not** touch `_select_control`.

### Notes / landmines for the implementer

- `OptionList` (the widget inside the modal) does **not** do type-ahead selection
  in Textual 7.4, so a `q` keypress bubbles up to the screen binding — no conflict
  with the option list. The existing `enter` binding is `priority=True`; leave it.
- Textual version is pinned `>=0.85.0`; installed is **7.4.0**. `check_action`
  returning `None`-to-hide is stable across this range and is already relied on in
  this repo.
- There is a **local-only** `CLAUDE.md` in the checkout that is not on
  `origin/main` — ignore it; work from `origin/main`.

## Testing

This project has **no CI** — the local pytest suite is the gate — and the Textual
TUI does **not** render under tmux on the dev host, so **do not** drive this via a
pty/tmux. Use the repo's established **DB-free, Pilot-free "mock-`self`" idiom**
(see `tests/test_save_select_screen.py` for the `SimpleNamespace`-as-`self` +
captured-`dismiss` pattern, and `tests/test_season_setup_flow.py` for the `FakeApp`
that records `push_screen(screen, callback)`). If any in-process `Pilot`
(`app.run_test()`) test is added it must run in-process only — never under tmux.

Add `tests/test_choice_screen.py` covering the definition of done:

- `action_quit` calls `dismiss(None)` (mock-`self` + captured `dismiss`).
- `check_action("quit", ())` returns `True` when `allow_quit=True` and `None` when
  `allow_quit=False`; `check_action` returns `True` for a non-quit action in both
  cases.
- The `#choice-hint` text includes a `q`/quit affordance when `allow_quit=True`
  and does **not** when `allow_quit=False` (assert on the string built in
  `compose`, constructing a real `ChoiceScreen(...)` — no app needed to read the
  hint string).
- `SetupFlow._select_mode` pushes a `ChoiceScreen` with `_allow_quit is True`,
  and `_select_control` pushes one with `_allow_quit is False` (use the `FakeApp`
  idiom; drive `_select_control` by invoking the mode callback with a non-branching
  id such as `"single"`).

## Definition of done

- Pressing `q` on the GAME MODE (main) menu exits the app cleanly (via
  `dismiss(None)` → `on_cancel` → `app.exit`).
- `q` is inert and not shown on the manager-control `ChoiceScreen` and any other
  `ChoiceScreen` constructed without `allow_quit=True`.
- The mode menu's hint line advertises `q` to quit; other `ChoiceScreen`s' hint is
  unchanged.
- Esc-picks-default and Enter-selects behavior is unchanged on every `ChoiceScreen`.
- New tests in `tests/test_choice_screen.py` pass and the full `pytest` suite is
  green.

## Issue breakdown

| Issue | Title | Depends on | Risk |
| --- | --- | --- | --- |
| FRE-98-a | Add opt-in `q → quit` binding to ChoiceScreen; enable on the main menu | — | — |
