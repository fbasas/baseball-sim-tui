# Spec: Season mode

**Source issue:** FRE-15 · **Date:** 2026-07-09 · **Status:** active

## Goal

Play a **season**: a custom league of 4–8 team-seasons from any eras (the
cross-era matchup is the product's signature — a league of the 1927 Yankees,
1975 Reds, 2016 Cubs, and 1906 White Sox is the point), on a balanced
round-robin schedule, with:

- a **standings table** (W-L, Pct, GB, RS/RA) that updates as games finish,
- **season-long stat accumulation** and league leaderboards (batting and
  pitching) aggregated from per-game box-score lines,
- the user **managing one team**: each of their games can be played
  interactively on the existing `GameScreen` or simmed; every other dugout is
  the manager AI, and all AI-vs-AI games sim headlessly,
- **pitcher rest carrying across the whole season** via the day-indexed
  `RestLedger`s (exactly as series mode already proves out),
- **save/resume of a whole season** — at the season hub between games, and
  mid-game via the existing Ctrl+S path,
- an **end-of-season summary**: final standings, a champion, league leaders.

Everything reuses the existing seams: `play_ai_game` for headless games,
`GameScreen` + `on_game_complete` for interactive ones, `RestLedger` for rest,
the `SaveFile` bundle for persistence, and the `SetupFlow` modal chain for
setup. The genuinely new work is a `src/season/` layer (schedule, standings,
stats, controller), a hub screen, and one engine-level refactor: box-score
line accumulation must move out of the TUI so headless games produce stat
lines too.

## Non-goals

- **No playoffs / postseason bracket.** The season ends with a champion by
  standings (tiebreak below). A playoff mode is a natural follow-up issue.
- **No historical schedule replay and no full historical league.** The league
  is a hand-picked set of 4–8 team-seasons on a generated round-robin — not
  the real 1927 AL schedule, not all 30 modern teams. `get_teams_for_year`
  makes a "whole league of year Y" preset easy later; out of scope now.
- **No pitcher W-L / save decisions.** Pitcher-of-record logic (who gets the
  W) is real scorekeeping complexity for little v1 value. Pitching leaders are
  ERA / SO / IP; the box score's existing "winning pitcher" heuristic on
  `BoxScoreScreen` is untouched.
- **No trades, injuries, roster moves, or player development.** Rosters are
  the Lahman season rosters for the whole season.
- **No fatigue carryover beyond rest.** As in series mode: `FatigueState` is
  per-game; cross-game carryover is the `RestLedger` (BF by day) only.
- **No parallel / multiprocess simulation.** A full 8-team season is ≤ 168
  games; `play_ai_game` runs a game in well under a second. Sim-ahead runs on
  a Textual worker with a progress line — that's enough.
- **No schema-version bump.** Season saves are additive: a new `kind ==
  "season"` plus an optional `season` field, with `game` becoming optional
  (present only for mid-game saves). Existing single/series saves keep
  loading; `SCHEMA_VERSION` stays 1.
- **No standalone-series regressions.** Single-game and best-of-N flows must
  behave exactly as today; season mode is a third mode beside them.

## Background — what exists and what's missing (audited 2026-07-09, main @ 3228847)

### Headless games work; headless *stat lines* do not

- `play_ai_game(away_team, home_team, away_ctx, home_ctx, rng_seed=None) ->
  AutoGameResult` (`src/game/autoplay.py:57`) plays a complete game with the
  manager AI running both dugouts through the same seams as the TUI
  (`ai_pregame`, `resolve_pitcher_stats`, `engine._apply_result`,
  `make_substitution`, `build_view`). It returns scores, innings, per-pitcher
  workloads (`pid -> BF`, ready to feed `RestLedger.record`), pitcher outs,
  starters, and manager `decisions` — **but no batting/pitching lines**.
