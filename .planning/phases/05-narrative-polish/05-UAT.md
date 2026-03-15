---
status: complete
phase: 05-narrative-polish
source: 05-01-SUMMARY.md, 05-02-SUMMARY.md, 05-03-SUMMARY.md, 05-04-SUMMARY.md
started: 2026-03-14T22:00:00Z
updated: 2026-03-14T22:30:00Z
---

## Current Test

[testing complete]

## Tests

### 1. Pitcher Selection Modal
expected: On app launch, two pitcher selection modals appear sequentially (away team first, then home team). Each shows available pitchers sorted by games started with the default pre-highlighted.
result: pass

### 2. Historically Accurate Lineup Positions
expected: After pitcher selection, the 1927 Yankees lineup card shows Ruth at RF and Gehrig at 1B.
result: pass

### 3. Baseball Visual Theme
expected: Dark green field background, cream lineup cards with brown borders, gold-bordered situation panel, dark brown footer/header.
result: pass

### 4. Base Diamond Display
expected: ASCII base diamond in situation panel with bold yellow highlighted occupied bases and dimmed empty bases.
result: pass

### 5. Footer Key Bindings
expected: Footer bar at bottom shows key bindings (Space, S, F, Q).
result: issue
reported: "No footer appears with described keybindings"
severity: major

### 6. Narrative Play-by-Play Text
expected: Broadcaster-style narrative text instead of raw outcome text.
result: issue
reported: "No narrative text shows up at all"
severity: blocker

### 7. Home Run Highlighting
expected: Home run narrative text appears in bold yellow in play log.
result: issue
reported: "The score field blinks yellow, but no play log"
severity: blocker

### 8. Error Highlighting
expected: Error narrative text appears in bold red in play log.
result: issue
reported: "no play log"
severity: blocker

### 9. Narrative Variety
expected: Multiple at-bats with same outcome show varied narrative text.
result: issue
reported: "no play log or narrative text"
severity: blocker

### 10. Inning Transition Summary
expected: Italic summary text at half-inning end before next inning divider.
result: issue
reported: "no summary text"
severity: major

### 11. Substitution Narrative
expected: Dramatic narrative for pitching changes instead of generic text.
result: issue
reported: "no narrative"
severity: major

### 12. Full-Screen Box Score at Game End
expected: Full-screen box score with newspaper-format linescore and R/H/E totals.
result: pass

### 13. Box Score Batting Stats
expected: Batting lines for both teams with AB, R, H, RBI, BB, K and TOTALS row.
result: pass

### 14. Box Score Pitching Stats
expected: Pitching lines with IP, H, R, ER, BB, K and W/L markers for both teams.
result: issue
reported: "pitching lines appeared for the Yankees, but not for the Cubs"
severity: major

### 15. Box Score Navigation
expected: Replay, New Game, Quit buttons work (R/N/Q keyboard shortcuts).
result: pass

## Summary

total: 15
passed: 7
issues: 8
pending: 0
skipped: 0

## Gaps

- truth: "Footer bar shows key bindings (Space, S, F, Q)"
  status: failed
  reason: "User reported: No footer appears with described keybindings"
  severity: major
  test: 5
  root_cause: ""
  artifacts: []
  missing: []
  debug_session: ""

- truth: "Play log renders broadcaster-style narrative text for every at-bat"
  status: failed
  reason: "User reported: No narrative text shows up at all / no play log"
  severity: blocker
  test: 6
  root_cause: ""
  artifacts: []
  missing: []
  debug_session: ""

- truth: "Home runs display in bold yellow in play log"
  status: failed
  reason: "User reported: Score blinks yellow but no play log"
  severity: blocker
  test: 7
  root_cause: ""
  artifacts: []
  missing: []
  debug_session: ""

- truth: "Pitching stats display for both teams in box score"
  status: failed
  reason: "User reported: pitching lines appeared for the Yankees, but not for the Cubs"
  severity: major
  test: 14
  root_cause: ""
  artifacts: []
  missing: []
  debug_session: ""
