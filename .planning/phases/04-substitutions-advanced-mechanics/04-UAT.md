---
status: diagnosed
phase: 04-substitutions-advanced-mechanics
source: [04-01-SUMMARY.md, 04-02-SUMMARY.md, 04-03-SUMMARY.md, 04-04-SUMMARY.md, 04-05-SUMMARY.md]
started: 2026-01-29T16:00:00Z
updated: 2026-01-29T16:15:00Z
---

## Current Test

[testing complete]

## Tests

### 1. Fatigue Display Shows Pitcher Name and Percentage
expected: Run `python -m src.tui.app`. The game dashboard shows a fatigue widget displaying the current pitcher's name and fatigue percentage (starts at 0%).
result: pass

### 2. Fatigue Increases After At-Bats
expected: Advance a few plays (press Space). The fatigue percentage increases as the pitcher faces more batters. Color changes: green (<30%), yellow (30-60%), red (>60%).
result: pass

### 3. Substitution Menu Opens with S Key
expected: Press 'S' during gameplay. A substitution menu modal appears showing available pitchers from the bullpen.
result: issue
reported: "modal appears but is too narrow, that'll be an item to tackle once we finish going through the rest of the verification"
severity: minor

### 4. Available Pitchers Listed in Menu
expected: The substitution menu shows a list of available relief pitchers with their stats. Used pitchers should NOT appear (no re-entry rule).
result: skipped
reason: blocked by narrow substitution modal (test 3 issue)

### 5. Make Pitching Change
expected: Select a pitcher from the list. The pitching change executes: fatigue resets to 0%, new pitcher name appears in fatigue widget, play log shows substitution message.
result: skipped
reason: blocked by narrow substitution modal (test 3 issue)

### 6. Removed Pitcher Cannot Re-Enter
expected: After making a pitching change, press 'S' again. The previously-removed starting pitcher should NOT be available in the list.
result: skipped
reason: blocked by narrow substitution modal (test 3 issue)

### 7. Complete Game with Substitutions
expected: Play through a complete game making at least one pitching change. Game ends normally with final score displayed.
result: skipped
reason: blocked by narrow substitution modal (test 3 issue)

## Summary

total: 7
passed: 2
issues: 1
pending: 0
skipped: 4

## Gaps

- truth: "Substitution menu modal appears at readable width showing available pitchers"
  status: failed
  reason: "User reported: modal appears but is too narrow"
  severity: minor
  test: 3
  root_cause: "SubstitutionMenu.DEFAULT_CSS only sets align:center middle. Width rules are in game.tcss but ModalScreens don't inherit App CSS_PATH styles. EndGameMenu works because it has all CSS in DEFAULT_CSS."
  artifacts:
    - path: "src/tui/screens/substitution_menu.py"
      issue: "DEFAULT_CSS missing width/height rules for Vertical container"
    - path: "src/tui/styles/game.tcss"
      issue: "SubstitutionMenu CSS rules here are never loaded by ModalScreen"
  missing:
    - "Move SubstitutionMenu CSS from game.tcss into SubstitutionMenu.DEFAULT_CSS"
  debug_session: ""
