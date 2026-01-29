---
status: diagnosed
phase: 01-data-foundation-simulation-core
source: [01-01-SUMMARY.md, 01-02-SUMMARY.md, 01-03-SUMMARY.md, 01-04-SUMMARY.md, 01-05-SUMMARY.md]
started: 2026-01-28T23:00:00Z
updated: 2026-01-29T00:30:00Z
---

## Current Test

[testing complete]

## Tests

### 1. Load Team Roster from Lahman Database
expected: Repository can load any historical team roster with player info, stats, and computed properties (singles, plate appearances, innings pitched)
result: issue
reported: "Can't test - no database. Downloaded file gave 'file is not a database' error. Want to add scope to build the SQLite database ourselves using the latest Lahman data."
severity: major

### 2. Odds-Ratio Probability Calculation
expected: Given batter stats, pitcher stats, and league averages, the odds-ratio formula produces reasonable matchup probabilities. Elite pitchers should dominate weak hitters more than naive averaging would suggest.
result: pass

### 3. Simulate Single At-Bat
expected: The simulation engine can take a batter and pitcher and produce a realistic at-bat outcome (strikeout, walk, single, double, triple, home run, or various outs) with reproducible results when using the same seed.
result: pass

### 4. Runner Advancement on Hits
expected: When a hit occurs with runners on base, runners advance appropriately (e.g., runner on second scores on a single approximately 60% of the time, home runs clear all bases).
result: pass

### 5. Statistical Validation - Batting Average
expected: Simulating many at-bats for a hitter produces a batting average within 10% of their historical average (e.g., a .300 hitter simulates between .270-.330 over 5000 at-bats).
result: pass

### 6. Audit Trail for Reproducibility
expected: The RNG wrapper captures all random decisions, enabling exact replay of any simulation. Same seed produces identical outcomes every time.
result: pass

## Summary

total: 6
passed: 5
issues: 1
pending: 0
skipped: 0

## Gaps

- truth: "Repository can load any historical team roster with player info, stats, and computed properties"
  status: failed
  reason: "User reported: Can't test - no database. Downloaded file gave 'file is not a database' error. Want to add scope to build the SQLite database ourselves using the latest Lahman data."
  severity: major
  test: 1
  root_cause: "Project relies on third-party pre-built SQLite (jknecht/baseball-archive-sqlite) which is outdated (2022 data) and download unreliable. Original Chadwick Bureau CSV source returns 404. SABR is now the authoritative source with 1871-2025 data."
  artifacts:
    - path: "data/.gitkeep"
      issue: "Contains outdated download instructions pointing to third-party SQLite"
    - path: "src/data/lahman.py"
      issue: "Expects SQLite at data/lahman.sqlite but no build script exists"
  missing:
    - "scripts/build_lahman_db.py - Download SABR CSVs and convert to SQLite"
    - "Update data/.gitkeep with SABR download URL and build instructions"
  debug_session: ".planning/debug/lahman-sqlite-build.md"
