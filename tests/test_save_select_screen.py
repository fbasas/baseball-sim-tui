"""Unit tests for the Load/Resume save picker (FRE-48).

Two layers, both DB-free and Pilot-free (house mock-``self`` idiom, mirroring
``tests/test_lineup_edit_screen.py`` / ``tests/test_game_screen_save.py``):

- ``list_save_entries`` — the listing/sorting helper: reads each save's
  ``label``/``created_at``/``kind`` from disk, skips unreadable/incomplete
  files, and returns them newest-first.
- ``SaveSelectScreen`` selection handlers — ``_select_index`` / ``action_confirm``
  / ``action_cancel`` / ``on_option_list_option_selected`` driven with a
  ``types.SimpleNamespace`` standing in for ``self`` and a captured ``dismiss``.
"""

import json
from pathlib import Path
from types import SimpleNamespace

from src.tui.screens.save_select_screen import (
    SaveEntry,
    SaveSelectScreen,
    list_save_entries,
)


# ---------------------------------------------------------------------------
# Fixtures / factories
# ---------------------------------------------------------------------------


def _write_save(
    directory: Path,
    name: str,
    *,
    label: str,
    created_at: str,
    kind: str = "single",
) -> Path:
    """Write a minimal save-shaped JSON file (only the listed metadata matters)."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": kind,
                "created_at": created_at,
                "label": label,
                "game": {},
            }
        )
    )
    return path


def _entry(
    name: str = "save-a.json",
    label: str = "L",
    created_at: str = "2026-07-07T06:00:00+00:00",
    kind: str = "single",
) -> SaveEntry:
    return SaveEntry(path=Path(name), label=label, created_at=created_at, kind=kind)


def _screen_mock(entries, highlighted=0):
    """A mock-``self`` for SaveSelectScreen selection handlers.

    Returns ``(mock_self, captured)`` where ``captured`` collects ``dismiss``
    results. ``query_one`` returns a stub OptionList carrying ``highlighted``;
    ``_select_index`` is lambda-bound to the real method (house style).
    """
    captured = []
    option_list = SimpleNamespace(highlighted=highlighted)
    mock = SimpleNamespace(
        _entries=entries,
        dismiss=lambda result=None: captured.append(result),
        query_one=lambda *a, **k: option_list,
    )
    mock._select_index = lambda index: SaveSelectScreen._select_index(mock, index)
    return mock, captured


# ---------------------------------------------------------------------------
# list_save_entries — listing / sorting / skipping
# ---------------------------------------------------------------------------


def test_list_save_entries_sorts_newest_first(tmp_path):
    _write_save(tmp_path, "save-old.json", label="Oldest", created_at="2026-07-07T06:00:00+00:00")
    _write_save(tmp_path, "save-new.json", label="Newest", created_at="2026-07-07T08:00:00+00:00")
    _write_save(tmp_path, "save-mid.json", label="Middle", created_at="2026-07-07T07:00:00+00:00")

    entries = list_save_entries(tmp_path)

    assert [e.label for e in entries] == ["Newest", "Middle", "Oldest"]
    # Each entry points at its own file.
    assert {e.path.name for e in entries} == {"save-new.json", "save-mid.json", "save-old.json"}


def test_list_save_entries_captures_kind(tmp_path):
    _write_save(tmp_path, "save-s.json", label="Series", created_at="2026-07-07T06:00:00+00:00", kind="series")

    (entry,) = list_save_entries(tmp_path)

    assert entry.kind == "series"


def test_list_save_entries_skips_corrupt_and_incomplete(tmp_path):
    _write_save(tmp_path, "save-good.json", label="Good", created_at="2026-07-07T06:00:00+00:00")
    # Not valid JSON.
    (tmp_path / "save-bad.json").write_text("{ not json ]")
    # Valid JSON but missing the metadata the list needs.
    (tmp_path / "save-nometa.json").write_text(json.dumps({"schema_version": 1, "game": {}}))
    # Valid JSON but not an object.
    (tmp_path / "save-list.json").write_text(json.dumps([1, 2, 3]))

    entries = list_save_entries(tmp_path)

    assert [e.label for e in entries] == ["Good"]


def test_list_save_entries_ignores_non_json_files(tmp_path):
    _write_save(tmp_path, "save-good.json", label="Good", created_at="2026-07-07T06:00:00+00:00")
    (tmp_path / "notes.txt").write_text("not a save")

    entries = list_save_entries(tmp_path)

    assert [e.label for e in entries] == ["Good"]


def test_list_save_entries_missing_directory_is_empty(tmp_path):
    assert list_save_entries(tmp_path / "does-not-exist") == []


def test_list_save_entries_empty_directory_is_empty(tmp_path):
    tmp_path.mkdir(exist_ok=True)
    assert list_save_entries(tmp_path) == []


# ---------------------------------------------------------------------------
# SaveEntry.display
# ---------------------------------------------------------------------------


def test_display_includes_label_and_short_time():
    entry = _entry(label="1927 NYA @ 1927 CHN — B7, 3-2", created_at="2026-07-07T06:20:00+00:00")
    text = entry.display()
    assert "1927 NYA @ 1927 CHN — B7, 3-2" in text
    assert "2026-07-07 06:20" in text
    assert "(series)" not in text


def test_display_marks_series_saves():
    assert "(series)" in _entry(kind="series").display()


# ---------------------------------------------------------------------------
# Selection handlers (mock-self)
# ---------------------------------------------------------------------------


def test_select_index_dismisses_with_chosen_path():
    entries = [_entry("save-a.json"), _entry("save-b.json")]
    mock, captured = _screen_mock(entries)

    SaveSelectScreen._select_index(mock, 1)

    assert captured == [Path("save-b.json")]


def test_select_index_out_of_range_dismisses_none():
    entries = [_entry("save-a.json")]
    mock, captured = _screen_mock(entries)

    SaveSelectScreen._select_index(mock, None)
    SaveSelectScreen._select_index(mock, 5)
    SaveSelectScreen._select_index(mock, -1)

    assert captured == [None, None, None]


def test_action_confirm_dismisses_highlighted_path():
    entries = [_entry("save-a.json"), _entry("save-b.json")]
    mock, captured = _screen_mock(entries, highlighted=1)

    SaveSelectScreen.action_confirm(mock)

    assert captured == [Path("save-b.json")]


def test_action_confirm_with_no_entries_dismisses_none():
    # An empty picker never touches query_one — confirming just backs out.
    captured = []
    mock = SimpleNamespace(
        _entries=[],
        dismiss=lambda result=None: captured.append(result),
        query_one=lambda *a, **k: (_ for _ in ()).throw(AssertionError("queried")),
    )

    SaveSelectScreen.action_confirm(mock)

    assert captured == [None]


def test_action_cancel_dismisses_none():
    entries = [_entry("save-a.json")]
    mock, captured = _screen_mock(entries)

    SaveSelectScreen.action_cancel(mock)

    assert captured == [None]


def test_on_option_selected_dismisses_the_options_path():
    entries = [_entry("save-a.json"), _entry("save-b.json")]
    mock, captured = _screen_mock(entries)
    event = SimpleNamespace(option=SimpleNamespace(id="1"))

    SaveSelectScreen.on_option_list_option_selected(mock, event)

    assert captured == [Path("save-b.json")]
