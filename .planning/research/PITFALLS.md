# Pitfalls Research

**Domain:** Baseball Simulation (Terminal-based TUI)
**Researched:** 2026-01-28
**Confidence:** HIGH

## Critical Pitfalls

### Pitfall 1: Naive Pitcher-Batter Matchup Averaging

**What goes wrong:**
Simply averaging pitcher and batter statistics produces catastrophically wrong outcomes. A strikeout-prone pitcher (30% K rate) facing a contact hitter (10% K rate) should not produce 20% strikeouts. The probabilities must be combined using proper statistical methods that preserve the multiplicative nature of pitcher-batter interactions.

**Why it happens:**
Averaging seems intuitive and is simpler to implement. Developers underestimate the complexity of combining opposing probabilities correctly. The temptation is to take shortcuts during MVP development.

**How to avoid:**
Use the Odds Ratio method with chained binomial logic to maintain probabilistic validity across multiple outcome categories. This properly accounts for the multiplicative interaction between pitcher skill and batter skill while preserving the overall statistical distributions.

**Warning signs:**
- Simulation produces league-average results regardless of matchup quality
- Elite pitchers don't dominate weak hitters as expected
- Statistical tests show simulated K%, BB%, or hit rates diverge from player season totals
- Extreme players (high strikeout pitchers, low contact hitters) produce unrealistic results

**Phase to address:**
Phase 1 (Simulation Engine Core) - This is foundational. Getting the pitcher-batter matchup algorithm wrong invalidates everything built on top of it.

---

### Pitfall 2: Wrong Simulation Granularity (Variance Collapse)

**What goes wrong:**
Models can satisfy expected value requirements while producing absurd variance. Example: simulating an entire season with a single roll gives correct batting average expectations but assigns "roughly a 35 percent chance of Ramirez batting 1.000 for a season, which is patently absurd." Conversely, too fine-grained simulation (pitch-by-pitch when only at-bat stats available) introduces fabricated variance.

**Why it happens:**
Developers focus on getting expected values correct without validating variance. Statistical testing of variance is skipped during development. The discrete event choices (at-bat vs. pitch vs. entire game) seem like implementation details rather than fundamental design decisions.

**How to avoid:**
Choose granularity that matches available data precision. For Lahman database (seasonal stats only), at-bat level simulation is appropriate. Validate both expected value AND variance against historical distributions. Test: "Can Mike Trout's simulated full season reasonably vary between .360 and .420 wOBA?" (yes), but "Can he bat 1.000 or .000?" (no).

**Warning signs:**
- Player season simulations produce results outside plausible ranges
- Variance in simulated outcomes is either too tight (deterministic feel) or too wide (unrealistic extremes)
- 162-game season simulations for .500 team cluster around 81 wins instead of spreading 70-92
- Individual game outcomes feel scripted rather than variable

**Phase to address:**
Phase 1 (Simulation Engine Core) - Granularity is a foundational architecture decision. Also Phase 5 (Validation Testing) - variance validation must be part of acceptance testing.

---

### Pitfall 3: Ignoring Platoon Splits and Handedness

**What goes wrong:**
Most hitters perform significantly better against pitchers of the opposite hand. Ignoring this creates unrealistic outcomes, especially for extreme platoon players. Baseball Reference and many systems don't even account for handedness in park factors, compounding the error. Sample size issues arise because players with severe platoon splits often don't face same-handed pitching, creating selection bias in available data.

**Why it happens:**
Lahman database doesn't include platoon splits by default - you only get overall season statistics. Adding handedness splits requires external data sources or approximation methods. The added complexity seems optional for MVP, leading to deferral.

**How to avoid:**
Either acquire platoon split data from sources beyond Lahman (Retrosheet, FanGraphs) or implement approximation algorithms based on handedness. At minimum, track batter handedness and pitcher handedness, applying league-average platoon adjustments (roughly 70/30 weighting for RHP vs LHP frequency). Document the limitation clearly if using approximations.

**Warning signs:**
- Switch hitters show no performance difference across at-bats
- Historical matchups don't reflect known platoon advantages
- Extreme platoon specialists (e.g., players with .900 OPS vs RHP, .600 vs LHP) perform at season averages
- Simulation doesn't incentivize strategic pitching changes or pinch-hitting based on handedness

