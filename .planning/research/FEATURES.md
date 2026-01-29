# Feature Research

**Domain:** Baseball Simulation Games
**Researched:** 2026-01-28
**Confidence:** MEDIUM

## Feature Landscape

### Table Stakes (Users Expect These)

Features users assume exist. Missing these = product feels incomplete.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Statistical accuracy | All modern sims use real player stats; users expect outcomes based on historical data | MEDIUM | Requires stat lookup from Lahman DB and probability calculations |
| Lineup management | Core management task in all baseball games from OOTP to Strat-O-Matic | LOW | Setting batting order, defensive positions |
| Pitching changes | Fundamental in-game decision; present in every simulator reviewed | LOW | Requires pitcher fatigue tracking, bullpen roster |
| At-bat-by-at-bat progression | Users expect to see each plate appearance, not just game summaries | MEDIUM | Text-based play-by-play, outcome generation |
| Pinch hitters | Standard baseball strategy; absent in only the most basic simulations | LOW | Requires bench management, player substitution |
| Realistic game flow | Innings, outs, baserunners, runs - users expect proper baseball structure | MEDIUM | State machine for game progression |
| Box score / game summary | Every simulator provides final stats; users expect to review what happened | LOW | Track player stats during game, display at end |
| Historical rosters | Games like APBA, OOTP, Baseball Mogul all support playing any season 1900+ | LOW | Already have Lahman DB with historical data |

### Differentiators (Competitive Advantage)

Features that set the product apart. Not expected, but valued.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Terminal-based interface (TUI) | Lightweight, fast, works over SSH, nostalgic for command-line users | MEDIUM | Textual framework provides foundation; unique in modern market |
| Instant startup | No loading screens, no graphics engine, immediate gameplay | LOW | Natural benefit of text-based design |
| Single-game focus | Most sims try to be "everything" - seasons, franchises, etc. Laser focus on one game at a time | LOW | Intentional scope limitation becomes differentiator |
| Play-by-play narrative | Textual description of action creates mental theater vs passive stat watching | MEDIUM | Rich text generation, varied descriptions per outcome type |
| Historical matchup mode | "What if 1927 Yankees played 1975 Reds?" - taps into nostalgia and debate | LOW | Already have data; just need team selection UI |
| Defensive positioning | Diamond Mind and APBA have this; OOTP has it; differentiates from simpler sims | MEDIUM | Field depth settings, shifts affect hit probabilities |
| Situational hitting strategies | Hit-and-run, sacrifice bunt, stealing - gives tactical depth | MEDIUM | Multiple decision points, outcome probability modifications |
| Ballpark effects | Different stadiums affect doubles, homers (per research on environmental factors) | MEDIUM | Requires ballpark data, outcome probability adjustments |
| Real-time decision tension | Game pauses for key decisions (pinch hit now? bring in closer?) creates engagement | LOW | Natural with at-bat-by-at-bat pacing |

### Anti-Features (Commonly Requested, Often Problematic)

Features that seem good but create problems.

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| Full season simulation | "I want to play 162 games!" | Becomes repetitive grind; most users abandon after 20 games; creates fatigue feature pressure | Offer tournament modes (playoffs), short series, exhibition games |
| Graphics/animations | "Text is boring, add visuals!" | Destroys TUI advantage; requires massive complexity; slow rendering; loses SSH capability | Rich text descriptions that create mental theater; ASCII diamond diagrams |
| Franchise mode with finances | "Let me be GM with budget!" | Scope explosion; requires offseason, contracts, salary cap, trades - becomes different game | Focus on in-game management; single game at a time keeps scope tight |
| Multiplayer/online play | "Let me play against friends!" | Requires networking, matchmaking, synchronization, anti-cheat; maintenance burden | Hot-seat mode (pass keyboard) much simpler; focus on AI opponent quality |
| Real-time MLB data integration | "Update with today's stats!" | API dependencies, data licensing, staleness issues, internet requirement | Ship with complete Lahman historical DB; add current season manually in updates |
| Complex injury system | Diamond Mind has "Advanced Injury Management" | Adds RNG frustration without strategic depth; users hate losing stars to random chance in single games | Simple fatigue system for pitchers only; injuries irrelevant in single-game context |
| 3D physics engine | "Simulate ball trajectory!" | Massive complexity; no value over probability-based outcomes; performance hit | Probability-based outcomes from historical data are more accurate anyway |

## Feature Dependencies

