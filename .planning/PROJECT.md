# Baseball Simulation TUI

## What This Is

A terminal-based baseball simulation that lets you manage a team through individual games using historical player data. Built with Python and Textual, it uses Sean Lahman's baseball database (bundled as SQLite) to enable matchups between any teams from any era — 1927 Yankees vs 2016 Cubs, or any other combination. You make managerial decisions (lineups, pitching changes, pinch hitters) while watching games unfold at-bat-by-at-bat through a dashboard interface.

## Core Value

The simulation produces realistic baseball outcomes based on actual historical player statistics, letting you experience "what if" scenarios across baseball history.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Load and query Sean Lahman's database (all years, all teams)
- [ ] Select any two teams from any year for a matchup
- [ ] Set starting lineup and starting pitcher before game
- [ ] Simulate at-bat outcomes using researched algorithms
- [ ] Make pitching changes during the game
- [ ] Make pinch-hitting substitutions
- [ ] Display dashboard TUI with boxscore, lineup cards, situation panel, play-by-play log
- [ ] Generate narrative play-by-play text for each at-bat

### Out of Scope

- Base running tactics (steals, bunts, hit-and-run) — deferred to v2
- Season mode with standings — deferred to v2
- AI manager suggestions — deferred to v2
- Injuries and player fatigue — deferred to v2
- Hot streaks and slumps — deferred to v2
- Roster management, trades, call-ups — deferred to v2
- Pitch-by-pitch simulation — at-bat level is sufficient
- Graphical UI — terminal only

## Context

**Data source:** Sean Lahman's Baseball Database contains comprehensive statistics from 1871 to present, including batting, pitching, fielding, and team data. Available as CSV, will be loaded into SQLite for the application.

**Simulation approach:** Will research proven baseball simulation algorithms (OOTP, Diamond Mind, Strat-O-Matic, APBA) to understand how real-world stats translate to game outcomes. Key factors include batter/pitcher matchups, handedness, park factors, and statistical variance.

**TUI design:** Dashboard layout with multiple panels — no ASCII diamond needed. Focus on information density: current situation, lineup cards for both teams, running boxscore, and scrolling play-by-play narrative.

**Personal project:** Built as a learning exercise and to explore baseball "what if" scenarios. Not targeting external users initially.

## Constraints

- **Language**: Python — best fit for data processing + TUI
- **TUI Framework**: Textual — modern, supports complex layouts
- **Database**: SQLite — bundled with application, no external dependencies
- **Data**: Sean Lahman's database — public domain, comprehensive historical coverage

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Python + Textual | Rich data ecosystem, modern TUI framework, fast iteration | — Pending |
| SQLite bundled | No external dependencies, works offline, fast queries | — Pending |
| At-bat level (not pitch-by-pitch) | Better pacing, sufficient realism for management sim | — Pending |
| Research existing sim algorithms | Leverage decades of prior art rather than inventing from scratch | — Pending |

---
*Last updated: 2026-01-28 after initialization*