**Phase to address:**
Phase 2 (Enhanced Realism) - Can ship MVP without this if documented, but quality simulation requires it. Alternatively, Phase 1 if you can acquire split data upfront.

---

### Pitfall 4: Defensive Metrics Black Hole

**What goes wrong:**
Defense is notoriously difficult to measure accurately. Traditional fielding percentage is "highly subjective" and "doesn't account for range - you can't be charged with an error on a ball you didn't have the skills to reach." Advanced metrics (UZR, DRS) are "notoriously inconsistent, disagreeing both with each other's ratings over the course of a season and with their own rankings from year to year" and "can be befuddled by heavy shifting." Sample sizes are tiny - "a pretty small number of difficult batted balls hit to every fielder each year" means luck dominates.

**Why it happens:**
Developers underestimate how bad defensive data is, especially in historical databases. The temptation to include defensive skill creates more noise than signal. There are "questions about the data quality, as yet unresolved" even in modern metrics.

**How to avoid:**
For v1, use league-average defense or position-based defensive expectations rather than individual fielder ratings. Document this explicitly: "Defensive skill not modeled - all fielders perform at positional average." If you must include defense, use multi-year averages and accept high uncertainty. Never use single-season fielding percentage or error rates as skill indicators.

**Warning signs:**
- Defensive ratings produce wild season-to-season swings
- Players with identical defensive reputations show vastly different simulation outcomes
- Error rates don't correlate with scouting reports or other defensive measures
- Gold Glove winners and replacement-level fielders perform similarly in simulation

**Phase to address:**
Out of scope for v1. If added in v2+, treat as low-confidence experimental feature requiring extensive validation.

---

### Pitfall 5: Forgetting the Times Through Order Penalty (TTOP)

**What goes wrong:**
Research shows batters improve against pitchers the more times they face them in a game, but the cause is debated. Is it fatigue or familiarity? "The TTOP is not about fatigue. It is about familiarity." However, "pitch count is the real culprit in stealing pitchers' mojo." Using simplistic "starter gets 6 innings" rules produces unrealistic bullpen usage and pitcher effectiveness patterns.

**Why it happens:**
Pitcher stamina seems like a simple linear degradation model, but reality is more complex. Developers implement "fatigue = innings pitched" without considering pitch count, times through order, or batter learning effects. The statistical evidence for TTOP is nuanced - "little evidence of strong discontinuity...after adjusting for confounders."

**How to avoid:**
Model pitcher effectiveness based on pitch count (primary) and times through order (secondary). Don't treat TTOP as deterministic - use probabilistic degradation. Allow variance in pitcher stamina (some tire quickly, others are workhorses). For MVP, a simple pitch count threshold (80-100 pitches) with gradual effectiveness decay is acceptable. Document whether you're modeling fatigue, familiarity, or both.

**Warning signs:**
- All pitchers tire at identical rates
- Complete games occur at unrealistic frequencies (too high or too low)
- No relationship between pitch count and performance degradation
- Third time through the order shows identical results to first time
- Simulation doesn't incentivize bullpen management decisions

**Phase to address:**
Phase 2 or 3 (Pitching Changes / Advanced Mechanics) - Not critical for basic simulation but important for managerial decision realism.

---

### Pitfall 6: Overfitting to Historical Outliers

**What goes wrong:**
Training simulation algorithms on specific seasons or player performances can create models that reproduce those results but fail on different datasets. "A disproportionally higher training versus testing accuracy is indicative of overfitting." The outcome of any single MLB game contains "unadulterated luck" with "inevitable variance" - even the best prediction models only achieve 57-59.5% accuracy.

**Why it happens:**
Developers tune parameters until simulated 1927 Yankees match historical win totals, inadvertently encoding season-specific randomness as skill. Small sample sizes for rare events (triples, caught stealing) lead to parameter instability. No train/test split discipline applied to simulation validation.

