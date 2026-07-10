"""Season mode: a round-robin league of 4-8 team-seasons.

Pure model layer (schedule, standings state, stat aggregation) mirroring
:mod:`src.series`. The TUI-side controller and persistence wiring live in
later parts; nothing here touches the UI, the engine, or the database.
"""
