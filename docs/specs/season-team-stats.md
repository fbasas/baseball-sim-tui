# Spec: Season team stat page

**Source issue:** FRE-113 · **Date:** 2026-07-15 · **Status:** active

## Goal

During a season, let the user open a **per-team stat page** — for any one
league team, the season-to-date batting and pitching stat lines for every
player on that club, resolved to names and laid out in aligned columns. This
is the "box score of the whole season, one team at a time" view that
complements the existing *league-wide* leaderboards: leaders answer "who's
best in the league?", this answers "how is my team hitting?".

It is a **pure-rendering follow-up** to season mode (FRE-15): the data already
exists. `SeasonStats` accumulates `team_key → player_id → line` for both
batting and pitching every game (`src/season/stats.py`); the season hub
already resolves ids to names and renders leader tables. This feature adds one
new screen over that same data plus a hub key to reach it.

## Non-goals

- **No new stats collected.** The page renders only what `SeasonStats` already
  holds — batting `AB/R/H/2B/3B/HR/RBI/BB/K` (+ derived AVG) and pitching
  `outs/H/R/ER/BB/K` (+ derived IP, ERA). No OBP/SLG/OPS (needs HBP/SF/TB
  bookkeeping the box score doesn't track), no W-L/saves (season mode
  explicitly has no pitcher-of-record logic — see season-mode.md non-goals),
  no fielding, no splits.
- **No changes to accumulation, persistence, the controller, or the game
  engine.** `SeasonStats` / `SeasonSnapshot` / save format are untouched;
  reading `.batting` / `.pitching` is all this needs. `SCHEMA_VERSION` stays 1.
- **No standings/leaders changes.** The existing `SeasonHubScreen` standings,
  matchups, recent results, and `LeagueLeadersScreen` are untouched; this adds
  a screen beside them, not a rewrite.
- **No sortable/interactive columns, filtering, or export.** Fixed sort orders
  (below), keyboard to change team and to leave. A DataTable-style sortable
  grid is a possible follow-up, not this.
- **No per-player game logs or rate-stat qualifiers.** Every player with at
  least one accumulated line is shown; there is no "qualified only" filter (a
  team page is meant to be complete, unlike the league leaderboards).

## Design

### Where the data already lives (audited 2026-07-15, main @ origin/main)

- `SeasonStats` (`src/season/stats.py`): `batting: team_key → pid → line` and
  `pitching: team_key → pid → line`, each an int dict. Batting keys:
  `AB R H RBI BB K 2B 3B HR`. Pitching keys: `outs H R ER BB K`. Read with
  `.get(key, 0)` (older lines may lack `2B/3B/HR`). `games_played: team_key →
  int` is also there (used by the leaderboard qualifiers; not needed here).
- `SeasonController` (`src/season/controller.py`) holds `.stats`
  (`SeasonStats`), `.teams` (`team_key → Team`, loaded rosters for name
  resolution), and `.state` (`SeasonState`). `state.teams` is a list of
  `LeagueTeam(key, team_id, year, display_name)`; `state.standings` is a
  sorted `List[StandingsRow]` with `.key/.wins/.losses/.pct/.games_behind/
  .runs_scored/.runs_allowed`.
- `src/tui/screens/season_hub_screen.py` already has the reusable pure
  helpers this screen builds on — **import them, do not re-implement**:
  `_resolve_name(controller, team_key, pid) -> "F. Last"`, `_fit(text, width)`
  (fixed-width truncate+pad, the column-alignment primitive), and the
  formatters `_format_avg`, `_format_era`, `_format_ip`, `_format_int`. The
  hub test (`tests/test_season_hub_screen.py`) already imports several of
  these underscored names across modules, so this is house-acceptable.

### New model accessors (`src/season/stats.py`)

Add two thin, tested read accessors so the screen never reaches into the
accumulator internals:

- `team_batting(team_key: str) -> Dict[str, Dict[str, int]]` — returns
  `self.batting.get(team_key, {})` (pid → line, or `{}` for a team with no
  games yet).
- `team_pitching(team_key: str) -> Dict[str, Dict[str, int]]` — same over
  `self.pitching`.

These return the live dicts (callers only read); mirror the existing
`_games`/leaderboard read style. No serialization change.

### New screen: `TeamStatsScreen` (`src/tui/screens/team_stats_screen.py`)

A `Screen` (full-screen, like `LeagueLeadersScreen`), pure rendering over the
controller. New module (not appended to `season_hub_screen.py`, which is
already large) that imports the shared helpers from `season_hub_screen`.

**Construction:** `TeamStatsScreen(controller, initial_key: str)`.

**Team cycling in-screen (no separate picker):** the screen shows one team at
a time and lets the user step through **all league teams in standings order**
with `left`/`right` (wrapping). It holds the ordered key list
(`[row.key for row in controller.state.standings]`) and an index initialized
to `initial_key`'s position (fall back to 0 if not found). Changing team
re-renders in place. This keeps it to one screen and one keyboard idiom;
no `ChoiceScreen` round-trip.

**Layout (top to bottom, in a `VerticalScroll`):**

- **Title** — `⚾ TEAM STATS`.
- **Team header** — `display_name` + record, e.g.
  `1927 Yankees   (12-3, .800)`, pulled from the matching `StandingsRow`
  (fall back to just the name if the team has no standings row yet). Team name
  from `state.teams` (match `LeagueTeam.key`), record from `state.standings`.