```
[Statistical Engine]
    └──requires──> [Lahman Database Access]
                       └──requires──> [SQLite Integration]

[At-bat Simulation]
    └──requires──> [Statistical Engine]
    └──requires──> [Game State Management]
                       └──requires──> [Baserunner Tracking]
                       └──requires──> [Score Tracking]
                       └──requires──> [Out Counting]

[Lineup Management]
    └──requires──> [Team Roster Data]
    └──enables──> [Pinch Hitting]
    └──enables──> [Defensive Positioning]

[Pitching Changes]
    └──requires──> [Pitcher Fatigue Tracking]
    └──requires──> [Bullpen Roster]

[Situational Strategies]
    └──requires──> [At-bat Simulation]
    └──requires──> [Game State Management]
    └──enhances──> [Play-by-play Narrative]

[Ballpark Effects]
    └──requires──> [Statistical Engine]
    └──enhances──> [At-bat Simulation]

[Historical Matchups]
    └──requires──> [Team Selection UI]
    └──requires──> [Historical Rosters]
```

### Dependency Notes

- **Statistical Engine requires Lahman Database:** All outcome probabilities derive from historical player stats in the database
- **At-bat Simulation requires Game State:** Can't determine outcomes without knowing baserunners, outs, score, inning
- **Situational Strategies enhance Play-by-play:** Strategic decisions make narrative more engaging (stealing attempt creates tension)
- **Ballpark Effects enhance At-bat Simulation:** Environmental factors modify outcome probabilities but aren't core requirement
- **Pitching Changes require Fatigue Tracking:** Without fatigue model, no reason to change pitchers

## MVP Definition

### Launch With (v1)

Minimum viable product - what's needed to validate the concept.

- [ ] At-bat-by-at-bat game simulation - Essential: This IS the product
- [ ] Statistical outcome engine using Lahman data - Essential: Core value proposition is realism
- [ ] Lineup setting (batting order + positions) - Essential: Table stakes; users expect this control
- [ ] Pitching changes - Essential: Table stakes; fundamental baseball decision
- [ ] Pinch hitting - Essential: Table stakes; standard substitution strategy
- [ ] Play-by-play text narrative - Essential: Differentiator; creates engagement in TUI context
- [ ] Basic game state tracking (score, inning, outs, baserunners) - Essential: Can't play baseball without this
- [ ] Team/year selection from Lahman DB - Essential: Enables historical matchups (differentiator)

### Add After Validation (v1.x)

Features to add once core is working.

- [ ] Situational strategies (steal, bunt, hit-and-run) - Add when users request more tactical depth
- [ ] Defensive positioning (shift infield, outfield depth) - Add when users want defensive control
- [ ] Ballpark effects - Add when users notice home field doesn't matter
- [ ] Pitcher fatigue visualization - Add when users can't tell when to change pitchers
- [ ] Box score with detailed stats - Add when users want to review performance
- [ ] Save/load game state - Add when users want to pause mid-game
- [ ] AI manager opponent - Add when users want to sim without decisions

### Future Consideration (v2+)

Features to defer until product-market fit is established.

- [ ] Tournament/playoff modes - Why defer: Multi-game modes add complexity; validate single-game first
- [ ] Hot-seat multiplayer - Why defer: Requires input state management; focus on solo play first
- [ ] Custom leagues/teams - Why defer: Edge case; historical teams provide plenty of content
- [ ] Advanced statistics (WAR, BABIP, etc.) - Why defer: Doesn't affect gameplay; display feature only
- [ ] Replay system - Why defer: Nice-to-have; doesn't affect core loop
- [ ] Configurable simulation rules - Why defer: Adds complexity; default rules work for 99% of users

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| At-bat simulation engine | HIGH | HIGH | P1 |
| Statistical outcome generation | HIGH | MEDIUM | P1 |
| Lineup management UI | HIGH | MEDIUM | P1 |
| Play-by-play narrative | HIGH | MEDIUM | P1 |
| Game state tracking | HIGH | MEDIUM | P1 |
| Pitching changes | HIGH | LOW | P1 |
| Pinch hitting | HIGH | LOW | P1 |
| Team/year selection | HIGH | LOW | P1 |
| Situational strategies | MEDIUM | MEDIUM | P2 |
| Defensive positioning | MEDIUM | MEDIUM | P2 |
| Ballpark effects | MEDIUM | LOW | P2 |
| Box score display | MEDIUM | LOW | P2 |
| Pitcher fatigue tracking | MEDIUM | LOW | P2 |
| Save/load game | MEDIUM | MEDIUM | P2 |
| AI manager mode | LOW | HIGH | P3 |
| Tournament modes | LOW | HIGH | P3 |
| Hot-seat multiplayer | LOW | MEDIUM | P3 |
| Advanced statistics | LOW | MEDIUM | P3 |
| Custom teams | LOW | HIGH | P3 |

