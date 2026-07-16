# Spec: Historical-season setup UX — scalable year picker + non-transient failure feedback

**Source issue:** FRE-151 · **Date:** 2026-07-16 · **Status:** active

## Goal

Make the historical-season setup flow (`src/tui/historical_setup_flow.py`) usable
at the scale it actually operates at (≈149 selectable years, 1877–2025) and honest
about failure. Two concrete outcomes:

1. **A scannable year picker.** Replace the flat ~149-item `ChoiceScreen` — where
   reaching 1927 is ~98 arrow presses — with a two-phase **Decade ▸ Year** browser,
   reusing the exact pattern the single-game flow already ships
   (`src/tui/screens/team_select_screen.py`). Any buildable year is ≤ ~10 keypresses
   away.
2. **Failure feedback that survives.** Today every build/fetch failure is a 12-second
   `notify` toast that then vanishes, dropping the user back at the picker with no
   record of what went wrong (during live QA the toast was easy to miss entirely).
   Add a **persistent inline "last failure" line** on the picker that all failure
   paths route through, and **annotate each year** as already-cached (schedule
   downloaded) vs. needs-a-network-fetch, so the user can see which picks are cheap
   and read the reason the previous pick failed.

This is a UX-quality issue. It compounds — but is independent of — the correctness
fixes for the same flow (FRE-147 schedule parse, FRE-149 shape validation, FRE-154
team-join, FRE-155 actionable unresolved-team error): those make the *right* years
work; this makes the picker survivable and self-explanatory while they land and
after.

## Non-goals

- **No change to what a year *does* once picked.** The fetch-if-missing seam
  (`ScheduleIngest`, FRE-145), the schedule-type toggle, the league build, the
  your-team pick, and the role-card pass are all untouched in their behavior. Only
  (a) how the year is *chosen* and (b) how a failure is *surfaced back at the picker*
  change.
- **No new failure *cause* handling, no new error types, no builder/parser/ingest
  changes.** This spec re-presents the failures the flow already produces; it does
  not add, remove, or reclassify any. FRE-147/149/154/155 own the causes.
- **No digit type-ahead on `ChoiceScreen`.** The issue floated "or add digit
  type-ahead"; we deliberately choose the Decade ▸ Year browser instead (rejected
  alternative below) so the historical flow matches the single-game flow and gets a
  natural home for per-year annotations. `ChoiceScreen` is left unchanged — it still
  serves the schedule-type and your-team steps.
- **No marking of "known-bad" years.** The issue floated annotating known-bad years
  in the list. We do **not** — "bad" is year-, DB-, and network-dependent and would
  require the builder to pre-flight every year (expensive, and a moving target as
  FRE-147/154 land). The persistent last-failure line covers the same user need
  (why did my pick fail) without a speculative, quickly-stale blocklist. The only
  per-year annotation is the cheap, certain cached-vs-fetch bit from
  `repo.has_schedule(year)`.
- **No change to the "no buildable years at all" path** (empty picker → mode menu
  with a message). That stays as-is.

## Background — the current flow

`HistoricalSeasonSetupFlow._select_year()` builds
`choices = [(str(year), str(year)) for year in self._available_years()]` and pushes
a single `ChoiceScreen` (title "⚾ HISTORICAL SEASON"), most-recent-first.
`_available_years()` is `repo.get_available_years()` (descending) intersected with
`schedule_available_for(year)` — ≈149 entries.

Every downstream failure calls `self._app.notify(..., severity="error", timeout=12)`
and then `self._select_year()` (re-pushes a *fresh* picker). The failure sites:

| Site | Failure | Current message shape |
| ---- | ------- | --------------------- |
| `ScheduleIngest._fail_network` | Retrosheet unreachable | "Couldn't reach Retrosheet to fetch the {year} schedule…" |
| `ScheduleIngest._fail_unavailable` | no schedule published / no rows | "No schedule is available for {year}." |
| `ScheduleIngest._fail_other` | any other fetch/DB-write error | "Couldn't fetch the {year} schedule: {msg}." |
| `_build_league` `HistoricalSeasonError` | unresolved/unloadable teams | "Couldn't build the {year} season: N team(s)…" |
| `_build_league` `ValueError` | no schedule rows / none played / (FRE-149) degenerate shape | the raised message |
| `_build_league` team-load loop | `Team.load_from_repository` failed | "Couldn't load N team(s) for the {year} season…" |

All six drop the toast and re-enter `_select_year()`. The user sees a fresh,
context-free picker.

The single-game flow's `TeamSelectScreen` is the pattern to reuse: a
`ModalScreen[Optional[Tuple[str,int]]]` that walks **Decade → Year → Team** phases in
one screen, driven by ↑/↓ + Enter (advance) + Esc (step back; cancel from the first
phase), with a `Decade ▸ Year ▸ Team` breadcrumb in the title. Decades are
`sorted({y//10*10 for y in years}, reverse=True)`; the year phase filters
`years` to the chosen decade.

## Design

Two independently-shippable pieces, sequenced so they never edit the same new code
in parallel.

### Piece 1 — Decade ▸ Year year picker (issue FRE-160)

A new modal, `src/tui/screens/historical_year_select_screen.py`:

- `class HistoricalYearSelectScreen(ModalScreen[Optional[int]])`.
- Constructor takes the **list of buildable years** (descending ints, as
  `_available_years()` returns) — *not* the repo — plus an optional `default_year`.
  Keeping it a pure `List[int]` in / `Optional[int]` out keeps it DB-free and unit-
  testable, and lets Piece 2 pass in annotation data without a second constructor
  churn (see Piece 2).