- **BATTING** section header + a monospaced table:
  - Columns: `Player  AVG   AB   R   H  2B  3B  HR  RBI  BB   K`.
  - One row per pid in `team_batting(key)`. AVG via `_format_avg`
    (`H/AB`, blank/`—` when `AB == 0`); the rest are integers.
  - **Sort:** AB descending, then AVG descending, then name — so regulars
    lead, pinch bats trail. Deterministic.
  - Optional trailing **TEAM** totals row (sum each column; AVG = ΣH/ΣAB).
  - Name column fixed width via `_fit`; numeric columns right-aligned under
    their headers (mirror `_build_standings_table`'s alignment approach).
- **PITCHING** section header + table:
  - Columns: `Pitcher  ERA    IP    H   R  ER  BB   K`.
  - One row per pid in `team_pitching(key)`. ERA via `_format_era`
    (`ER/(outs/3)*9`, blank/`—` when `outs == 0`); IP via `_format_ip`
    (from `outs`, standard `.0/.1/.2` thirds); rest integers.
  - **Sort:** outs (IP) descending, then ERA ascending, then name — starters
    and workhorses first.
  - Optional trailing **TEAM** totals row.
- **Empty state:** a team with no games yet (both dicts empty) shows a dim
  `No stats yet` placeholder in place of the tables (reuse the hub's
  `[#6b7d6b]…[/]` dim style), not empty tables.
- **Footer** (`textual.widgets.Footer`) advertising the bindings.

**Bindings:** `left`/`right` change team (also `[`/`]` optional aliases, `show=False`);
`escape` and `q` pop back to the hub. Matches `LeagueLeadersScreen`'s
`escape`/`q` = Back idiom.

**Styling:** reuse the existing hub CSS classes (`hub-header`, `hub-section`)
and the `VerticalScroll` container pattern from `LeagueLeadersScreen`; add a
container `id` and, only if needed for the title, a tiny block in
`src/tui/styles/game.tcss` mirroring `#leaders-title`. No new colors.

### Reaching the screen from the hub (`season_hub_screen.py`)

- Add a binding `Binding("t", "team_stats", "Team stats")` to
  `SeasonHubScreen.BINDINGS`.
- `action_team_stats(self)` pushes `TeamStatsScreen(self._controller,
  initial_key)` where `initial_key` is the user's team
  (`state.user_team_key`) when set, else the standings leader
  (`state.standings[0].key` if any, else `state.teams[0].key`). Push directly
  (`self.app.push_screen(...)`), exactly as `action_leaders` pushes
  `LeagueLeadersScreen` — the hub owns this subscreen, it does not route
  through the owner `on_choice` seam.
- `check_action`: team stats is **always available** (mid-season *and* on the
  complete-season summary — reviewing final team stats is a natural end-of-
  season action). Add `"team_stats"` to the always-return-`True` set (it isn't
  gated, so the default `return True` at the end already covers it — just make
  sure no earlier branch accidentally hides it).

### Registration

Export `TeamStatsScreen` from `src/tui/screens/__init__.py` (import + `__all__`),
alphabetical with the rest.

## Testing (DoD)

House idiom — **DB-free, Pilot-free**, driving the screen's pure render/dispatch
methods with a `types.SimpleNamespace` mock-`self` over a lightweight fake
controller wrapping a *real* `SeasonState`/`SeasonStats` (exactly as
`tests/test_season_hub_screen.py` does; copy its `_FakeTeam`/`_FakePlayer`
factories). New file `tests/test_team_stats_screen.py` plus a couple of
assertions in the existing hub test for the new hub action. Cover:

- **Model accessors:** `team_batting`/`team_pitching` return the right pid→line
  dict for a team with data and `{}` for an unknown/empty team.
- **Batting table:** a row per player; AVG formatted `.333` (no leading zero)
  and blank/`—` at 0 AB; rows sorted AB-desc; every batting column present and
  aligned (assert header/data column positions or use a regex per row).
- **Pitching table:** a row per pitcher; ERA `2.50` and IP thirds `12.1`
  formatted; sorted by IP desc; ERA/IP blank/`—` at 0 outs.
- **Name resolution:** ids render as `F. Last` via the fake rosters, never raw.
- **Team header:** shows display name + `(W-L, .pct)` from standings.
- **Cycling:** `action`/handler for `left`/`right` advances the index through
  standings order and wraps at both ends; the rendered team header follows.
- **Empty team:** a club with no games shows the `No stats yet` placeholder,
  no table rows.
- **Hub wiring:** `SeasonHubScreen.action_team_stats` pushes a
  `TeamStatsScreen` with `initial_key` = user's team when set and the standings
  leader in a watch-only season; `check_action("team_stats", ())` is truthy
  both mid-season and when complete.

All existing tests must stay green; no engine/persistence/controller test
changes are expected (nothing they cover changes).

## Open questions

None require a human checkpoint. Product-taste calls resolved in-spec with
defaults consistent with the existing season UI: full roster (no qualifier
filter), fixed sort orders (batting by AB, pitching by IP), stats limited to
what's already tracked (AVG + counting for batting; ERA/IP + counting for
pitching; no W-L, per season-mode's no-pitcher-of-record non-goal), in-screen
`←/→` team cycling rather than a separate picker. If the human later wants
OBP/SLG, sortable columns, or a picker, those are follow-up issues.

## Issue breakdown

One issue: the data model already exists (season mode is merged), so this is a
single cohesive, user-visible rendering unit (new screen + two model
accessors + hub binding + tests) that leaves the app working and merged. It is
well within the sizing rule (~1 new screen module, ~2 accessor methods, a few
hub lines, one test module — ≤ ~300 lines, ~5 files, one new concept). Pure
rendering over merged data with no external services or data-loss surface →
not `risk:high`.

| Issue | Title | Depends on | Risk |
| --- | --- | --- | --- |
| FRE-114 | Season team stat page: per-team batting/pitching lines screen | — (season mode already merged) | — |
