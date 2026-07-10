"""Season mode: a round-robin league of 4-8 team-seasons.

Pure model layer (schedule, standings state) mirroring :mod:`src.series`.
The TUI-side controller, stat aggregation, and persistence wiring live in
later parts; nothing here touches the UI, the engine, or the database.
"""
