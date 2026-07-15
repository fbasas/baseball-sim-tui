# 1. Ingest Retrosheet schedule data into a `Schedules` table, joined to Lahman via `teamIDretro`

**Date:** 2026-07-15 · **Issue:** FRE-116 · **Status:** accepted

## Context

Historical season mode ([spec](../specs/historical-season-mode.md)) replays a
real year's day-by-day slate of matchups. The Lahman database
(`data/lahman.sqlite`) carries rosters, stats, park factors, and league/division
— but **no game-level schedule**. The schedule lives in Retrosheet, published as
one ZIP per year. Part 1 is the data foundation: bring that schedule into the
local DB, expose it through the repository, and establish the Retrosheet↔Lahman
team-id join. This ADR is the **research-spike writeup** required by the issue —
it records the file format *as actually observed* (not just as documented) and
an **empirical characterization** of schedule structure across eras, produced by
downloading and parsing a real sample. Those findings set expectations for the
Part 2 builder.

## Decision

**Storage.** `scripts/build_schedule_db.py` downloads
`https://www.retrosheet.org/schedule/{year}SKED.zip`, parses it, and populates a
`Schedules` table inside the existing `data/lahman.sqlite` (rather than a second
DB file, so the schedule and the Lahman join tables share one connection).
Columns: `year, date, game_num, dow, vis_team, vis_league, home_team,
home_league, time_of_day, postponed, makeup_date`, with an index on `(year)`.
`date` and `makeup_date` are `yyyymmdd` integers; `game_num` is an integer
(`0` single · `1`/`2` doubleheader halves); `postponed`/`makeup_date` are `NULL`
when the game was played as scheduled. The two per-team *season game number*
fields (Retrosheet fields 6 and 9) are dropped — they are derivable and unused.
Re-running a year does `DELETE FROM Schedules WHERE year=?` then reinserts, so
builds are **idempotent** (verified: 2016 re-run stays at 2,430 rows).

**Join.** Retrosheet team ids are not always equal to Lahman `teamID`. The
Lahman `Teams` table already carries a `teamIDretro` column mapping the two;
`build_lahman_db.py`'s Teams import previously **omitted** it, so Part 1 adds it
to the column list. `LahmanRepository.retro_to_lahman_team(retro_id, year)`
resolves via `teamIDretro` first, then falls back to an exact
`teamID == retro_id` match (correct for most modern teams), returning `None` if
neither resolves. The lookup is **year-scoped** because a franchise's Retrosheet
id can change over its history.

**Repository surface.** `get_schedule(year) -> List[ScheduleRow]` (ordered by
`(date, game_num)`), `retro_to_lahman_team(...)`, and `has_schedule(year)`
(which returns `False` — not an error — when the `Schedules` table is absent, so
older DBs degrade gracefully).

### Format notes — observed vs. documented (verified 2026-07-15)

Parsing the real files surfaced three deviations from the spec's field notes;
the parser is written to tolerate all of them:

- **File names differ.** The member inside `{year}SKED.zip` is
  `{year}schedule.csv` (e.g. `2016schedule.csv`), **not** `{year}SKED.TXT`. The
  parser selects the member by pattern rather than a fixed name.
- **Files carry a header row.** Every sampled file begins with
  `Date,Num,Day,Visitor,League,Game,Home,League,Game,Day/Night,Postponed,Makeup`
  — contrary to the spec's "no header". The parser skips any line whose first
  field is not an 8-digit `yyyymmdd`, which drops the header and any blank/short
  lines without special-casing.
- **2020 member names.** The 2020 ZIP holds `2020schedule.csv` (the played
  60-game slate — what we want) and `2020sched-orig.csv` (the pre-pandemic
  original). Selection excludes any member containing `orig`, so 2020 resolves
  to the played schedule automatically (900 rows = 30 teams × 60 ÷ 2). This is
  the spec's "use the rev file for 2020", generalized.
- **Time-of-day case varies.** 2020 rows use lowercase `d`/`n`; stored verbatim.

### Empirical characterization (sample parsed 2026-07-15)

