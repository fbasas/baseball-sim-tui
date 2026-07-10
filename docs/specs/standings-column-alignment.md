# Spec: Season standings — fix column alignment for long team names

**Source issue:** FRE-100 · **Date:** 2026-07-10 · **Status:** active

## Goal

In season mode, the standings table on the season hub (and the identical final
standings on the season-complete summary) misaligns its columns: for many teams the
`W L Pct GB RS RA` values do not line up under their headers, and rows are shifted
relative to one another. This spec fixes the standings renderer so every column lines
up under its header for **all** teams, regardless of how long a team's display name
is. Same monospace, single-`Static` rendering as today — just correct alignment.

## Root cause

`src/tui/screens/season_hub_screen.py::_build_standings_table` builds the table by
hand with f-string field widths. The team-name cell is left-justified to a fixed width
of 20:

```python
header = (
    f"   {'Team':<20} {'W':>3} {'L':>3} {'Pct':>5} "
    f"{'GB':>5} {'RS':>4} {'RA':>4}"
)
...
body = (
    f" {marker} {self._team_name(row.key):<20} "
    f"{row.wins:>3} {row.losses:>3} {_format_pct(row.pct):>5} "
    f"{_format_gb(row.games_behind):>5} "
    f"{row.runs_scored:>4} {row.runs_allowed:>4}"
)
```

Python's `:<20` (`str.ljust`) **pads short strings but never truncates long ones**.
Real team display names are built in
`src/tui/season_setup_flow.py::_add_pick` as `f"{info.year} {info.team_name}"`, where
`team_name` is the full Lahman franchise name (`src/data/lahman.py` → `Teams.name`).
That routinely exceeds 20 characters, e.g.:

- `"1998 Los Angeles Dodgers"` — 24
- `"2016 Arizona Diamondbacks"` — 25
- `"1927 Philadelphia Phillies"` — 27

Any name longer than 20 overflows its cell, pushing that row's `W L Pct GB RS RA` to
the right while the header (a literal `"Team"`) and shorter-named rows stay put — the
visible misalignment. The numeric columns themselves never overflow (a season's W, L,
RS, RA, and GB all fit their widths), so **the team-name cell is the only source of
the bug.**

Why the existing tests missed it: `tests/test_season_hub_screen.py` uses short fake
names like `"1927 Yankees"` (12 chars), which never overflow the 20-char cell.

## Non-goals

- **No switch to a Rich `Table` / `DataTable` widget.** Keep the current approach:
  the hub renders the standings as a single markup string into a `Static`, with the
  user's team marked by a `►` caret and a `[bold]` row wrapper. Preserve that exact
  presentation (caret, bold user row, header color, em-dash for the GB leader).
- No new columns, no reordering columns, no changes to what the numbers mean or how
  they are formatted (`_format_pct`, `_format_gb` stay as-is).
- No change to `LeagueTeam.display_name` or how names are constructed in
  `season_setup_flow.py`. The renderer must cope with whatever name it is given, not
  push the fix upstream into the data.
- No handling of full Unicode east-asian / combining-character display width, and no
  hardening against Rich-markup metacharacters in names — franchise names are ASCII.
  (A brief note only; not in scope to implement.)
- No visual/layout changes to the matchups, recent-results, or leaders blocks.

## Design

The fix is surgical: guarantee the team-name cell occupies a **fixed number of display
columns** by truncating names that are too long (with a trailing ellipsis) and padding
names that are short — and drive both the header and every body row from a **single
shared width constant** so they can never drift apart again.

### 1. One source of truth for the column width

Add a module-level constant near the other formatting constants, e.g.:

```python
# Fixed display width of the standings team-name column. Long franchise
# display names (e.g. "1998 Los Angeles Dodgers") are truncated to fit so
# every downstream column stays aligned under its header.
_TEAM_COL_WIDTH = 24
```

`24` comfortably fits the great majority of `"{year} {franchise}"` names; a handful of
the longest names will truncate. The exact number is a taste choice — what matters is
that the **same constant** feeds the header and the body, and that names are truncated
to it so overflow is impossible. If the implementer prefers a slightly larger value to
truncate fewer names, that is fine; do not exceed a value that would make a typical
80-column terminal wrap the row (header + all numeric columns is ~29 chars of overhead,
so keep the team column ≲ 50).