- Two phases, mirroring `TeamSelectScreen` minus the team phase:
  - **Decade phase** — options are `{decade}s` for each decade present in the year
    list, descending (2020s … 1870s). Enter → year phase for that decade. Esc →
    `dismiss(None)` (cancel; the flow treats this as "back to mode menu", exactly as
    the flat picker's `choice_id is None` does today).
  - **Year phase** — options are the years within the chosen decade, descending.
    Enter → `dismiss(year)`. Esc → back to the decade phase.
- A `Decade ▸ Year` breadcrumb in the panel title with the active phase lit (drop
  `TeamSelectScreen`'s third `Team` crumb).
- Same key-hint line and CSS idiom as `TeamSelectScreen` (arrows / Enter / Esc; a
  `q` quit is **not** required here — the flat picker had none — but keep the option
  list styling and in-box hint so it reads as one system).
- Title "⚾ HISTORICAL SEASON" to match the step it replaces.

Wire it in `HistoricalSeasonSetupFlow._select_year()`: build the buildable-years
list as today, push `HistoricalYearSelectScreen(years, default_year=years[0])` with
the existing `on_chosen(choice)` callback — `choice is None` → `_on_cancel()`,
otherwise `_fetch_schedule_if_missing(choice)` (now already an `int`, so drop the
`int(choice_id)` cast). The empty-years guard and its notify are unchanged.

The flow's callback-driven test idiom (`FakeApp` records `push_screen(screen,
callback)`; the test invokes the callback with what a real screen would dismiss)
keeps working verbatim: the pushed screen type changes and the callback now receives
an `int`/`None` instead of a `str`/`None`.

### Piece 2 — Persistent failure line + cached-year annotation (issue FRE-161)

Builds on Piece 1's screen. Two additions, both surfaced *in the picker*:

**(a) Persistent "last failure" line.** The flow remembers the most recent failure
message (an `Optional[str]`, `self._last_error`, set at each of the six failure
sites above just before it calls `_select_year()`, cleared when a year advances past
the build successfully). `_select_year()` passes it to the screen, which renders it
as a **persistent** (non-auto-dismiss) inline line at the bottom of the modal —
styled as an error, only shown when non-empty. Because the flow re-enters
`_select_year()` after every failure, the line is always present on the picker the
user lands back on, with the exact reason the last pick failed. The transient
`notify` toasts may stay (immediate feedback) or be dropped in favor of the inline
line — implementer's call — but the **inline line is the durable record** and is the
required deliverable.

This **generalizes FRE-155**: FRE-155 makes the *unresolved-team* failure persistent
and actionable (with the `build_lahman_db.py` remediation) via a mechanism of the
implementer's choice. Piece 2 provides the single mechanism — the inline picker line
— that every failure routes through. **FRE-161 is blocked by FRE-155** so FRE-155
lands its actionable message first; Piece 2 then relocates that message onto the
inline line (preserving FRE-155's DoD: the unresolved-id case still shows the
rebuild command, now on the persistent line) and extends the same durable treatment
to the fetch / no-played-games / degenerate-shape / team-load failures. This
ordering also guarantees the two issues never edit `_build_league`'s messaging in
parallel.

**(b) Cached-vs-fetch annotation.** For each year option, annotate whether its
schedule is already cached (`repo.has_schedule(year)` — instant, in-DB) vs. needs a
network fetch on pick. The flow computes a `{year: bool}` map once (cheap: one
`has_schedule` per buildable year, already the check `ScheduleIngest` does) and
passes it to the screen; the year-phase options render a marker (e.g. a
"● cached" / "↓ fetch" suffix or a dim tag — implementer picks glyphs, keep it
legible in the existing green/gold palette). Decade-phase rows are unannotated.
This is the issue's "bonus": the user sees which picks are offline-cheap before
committing to one that needs the network.

The `HistoricalYearSelectScreen` constructor therefore accepts optional
`last_error: Optional[str] = None` and `cached: Optional[Dict[int, bool]] = None`
(both default off, so Piece 1 constructs it with neither and Piece 2 adds them — no
signature break between the two issues, only additive optional params).

### Why serialize B after A (and after FRE-155)

A → B is a hard code dependency (B annotates and adds a line to the screen A
creates). B → after-FRE-155 is a coordination dependency (both concern the
persistent presentation of the unresolved-team failure; serializing prevents a
duplicated/competing mechanism and a parallel edit to `_build_league`). FRE-155 and
Piece 1 are mutually independent (different concerns; the only shared file is
`historical_setup_flow.py`, FRE-155 in `_build_league`, Piece 1 in `_select_year` —
a trivial rebase at worst) and may run in parallel.

## Open questions

None require a human checkpoint. The one real fork — Decade ▸ Year browser vs.
`ChoiceScreen` digit type-ahead — is a scaffolding decision resolved in favor of
reusing the shipped `TeamSelectScreen` pattern (consistency + it hosts the
annotations); recorded here, not deferred to a human.

## Alternatives rejected

- **Digit type-ahead on `ChoiceScreen`** — would keep a single 149-row list and
  jump on typed digits. Rejected: no home for per-year cached/fetch annotations,
  diverges from the single-game flow's already-shipped Decade ▸ Year idiom, and
  type-ahead over a 4-digit year in a reverse-sorted list is fiddlier than a
  two-tap decade drill-down.
- **Marking "known-bad" years in the list** — rejected (see Non-goals): "bad" is a
  moving, DB/network-dependent target and pre-flighting every year is expensive.
  The persistent last-failure line meets the same need.

## Issue breakdown

| Issue | Title | Depends on | Risk |
| --- | --- | --- | --- |
| FRE-160 | Decade ▸ Year picker for the historical-season setup flow | — | — |
| FRE-161 | Persistent inline last-failure line + cached-year annotation on the historical picker | FRE-160, FRE-155 | — |
