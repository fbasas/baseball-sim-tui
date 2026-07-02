---
phase: 08-computer-manager
type: phase-plan
status: implemented
created: 2026-07-02
completed: 2026-07-02
requirements: [MGR-01, MGR-02, MGR-03, MGR-04, SER-01, SER-02]
---

# Phase 8: Computer Manager — Implementation Plan

## Goal

An AI manager that runs a team the way its real-life counterpart did: historical
usage defines player **roles** (rotation order, bullpen roles, bench roles,
workload leashes), and the AI optimizes **tactically within those roles** using
only the effects the simulation actually models. Plus a best-of-N exhibition
series mode so rotation order and bullpen rest emerge naturally across games.

## Agreed design decisions (from requirements session 2026-07-02)

1. **Philosophy**: Historical usage = optimal day-to-day usage. Roles are
   given, not second-guessed. In-game tactics are optimized within roles.
   History sets boundaries (a 1927 workhorse's leash ≈ 9 innings); tactics
   pick the moment within them.
2. **Control scope**: AI always manages the opponent; the user's team can be
   toggled manual vs AI-managed (enables full auto-sim games).
3. **Data**: Lahman now; Retrosheet enrichment later when acquired. Artifact
   schema leaves room for Retrosheet-backed fields with Lahman-inferred
   defaults.
4. **Offline role pass**: explicit CLI step (`scripts/build_roles.py`), pure
   Python inference in v1. LLM optionally allowed in this offline pass later;
   **never in-game**. Manual play works without an artifact; AI-managing a
   team requires one (setup flow prompts the user to run the script).
5. **In-game engine**: heuristic rules only. No LLM, no calls into the
   engine's odds-ratio math, no Monte Carlo. "Knows the sim" = knows which
   heuristics are active in the current state.
6. **v1 heuristic surface — only what the sim rewards today**: pitcher
   fatigue, times-through-order, overall-stats matchup quality, score/base/out
   leverage. **Deferred** (with their sim extensions): platoon L/R effects,
   fielder quality, baserunning speed. Consequence: the AI will rarely make
   defensive subs or pinch-run in v1 — the surface exists, the incentive
   doesn't yet.
7. **Decision surface (v1)**: pregame starter selection + batting order,
   pitching changes, pinch-hitting.
8. **Game modes**: Exhibition **single game** (fully rested, as today) and
   **best-of-N series (3/5/7)** with pitcher rest/usage carryover between
   games. Rest machinery designed for reuse by a future season mode (out of
   scope now).

## Architecture

Two decoupled pieces joined by a data artifact and a narrow view interface.

```
scripts/build_roles.py ──► data/roles/<TEAM>-<YEAR>.json     (offline, CLI)
                                     │
                                     ▼
src/manager/            ◄── ManagerGameView (read-only projection)
  roles.py                  built by adapter at the TUI/engine boundary
  view.py                            │
  heuristics.py                      ▼
  manager.py            ──► ManagerDecision(s)
  rest.py                            │
                                     ▼
                          GameScreen applies via existing
                          GameEngine.make_substitution seam
```

**Decoupling contract**: `src/manager/` imports nothing from
`src/simulation/` or `src/game/`. It consumes:
- a `TeamRoleCard` (parsed role artifact — includes precomputed per-player
  metrics like OPS/WHIP so the manager never touches the repo in-game), and
- a `ManagerGameView` (plain dataclass: inning, half, outs, score diff,
  runners-on count, current pitcher id + fatigue value + times-through-order,
  batter due up, per-player availability flags, DH in effect).

It emits `ManagerDecision` values (`SetLineup`, `PitchingChange`, `PinchHit`,
`NoAction`). An adapter module at the boundary
(`src/tui/manager_adapter.py`) builds the view from
`GameState`/`Team`/`SubstitutionManager` and applies decisions through
`GameEngine.make_substitution` — the same seam human subs use
(engine.py:208). The manager is pure and deterministic: same view + same
role card → same decision (tie-breaks by player_id, never RNG).

### Key existing seams (from architecture survey)

- TUI hot path is `GameScreen._advance_one` (game_screen.py:453) — the TUI
  drives at-bats itself via `resolve_pitcher_stats` + `sim.simulate_at_bat`;
  it does NOT call `simulate_half_inning`. The manager hook goes here,
  before `resolve_pitcher_stats`.
- All substitutions already route through `GameEngine.make_substitution`
  (returns new GameState + Team; resets FatigueState on pitching change).
- Fatigue is fully readable off immutable `GameState`
  (`state.current_pitcher_fatigue.current_fatigue`,
  `.times_through_order`) — no engine changes needed for the manager to
  observe it.
- Bench/bullpen are derived (roster stat dicts minus lineup ids, filtered by
  `SubstitutionManager.is_player_available`) — same derivation feeds the
  view's availability flags.
- Setup flow chain (`SetupFlow.begin` → team → pitcher → `_launch_game`)
  widens to carry mode/series-length/AI-side flags.

## Role artifact schema (v1)

`data/roles/<TEAMID>-<YEAR>.json`, e.g. `NYA-1927.json`:

```jsonc
{
  "schema_version": 1,
  "team_id": "NYA", "year": 1927,
  "sources": {"lahman": true, "retrosheet": false},
  "generator": "build_roles.py v1 (pure inference)",
  "pitchers": {
    "<player_id>": {
      "role": "starter | swingman | long_relief | middle_relief | setup | closer",
      "rotation_slot": 1,            // 1..N for starters, null otherwise
      "leash_bf": 33,                // batters-faced leash: (3*IP + H + BB)/GS, scaled by CG rate
      "leash_fatigue": 0.70,         // fatigue threshold where hook logic activates
      "typical_rest_days": 3,        // inferred from GS vs team schedule density
      "appearance_share": 0.24,      // G / team games — drives relief usage frequency
      "metrics": {"whip": 1.18, "era": 3.02, "ip": 278.1, "g": 36, "gs": 32,
                   "cg": 18, "sho": 3, "sv": 0, "gf": 2, "throws": "R"},
      "retrosheet": null             // reserved: hook-timing dist, usage-by-leverage
    }
  },
  "batters": {
    "<player_id>": {
      "role": "regular | platoon | bench | pinch_specialist",
      "primary_position": "CF",
      "eligible_positions": ["CF", "LF"],   // from Appearances game counts
      "start_share": 0.92,                  // position G / team games
      "metrics": {"obp": 0.486, "slg": 0.772, "ops": 1.258, "bats": "L"},
      "retrosheet": null             // reserved: platoon splits, PH frequency
    }
  },
  "batting_order": ["id1", "...9 ids"],  // recommended order vs default
  "notes": []                            // inference warnings (e.g. ambiguous roles)
}
```

**Inference rules (Lahman-only)**:
- Starters: GS ≥ max(5, 0.08 × team games), ranked by GS then IP →
  rotation slots. Rotation size = era-typical (3–4 pre-1900s handled
  loosely, 4 deadball–1960s, 5 modern) clamped to available arms.
- Closer: max SV if SV ≥ 8 (post-~1969 era where saves are meaningful);
  otherwise highest GF reliever gets `setup`-equivalent trust. Requires
  adding SV/CG/SHO/GF to `PitchingStats` + repo SELECT (Wave 1).
- Swingman: GS ≥ 3 and relief appearances ≥ 25% of G.
- Leash: `leash_bf = (3*IP_outs/3 + H + BB) / GS` (avg batters per start);
  `leash_fatigue` scales with CG rate — a 60% CG pitcher hooks near 0.85
  fatigue, a modern 5-and-dive starter near 0.55.
- Batter roles: start_share ≥ 0.65 → regular; 0.30–0.65 → platoon;
  else bench. `pinch_specialist`: low start_share, meaningful AB count.
- Era rules: DH availability already handled by existing lineup code;
  role card records nothing about DH.

## In-game heuristics (v1 — sim-rewarded signals only)

**Leverage proxy** (pure function, no engine calls):
`leverage(inning, score_diff, outs, runners_on)` — late + close + traffic =
high. Coarse 3-tier output (LOW / MED / HIGH) is enough for v1.

**Pitching change** (checked before each defensive at-bat):
1. Hook check — pull the pitcher when ANY of:
   - `fatigue ≥ leash_fatigue` (role-scaled from artifact), or
   - `times_through_order ≥ 3` AND leverage ≥ MED AND fatigue ≥ 0.45, or
   - blowout-in-progress guard: allowed runs this outing ≥ threshold scaled
     by leash (knocked-out-early → long relief).
2. Reliever selection — filter to available (rest ledger + not yet used +
   `SubstitutionManager` legality), then role-priority by situation:
   - 9th (or extras), leading by 1–3 → closer;
   - 8th, leverage HIGH → setup;
   - starter out before 5th → long_relief/swingman;
   - blowout either way → mop-up (worst-WHIP available reliever);
   - otherwise middle_relief, best WHIP among available.
   - Never burn the closer in LOW leverage; never bring back a used pitcher.

**Pinch-hit** (checked before each offensive at-bat):
- Pitcher's spot due (non-DH game), inning ≥ 6, trailing or tied, leverage ≥
  MED → PH with best-OPS available bench bat (must leave a legal defense:
  v1 restricts to PH-for-pitcher and like-for-like position coverage on the
  bench; otherwise decline).
- Weak regular (OPS below team median − margin) due, inning ≥ 8, leverage
  HIGH, bench bat with OPS advantage ≥ 0.100 and position coverage → PH.
- Respect roles: `regular`s are not lifted for marginal gains; `bench` bats
  with `pinch_specialist` role are preferred pinch hitters.

**Pregame**:
- Starter = lowest rotation_slot among rested starters (rest ledger).
- Batting order = artifact's `batting_order`, filtered for availability;
  falls back to existing `lineup_builder` heuristics for holes.

**Explainability**: every `ManagerDecision` carries a `reason: str`
(e.g. "Hook: 3rd time through, fatigue 0.62, one-run game") surfaced in the
play-by-play log — makes heuristics debuggable and the game more fun.

## Series mode & rest carryover

- `SeriesState` (src/manager/rest.py + src/series/): best_of (3/5/7), game
  results, per-team `RestLedger`.
- `RestLedger`: per pitcher — days since last appearance, BF in each of the
  last 3 games. Availability rules:
  - starter available if days_rest ≥ typical_rest_days (artifact);
  - reliever unavailable after appearances on 2 consecutive days, or > 2×
    typical BF yesterday;
  - position players always available (v1).
- Series games are assumed on consecutive days (no travel days in v1).
- Single-game exhibition = fresh ledger (everyone rested) — current behavior.
- Ledger is a plain serializable dataclass → future season mode persists it;
  series mode keeps it in memory on the series controller.
- Flow: mode select → team select → per-game loop (pregame decisions →
  GameScreen → result into ledger/series record → series status screen) →
  series end screen.

## Plan breakdown

### Wave 1 — foundations (parallelizable)

- **08-01 Data layer: pitching role fields.**
  Add `saves, complete_games, shutouts, games_finished` to `PitchingStats`
  (models.py) and the repo SELECT (lahman.py:150–168). Tests against known
  seasons (e.g. 2016 CHN Chapman SV, 1927 NYA Hoyt CG).
  Files: `src/data/models.py`, `src/data/lahman.py`, `tests/test_data_layer.py`.

- **08-02 Role artifact: schema + inference + CLI.**
  `src/manager/roles.py` (dataclasses, JSON round-trip, schema_version),
  role inference from Lahman per rules above, `scripts/build_roles.py
  <TEAM> <YEAR> [--all-teams] [--force]` writing `data/roles/`.
  Golden tests: 1927 NYA (4-man rotation, huge leashes, no closer) and
  2016 CHN (5-man rotation, Chapman closer, short leashes) — assert role
  assignments and leash ranges, not exact floats.
  Files: `src/manager/roles.py`, `src/manager/inference.py`,
  `scripts/build_roles.py`, `tests/test_roles.py`. Depends on: 08-01.

### Wave 2 — manager core (pure logic, no TUI)

- **08-03 Manager decisions.**
  `src/manager/view.py` (`ManagerGameView`, `ManagerDecision` types),
  `src/manager/heuristics.py` (leverage proxy, hook check, reliever
  selection, pinch-hit logic — all pure functions),
  `src/manager/manager.py` (`ManagerAI.decide_defense(view) ->
  Optional[PitchingChange]`, `decide_offense(view) -> Optional[PinchHit]`,
  `build_pregame(view) -> SetLineup`). Exhaustive unit tests: table-driven
  scenarios (fatigued starter/3rd TTO/closer situation/blowout/no legal PH).
  Deterministic tie-breaking asserted.
  Files: `src/manager/{view,heuristics,manager}.py`, `tests/test_manager_*.py`.
  Depends on: 08-02 (role card shape).

- **08-04 Rest ledger + series state.**
  `src/manager/rest.py` (`RestLedger`, availability rules, serialization),
  `src/series/state.py` (`SeriesState`, win tracking, game advance).
  Pure unit tests (starter skips a start on short rest; reliever sits after
  back-to-backs; best-of-5 ends at 3 wins).
  Files: `src/manager/rest.py`, `src/series/state.py`, tests.
  Depends on: 08-02.

### Wave 3 — integration

- **08-05 TUI: AI-managed game.**
  Mode-select + AI-toggle in setup flow (`SetupFlow.begin` gains a leading
  modal; `on_complete`/`_launch_game`/`GameScreen.__init__` widen to carry
  a `GameConfig`), `src/tui/manager_adapter.py` (build view, apply
  decisions via `make_substitution`), manager hook in
  `GameScreen._advance_one` before `resolve_pitcher_stats`, decision
  `reason` lines in play-by-play, auto starter/lineup for AI sides (skip
  the pitcher-select modal), setup-flow prompt when a role artifact is
  missing for an AI-managed team. Fast-forward path exercises the same
  hook (it calls `_advance_one`).
  Files: `src/tui/setup_flow.py`, `src/tui/app.py`,
  `src/tui/screens/game_screen.py`, `src/tui/manager_adapter.py`,
  new mode-select screen, tests following the SimpleNamespace pattern
  from `test_game_screen_substitutions.py`. Depends on: 08-03.

- **08-06 TUI: series flow.**
  Series controller above GameScreen (owns `SeriesState` + both
  `RestLedger`s), between-games status screen (line scores, series record,
  probable starters), end-of-series screen, ledger updates from box-score
  data on game completion, replay/new-series wiring in `restart_setup`.
  Files: `src/series/controller.py`, new screens, `src/tui/app.py`, tests.
  Depends on: 08-04, 08-05.

### Wave 4 — verification & docs

- **08-07 End-to-end sanity + human verification.**
  Headless AI-vs-AI auto-sim harness (drive `_advance_one`-equivalent loop
  or extend `simulate_game` to honor manager + GameState pitcher tracking)
  running ~100 games for two era pairs; assert usage sanity bands:
  1927 starters average ≥ 7 IP with frequent CG; 2016 starters average
  5–7 IP, closer appears mostly in save situations, no pitcher re-entry,
  series rest rules never violated. Human check via tmux (per project
  convention) of one full best-of-3. Update ROADMAP.md Phase 8 entry and
  REQUIREMENTS.md with MGR-*/SER-* requirement IDs.
  Depends on: 08-06.

## Success criteria (what must be TRUE)

1. `scripts/build_roles.py NYA 1927` emits an artifact where the rotation,
   leashes, and bullpen roles match that team's historical usage shape.
2. In an AI-managed game, pitching changes and pinch-hits occur at
   sim-justified moments (fatigue/TTO/leverage) with era-appropriate leashes,
   each with a visible reason in the play-by-play.
3. The AI never proposes an illegal substitution (`SubstitutionManager`
   rules hold: no re-entry, DH rules respected).
4. A best-of-N series carries pitcher rest between games: game 2's starter
   is the #2 rotation slot, a heavily-used reliever sits the next day.
5. `src/manager/` has zero imports from `src/simulation/` or `src/game/`
   (enforced by a test).
6. Manual play (both teams human) is unchanged; single-game exhibition
   works with no role artifact present.

## Deferred (roadmap, post-v1)

- Platoon L/R heuristics + sim handedness modeling (era-average platoon
  adjustment keyed on bats/throws).
- Defensive-replacement heuristics + fielder-quality sim effect (Lahman
  Fielding table — currently unread).
- Pinch-running + baserunning speed model; steals/bunts/IBB as manager
  decisions once the sim models them.
- Retrosheet ingestion → `retrosheet` blocks in the role artifact (real
  hook-timing distributions, platoon splits, PH tendencies).
- LLM-assisted role adjudication in the offline pass (ambiguous swingman /
  spot-starter cases).
- Season mode reusing `RestLedger`/`SeriesState` persistence.