**How to avoid:**
Validate against multiple seasons and eras, not just one. Use 90/10 or 80/20 train/test split - tune on 1920s-1980s, validate on 1990s-2020s. Accept that models cannot and should not reproduce exact historical outcomes - if 1927 Yankees went 110-44, simulations should produce a distribution centered around their talent level (maybe 105-115 wins), not always exactly 110. Test on holdout seasons before declaring validation complete.

**Warning signs:**
- Model performs much better on tuning data than test data
- Different parameter values produce identical results on training set
- Simulation reproduces exact historical seasons with high frequency
- Changing random seed doesn't change season outcomes meaningfully
- Model parameters have implausibly precise values (0.2847 rather than ~0.28)

**Phase to address:**
Phase 5 (Validation & Testing) - Build validation framework early, but comprehensive overfitting tests come during final validation.

---

### Pitfall 7: Data Quality Blind Spots in Lahman Database

**What goes wrong:**
Lahman database has "errors (very few)" and "little nice imperfections" including "a primary key missing, an unenforceable foreign key, or missing records, outdated documentation." More critically, "data is available only for single seasons - the database cannot provide granular sub-season data like monthly performance splits." Early baseball eras (pre-1920) have incomplete data with different statistical tracking standards.

**Why it happens:**
Developers assume "comprehensive historical database" means "perfect data." The bundled SQLite version may not match latest Lahman releases. Documentation lags behind data changes. Data quality varies dramatically by era - 2020s data is much cleaner than 1880s.

**How to avoid:**
Implement data quality checks on database load: verify primary keys, check for null values in critical fields, validate year ranges. Handle missing data gracefully with fallback strategies (e.g., use league averages for missing platoon splits). Document data quality by era: "pre-1920 simulations use incomplete fielding data." Don't silently fail on data errors - warn users when data quality is questionable.

**Warning signs:**
- Application crashes on specific teams or years
- Missing players in lineup selection screens
- Statistics that seem wildly off (0.000 or 1.000 rates where unrealistic)
- Inconsistent data between related tables (player appears in Batting but not People)
- Foreign key references to non-existent records

**Phase to address:**
Phase 1 (Data Layer) - Data validation is foundational. Also Phase 5 (Testing) - validate against multiple eras systematically.

---

### Pitfall 8: Edge Case Rule Implementation Gaps

**What goes wrong:**
Baseball has numerous edge cases that seem rare but compound over a season: intentional walks where batter swings (happened 12 times 1900-2011, including a Gary Sanchez sacrifice fly), sacrifice fly rules, double switches, pinch-running restrictions, caught stealing vs. fielder's choice distinction, balks, interference calls. Each edge case omitted creates a tiny realism leak, and dozens of tiny leaks destroy immersion.

**Why it happens:**
Developers focus on common paths (single, strikeout, walk) and treat edge cases as "we'll add that later." Documentation of official scoring rules is dense and scattered. The interaction between rules creates combinatorial complexity. Testing doesn't cover edge cases systematically.

**How to avoid:**
Create comprehensive edge case test suite early using actual historical plays as test cases. Reference official scoring rules (Rule 9.07 for SB/CS, Rule 2-31 for sacrifices, etc.) when implementing features. Maintain an "edge case registry" documenting which scenarios are handled vs. not implemented. For v1, it's acceptable to simplify (no balks, no interference) if documented clearly.

**Warning signs:**
- Play-by-play descriptions say impossible things ("runner scored on strikeout")
- Statistics don't match actual statistical definitions (sacrifice flies counted as at-bats)
- Users discover "if I do X then Y happens incorrectly"
- No testing for multi-runner scenarios
- Baserunner advancement logic has unexplained special cases

**Phase to address:**
Ongoing across all phases - each feature needs edge case analysis. Create edge case test registry in Phase 1, expand throughout development.

---

### Pitfall 9: Pacing Mismatch (Too Slow or Too Fast)

**What goes wrong:**
Strat-O-Matic baseball, despite incredible accuracy, can have "a single game take longer to play than an actual 162-game season" with full manual play. Conversely, instant simulation removes all tension and decision-making opportunities. Terminal UI compounds this - reading play-by-play in a scrolling log is slower than visually tracking a diamond diagram, but not having enough information makes decisions feel arbitrary.