### 2. A pure fit-to-width helper

Add a small pure helper that truncates-with-ellipsis then pads to exactly `width`
display columns:

```python
def _fit(text: str, width: int) -> str:
    """Truncate ``text`` to ``width`` columns (ellipsis if clipped), then left-pad
    to exactly ``width``. Guarantees a fixed-width cell so table columns align."""
    if len(text) > width:
        return text[: width - 1] + "…"  # "…"
    return text.ljust(width)
```

(`…` is the single-cell horizontal ellipsis `…`, matching the em-dash the file
already uses for GB. A literal `…` in the source is equally fine.)

### 3. Use the constant + helper in the header and body

- Header: replace `{'Team':<20}` with a `Team` label padded to `_TEAM_COL_WIDTH`
  (e.g. `f"{'Team':<{_TEAM_COL_WIDTH}}"`, or `_fit('Team', _TEAM_COL_WIDTH)`).
- Body: replace `{self._team_name(row.key):<20}` with
  `_fit(self._team_name(row.key), _TEAM_COL_WIDTH)`.

Leave the 3-char row prefix (`"   "` header vs `" " + marker + " "` body), the numeric
field widths, and all markup exactly as they are — they already agree and are not the
bug. The caret marker and `[bold]` wrapping wrap the *whole* body string, so they do
not affect internal column offsets.

After the change, the team cell is always exactly `_TEAM_COL_WIDTH` columns for both
header and every row, so all subsequent columns start at the same offset in every line.

### Invariant to verify

For a standings table built from teams whose display names include at least one name
**longer** than `_TEAM_COL_WIDTH` and at least one **shorter**, every rendered line
(header and each row), after stripping Rich markup, has its `W` column — and therefore
every column after it — beginning at the same character offset.

## Tests

Home: `tests/test_season_hub_screen.py`, which already exercises
`SeasonHubScreen._build_standings_table(mock)` (see
`test_standings_rows_in_order_with_user_marked`). Follow that file's existing mock
pattern.

Add coverage that would have caught this bug:

1. **Long-name alignment (the core test).** Build standings whose `LeagueTeam`
   display names include a realistic long name (e.g. `"1998 Los Angeles Dodgers"`,
   24+ chars — longer than `_TEAM_COL_WIDTH` if the implementer keeps 24, so include
   one clearly longer such as `"1927 Philadelphia Phillies"`) alongside a short one
   (e.g. `"1927 Reds"`). Assert that across the header and all rows, the numeric
   columns align — e.g. strip markup (`►`, `[bold]`, `[/]`, the header color tag),
   then assert the team-name cell of every row is exactly `_TEAM_COL_WIDTH` columns,
   or that the offset of the `W`/first numeric field is identical on every line.
2. **Truncation.** Assert a name longer than `_TEAM_COL_WIDTH` is rendered clipped
   with a trailing `…` and occupies exactly `_TEAM_COL_WIDTH` columns.
3. Keep the existing standings tests green (they use short names and must still pass
   unchanged, including the user-team caret + bold marking).

A direct unit test of `_fit` (short → padded, long → ellipsized, both exactly `width`)
is also welcome. The PR must include test changes (per FACTORY.md).

## Definition of done

- In `_build_standings_table`, the team-name column is driven by a single shared width
  constant and never overflows: long display names are truncated (ellipsis), short
  ones padded, so the header and every row's `W L Pct GB RS RA` columns line up.
- The fix works for both the active-season hub standings and the season-complete
  summary standings (both call `_build_standings_table`, so one fix covers both).
- Presentation is otherwise unchanged: `►` caret on the user's team, bold user row,
  header color, GB em-dash, and all numeric formatting identical to before.
- New test(s) in `tests/test_season_hub_screen.py` cover long-name alignment and
  truncation; the full test suite is green.
- No changes outside the standings renderer and its tests (no data-layer or
  setup-flow changes).

## Open questions

None — the fix is fully specified by the existing code. No human checkpoint required.
The team-column width value is a minor taste choice left to the implementer within the
guidance above; it does not need a human decision.

## Issue breakdown

| Issue | Title | Depends on | Risk |
| --- | --- | --- | --- |
| FRE-100 child | Fix standings column alignment for long team names in season mode | — | — |
