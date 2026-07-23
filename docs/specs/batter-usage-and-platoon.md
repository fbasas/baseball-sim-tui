# Spec: Season-realistic batter usage — rest rotation & platoon lineups

**Source issue:** FRE-173 · **Date:** 2026-07-23 · **Status:** active

## Goal

Make position-player usage vary across a simulated season the way it does in real
baseball, so the manager AI stops running one fixed lineup per team all year. Two
concrete gaps, both confirmed against `origin/main`:

1. **No cross-game batter model.** Pitchers have a game-to-game rest model
   (`src/manager/rest.py::RestLedger`, recorded per day in the season loop and
   consumed to rotate starters). Position players have nothing — they never rest or
   rotate. Add a batter usage/rest model parallel to the pitcher one so regulars sit
   occasionally and bench players get starts.
2. **Batter role cards are built but not consumed for lineup selection.** Every
   game emits `card.batting_order` verbatim; the only bench path is "this Team load
   has no stats for that player." Nothing reads the opposing pitcher's handedness, so
   the `BatterRoleType.PLATOON` classification is **dead weight** — inferred, stored,
   and never used. Wire the sim to build platoon-aware lineups against the opposing
   starter's throwing hand, so PLATOON roles are actually exercised and lineups vary
   by matchup.

"Done" is a headless season sim in which a team's lineup is **not identical**
game-to-game: regulars get rest days, backups start, and the bats that start shift
with the opposing starter's handedness — all driven by data already in the role
cards (Lahman handedness + historical start share), with no Retrosheet dependency.

## Non-goals (explicitly out of scope for this feature)

These are deliberately excluded to keep the work sized and to avoid repeating the
exact mistake this feature fixes — **adding inference that nothing consumes.** Do not
build them; they are recorded here as the future roadmap.

- **In-sim *performance* effects.** The simulation (`src/simulation/`, odds-ratio at
  `at_bat.py`) models no handedness, defense, or baserunning. This feature changes
  **who starts** (usage/variation); it does **not** make a platoon-advantaged bat hit
  better in the sim, because the sim can't reward that yet. Managing expectations:
  starting the lefty vs the RHP is realistic *usage*, not a modeled edge.
- **Real vs-LHP / vs-RHP performance splits (Retrosheet).** Lahman carries no split
  data; `BatterRoleCard.retrosheet` is a reserved, unwired field. True split-based
  platoon *value* is a later tranche blocked on Retrosheet ingestion. Platoon
  *selection* here uses only each player's own `bats` hand — no splits needed.
- **`DEFENSIVE_REPLACEMENT` and `PINCH_RUNNER` (speed) roles.** These only pay off
  once the sim models fielding and baserunning, which it does not. Adding them now
  would recreate the dead-PLATOON problem. Deferred until the sim models those
  effects.
- **Batter in-game fatigue as a *performance* penalty.** This models cross-game
  *usage/rotation* only (who is rested enough to start), not an in-at-bat fatigue
  debuff.
- **Series-mode batter rest parity.** The reported gap is the *season* sim. Batter
  usage is wired into the season path; series mode keeps today's behavior. A
  pitcher-parity follow-up can extend it later (the pitcher model itself went
  series-first, then season).
- **Era-awareness of batter roles / DH-by-league-year.** The sim always fields a DH
  lineup today; refining DH eligibility by league/year is orthogonal to Fred's
  lineup-variation ask and is left for later.

## Background: what exists on `origin/main` (commit `c6fa141`)

Grounding so each issue can be built without re-deriving the architecture.

- **Inference (offline):** `src/manager/inference.py::_infer_batters()` classifies
  every position player into `REGULAR` / `PLATOON` / `BENCH` / `PINCH_SPECIALIST`
  purely from **start share** (usage games / team games): `≥0.65` REGULAR,
  `≥0.30` PLATOON, else BENCH/PINCH_SPECIALIST. It already stores each batter's
  handedness in `metrics["bats"]` and computes `eligible_positions`,
  `primary_position`, `start_share`, and OPS/OBP/SLG/AVG. `_recommend_batting_order()`
  produces the static 9-man order + positions.