**Why it happens:**
Developers optimize for either realism (show everything, maximum detail) or speed (instant results). The middle ground of "engaging pace" requires careful UX design. Text-based interfaces lack visual shortcuts, making information hierarchy critical. User control over pace is overlooked - some want to savor every at-bat, others want to sim to decision points.

**How to avoid:**
Provide pace control: "Step through at-bats," "Auto-play to inning end," "Sim to decision point," "Instant finish." Use information layering - summary view by default, details on request. For v1 terminal UI, aim for 20-30 seconds per inning when auto-playing (Deadball's 20 minutes for a full game is a good benchmark). Test with actual play sessions - if reading play-by-play takes longer than real baseball, it's too slow.

**Warning signs:**
- Playtesting reveals users skipping/skimming play-by-play text
- Games take 30+ minutes to complete even with automation
- Users ask "can I just see the final score?"
- Conversely: users complain they missed what happened
- Decision points arrive before users understand game state
- No ability to review previous plays/decisions

**Phase to address:**
Phase 4 (Dashboard UI) - Pacing is primarily a UI/UX concern. However, simulation architecture (Phase 1) should support variable speeds from the start.

---

### Pitfall 10: Regression to Mean Blindness

**What goes wrong:**
"Regression toward the mean accounts for the fact that you can observe outcomes that are not in line with a player's true talent simply due to randomness." Simulations that don't account for regression will overvalue career-year performances and undervalue down years, creating unrealistic projection distributions. A .350 batting average season is likely regression candidate, not new talent level.

**Why it happens:**
Lahman provides single-season statistics, making it easy to treat each season as "true talent" rather than "talent + variance." Regression to mean requires choosing a population mean and regression coefficient, both non-obvious. Statistical rigor during validation is lacking - developers trust that historical stats = skill.

**How to avoid:**
For projection-based features (if added), apply regression to mean using multi-year averages or Bayesian shrinkage toward population means. For basic simulation using seasonal stats, document that you're simulating "the player as they performed that season" not "the player's true talent." If validating simulations, expect variance - a .300 hitter's simulated season can reasonably vary .250-.350, and that's correct, not a bug.

**Warning signs:**
- No variance in repeated simulations of same player/season matchup
- Career outlier seasons (fluke .320 hitter normally .260) perform at outlier level consistently
- Projection systems show no awareness of sample size (100 PA treated same as 600 PA)
- Early season small samples treated as definitive skill measures

**Phase to address:**
Phase 5 (Validation) - Understanding regression to mean is critical for interpreting validation results. If building projection system (v2+), Phase 1 of that effort.

---

## Technical Debt Patterns

Shortcuts that seem reasonable but create long-term problems.

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Using league averages for all players | No player data loading required | Completely non-personalized, no strategic decisions matter | Never - invalidates core value proposition |
| Skipping platoon splits | Simpler data model, single stats per player | Unrealistic matchups, no handedness strategy | MVP only if documented limitation |
| Linear pitcher fatigue (innings = stamina %) | Easy to implement, intuitive | Ignores pitch counts, times through order, individual differences | Acceptable for v1 with plan to enhance |
| Position-average defense for all players | Avoids bad defensive data | Removes defensive skill differentiation | Recommended for v1 given data quality issues |
| Hardcoded baserunner advancement rules | Fast execution, deterministic | Can't model baserunning skill, stealing, aggressive coaching | Acceptable for v1 (baserunning deferred to v2) |
| No park factors | Reduces data requirements | Coors Field = Dodger Stadium unrealistically | Defer to v2, but get architecture ready |
| Skipping double switches | Avoid complex substitution logic | National League strategy opportunities missing | Acceptable omission if documented |
| No validation framework | Ship faster | Can't prove accuracy, bugs hide in statistical noise | Never - build validation early |

## Performance Traps

Patterns that work at small scale but fail as usage grows.

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Loading entire Lahman DB into memory | Fast queries during development | Memory bloat, slow startup | Full database is 50MB+ when loaded |
| Recalculating league averages every at-bat | Works fine for single game | CPU bottleneck in season simulations | Simulating 162-game season |
| No database indexing on player lookups | Small datasets feel instant | Lineup selection becomes sluggish | Searching across 20,000+ players |
| Storing every at-bat result in detail | Complete audit trail | Database/memory bloat | 162 games * 9 innings * 6 outs * detailed events |
| Synchronous UI updates per at-bat | Real-time feedback | Textual rendering can't keep up at speed | Auto-play mode or season simulation |
| Deep copying game state for undo | Simple implementation | Memory pressure in long games | Extra innings, lots of substitutions |

## Integration Gotchas

Common mistakes when connecting to external services.

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| SQLite bundled DB | Not checking SQLite version compatibility | Verify SQLite version on load, handle migration if schema version mismatches |
| Lahman database version | Assuming static data, hardcoding table schemas | Check database version on startup, handle schema variations across versions |
| External stats sources (if added) | Not handling API failures or rate limits | Graceful degradation to Lahman data, cache external data locally |
| Textual framework | Assuming instant rendering, not handling async events | Use Textual workers for simulation, don't block UI thread |
| CSV imports (if updating Lahman) | Not validating data format changes | Schema validation before import, reject incompatible formats |

## UX Pitfalls

Common user experience mistakes in this domain.

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| Baseball jargon without tooltips | Non-experts confused by wOBA, FIP, BABIP, wRC+ | Provide glossary or hover explanations for advanced stats |
| No game state summary | User must read entire log to know situation | Always-visible scoreboard with inning, outs, runners, score |
| Irreversible decisions without confirmation | Accidental substitutions ruin game | Confirm critical actions (pitching changes, pinch hitters) |
| Play-by-play text without context | "Jones singles" - who is Jones? Which team? | Include context: "Yankees' Jones singles to right" |
| No save/resume game functionality | Must complete game in one session or lose progress | Serialize game state, allow resume later |
| Overwhelming initial team selection | 150 years * 30 teams = 4,500 options | Provide filters (decade, league), favorites, recent selections |
| Statistical deep dive without narrative | Feels like spreadsheet, not baseball game | Balance stats with narrative play-by-play, highlight drama |
| No tutorial or onboarding | New users don't know where to start | Quick-start mode: pick famous matchup, explain controls as you play |

## "Looks Done But Isn't" Checklist

Things that appear complete but are missing critical pieces.

- [ ] **Simulation Engine:** Statistics match expected values BUT variance not validated - test full season distribution, not just averages
- [ ] **Pitcher-Batter Matchup:** Uses both stats BUT simple averaging instead of proper odds ratio method - verify with extreme cases (great vs. terrible)
- [ ] **Substitutions:** Can make pitching changes BUT doesn't enforce eligibility rules (pitcher already used, position player on mound restrictions) - test edge cases
- [ ] **Play-by-Play:** Generates narrative text BUT doesn't update game state correctly (score shown doesn't match boxscore) - reconcile all state
- [ ] **Baserunning:** Runners advance on hits BUT advancement logic is wrong for edge cases (runner on 1st, double - should stop at 3rd sometimes) - verify with scoring rules
- [ ] **Statistics:** Boxscore displays stats BUT calculations wrong (sacrifice flies counted as at-bats, caught stealing not tracked) - validate against official scoring
- [ ] **Database Layer:** Queries work for modern era BUT fail on pre-1920 teams (missing data fields) - test across all eras in database
- [ ] **UI Rendering:** Dashboard looks good at 80x24 terminal BUT breaks at different sizes - test various terminal dimensions
- [ ] **Error Handling:** Works with valid inputs BUT crashes on edge cases (empty lineup, no available pitchers) - negative testing

