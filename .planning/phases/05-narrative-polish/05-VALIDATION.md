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
| 05-01-01 | 01 | 1 | NARR-02 | unit | `python -m pytest tests/test_narrative.py::test_all_outcomes -x` | ❌ W0 | ⬜ pending |
| 05-01-02 | 01 | 1 | NARR-02 | unit | `python -m pytest tests/test_narrative.py::test_clutch_context -x` | ❌ W0 | ⬜ pending |
| 05-01-03 | 01 | 1 | NARR-02 | unit | `python -m pytest tests/test_narrative.py::test_streak_tracking -x` | ❌ W0 | ⬜ pending |
| 05-02-01 | 02 | 1 | NARR-01 | unit | `python -m pytest tests/test_box_score.py::test_linescore_format -x` | ❌ W0 | ⬜ pending |
| 05-02-02 | 02 | 1 | NARR-01 | unit | `python -m pytest tests/test_box_score.py::test_stat_accumulation -x` | ❌ W0 | ⬜ pending |
| 05-03-01 | 03 | 1 | TUI-06 | unit | `python -m pytest tests/test_lineup_builder.py -x` | ❌ W0 | ⬜ pending |
| 05-03-02 | 03 | 1 | TUI-06 | unit | `python -m pytest tests/test_lineup_builder.py::test_conflict_resolution -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_narrative.py` — stubs for NARR-02: narrative engine output for all 19 outcomes + context variants
- [ ] `tests/test_box_score.py` — stubs for NARR-01: stat accumulation, linescore formatting, screen data assembly
- [ ] `tests/test_lineup_builder.py` — stubs for TUI-06: Appearances-based position assignment, conflict resolution, batting order heuristic
- [ ] `data/lahman.sqlite` rebuild with Appearances table — prerequisite for lineup builder tests

*Existing infrastructure: pytest, 10 test files. Framework install not needed.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| TCSS visual theme looks correct | TUI-06 | Visual styling; automated tests can't judge aesthetics | Launch app, verify dark green background, cream panels, brown borders, gold accents |
| Base diagram renders in situation panel | TUI-06 | Visual layout | Play a game, check situation widget shows diamond with occupied bases |
| Footer bar displays key bindings | TUI-06 | Visual layout | Verify Space/S/F/Q bindings shown at bottom of game screen |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