- **Role card schema:** `src/manager/roles.py` — `BatterRoleCard`, `TeamRoleCard`
  (`SCHEMA_VERSION = 1`). `to_dict`/`from_dict` round-trip; `from_dict` **raises on a
  version mismatch** (cards are regenerated, never migrated in place). Cards live at
  `data/roles/<TEAMID>-<YEAR>.json` (gitignored, built on demand by
  `scripts/build_roles.py`; rebuilt in-process on load — see `rehydrate.py`).
- **Pitcher rest model:** `src/manager/rest.py::RestLedger` records
  `pitcher_id -> {day: batters_faced}`, answers `available_pitchers(card, day)`.
  Recorded per game in `src/season/controller.py::_record()` (from
  `AutoGameResult.*_workloads`), synced onto `TeamManagerContext.ledger` before each
  game, and **persisted** in `SeasonSnapshot` / `SeriesSnapshot`
  (`src/game/persistence.py`, `to_dict`/`from_dict`).
- **Pregame flow:** `src/game/autoplay.py::play_ai_game()` calls
  `ai_pregame(team, ctx)` for each side (`src/game/manager_adapter.py`), which calls
  `ManagerAI.build_pregame(available_pitchers, unavailable_batters)`
  (`src/manager/manager.py`). `unavailable_batters` today is **only** "batter ids the
  Team load has no stats for." No opposing-pitcher information crosses the boundary.
- **In-game heuristics** (`heuristics.py`) already consume batter cards for
  `should_pinch_hit`; its header explicitly notes platoon/defense/baserunning are
  "deliberately NOT here (sim doesn't model them yet)."

## Design

Two independent tracks that converge in the platoon lineup selector:

```
  Track 1 (rest/rotation)          Track 2 (platoon inference)
  ─────────────────────            ──────────────────────────
  A1 BatterUsageLedger (model)     C  handedness-aware platoon
        │                              inference + depth metadata
  A2 wire into season sim               │
        │                               │
        └──────────────┬────────────────┘
                       ▼
        B  platoon-aware lineup selection
           (consumes rest availability + handedness + depth chart)
```

### Track 1 — batter cross-game usage/rest model

**A1 — `BatterUsageLedger` (model + serialization).** A new
`src/manager/batter_rest.py`, structured like `RestLedger` but for position players:

- State: `starts: Dict[str, Dict[int, int]]` — `player_id -> {day_index: 1}` for days
  the player was in the starting lineup. `record(day, started_ids)` marks starters.
- `consecutive_starts(pid, today)`: walk the team's recorded game-days (the ledger's
  own recorded day set is that team's played-days sequence) descending from the latest
  day `< today`, counting while `pid` started each — the current start streak.
- `should_rest(batter_card, today)`: **True** when a REGULAR's start streak has
  reached a threshold derived from historical usage, so heavier-used regulars rest
  less often. Recommended rule: `streak >= max(_MIN_STREAK, round(1 / (1 -
  start_share)))` (a .90-usage regular rests roughly every ~10 starts, a .80 regular
  roughly every ~5), with a floor `_MIN_STREAK` (e.g. 5) so nobody is rested after a
  couple of games. PLATOON/BENCH/PINCH_SPECIALIST return False here (their rotation is
  matchup-driven in B, and bench players are the fill-ins, not the rested).
- `resting_batters(card, today) -> List[str]`: the REGULARs flagged to sit today. The
  ledger only flags fatigue; **feasibility** (don't sit someone if there's no eligible
  replacement, never break the 9) is the adapter/manager's job (A2/B).
- `to_dict`/`from_dict` mirroring `RestLedger` for later persistence.

Pure model, fully unit-tested, **not yet wired** — compiles and passes, unused until
A2. This is the one "add a library" issue in the set.

**A2 — wire batter usage into the season sim (live + persistence).** Make the season
loop record starts, rest regulars, and rotate backups in:

- `AutoGameResult` gains `away_batter_starts` / `home_batter_starts` (the 9 starting
  batter ids per side); `play_ai_game` fills them from each pregame plan's
  `batting_order`.
- `TeamManagerContext` gains a `batter_ledger: BatterUsageLedger`; `sim_game` syncs it
  and `ctx.day` alongside the pitcher ledger.
- `SeasonController._record()` records both teams' batter starts into per-team
  `batter_ledgers` (a new dict parallel to `ledgers`); `record_user_game` reads the
  starts from the GameScreen payload (payload gains the same two keys).