## Recovery Strategies

When pitfalls occur despite prevention, how to recover.

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Wrong pitcher-batter algorithm | HIGH - requires engine rewrite | Replace averaging with odds ratio method, re-validate all simulations, may invalidate saved games |
| Missing platoon splits | MEDIUM - data enhancement | Source split data from Retrosheet/FanGraphs, add handedness fields, create migration path for existing saves |
| No variance validation | MEDIUM - testing infrastructure | Build statistical test framework, create validation dataset, may discover algorithm is fundamentally wrong |
| Ignored edge cases | LOW to MEDIUM - depends on scope | Catalog missing rules, prioritize by frequency, add incrementally with tests for each |
| Overfitting to training data | MEDIUM - requires new validation | Create train/test split, re-tune parameters on training set only, accept accuracy degradation on test set |
| Pacing too slow/fast | LOW - UI tuning | Add pace controls, information layering, doesn't require simulation changes |
| Memory leaks in long sessions | LOW - optimization | Profile memory usage, add cleanup logic, release game state references properly |
| Bad defensive metrics | LOW - remove feature | Revert to league average, document limitation, potentially better than keeping bad implementation |
| Database version incompatibility | MEDIUM - migration system | Build schema versioning, create migration scripts, add version check on startup |
| Missing TTOP modeling | MEDIUM - enhance pitcher model | Add pitch count tracking, times-through-order counter, adjust effectiveness formula |