**Priority key:**
- P1: Must have for launch
- P2: Should have, add when possible
- P3: Nice to have, future consideration

## Competitor Feature Analysis

| Feature | OOTP 26 | Diamond Mind | Strat-O-Matic | Baseball Mogul | APBA | Our TUI Sim |
|---------|---------|--------------|---------------|----------------|------|-------------|
| Historical rosters | Full 1871+ | 1919-2025 | All seasons | 1901-present | 1901+ | Full via Lahman |
| Statistical accuracy | High (licensed) | Pitch-by-pitch | Card-based | Pitch simulation | Card-based | High via Lahman |
| Lineup management | Full | Full | Full | Full | Full | Basic (v1) |
| In-game decisions | Full | Full | Full | Variable control | Full | Core set (v1) |
| Franchise mode | Complex | No | Limited | Full | No | NO (anti-feature) |
| Graphics/UI | Windows GUI | Windows GUI | Windows GUI | Windows GUI | Windows GUI | Terminal/TUI |
| Ballpark effects | Yes | Yes | Basic | Yes | No | Future (v2) |
| Multiplayer | Online leagues | No | Netplay | No | Hot-seat | Future (v3) |
| Price | $49.99 | $40+ | $40+ | $35+ | $35+ | Open source/Free |
| Platform | Win/Mac/Linux | Windows | Windows | Win/Mac | Windows | Any (Python/TUI) |
| Startup time | 30+ seconds | Long | Moderate | Long | Moderate | Instant |
| Installation | Heavy | Heavy | Heavy | Heavy | Heavy | Lightweight |
| Learning curve | Steep | Moderate | Moderate | Steep | Gentle | Gentle |

**Our Competitive Advantages:**
1. **Terminal-based**: Works over SSH, lightweight, instant startup
2. **Single-game focus**: No complexity overload; laser-focused experience
3. **Free/open source**: No $40-50 price barrier
4. **Cross-platform by design**: Python + TUI works everywhere
5. **Historical matchups**: Easy "1927 Yankees vs 1975 Reds" fantasy games
6. **Instant engagement**: No franchise setup overhead; pick teams and play

**Where We Intentionally Trail:**
- No franchise/season management (anti-feature for v1)
- No complex financial simulation (anti-feature)
- No graphics/animations (architectural choice)
- No multiplayer initially (defer to v3)
- Simpler UI than full-featured Windows apps (acceptable tradeoff)

## Sources

**Official Game Sites:**
- [Out of the Park Baseball 26](https://www.ootpdevelopments.com/out-of-the-park-baseball-home/)
- [OOTP 26 on Steam](https://store.steampowered.com/app/3116890/Out_of_the_Park_Baseball_26/)
- [Diamond Mind Baseball](https://diamond-mind.com/)
- [Strat-O-Matic Baseball](https://www.strat-o-matic.com/baseball-digital-games/)
- [Baseball Mogul](https://www.sportsmogul.com/baseballmogul.html)
- [APBA Baseball](https://www.apbagames.com/baseball-game)

**Feature Analysis:**
- [Best MLB Baseball Manager Games](https://gmgames.org/section/mlb-baseball-manager-simulator-games/)
- [10 Greatest Baseball Simulators](https://www.liveabout.com/top-baseball-simulators-321141)
- [The Future of Baseball Gaming Simulations (SABR)](https://sabr.org/journal/article/the-future-of-baseball-gaming-simulations/)

**Design Insights:**
- [10 Lessons from Creating a Baseball Simulator (The Hardball Times)](https://tht.fangraphs.com/10-lessons-i-learned-from-creating-a-baseball-simulator/)
- [So You Want to Build a Baseball Sim? (DraftKick)](https://draftkick.com/blog/so-you-want-to-build-a-baseball-sim/)
- [Strategic Baseball Simulator](https://sbs-baseball.com/)
- [Python Baseball Simulator (GitHub)](https://github.com/benryan03/Baseball-Simulator)

**Academic Research:**
- [Baseball Simulation: Technology-Mediated Stimuli and Telepresence](https://www.tandfonline.com/doi/full/10.1080/24704067.2023.2209870)

---
*Feature research for: Terminal-based Baseball Simulation Game*
*Researched: 2026-01-28*
*Confidence: MEDIUM - Based on web research of competitor products and community discussions; features verified across multiple sources but not through hands-on product testing*
