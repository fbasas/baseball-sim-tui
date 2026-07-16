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
  `_available_years()` returns) — *not* the repo — plus an optional `default_year`
  and an optional **`notice: Optional[str] = None`** (see the persistent-notice
  bullet below). Keeping it a pure `List[int]`/`Optional[str]` in / `Optional[int]`
  out keeps it DB-free and unit-testable, and lets Piece 2 add its per-year cached
  annotation without a second constructor churn (see Piece 2).
- **Persistent notice line (moved here from Piece 2 — see the FRE-165 correction
  below).** The screen accepts `notice: Optional[str] = None`, stores it as
  `self._notice`, and — when non-empty — renders it as a **persistent**
  (non-auto-dismiss) error-styled inline line at the bottom of the modal. This is a
  faithful port of the `#choice-notice` line the flat `ChoiceScreen` already ships
  (FRE-155): reuse its CSS idiom (error color, top border, only composed when
  `self._notice` is truthy). Storing it as `self._notice` keeps main's shipped
  `test_unresolved_id_failure_shows_persistent_notice` (which asserts the pushed
  screen's `_notice is not None`) green after the flat picker is replaced. The
  *content* of the notice and the flow-side accumulation of failures across all six
  sites remain Piece 2's job; Piece 1 only builds the screen's rendering seam and
  preserves the one caller that already passes a notice (the unresolved-id case).
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

Wire it in `HistoricalSeasonSetupFlow._select_year()`. **This method already carries
a `notice: Optional[str] = None` parameter on `main` (added by FRE-155)** — keep it.
Build the buildable-years list as today and push
`HistoricalYearSelectScreen(years, default_year=years[0], notice=notice)`, threading
the existing `notice` straight into the new screen (this is the port of the old
`ChoiceScreen(..., notice=notice)` call). The `on_chosen(choice)` callback keeps its
shape — `choice is None` → `_on_cancel()`, otherwise `_fetch_schedule_if_missing(choice)`
(now already an `int`, so drop the `int(choice_id)` cast). The empty-years guard and
its notify are unchanged. `_build_league`'s unresolved-id path (which on `main` calls
`self._select_year(notice=notice)` with **no** toast) is left exactly as FRE-155 shipped
it — the notice now renders on the new screen instead of `ChoiceScreen`, so there is no
regression window.