## Pitfall-to-Phase Mapping

How roadmap phases should address these pitfalls.

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Naive pitcher-batter averaging | Phase 1: Simulation Engine | Validate with extreme matchups (Cy Young vs. worst hitter), check statistical distributions |
| Wrong simulation granularity | Phase 1: Simulation Engine | Run 1000-season simulations, verify variance matches historical ranges |
| Ignoring platoon splits | Phase 2: Enhanced Realism | Compare LHP vs. RHP outcomes, validate known platoon specialists perform correctly |
| Defensive metrics black hole | Out of v1 Scope (document limitation) | If added in v2+: multi-year correlation tests, compare to scouting consensus |
| TTOP/pitcher fatigue neglect | Phase 3: Pitching Changes | Track effectiveness by pitch count and times through order, validate bullpen usage patterns |
| Overfitting to historical outliers | Phase 5: Validation & Testing | Holdout era testing (train on pre-1990, test on 1990+), distribution matching tests |
| Lahman data quality issues | Phase 1: Data Layer | Era-specific validation, null checks, foreign key verification, graceful degradation |
| Edge case rule gaps | Ongoing: Each Feature | Maintain edge case test suite, reference official scoring rules, historical play validation |
| Pacing mismatch | Phase 4: Dashboard UI | Playtesting with target users, measure time per game, gather pacing feedback |
| Regression to mean blindness | Phase 5: Validation | Accept variance in repeated sims, understand seasonal stats ≠ true talent |

## Sources