- The per-game box-score lines live **only on the TUI `GameScreen`** as loose
  fields (`_batting_lines` / `_pitching_lines`, `game_screen.py:278-279`),
  mutated in `_log_play` (`game_screen.py:1037`) with runs credited by
  `_credit_runs_scored` (`game_screen.py:1021`) from
  `AdvancementResult.runners_scored`, and seeded by `_init_stat_lines`
  (`game_screen.py:568`). `src/game/persistence.py::BoxScore`
  (`persistence.py:124`) is already a plain container for exactly these
  accumulators (created for saves) — but nothing engine-side *fills* one.
- **Consequence:** season stat aggregation requires extracting the
  accumulation logic into the engine layer so both `GameScreen` and
  `play_ai_game` produce a `BoxScore` per game. This is the one refactor that
  touches the interactive hot path — it is Part 1 and `risk:high`.
- The current line shape is batting `AB/R/H/RBI/BB/K`, pitching
  `outs/H/R/ER/BB/K`. **Season leaderboards want HR**, so the extraction also
  adds `2B/3B/HR` keys to batting lines (from `AtBatOutcome`, trivially
  available in `_log_play`'s `result.outcome`). Loading an old save whose
  lines lack the new keys must keep working (treat missing keys as 0);
  `BoxScoreScreen` reads only the keys it names today and is untouched.

### Cross-game infrastructure is series-shaped but season-ready

- `SeriesController` (`src/series/controller.py:22`) is the pattern to
  generalize: it owns `SeriesState` + two `RestLedger`s, `record_game(away,
  home, GameWorkloads)` records usage by `current_day` then appends the
  result. A season is the same loop with N teams, a schedule, and W-L
  standings instead of best-of-N wins.
- `RestLedger` (`src/manager/rest.py:31`, `outings: pitcher -> day -> BF`)
  was explicitly designed for season reuse ("a future season mode can persist
  it") and already has `to_dict`/`from_dict`. Manager contexts are synced per
  game exactly as `app._push_game` does (`app.py:234-241`): set `ctx.ledger`
  and `ctx.day` before the game starts.
- The manager AI needs a **role card per team-season**
  (`data/roles/<TEAMID>-<YEAR>.json`); `load_manager_for_team` raises
  `FileNotFoundError` when missing and the app currently degrades that side
  to manual control (`app.py:196-219`) — unacceptable for a 7-AI-team league.
  **Role cards are buildable in-process**: `scripts/build_roles.py` is a thin
  CLI over `src.manager.inference.build_role_card(team_season, roster,
  batting, pitching, appearances)` + `src.manager.roles.save_role_card`, all
  importable. Season setup builds missing cards itself (with per-team error
  reporting), rather than telling the user to run a script 8 times.
- Every league team needs a card — **including the user's** (their games can
  be simmed, and `play_ai_game` requires contexts for both dugouts).

### Interactive-game and persistence seams to reuse

- `GameScreen(..., on_game_complete=...)` already supports an owner above it:
  the end-of-game payload is `{"away_score", "home_score", "away_workloads",
  "home_workloads"}` (`game_screen.py:1241-1246`). Season needs the game's
  batting/pitching lines in that payload too (available once Part 1 lands —
  the screen's accumulator IS a `BoxScore`).
- `GameConfig` (`src/tui/game_config.py:8`) is `{mode, best_of, away_ai,
  home_ai}` with `mode ∈ {"single", "series"}`; season adds `mode ==
  "season"`. `GameSnapshot.config` round-trips via `GameConfig(**dict)`, so
  a new mode value is save-compatible.
- `SaveFile` (`src/game/persistence.py:328`) is `{schema_version, kind,
  created_at, label, game, series?}` with `kind ∈ {"single", "series"}`;
  `SeriesSnapshot.from_controller`/`to_controller` (`persistence.py:292/308`)
  is the exact bridge pattern a `SeasonSnapshot` copies. `SaveFile.from_dict`
  currently requires `data["game"]` — season-hub saves have no in-progress
  game, so `game` becomes `Optional` (present ⇔ saved mid-game; always
  present for single/series).
- The load flow is wired end-to-end: `SetupFlow._select_saved_game` →
  `SaveSelectScreen` → `app._resume_saved_game` dispatches on `save.kind`
  (`app.py:95-119`) — season adds a third branch. `SaveSelectScreen` /
  `list_save_entries` (`src/tui/screens/save_select_screen.py`) lists by
  label and must render season saves too.
- Setup entry point: `_MODE_CHOICES` (`setup_flow.py:34`) gets a `("season",
  "Season — round-robin league, standings, full stats")` entry. The season
  branch diverges from the two-team flow (league builder loop instead), so it
  hands off to a separate `SeasonSetupFlow` rather than growing `SetupFlow`'s
  single/series chain.

### Testing idioms (house style — the DoD must match these)

- **pytest**, plain `assert`, `pytest.raises(match=...)`, `parametrize`;
  synthetic teams via the `make_batting_stats` / `make_lineup` /
  `_make_team_with_two_pitchers`-style factories (`tests/test_game_engine.py`,
  `tests/test_autoplay_e2e.py` builds full AI-playable teams + contexts).
- **Serialization round-trips** with synthetic dataclasses, no DB
  (`tests/test_series_persistence.py` is the direct precedent).
- **DB-backed integration tests are guarded** with `pytest.skip` when
  `data/lahman.sqlite` is missing.
- **Screens are tested without `Pilot`** — unbound methods driven with
  `types.SimpleNamespace` mock-`self` (`tests/test_save_select_screen.py`,
  `tests/test_load_resume_flow.py`).

## Design

### League shape and schedule

- **League:** 4, 6, or 8 team-seasons (even counts ⇒ everyone plays every
  day, no byes; a duplicate `(team_id, year)` entry is rejected). Teams are
  keyed `"{team_id}-{year}"` (e.g. `"NYA-1927"`) everywhere — schedule,
  standings, stats, ledgers.
- **Length:** the user picks **games vs each opponent** `G ∈ {2, 4, 6, 10}`
  (even ⇒ home/away balanced). Season length per team = `(N−1) × G`: an
  8-team league at G=6 is a 42-game season (168 games total); 4 teams at G=2
  is a 6-game sprint.
- **Schedule generation** (`src/season/schedule.py`): classic circle-method
  round robin. One **day** = one round = `N/2` simultaneous games; a full
  cycle is `N−1` days; the cycle repeats `G/2` times with home/away swapped
  on alternate cycles. Output: `List[SeasonDay]` where each day is a list of
  `ScheduledGame {game_id, day, home_key, away_key}`. Deterministic given
  (teams order, G): regenerable, but persisted anyway (explicit beats
  re-derived). Day indices feed the `RestLedger`s directly.

### The `src/season/` package (mirrors `src/series/`)

- **`SeasonState`** (`src/season/state.py`): `teams: List[TeamRef-like]`
  (key, team_id, year, display name), `games_per_opponent`, `user_team_key:
  Optional[str]`, `schedule`, `results: List[SeasonGameRecord]`. Derived
  `@property`s (never stored): `current_day` (first day with unplayed games),
  `is_complete`, `standings` (list of rows: key, W, L, Pct, GB, RS, RA,
  sorted), `champion`. `SeasonGameRecord`: `{game_id, day, home_key,
  away_key, home_score, away_score, innings}`. Champion tiebreak: winning
  pct, then head-to-head record among the tied, then run differential.
  `to_dict`/`from_dict` on both.
- **`SeasonStats`** (`src/season/stats.py`): per-player season accumulation,
  `ingest(box_score: BoxScore)` sums each game's batting/pitching lines into
  `batting: key -> pid -> line` / `pitching: key -> pid -> line` (team
  attribution via the accumulator's team fields). Leaders queries: batting
  AVG (qualify: AB ≥ 2 × team games played), HR, RBI, H; pitching ERA
  (qualify: outs ≥ 3 × team games played), SO, IP. Names resolve through the
  loaded `Team` rosters at render time — `SeasonStats` stores IDs only.
  `to_dict`/`from_dict`.
- **`SeasonController`** (`src/season/controller.py`): the season-scale
  `SeriesController`. Owns `SeasonState`, `SeasonStats`, and `ledgers: key ->
  RestLedger`; holds (but never serializes) the loaded `Team`s and
  `TeamManagerContext`s. API: `games_for_day(day)`, `next_user_game()`,
  `sim_game(scheduled_game) -> SeasonGameRecord` (syncs both contexts'
  `ledger`/`day`, runs `play_ai_game`, records workloads into both ledgers,
  ingests the box score, appends the result), `record_user_game(scheduled_game,
  payload)` (same bookkeeping from a `GameScreen` completion payload), and
  `sim_day()` / remaining-day iteration for the hub's sim-ahead. Uses
  `play_ai_game` unseeded (system entropy), matching the interactive game.

### Setup flow

`_MODE_CHOICES` gains `("season", ...)`. Choosing it runs a
**`SeasonSetupFlow`** (new module, same modal-chain style as `SetupFlow`):

1. **League size** — `ChoiceScreen` (4 / 6 / 8 teams).
2. **Games per opponent** — `ChoiceScreen` (2 / 4 / 6 / 10).
3. **Team picker loop** — `TeamSelectScreen` × N (context line shows picks so
   far; duplicate team-season re-prompts).
4. **Your team** — `ChoiceScreen` over the N picks, plus a "watch-only
   (commissioner)" option: `user_team_key = None`, every game AI-simmable.
5. **Role-card pass** — for each league team missing
   `data/roles/<TEAM>-<YEAR>.json`, build it in-process via
   `build_role_card` + `save_role_card` (worker + progress notify). A team
   whose card can't be built (inference `ValueError`) is reported and blocks
   season start — no silent manual-control fallback in season mode.

The flow ends by constructing the `SeasonController` and pushing the hub.
Lineup/pitcher choices are **not** made at setup — the user picks a starter
pregame for each of their games (series precedent: `_pick_series_starter`),
and the AI sides pick their own via `ai_pregame`.

### The season hub (`SeasonHubScreen`)

The home base between games — the season-scale `SeriesStatusScreen`. Shows:
standings table (user's team highlighted), day header ("Day 12 of 42"),
today's matchups with the user's game marked, last results, and key bindings:

- **p** — play my game: pregame starter pick → push `GameScreen` with the
  season contexts and `on_game_complete` recording into the controller; the
  rest of the day's AI games sim on return to the hub.
- **s** — sim my game (headless, same as any AI game), then the rest of the
  day.
- **d** — sim this day (everything headless; available always; in watch-only
  seasons this is the primary action).
- **a** — sim ahead: `ChoiceScreen` for "to my next game / 7 days / to end of
  season", run on a Textual worker with a progress line.
- **l** — league leaders screen (batting/pitching tables from `SeasonStats`).
- **ctrl+s** — save season (hub-state save, no `game` snapshot).
- **q** — quit to main menu (with a "save first?" prompt if unsaved games
  were played this session).

When `is_complete`, the hub flips to the **season summary**: final standings,
champion line, leaders — with "new season / main menu / quit".

### Interactive season games

`GameScreen` needs no structural change: the hub passes `on_game_complete`
exactly as series mode does, and (post-Part-1) the completion payload gains
the game's `BoxScore` so `record_user_game` can ingest lines. Ctrl+S inside a
season game produces a `kind == "season"` save with both `game` and `season`
populated (see below). Season games use the home team's park factor exactly
as today.

### Persistence: `kind == "season"`

- **`SeasonSnapshot`** (in `src/game/persistence.py`, beside
  `SeriesSnapshot`): `{teams, games_per_opponent, user_team_key, schedule,
  results, stats, ledgers: key -> RestLedger.to_dict()}` — i.e.
  `SeasonState.to_dict()` + `SeasonStats.to_dict()` + the ledgers. Bridges
  `from_controller` / `to_controller` like `SeriesSnapshot`. Loaded `Team`s
  and contexts re-hydrate from keys via `Team.load_from_repository` +
  `load_manager_for_team` (missing team ⇒ `MissingTeamError`; missing role
  card on load ⇒ rebuilt in-process as at setup).
- **`SaveFile`** gains `season: Optional[SeasonSnapshot]`; `game` becomes
  `Optional[GameSnapshot]` — required for `kind ∈ {"single", "series"}`,
  present for `kind == "season"` **only when saved mid-game**. Old saves
  parse unchanged; `SCHEMA_VERSION` stays 1.
- **Save points:** the hub (season-only bundle; label like `"Season Day
  12/42 — 1927 NYA 8-3, 1st"`) and mid-game Ctrl+S (game + season; the
  in-progress game is NOT in `results`, mirroring the series rule).
- **Resume:** `app._resume_saved_game` grows a season branch: rebuild the
  controller, re-hydrate teams/contexts, then push the hub — or, for a
  mid-game save, restore the `GameScreen` via the FRE-47 replay-safe path
  with the hub's `on_game_complete` re-wired, so finishing the resumed game
  records into the season exactly as an unsaved one would.

### Error handling

- League team with an unbuildable role card → named error at setup, season
  doesn't start.
- Season save referencing a `(team_id, year)` missing from the local DB →
  `MissingTeamError` naming the team (existing message pattern).
- A `kind == "season"` save with neither valid `season` data nor (when
  mid-game) a valid `game` → `CorruptSaveError`.
- `play_ai_game`'s PA-cap `RuntimeError` during a sim-ahead → surfaced via
  `notify`, day left partially played (already-recorded games stand; the
  failed game stays unplayed and re-simmable).

## Open questions

None require a human checkpoint. Product-taste decisions resolved in-spec
with defaults consistent with the product's cross-era identity: hand-picked
league (4/6/8 teams) rather than historical league replay; G ∈ {2,4,6,10}
games per opponent; no playoffs (champion by Pct → head-to-head → run diff);
no pitcher W-L; watch-only commissioner seasons allowed. If the human wants
playoffs, historical schedules, or larger leagues, those are follow-up
issues, not blockers. The `risk:high` issues route through `Verify` for live
DoD proof after merge.

## Issue breakdown

Parts 1–2 are independent foundations. The season becomes playable end-to-end
at Part 7; Part 8 makes it durable. Each part leaves the app working and
merged. The engine-refactor (1), the game/sim integration (7), and the save
format extension (8) are the correctness-sensitive pieces and are flagged
`risk:high`.

| # | Title | Depends on | Risk |
| --- | --- | --- | --- |
| 1 | Engine-level box score: shared per-game stat accumulation for TUI + headless games (adds 2B/3B/HR) | — | high |
| 2 | Season model layer: league config, round-robin schedule, `SeasonState` + standings | — | — |
| 3 | Season stat aggregation + leaderboards (`SeasonStats`) | 1, 2 | — |
| 4 | `SeasonController`: day-by-day orchestration, headless league sim, rest ledgers | 1, 2, 3 | — |
| 5 | `SeasonHubScreen`: standings, schedule, leaders, day actions | 4 | — |
| 6 | Season setup flow: league builder + in-process role-card pass + team choice | 2, 5 | — |
| 7 | Play/sim integration: interactive season games, sim-day/sim-ahead workers, end-of-season summary | 5, 6 | high |
| 8 | Season save/resume: `SeasonSnapshot` (`kind == "season"`), hub + mid-game saves, load UI | 4, 7 | high |
