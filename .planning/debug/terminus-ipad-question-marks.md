# Bug: Question marks render in place of some Unicode characters (Terminus iPad over SSH)

**Status:** Open, low priority
**Reported:** 2026-05-21
**Environment:** Terminus terminal on iPad, connected over SSH

## Symptom

A string of `?` characters appears on the row right above the bottom border of one
of the center-panel widgets (most often the FatigueWidget, which sits just above
the SituationWidget). Renders correctly in headless Textual screenshots and in
desktop terminals — only seen on Terminus over SSH.

## What we tried

1. **Suspected fatigue bar block chars** (`█`/`░`) — replaced with ASCII `#`/`-`.
   Issue still reproduces.
2. **Suspected `double`/`round` border styles** on `#situation` and `#play-log` —
   switched both to `border: solid` (`┌─┐│└┘`). Issue still reproduces.
3. **Verified non-ASCII inventory** in `src/`:
   - `═` in `box_score_screen.py` and `substitution_menu.py` (modal decoration,
     not in main game screen, so unrelated to the row reported)
   - Already-fixed `█░` in fatigue bar
   - Diamond ASCII art in `SituationWidget` uses only ASCII (`/ \ H`)
4. **Confirmed headless render is clean** — captured with `app.run_test()` +
   `compositor.render_full_update()` and `app.export_screenshot()`. All
   box-drawing chars present, no `?` anywhere.

## Current hypothesis

User suspects **Terminus dropping bytes on a slow connection**, not a font/glyph
issue. Consistent with:
- Intermittent ("happened twice", not every frame)
- Headless render fine
- Switching characters didn't help — implies the byte stream itself is being
  corrupted in transit, not that specific glyphs fail to render

## Next steps if revisited

- Try forcing a smaller Textual frame rate or disabling double-width rendering
- Test on a different SSH client to confirm Terminus-specific
- Check if Textual has a "redraw on resize" or "force full refresh" keybinding
  that clears the artifact when it appears
- Consider lowering Textual's refresh rate via env var (e.g., `TEXTUAL_FPS`)