### Simulation Design and Lessons Learned
- [10 Lessons I Learned from Creating a Baseball Simulator](https://tht.fangraphs.com/10-lessons-i-learned-from-creating-a-baseball-simulator/) - Matt Hunter's comprehensive post-mortem covering pitcher-batter matchups, variance, optimization
- [Little Professor Baseball: Mathematics and Statistics](https://bob-carpenter.github.io/games/baseball/math.html) - Detailed technical analysis of accuracy requirements, implementation mistakes, negative probability issues
- [Matt Hunter: Lessons from creating a baseball simulator (Diamond Mind Forums)](https://www.tapatalk.com/groups/fansofdmb/matt-hunter-10-lessons-i-learned-from-creating-a-b-t3415.html)

### Statistical Accuracy and Validation
- [Building an MLB Game Outcome Simulator](https://medium.com/@dmgrifka_64770/who-deserved-to-win-building-an-mlb-game-outcome-simulator-b4a8d4bca2a9) - 2025 perspective on prediction accuracy limits
- [Simulation in Baseball](https://bayesball.github.io/BLOG/Simulation.html) - Bayesian approach to baseball simulation
- [Building an At-Bat Simulator](https://www.baseballdatascience.com/building-an-at-bat-simulator/) - Practical implementation details
- [Simulation of empirical Bayesian methods (using baseball statistics)](http://varianceexplained.org/r/simulation-bayes-baseball/) - Testing statistical methods via simulation

### Comparative Analysis (OOTP vs. Diamond Mind)
- [Diamond Mind Vs. OOTP Discussion](https://forums.ootpdevelopments.com/showthread.php?t=588) - Community comparison of design philosophies
- [10 Lessons I Learned from Creating a Baseball Simulator](https://tht.fangraphs.com/10-lessons-i-learned-from-creating-a-baseball-simulator/) - Design decisions and their consequences

### Pacing and User Experience
- [Realism vs. Playability in Simulation Games](https://littlebrokenrobots.com/realism-vs-playability-striking-the-balance-in-simulation-games/) - Balancing competing concerns
- [Baseball by the numbers: simulation games and lessons learned](https://www.blessyouboys.com/2013/11/1/4664552/baseball-mlb-stratomatic-games-simulation-fantasy) - Strat-O-Matic pacing issues
- [Strategic Baseball Simulator](https://sbs-baseball.com/general.html) - Text-based simulation approach

### Platoon Splits and Handedness
- [The Beginner's Guide To Splits](https://library.fangraphs.com/the-beginners-guide-to-splits/) - Understanding platoon advantages
- [Park Factors and Handedness Discussion](https://www.baseball-fever.com/forum/general-baseball/statistics-analysis-sabermetrics/77707-park-factors-and-handedness) - Commonly ignored interaction
- [Everything You've Wanted to Know About Park Factors](https://baseballiq.substack.com/p/everything-youve-wanted-to-know-about) - Implementation complexity

### Defensive Metrics Challenges
- [Measuring Defense: Entering the Zones of Fielding Statistics](https://sabr.org/journal/article/measuring-defense-entering-the-zones-of-fielding-statistics/) - SABR analysis of measurement difficulties
- [Sabermetrics: Fielding percentage and errors don't tell whole story](https://www.browndailyherald.com/2013/04/16/sabermetrics-fielding-percentage-and-error-dont-tell-whole-story/) - Why traditional metrics fail
- [Indefensible: What Do We Really Know About Defense?](https://www.baseballprospectus.com/news/article/11476/indefensible-what-do-we-really-know-about-defense/) - Data quality concerns

### Pitcher Fatigue and Times Through Order
- [Baseball Therapy: Is There a Times Through The Order Penalty?](https://www.baseballprospectus.com/news/article/28506/baseball-therapy-is-there-a-times-through-the-order-penalty/) - Research findings
- [A Bayesian analysis of the time through the order penalty](https://www.degruyterbrill.com/document/doi/10.1515/jqas-2022-0116/html) - Statistical analysis showing nuanced results
- [Studying Pitcher Fatigue Using a Multinomial Regression Model](https://baseballwithr.wordpress.com/2022/10/20/studying-pitcher-fatigue-using-a-multinomial-regression-model/) - Modeling approaches

### BABIP and Luck vs. Skill
- [Extracting Luck From BABIP](https://community.fangraphs.com/extracting-luck-from-babip/) - Separating skill from randomness
- [Is BABIP simply sheer luck?](https://www.beyondtheboxscore.com/2012/10/26/3553142/is-babip-simply-sheer-luck) - Debate on modeling approach
- [Clutch, Luck, or Skill in OOTP?](https://forums.ootpdevelopments.com/showthread.php?t=273074) - Simulation design decisions

### Regression and Overfitting
- [Regression toward the Mean](https://library.fangraphs.com/principles/regression/) - FanGraphs explanation
- [Applying Regression to the Mean](https://andrewgrenbemer.medium.com/applying-regression-to-the-mean-and-final-adjustments-creating-a-college-baseball-projection-1213154cac85) - Projection system approach

### Data Quality (Lahman Database)
- [Lahman Baseball Database](https://sabr.org/lahman-database/) - Official SABR source
- [A Guide to Sabermetric Research: How to Find Raw Data](https://sabr.org/sabermetrics/data) - Data source overview
- [The Lahman's Baseball Database - real life sample data](https://www.linkedin.com/pulse/lahmans-baseball-database-real-life-sample-data-davide-moraschi) - Quality assessment

### Edge Cases and Rules
- [Intentional base on balls](https://en.wikipedia.org/wiki/Intentional_base_on_balls) - Edge case rules
- [9.07 Stolen Bases and Caught Stealing](https://baseballrulesacademy.com/official-rule/mlb/9-07-stolen-bases-caught-stealing/) - Official scoring rules
- [Rule 2 - Section 31 - SACRIFICE](https://baseballrulesacademy.com/official-rule/nfhs/rule-2-section-31-sacrifice/) - Sacrifice fly/bunt rules

---
*Pitfalls research for: Baseball Simulation TUI*
*Researched: 2026-01-28*
