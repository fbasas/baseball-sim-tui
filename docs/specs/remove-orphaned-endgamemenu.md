# Spec: Remove orphaned `EndGameMenu` screen

**Source issue:** FRE-7 · **Date:** 2026-07-06 · **Status:** active

## Goal

Delete the dead `EndGameMenu` modal screen and every reference to it, leaving the
TUI codebase free of the orphan that the v1.0 milestone audit flagged. The
end-of-game flow already runs entirely through `BoxScoreScreen`; `EndGameMenu`
is unreachable code that only adds confusion and maintenance surface. When done,
`EndGameMenu` and its CSS no longer exist anywhere in the repo and the full test
suite still passes.

## Non-goals

- **Do NOT remove `simulate_game()` / `GameResult`** (`src/game/engine.py`,
  exported from `src/game/__init__.py`). The FRE-7 description asks to "check for
  related orphans" and notes the v1.0 audit flagged these as "TUI-orphaned
  (test-only)." Verified against `origin/main` @ `0883c52`, they are **not** dead
  code:
  - Exercised by `tests/test_game_loop.py` (`TestSimulateGame` / `TestGameResult`,
    ~8 tests).
  - Documented as a legitimate **batch/headless** game path in
    `docs/specs/save-load-game-state.md:79` ("The batch/headless `simulate_game`
    and AI-vs-AI `play_ai_game` paths keep their own `play_log`/accumulators…"),
    a spec written *after* the v1.0 audit.

  "Test-only from the TUI's perspective" ≠ dead: this is a deliberately retained
  headless entry point with real coverage. The newer save-load spec supersedes
  the older audit note. Removing it would delete tests and a documented
  capability for no benefit. If Fred later decides the headless path isn't wanted,
  that is a separate, explicit decision — file a new issue; it is out of scope here.
- No behavior change to `BoxScoreScreen` or any live end-of-game flow.
- No refactor of unrelated screens or CSS beyond the `EndGameMenu`/`#menu` blocks.

## Design

`EndGameMenu` is reachable from nothing at runtime. Verified references on
`origin/main` @ `0883c52` (grep for `EndGameMenu` / `end_game_menu` / `#menu`
across all tracked files):

| Location | What it is | Action |
| --- | --- | --- |
| `src/tui/screens/end_game_menu.py` | the module (class `EndGameMenu(ModalScreen[str])`) | **delete the file** |
| `src/tui/screens/__init__.py` | package docstring line, `from .end_game_menu import EndGameMenu`, and `"EndGameMenu"` in `__all__` | remove all three |
| `src/tui/styles/game.tcss` | `EndGameMenu { align: center middle; }` block **and** the `#menu` + `#menu Button` blocks | remove all three blocks |
| `docs/specs/save-load-game-state.md` (~line 150) | note: "`EndGameMenu` (`end_game_menu.py`) is **dead code** — do not use it (its removal is tracked by FRE-7)." | update to record that it has now been removed (see below) |

Notes for the implementer:

- **`#menu` is exclusive to `EndGameMenu`.** The only `id="menu"` in the codebase
  is `end_game_menu.py:80` (`with Vertical(id="menu")`). Confirm with
  `git grep -nE '#menu|id="menu"'` before deleting the `#menu` / `#menu Button`
  CSS blocks — grep must show no remaining producer of that id once the module is
  gone. (On `origin/main` today it shows only `end_game_menu.py` and `game.tcss`.)
- **Nothing imports `EndGameMenu` from the package.** No test references it, and
  no screen or app module imports it — so removing the export cannot break an
  `import *` or an `__all__` consumer. Re-verify with
  `git grep -nE 'EndGameMenu|end_game_menu'` after your edits: the only remaining
  hits should be inside this spec and your updated save-load note.
- **Docstring cleanup in `__init__.py`.** The module docstring's "Screens:" list
  includes an `EndGameMenu:` line — remove that line too so the docstring stays
  accurate.
- **Update the save-load spec note** rather than deleting it, so the record stays
  coherent. Replace the "dead code … removal is tracked by FRE-7" wording with a
  past-tense note, e.g.: "End-of-game screen is `BoxScoreScreen` (`r`/`n`/`q`).
  (`EndGameMenu` was removed in FRE-7.)" Keep it a single bullet; do not restructure
  the surrounding list.

## Definition of done (implementer)

1. `src/tui/screens/end_game_menu.py` deleted.
2. `src/tui/screens/__init__.py`: import, `__all__` entry, and docstring line for
   `EndGameMenu` all removed; file still imports cleanly.
3. `src/tui/styles/game.tcss`: `EndGameMenu`, `#menu`, and `#menu Button` blocks
   removed; no other CSS touched.
4. `docs/specs/save-load-game-state.md` note updated to past tense as above.
5. `git grep -nE 'EndGameMenu|end_game_menu|#menu|id="menu"'` returns **no**
   hits in `src/` (only this spec / the updated save-load note may mention the
   name historically).
6. `python -c "import src.tui.screens"` succeeds and the app still launches
   (`./play.sh` reaches the mode `ChoiceScreen` without a CSS/import error).
7. Full test suite green: `pytest` (from repo root; `testpaths = ["tests"]`).

## Test note

This is a pure dead-code deletion; there is no `EndGameMenu` test to remove or
add (grep confirms zero test references). The existing suite plus a clean
`import src.tui.screens` and an app launch are the regression guard. The PR body
should state this under the "why no test changes" requirement in FACTORY.md.

## Open questions

None. The one judgment call (`simulate_game`/`GameResult`) is resolved in
**Non-goals** above with a documented rationale; no human checkpoint is required.

## Issue breakdown

| Issue | Title | Depends on | Risk |
| --- | --- | --- | --- |
| FRE-7 (repurposed as the implementer issue) | Remove orphaned `EndGameMenu` screen | — | — |
