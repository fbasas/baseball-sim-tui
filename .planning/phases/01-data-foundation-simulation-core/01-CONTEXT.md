# Phase 1: Data Foundation & Simulation Core - Context

**Gathered:** 2026-01-28
**Status:** Ready for planning

<domain>
## Phase Boundary

Load Lahman database (1901+) and implement statistically accurate at-bat simulation using odds-ratio method. Produces detailed outcome data including hit types, batted ball location, fielding errors, stolen bases, and runner advancement. Supports cross-era matchups with era adjustment.

</domain>

<decisions>
## Implementation Decisions

### Outcome Granularity
- Full detail hit types: single, double, triple, home run
- Batted ball types: groundout, flyout, lineout, popup
- Track batted ball direction: left/center/right field
- Distinguish infield hits from outfield singles
- Simulate stolen base attempts based on runner/catcher/pitcher stats
- Simulate fielding errors as distinct outcomes (batter reaches on error tracked separately)
- Track wild pitches and passed balls separately (can advance runners)
- Hit-by-pitch as distinct outcome
- Track sacrifice flies and sacrifice bunts separately (matters for BA calculation)
- Track ground into double play (GIDP) as explicit outcome
- Distinguish swinging strikeout (K) from called strikeout (Kc)
- Track foul outs separately from other flyouts/popups
- Intentional walks folded into regular walks (not tracked separately)
- Skip rare outcomes: catcher's interference, batter's interference, fielder obstruction
- Bunts deferred to Phase 4 (requires situational AI for managerial decisions)
- Count at end of at-bat NOT tracked (narrative can embellish later)
- Runner advancement determined in Phase 1 (simulation outputs exact advancement)

### Statistical Realism
- Use league average fallback for missing/incomplete player data (era-appropriate)
- Natural variance in outcomes (same matchup can produce different results)
- Era-adjusted stats: park factors and era normalization applied
- Cross-era matchups: 1920s stats adjusted to be comparable with modern stats
- Target accuracy: within 10% of historical rates for 1000-game simulations

### Data Scope
- Modern era support: 1901 onward (American League founding)
- All players available regardless of plate appearance count (use league avg for gaps)
- Database bundled with app (works offline immediately)
- Cross-era matchups supported (any player from any year can face any other)
- Both historical rosters AND custom "All-Star" team building supported
- MLB only (no minor league data)
- Season-specific player versions: select "Babe Ruth 1927" vs "Babe Ruth 1921"

### Simulation Transparency
- Return full probability breakdowns with outcomes (HR 8%, 2B 12%, K 22%, etc.)
- Explain factors affecting probabilities (pitcher fatigue, park factor, handedness, etc.)
- Audit trail: log random values and thresholds for each at-bat (verify fairness)
- Expose computed ratings: power rating, contact rating derived from raw stats
- Expected value API: get expected outcome without rolling (Ruth vs Johnson: .285 AVG)
- Track cumulative live stats during game (Ruth: 2-for-3, 1 HR, 2 RBI)

### Claude's Discretion
- Exact odds-ratio algorithm implementation
- Database schema design
- Park factor calculation method
- Era adjustment formula specifics
- Probability distribution implementation
- Random number generation approach

</decisions>

<specifics>
## Specific Ideas

- "What if" scenarios across baseball history are the core value proposition
- Simulation should feel like real baseball unpredictability while matching historical averages
- Transparency into simulation mechanics is important for user trust and education

</specifics>

<deferred>
## Deferred Ideas

- Bunts and bunt strategies — Phase 4 (requires managerial AI)
- Pitch count at end of at-bat — could add later for narrative depth
- Minor league data — could expand scope later if demand

</deferred>

---

*Phase: 01-data-foundation-simulation-core*
*Context gathered: 2026-01-28*
