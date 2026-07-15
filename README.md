# ⚾ Baseball Time Machine

A terminal baseball simulator: pick any team from any era and play — single
games, best-of series, or a full season — with rosters, stats, and park factors
drawn from real historical data. Games are simulated by the engine, so the
matchups are history but the outcomes are freshly played.

## Running

```sh
./play.sh
```

## Data setup

The app reads a local SQLite database at `data/lahman.sqlite`. Two build
scripts populate it:

```sh
# Rosters, stats, park factors, league/division (Lahman database).
python scripts/build_lahman_db.py

# Day-by-day historical schedules (Retrosheet), for historical season mode.
python scripts/build_schedule_db.py --years 1927,1969,2016,2020
```

`build_schedule_db.py` adds a `Schedules` table to the same `lahman.sqlite`
file; re-running for a year is idempotent (it clears and reinserts that year).

> **Note:** the Lahman `Teams` import now includes the `teamIDretro` column —
> the key that joins Retrosheet schedule team ids to Lahman rosters/stats. A
> `lahman.sqlite` built before this column was added **must be rebuilt** with
> `build_lahman_db.py` for historical season mode to resolve teams.

## Data sources & attribution

**Lahman Baseball Database** — player, team, and season statistics.
Maintained by SABR (Society for American Baseball Research):
<https://sabr.org/lahman-database>.

**Retrosheet** — historical schedule data (the day-by-day slate of games).
The following notice is required by Retrosheet and also appears in-product:

> The information used here was obtained free of charge from and is
> copyrighted by Retrosheet. Interested parties may contact Retrosheet at
> "www.retrosheet.org".