- `manager_adapter.ai_pregame()` computes rest-driven sits:
  `resting = ctx.batter_ledger.resting_batters(ctx.card, ctx.day)`, keeps only those
  with an eligible, stats-present replacement (so `build_pregame` can still field 9),
  and unions them into `unavailable_batters`. `build_pregame`'s existing
  `_fill_holes` then starts the backups — lineups vary with no manager change needed.
- **Persistence:** `SeasonSnapshot` gains `batter_ledgers` (to_dict/from_dict/
  from_controller/to_controller); `rehydrate` installs them. Season save/load keeps
  batter rest, exactly like the pitcher ledger. (Series mode: out of scope — see
  Non-goals.)

Observable DoD: sim a full season headlessly and show (a) at least one team's lineup
differs across its games, (b) every REGULAR starts fewer than all of the team's games
(they got rest days) while ≥1 backup accrues starts, (c) the season still completes,
(d) a `SeasonSnapshot` round-trips the batter ledgers.

### Track 2 — platoon inference

**C — handedness-aware platoon inference + depth metadata (schema bump to v2).**
Replace the crude start-share PLATOON band with a real platoon signal and give B the
data it needs:

- Use each batter's `bats` hand (already fetched from `PlayerInfo`) to detect **true
  platoon pairs**: two players who share a position (overlapping `primary`/`eligible`),
  have complementary hands (one L or the batter-favorable side vs the other, switch
  hitters `B` are neutral/either), and whose start shares indicate a shared job (each
  in a part-time band, summing near a full-time share). Keep the `PLATOON` role but
  make it *mean* platoon.
- Add to `BatterRoleCard`: `platoon_partner: Optional[str]` (the paired player_id) and
  `platoon_side: Optional[str]` — the opposing-pitcher hand this batter should **start
  against** (`"R"` for a left-handed bat, `"L"` for a right-handed bat; `None`/neutral
  for switch hitters and non-platoon players).
- Add to `TeamRoleCard`: `depth_chart: Dict[str, List[str]]` — position abbrev →
  player_ids ranked by preference (starter first, then platoon partner, then bench
  cover), so B can pick a per-position bat by availability + matchup deterministically.
- Bump `SCHEMA_VERSION` to `2`; extend `to_dict`/`from_dict` (new fields additive,
  defaulting cleanly). A version bump forces regeneration of on-disk cards — acceptable
  because cards are built on demand and rebuilt in-process on load; add a one-line note
  to the build script output if helpful. Keep inference deterministic (ties by
  player_id).

No consumption change beyond richer cards; existing `_recommend_batting_order` still
produces the same static order. The new `platoon_partner`/`depth_chart` data is
consumed by B (which is blocked on C). DoD: on a known platoon team-season fixture,
the two job-sharing players are detected as partners with correct `platoon_side`, the
depth chart lists them under the shared position, and cards still round-trip.

### Convergence — B

**B — platoon-aware lineup selection.** Consume the opposing starter's hand + C's
depth chart, honoring A2's rest availability, to build a lineup that varies by
matchup:

