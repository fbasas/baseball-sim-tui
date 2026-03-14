---
phase: 5
slug: narrative-polish
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-14
---

# Phase 5 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest |
| **Config file** | none (pytest discovers tests/ directory) |
| **Quick run command** | `python -m pytest tests/ -x -q` |
| **Full suite command** | `python -m pytest tests/ -v` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/ -x -q`
- **After every plan wave:** Run `python -m pytest tests/ -v`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 05-01-01 | 01 | 1 | TUI-06 | unit | `python -m pytest tests/test_lineup_builder.py::test_appearances -x` | No W0 | pending |
| 05-01-02 | 01 | 1 | TUI-06 | unit | `python -m pytest tests/test_lineup_builder.py::test_position_assignment -x` | No W0 | pending |
| 05-01-03 | 01 | 1 | TUI-06 | import | `python -c "from src.tui.screens.pitcher_select_screen import PitcherSelectScreen"` | No W0 | pending |
| 05-02-01 | 02 | 1 | TUI-06 | import | `python -c "from src.tui.app import BaseballSimApp; print('OK')"` | Yes | pending |
| 05-02-02 | 02 | 1 | TUI-06 | import | `python -c "from src.tui.widgets.situation import SituationWidget; print('OK')"` | Yes | pending |
| 05-03-01 | 03 | 2 | NARR-02 | unit | `python -m pytest tests/test_narrative.py::test_all_outcomes -x` | No W0 | pending |
| 05-03-02 | 03 | 2 | NARR-02 | unit | `python -m pytest tests/test_narrative.py::test_pinch_hitter_text -x` | No W0 | pending |
| 05-04-01 | 04 | 3 | NARR-01 | unit | `python -m pytest tests/test_box_score.py::test_stat_accumulation -x` | No W0 | pending |
| 05-04-02 | 04 | 3 | NARR-01 | import | `python -c "from src.tui.screens.box_score_screen import BoxScoreScreen; print('OK')"` | No W0 | pending |

*Status: pending / green / red / flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_lineup_builder.py` — stubs for TUI-06: Appearances-based position assignment, conflict resolution, batting order heuristic
- [ ] `tests/test_narrative.py` — stubs for NARR-02: narrative engine output for all 19 outcomes + context variants + pinch hitter text
- [ ] `tests/test_box_score.py` — stubs for NARR-01: stat accumulation, linescore formatting, screen data assembly
- [ ] `data/lahman.sqlite` rebuild with Appearances table — prerequisite for lineup builder tests

*Existing infrastructure: pytest, 10 test files. Framework install not needed.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| TCSS visual theme looks correct | TUI-06 | Visual styling; automated tests can't judge aesthetics | Launch app, verify dark green background, cream panels, brown borders, gold accents |
| Base diagram renders in situation panel | TUI-06 | Visual layout | Play a game, check situation widget shows diamond with occupied bases |
| Footer bar displays key bindings | TUI-06 | Visual layout | Verify Space/S/F/Q bindings shown at bottom of game screen |
| Pitcher selection screen shows before game | TUI-06 | Interactive flow | Start game, verify pitcher selection modal appears for each team |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
