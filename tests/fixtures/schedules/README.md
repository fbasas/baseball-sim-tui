# Real-format Retrosheet schedule fixtures (FRE-157)

Committed plain-text excerpts of the two real Retrosheet schedule layouts, used
by `tests/test_schedule_formats.py` to exercise `src/data/schedule_ingest.py`'s
`parse_schedule_rows` / `parse_zip_bytes` against the *actual* on-disk formats —
not the synthetic 12-column rows that let FRE-147 (the 13-column misparse) ship
green. No binary blobs; every fixture is reviewable in a diff.

The verbatim rows and format facts below come from the authoritative sample in
`docs/specs/schedule-test-hardening.md` ("The real Retrosheet formats",
downloaded 2026-07-16). Implementer/reviewer sessions have no web access, so that
spec section is the source of record for the format; the files here reproduce it.

## `2012_head.csv` — pre-2024 **12-column** layout

Quoted CSV, abbreviated day-of-week, uppercase Day/Night, header present. Field
order: `Date, Num, Day, Visitor, Vis-League, Vis-GameNo, Home, Home-League,
Home-GameNo, Day/Night, Postponed, Makeup` — Postponed at index 10, Makeup at 11.

- Rows `20120328`, `20120410`, `20120420` are **verbatim** from the spec's
  `2012schedule.csv` sample.
- Rows `20120507` (Num 1 & 2) and `20120629` are **format-faithful additions**
  (same quoting/casing) so the fixture also covers a doubleheader and a
  postponed-without-makeup (cancelled) game, per the spec's fixture convention
  ("header + normal + doubleheader + postponed-with-makeup + cancelled"). The
  `20120507` doubleheader is the makeup slot for the `20120410` rain-out
  (`Makeup=20120507`), keeping the excerpt internally consistent.

## `2024_head.csv` — 2024+ **13-column** layout

UNquoted CSV, full day name, **lowercase** Day/Night, and a new `Location`
(ballpark-code) column inserted at index 10 — which pushes Postponed to index 11
and Makeup to index 12. A fixed-index parser reading index 10/11 mis-reads the
park code as `postponed`, so every 2024 game looks cancelled (the FRE-147 bug).

- Rows `20240320`, `20240321`, and the two `20240328` rows (`MIL@NYN … NYC20,
  Rain,20240329` and `ANA@BAL … BAL12`) are **verbatim** from the spec's
  `2024schedule.csv` sample. `20240320`/`20240321` are the Seoul Series
  (`Location=SEO01`, Gocheok Sky Dome) — *played* games whose park code must not
  leak into `postponed`. `MIL@NYN` is the target postponement:
  `postponed="Rain", makeup_date=20240329`.
- Rows `20240329` (Num 1 & 2) and `20240615` are **format-faithful additions**
  covering a doubleheader and a cancelled game in the 13-column layout. The
  `20240329` doubleheader is the makeup slot for the rained-out `MIL@NYN` game
  (`Makeup=20240329`), keeping the excerpt internally consistent.

## 2020 two-member ZIP

Not committed as a file — `tests/test_schedule_formats.py` builds it in-process
with `zipfile` from two 12-column member strings (`2020sched-orig.csv`, the
pre-pandemic original, and `2020schedule.csv`, the played 60-game slate) to prove
`pick_schedule_member` selects the non-`orig` played file. Keeps the tree
text-only.