- Refactor the pregame so **both starters are chosen before either lineup is built**
  (today `ai_pregame` picks each side's starter internally, so neither side knows the
  other's hand). In `play_ai_game`: resolve each side's starting pitcher, read its
  `throws` from the card's pitcher `metrics`, then build each side's lineup passing the
  **opponent** starter's hand.
- `ManagerAI.build_pregame(..., opposing_throws: Optional[str] = None)` and
  `ai_pregame(team, ctx, opposing_throws=None)` take the opposing hand. When known, for
  each position with a platoon pair / multi-deep depth chart entry, start the
  **platoon-advantaged, available** bat (`platoon_side == opposing_throws`), falling
  back to the historical `batting_order` / `_fill_holes` when there's no platoon choice
  or the advantaged bat is unavailable (rest/data-missing). Deterministic tie-breaks;
  always emits a legal 9 with positions.
- Interactive path: `app._play_user_game` knows the user's chosen starter, so pass its
  hand as the AI opponent's `opposing_throws`. **Deferred out of B** per the size
  budget — carried by tranche **D** below (spun off as FRE-181).

Observable DoD (the headline for Fred — PLATOON roles finally exercised): on a fixture
with a known L/R platoon, the **L bat starts vs a RHP and the R bat starts vs a LHP**;
across a simmed season the team's lineup shifts with the opposing starter's hand; the
season still completes and lineups are demonstrably not constant. (This DoD is proven
**headless** by B; the interactive user-game path is D below.)

### Convergence — D (interactive user-game AI opponent)

**D — wire the interactive AI opponent to platoon by the human's starter hand.**
*Depends on B (FRE-178).* B implemented the platoon path **headless only**
(`play_ai_game` resolves both starters up front via `resolve_ai_starter`, reads each
`throws` via `_starter_throws`, and passes each opponent's hand to `ai_pregame(...,
opposing_throws=...)`). The **interactive** TUI game does not: in
`src/tui/screens/game_screen.py::_build_lineups`, each AI-managed side calls
`ai_pregame(team, ctx)` with **no** opposing hand, so the AI opponent never platoons
against the human's chosen starter. Wire it through.

- In `_build_lineups`, for an **AI-managed side** (its `ctx` is not `None`), resolve
  the **opposing** starter's throwing hand and pass it as
  `ai_pregame(team, ctx, opposing_throws=<hand>)`.
- **The wrinkle — the human side has no role card.** In a user game exactly one side
  is human (`ctx is None`); its chosen starter id is already known on the screen as
  `self._away_pitcher_id` / `self._home_pitcher_id` (set in `after_pick` as `pid or
  default_pid`, so it is always a real pitcher id by build time — never `None`).
  Because the human dugout carries no `TeamManagerContext`/role card, its hand must
  come from **`PlayerInfo`**, not a card: resolve `throws` (`"L"`/`"R"`) via
  `team.get_player(pid).throws` (or `repo.get_player_info(pid).throws`) on the
  opposing team — both already available to the screen (`self.repo`, the two `Team`
  objects). Treat anything other than `"L"`/`"R"` (missing/unknown) as `None`, so the
  AI falls back to its historical order rather than guessing an edge — mirroring
  `_starter_throws`.
- **AI-vs-AI opposing side** (the shared `_build_lineups` also runs series games where
  the opposing side is itself AI): resolve that side's starter deterministically up
  front — `resolve_ai_starter(opp_team, opp_ctx)` — and read its hand from the card
  metrics (`_starter_throws`), exactly like headless, so ordering within the build
  loop can't leave the hand unknown. A single helper that returns a starter's hand
  from *either* a ctx-card or `PlayerInfo` keeps both cases in one place.
- No change to `ai_pregame` / `build_pregame` / the selection logic — this is a pure
  call-site wiring: the interactive path finally supplies the hand B already knows how
  to consume.

Observable DoD (D): with a known L/R platoon fixture, building the interactive
lineups (the `GameScreen` AI-hook methods are unit-testable as unbound functions
against a mock `self` — see `tests/test_manager_tui_integration.py`, reusing the
platoon fixture from `tests/test_platoon_lineup_integration.py`) yields an AI
opponent starting nine that **differs by the human starter's hand**: the platooned
position starts the L bat when the human throws R and the R bat when the human throws
L, and falls back to the historical order when the hand is unknown. No web, no live
Lahman dependency in the test.

## Open questions

None require a human checkpoint. The one judgment call — how aggressively to rest
regulars — is resolved with a usage-derived default (rest frequency scales with
`1 - start_share`, floored) whose effect is observable in A2's DoD; the implementer
tunes the constants to hit "regulars rest occasionally, backups start, lineups vary."
The Retrosheet split question raised in the original checkpoint is deferred by design
(Non-goals), not blocked on Fred, per the recorded Triage decision.

## Issue breakdown

| Issue | Title | Depends on | Risk |
| --- | --- | --- | --- |
| FRE-175 | Batter usage/rest ledger (`BatterUsageLedger` model + serialization) — *Track 1 › A1* | — | — |
| FRE-177 | Rest-driven batter rotation in season sims (wire the ledger, live + persistence) — *Track 1 › A2* | FRE-175 | high |
| FRE-176 | Handedness-aware platoon inference + depth-chart metadata (schema v2) — *Track 2 › C* | — | high |
| FRE-178 | Platoon-aware lineup selection (consume opposing-starter hand + depth chart) — *Convergence › B* | FRE-177, FRE-176 | high |
| FRE-182 | Wire interactive user-game AI opponent to platoon by the human's starter hand — *Convergence › D* | FRE-178 | — |
