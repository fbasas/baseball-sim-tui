---
status: complete
phase: 04-substitutions-advanced-mechanics
source: [04-01-SUMMARY.md, 04-02-SUMMARY.md, 04-03-SUMMARY.md, 04-04-SUMMARY.md, 04-05-SUMMARY.md]
started: 2026-01-29T16:00:00Z
updated: 2026-01-31T00:00:00Z
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
result: pass
notes: "Fixed - was too narrow due to ModalScreen layout:vertical default. Fixed with layout:horizontal + 50vw width."

### 4. Available Pitchers Listed in Menu
expected: The substitution menu shows a list of available relief pitchers with their stats. Used pitchers should NOT appear (no re-entry rule).
result: pass

### 5. Make Pitching Change
expected: Select a pitcher from the list. The pitching change executes: fatigue resets to 0%, new pitcher name appears in fatigue widget, play log shows substitution message.
result: issue
reported: "TypeError: SubstitutionRecord.__init__() got an unexpected keyword argument 'player_out'"
severity: blocker

### 6. Removed Pitcher Cannot Re-Enter
expected: After making a pitching change, press 'S' again. The previously-removed starting pitcher should NOT be available in the list.
result: skipped
reason: blocked by test 5

### 7. Complete Game with Substitutions
expected: Play through a complete game making at least one pitching change. Game ends normally with final score displayed.
result: skipped
reason: blocked by test 5

## Summary

total: 7
passed: 4
issues: 1
pending: 0
skipped: 2

## Gaps

- truth: "Substitution menu modal appears at readable width showing available pitchers"
  status: resolved
  reason: "User reported: modal appears but is too narrow"
  severity: minor
  test: 3
  root_cause: "ModalScreen default CSS uses layout:vertical which constrained child width. Fixed by overriding to layout:horizontal and using viewport units (50vw)."
  resolution: "commit 21fd236 - fix(ui): properly size SubstitutionMenu modal"

- truth: "Pitching change executes successfully: fatigue resets to 0%, new pitcher name appears in fatigue widget, play log shows substitution message"
  status: resolved
  reason: "User reported: TypeError: SubstitutionRecord.__init__() got an unexpected keyword argument 'player_out'"
  severity: blocker
  test: 5
  root_cause: "game_screen.py used wrong parameter names (player_out, player_in) but SubstitutionRecord expects (player_out_id, player_in_id)"
  artifacts:
    - path: "src/tui/screens/game_screen.py"
      issue: "Wrong parameter names in SubstitutionRecord constructor calls (lines 607-608, 657-658)"
  missing: []
  resolution: "Renamed player_out to player_out_id and player_in to player_in_id"

## Future Enhancements

- Keyboard navigation with arrow keys throughout the app (noted during UAT)