> **FRE-160 branches onto `main` after FRE-155.** PR #38 was cut from `562566a`
> (pre-FRE-155) and must be **rebased onto `main`**; the only real conflict is in
> `_select_year` (keep FRE-155's `notice` param + docstring; swap the pushed screen to
> `HistoricalYearSelectScreen(..., notice=notice)`). The two colliding tests are
> reconciled *in FRE-160*: keep `main`'s `test_unresolved_id_failure_shows_persistent_notice`
> (it now asserts the new screen's `_notice`), and drop the branch's stale pre-FRE-155
> `test_build_failure_names_teams_and_reprompts_year` toast assertion in favor of `main`'s
> toast-free unresolved-id expectation.

The flow's callback-driven test idiom (`FakeApp` records `push_screen(screen,
callback)`; the test invokes the callback with what a real screen would dismiss)
keeps working verbatim: the pushed screen type changes and the callback now receives
an `int`/`None` instead of a `str`/`None`.

### Piece 2 — Persistent failure line + cached-year annotation (issue FRE-161)

Builds on Piece 1's screen. Two additions surfaced *in the picker*. **The screen's
persistent-notice *rendering* now lands in Piece 1 (FRE-160)** — see the FRE-165
correction below; Piece 2 owns the *flow-side generalization* that feeds that line
and the cached annotation.

**(a) Generalize the persistent "last failure" line to every failure path.** The
screen already renders `self._notice` as a persistent inline line (Piece 1). Today
(after FRE-155) only the *unresolved-id* site passes a notice; the other five failure
sites still fire a transient toast and re-enter `_select_year()` with no notice.
Piece 2 makes the flow remember the most recent failure message
(`self._last_error: Optional[str]`), setting it at each of the **six** failure sites
just before it returns to `_select_year()`, and clearing it once a year advances past
the successful build. `_select_year()` passes it through as the screen's `notice`
(`_select_year(notice=self._last_error)` on the failure re-entry paths). The transient
`notify` toasts may stay (immediate feedback) or be dropped in favor of the inline
line — implementer's call — but the **inline line is the durable record** and is the
required deliverable.

This **completes FRE-155's generalization**: FRE-155 made the *unresolved-team*
failure persistent and actionable (with the `build_lahman_db.py` remediation) and
Piece 1 ported its rendering onto the new screen. Piece 2 routes the remaining five
failures (fetch / no-played-games / degenerate-shape / team-load) through the same
`self._last_error` → `notice` seam, **preserving FRE-155's content** (the unresolved-id
line must still name the rebuild command). **FRE-161 stays blocked by FRE-155 and
FRE-160** (both merged before it), so no two issues edit `_build_league`'s messaging in
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
`notice: Optional[str] = None` (added in Piece 1) and
`cached: Optional[Dict[int, bool]] = None` (added in Piece 2) — both default off, so
Piece 2's addition is a purely additive optional param with no signature break.

### Why serialize A → B → and both after FRE-155

**FRE-155 must land before Piece 1 (FRE-160), not beside it.** The original spec
claimed FRE-155 and Piece 1 were independent — *"the only shared file is
`historical_setup_flow.py`, FRE-155 in `_build_league`, Piece 1 in `_select_year` — a
trivial rebase at worst … may run in parallel."* **That was wrong** (see the FRE-165
correction below): FRE-155 also added a `notice` parameter to **`_select_year`** and
made the persistent picker line the *sole* feedback for the unresolved-id failure (it
removed that case's toast). Piece 1 replaces the very screen that renders that line, so
the two collide semantically, not textually — a naive rebase silences a shipped failure
message and breaks the suite. Piece 1 therefore **branches onto `main` after FRE-155**
and ports the notice-rendering seam across (the added `notice` param on the new screen).

A → B (Piece 1 → Piece 2) is a hard code dependency: Piece 2 adds the flow-side
`self._last_error` accumulation and the per-year cached annotation onto the screen and
`_select_year` seam that Piece 1 creates. B → after-FRE-155 is a coordination
dependency: both concern the persistent presentation of the unresolved-team failure, so
serializing keeps a single mechanism and one editor of `_build_league`'s messaging.

### FRE-165 correction (2026-07-16)

This spec originally decomposed the persistent-notice work so that FRE-160 built only
the DB-free Decade ▸ Year screen and **all** persistent-line work (rendering + flow-side
accumulation) sat in FRE-161, and it asserted FRE-155 ⟂ FRE-160 could run in parallel.
Both were defects, caught when FRE-160's PR #38 reached review (see FRE-165):

- **FRE-155 was not confined to `_build_league`.** It added `notice` to `_select_year`,
  threaded it into `ChoiceScreen(..., notice=notice)`, and **removed the unresolved-id
  toast** — making the picker line the only feedback for that case. Replacing the screen
  (FRE-160) without a notice seam is a silent regression + a test break, so there is no
  correct mechanical rebase.
- **Fix (Option A):** move the *screen-side* notice rendering into FRE-160 (a small
  additive `notice` param + a ported `#choice-notice`-style line), rebase FRE-160 onto
  `main`, and reconcile the two conflicting tests inside FRE-160. FRE-161 narrows to the
  flow-side generalization (`self._last_error` across all six sites, feeding the same
  `notice` seam) plus the cached-year annotation. FRE-160 now (correctly) depends on
  FRE-155, which is already merged.

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
| FRE-160 | Decade ▸ Year picker + persistent-notice rendering seam for the historical-season setup flow | FRE-155 (rebase onto `main`) | — |
| FRE-161 | Generalize the persistent last-failure line to all six failure sites + cached-year annotation | FRE-160, FRE-155 | — |

*Dependencies corrected by FRE-165 (2026-07-16): FRE-160 now depends on FRE-155 — see
the "FRE-165 correction" section above.*
