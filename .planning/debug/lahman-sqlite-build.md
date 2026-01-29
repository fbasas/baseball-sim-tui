---
status: diagnosed
trigger: "User cannot test roster loading because the pre-built Lahman SQLite database download failed ('file is not a database' error). User wants to add scope to build the SQLite database from the latest Lahman CSV data files instead of relying on a third-party pre-built database."
created: 2026-01-28T00:00:00Z
updated: 2026-01-29T06:10:00Z
symptoms_prefilled: true
goal: find_root_cause_only
---

## Current Focus

hypothesis: CONFIRMED - Project relies on third-party SQLite that is outdated (2022 data) and original Chadwick Bureau CSV source has moved
test: Verified database source status and identified required tables
expecting: N/A - diagnosis complete
next_action: Return root cause analysis with recommended approach

## Symptoms

expected: User can download Lahman SQLite database and test roster loading functionality
actual: Download produces "file is not a database" error - corrupted or invalid file
errors: "file is not a database" when trying to use the downloaded SQLite
reproduction: Attempt to download/use the pre-built Lahman SQLite database
started: Third-party pre-built database is unreliable or unavailable

## Eliminated

## Evidence

- timestamp: 2026-01-29T06:05:00Z
  checked: src/data/lahman.py - LahmanRepository implementation
  found: Repository queries 4 tables: People, Batting, Pitching, Teams
  implication: Any CSV-to-SQLite solution must include these 4 tables

- timestamp: 2026-01-29T06:05:30Z
  checked: Required columns per table from SQL queries
  found: |
    - People: playerID, nameFirst, nameLast, bats, throws
    - Batting: playerID, yearID, teamID, G, AB, R, H, 2B, 3B, HR, RBI, SB, CS, BB, SO, HBP, SF, SH, GIDP
    - Pitching: playerID, yearID, teamID, G, GS, W, L, IPouts, H, R, ER, HR, BB, SO, HBP, BFP, WP
    - Teams: yearID, lgID, teamID, name, BPF, PPF
  implication: CSV files for these tables must map to exactly these column names

- timestamp: 2026-01-29T06:06:00Z
  checked: data/.gitkeep file
  found: Points users to https://github.com/jknecht/baseball-archive-sqlite
  implication: Current setup relies on third-party pre-built SQLite

- timestamp: 2026-01-29T06:07:00Z
  checked: chadwickbureau/baseballdatabank GitHub repository
  found: Returns HTTP 404 - repository no longer exists or has moved
  implication: Original CSV source is unavailable at documented location

- timestamp: 2026-01-29T06:08:00Z
  checked: jknecht/baseball-archive-sqlite GitHub repository
  found: |
    - Exists (HTTP 200)
    - Last updated: 2023-04-02
    - Latest release: 2022 data (lahman_1871-2022.sqlite)
    - Release URL does work (302 redirect to download)
  implication: Third-party SQLite is accessible but outdated (3+ years old)

- timestamp: 2026-01-29T06:08:30Z
  checked: Official Lahman Database source
  found: |
    - SABR (sabr.org) is now official maintainer
    - Latest version: 1871-2025 data with Negro Leagues
    - Download at: https://sabr.org/lahman-database/
    - CSV format available
  implication: SABR is authoritative source for up-to-date Lahman data

## Resolution

root_cause: |
  1. The project references https://github.com/jknecht/baseball-archive-sqlite for pre-built SQLite
  2. This third-party repo is outdated (last updated April 2023 with 2022 data)
  3. The original CSV source (chadwickbureau/baseballdatabank) returns 404 - no longer available
  4. The "file is not a database" error indicates corrupted download or network issue
  5. SABR (sabr.org/lahman-database) is now the official source with up-to-date data (2025)
  6. The project has no capability to build SQLite from CSV source files
fix: |
  Recommended approach:
  1. Create scripts/build_lahman_db.py to convert SABR CSV files to SQLite
  2. Update data/.gitkeep with instructions pointing to SABR download
  3. Add pandas as dependency for CSV loading (or use stdlib csv module)
  4. Script should: download CSVs, create SQLite with correct schema, populate tables
verification:
files_changed: []