Downloaded and parsed a sample spanning the era variation. "Games/team" counts
only games actually played (postponed-without-makeup excluded); "cancelled" =
postponed with no makeup date.

| Year | Note | Teams | Games/team (played) | Doubleheaders | Cancelled (no makeup) | Retro→Lahman failures |
| ---- | ---- | ----- | ------------------- | ------------- | --------------------- | --------------------- |
| 1927 | pre-division, 16-team / 154 | 16 | 153–154 (mostly 153) | 31 | 5 | none |
| 1969 | first divisions, 24-team / 162 | 24 | 160–162 (mostly 162) | 110 | 3 | none |
| 2016 | modern 30-team / 162 | 30 | 161–162 (mostly 162) | 0 | 2 | none |
| 2020 | revised 60-game (COVID) | 30 | 57–60 (mostly 60) | 0 | 5 | none |
| 1981 | split season (strike) — irregular | 26 | 103–111 | 48 | **713** | none |
| 1994 | strike-shortened — irregular | 28 | 112–118 | 1 | **659** | none |

Takeaways for the Part 2 builder:

1. **The retro→Lahman join is robust.** Zero unresolved ids across every sampled
   era — `teamIDretro` + exact fallback covers 1927 through 2020. The builder's
   "fail with the named unresolved teams" path is a safety net, not an expected
   case for these years.
2. **Cancelled games must be dropped, and the count can be large.** In normal
   years cancellations are a handful (2–5), but the strike years show the tail:
   1981 has **713** and 1994 **659** postponed-without-makeup rows. A builder
   that drops cancelled games (spec Part 2, step 2) will produce a much smaller
   played schedule for these years — correct, but it means 1981/1994 seasons are
   **structurally irregular** (partial, split) and are flagged here as such per
   the issue. They parse and store fine; whether to *offer* them in the setup
   flow is a Part 4 product call.
3. **Games/team is not uniform within a year.** Even clean seasons vary by ±1–2
   (rainouts never made up, tie games). 1927 ends with most teams at 153, not
   154. The builder must **not** assume a fixed per-team game count.
4. **Doubleheaders are an era feature.** Heavy pre-1970 (110 in 1969), effectively
   gone from the *scheduled* file by 2016 (0) — modern doubleheaders are makeup
   games added after the fact, not on the published slate. The builder must
   handle scheduled DHs (`game_num` 1 & 2, same date/teams) but should not expect
   them in modern years.

## Alternatives considered

- **A separate `schedules.sqlite` file** — rejected: the builder and repository
  need the Lahman `Teams` table (for the `teamIDretro` join and roster loads) on
  the same connection; one file keeps `get_schedule` + `retro_to_lahman_team`
  trivially joinable and matches the single-DB deployment the app already uses.
- **Storing the raw Retrosheet fields verbatim (all 12, no header skip)** —
  rejected: the two season-game-number fields are unused and derivable, and the
  header is noise. A normalized 11-column table is what the repository needs.
- **A franchise-level (year-agnostic) retro↔lahman map** — rejected: Retrosheet
  ids are only stable within a franchise era; the year-scoped `Teams.teamIDretro`
  lookup is exact and already present in the data.
- **Downloading a fixed set of years at build time** — rejected: the script
  takes `--year` / `--years` / `--start`/`--end` so callers ingest exactly the
  years they want; coverage is 1877–2026.

## Consequences

- Historical season mode has its schedule data source. Part 2 builds
  `List[SeasonDay]` from `get_schedule`, applying the drop-cancelled /
  move-to-makeup / group-by-date rules the characterization validates.
- **Existing `lahman.sqlite` files must be rebuilt** to gain the `teamIDretro`
  column (documented in `build_lahman_db.py` and `README.md`). Until rebuilt,
  `retro_to_lahman_team` silently falls back to exact-id matching (still correct
  for modern teams) and `has_schedule` returns `False`.
- The Retrosheet attribution notice now ships in-product (app subtitle credits
  Retrosheet; full required notice in `README.md`), satisfying Retrosheet's
  licensing.
- Strike/irregular years (1981, 1994) are ingestible but produce partial
  schedules; surfacing them to users is deferred to the Part 4 setup flow.
