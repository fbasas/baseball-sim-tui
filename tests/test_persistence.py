"""Tests for the single-game save-file format and JSON disk I/O (FRE-45).

Two layers, per the house style:
  * Pure round-trip / error tests with synthetic data (no DB), reusing the
    ``make_*`` factories established in ``tests/test_serialization.py``.
  * One DB-guarded integration test for ``rehydrate_teams`` (skipped when
    ``data/lahman.sqlite`` is absent, mirroring
    ``tests/test_game_screen_substitutions.py``).
"""

import json
from pathlib import Path

import pytest

from src.game.persistence import (
    SCHEMA_VERSION,
    BoxScore,
    CorruptSaveError,
    GameSnapshot,
    MissingTeamError,
    SaveFile,
    SaveVersionError,
    TeamRef,
    capture_rng,
    load_game,
    restore_rng,
    save_game,
    saves_dir,
)
from src.game.state import InningHalf
from src.simulation.rng import SimulationRNG
from src.tui.game_config import GameConfig

# Reuse the FRE-43 serialization factories rather than duplicating them.
from tests.test_serialization import (
    make_lineup,
    make_populated_game_state,
    make_populated_sub_manager,
)

_DB_PATH = Path(__file__).parent.parent / "data" / "lahman.sqlite"


# --- Factories --------------------------------------------------------------


def make_box_score() -> BoxScore:
    """A populated box score exercising the enum + tuple-encoded fields."""
    return BoxScore(
        batting_lines={"b0": {"AB": 4, "R": 1, "H": 2, "RBI": 1, "BB": 0, "K": 1}},
        pitching_lines={"away_sp": {"outs": 18, "H": 5, "R": 2, "ER": 2, "BB": 1, "K": 6}},
        pitcher_teams={"away_sp": "away", "home_sp": "home"},
        batter_teams={"b0": "away"},
        away_hits=8,
        home_hits=6,
        inning_scores=[(0, 1), (2, 0), (1, 1)],
        away_errors=1,
        home_errors=0,
        current_inning_away_runs=1,
        current_inning_home_runs=0,
        current_half_inning=(7, InningHalf.BOTTOM),
    )


def make_snapshot() -> GameSnapshot:
    """A fully-populated snapshot from synthetic pieces (no DB)."""
    rng = SimulationRNG(seed=1927)
    rng.random()  # advance so bit-generator state != a fresh seed
    return GameSnapshot(
        config=GameConfig(mode="single", best_of=None, away_ai=False, home_ai=True),
        away_ref=TeamRef("NYA", 1927),
        home_ref=TeamRef("CHN", 1927),
        away_lineup=make_lineup().to_dict(),
        home_lineup=make_lineup().to_dict(),
        game_state=make_populated_game_state(),
        substitutions=make_populated_sub_manager(),
        box_score=make_box_score(),
        rng=capture_rng(rng),
    )


def make_save() -> SaveFile:
    return SaveFile(
        kind="single",
        created_at="2026-07-06T12:00:00+00:00",
        label="1927 NYA @ 1927 CHN — B7, 3-2",
        game=make_snapshot(),
    )


# --- Round-trip -------------------------------------------------------------


class TestRoundTrip:
    def test_savefile_round_trips_through_disk(self, tmp_path):
        save = make_save()
        path = tmp_path / "game.json"
        save_game(save, path)
        loaded = load_game(path)
        assert loaded == save

    def test_snapshot_round_trip_in_memory(self):
        snap = make_snapshot()
        assert GameSnapshot.from_dict(snap.to_dict()) == snap

    def test_savefile_is_valid_json_with_indent(self, tmp_path):
        path = tmp_path / "game.json"
        save_game(make_save(), path)
        text = path.read_text()
        # Pretty-printed (indent=2), matching roles.py.
        assert "\n  " in text
        data = json.loads(text)
        assert data["schema_version"] == SCHEMA_VERSION
        assert data["kind"] == "single"
        assert data["game"]["away_ref"] == {"team_id": "NYA", "year": 1927}

    def test_box_score_round_trip_preserves_tuples(self):
        box = make_box_score()
        restored = BoxScore.from_dict(box.to_dict())
        assert restored.current_half_inning == (7, InningHalf.BOTTOM)
        assert restored.inning_scores == [(0, 1), (2, 0), (1, 1)]

    def test_whole_savefile_json_serializable(self):
        # Every nested piece must be plain JSON types.
        json.dumps(make_save().to_dict())


# --- Backward compatibility: pre-FRE-90 saves (no 2B/3B/HR keys) -------------


class TestPreFre90BoxScore:
    """A save written before FRE-90 added the ``2B/3B/HR`` batting keys must
    keep loading, restoring, and accumulating — the missing keys read as 0."""

    def _old_box_dict(self) -> dict:
        """A serialized BoxScore whose batting lines lack the new keys."""
        return {
            "batting_lines": {
                "b0": {"AB": 4, "R": 1, "H": 2, "RBI": 1, "BB": 0, "K": 1},
            },
            "pitching_lines": {
                "sp": {"outs": 18, "H": 5, "R": 2, "ER": 2, "BB": 1, "K": 6},
            },
            "pitcher_teams": {"sp": "away"},
            "away_hits": 8,
            "home_hits": 6,
            "inning_scores": [[0, 1], [2, 0]],
            "away_errors": 1,
            "home_errors": 0,
            "current_inning_away_runs": 0,
            "current_inning_home_runs": 1,
            "current_half_inning": [7, "BOTTOM"],
        }

    def test_old_box_score_loads(self):
        """BoxScore.from_dict accepts pre-FRE-90 batting lines verbatim."""
        box = BoxScore.from_dict(self._old_box_dict())
        # Old lines load exactly as stored (no eager key backfill).
        assert box.batting_lines["b0"] == {
            "AB": 4, "R": 1, "H": 2, "RBI": 1, "BB": 0, "K": 1
        }
        assert box.current_half_inning == (7, InningHalf.BOTTOM)

    def test_old_save_file_round_trips(self, tmp_path):
        """A whole SaveFile carrying pre-FRE-90 box lines loads from disk."""
        snap = make_snapshot()
        snap.box_score = BoxScore.from_dict(self._old_box_dict())
        save = SaveFile(
            kind="single", created_at="t", label="old", game=snap,
        )
        path = save_game(save, tmp_path / "old.json")
        loaded = load_game(path)
        assert loaded.game.box_score.batting_lines["b0"]["H"] == 2

    def test_resumed_old_box_keeps_accumulating(self):
        """Recording into a resumed old box upgrades the touched line in place:
        the new 2B/3B/HR keys appear as 0 and increment normally, no KeyError."""
        box = BoxScore.from_dict(self._old_box_dict())
        result = _double_by("b0")
        box.record_play(result, batter_id="b0", pitcher_id="sp",
                        half=InningHalf.TOP)
        line = box.batting_lines["b0"]
        assert line["2B"] == 1 and line["3B"] == 0 and line["HR"] == 0
        assert line["AB"] == 5 and line["H"] == 3  # continued from the old line


def _double_by(batter_id: str):
    """A minimal real AtBatResult for a bases-empty double (no runs)."""
    from src.simulation.engine import AtBatResult
    from src.simulation.game_state import AdvancementResult, BaseState
    from src.simulation.outcomes import AtBatOutcome

    return AtBatResult(
        outcome=AtBatOutcome.DOUBLE,
        advancement=AdvancementResult(
            new_base_state=BaseState(), runs_scored=0, runners_scored=[]
        ),
        probabilities={},
        audit_trail=[],
    )


# --- RNG determinism --------------------------------------------------------


class TestRngCapture:
    def test_capture_restore_reproduces_sequence(self):
        rng = SimulationRNG(seed=7)
        for _ in range(5):
            rng.random()
        captured = capture_rng(rng)
        expected = [rng.random() for _ in range(10)]

        fresh = SimulationRNG()  # unseeded
        restore_rng(fresh, captured)
        assert [fresh.random() for _ in range(10)] == expected

    def test_capture_survives_json_round_trip(self):
        rng = SimulationRNG(seed=99)
        rng.random()
        captured = capture_rng(rng)
        expected = [rng.random() for _ in range(4)]

        reloaded = json.loads(json.dumps(captured))
        fresh = SimulationRNG()
        restore_rng(fresh, reloaded)
        assert [fresh.random() for _ in range(4)] == expected


# --- Error handling ---------------------------------------------------------


class TestErrorHandling:
    def test_wrong_schema_version_raises(self, tmp_path):
        save = make_save()
        data = save.to_dict()
        data["schema_version"] = SCHEMA_VERSION + 1
        path = tmp_path / "future.json"
        path.write_text(json.dumps(data, indent=2))
        with pytest.raises(SaveVersionError, match="schema_version"):
            load_game(path)

    def test_missing_schema_version_raises(self, tmp_path):
        data = make_save().to_dict()
        del data["schema_version"]
        path = tmp_path / "noversion.json"
        path.write_text(json.dumps(data))
        with pytest.raises(SaveVersionError):
            load_game(path)

    def test_corrupt_json_raises(self, tmp_path):
        path = tmp_path / "corrupt.json"
        path.write_text("{ this is not valid json ,,, ")
        with pytest.raises(CorruptSaveError, match="not valid JSON"):
            load_game(path)

    def test_malformed_structure_raises(self, tmp_path):
        # Valid JSON and correct version, but missing the "game" payload.
        path = tmp_path / "malformed.json"
        path.write_text(json.dumps({"schema_version": SCHEMA_VERSION, "kind": "single"}))
        with pytest.raises(CorruptSaveError):
            load_game(path)


# --- Saves directory --------------------------------------------------------


def test_saves_dir_is_repo_relative_and_created():
    d = saves_dir()
    assert d.name == "saves"
    assert d.parent.name == "data"
    # Repo-root-relative: data/ sits beside src/.
    assert (d.parent.parent / "src" / "game" / "persistence.py").exists()
    assert d.is_dir()


# --- DB-guarded integration -------------------------------------------------


def test_rehydrate_teams_matches_fresh_load(tmp_path):
    if not _DB_PATH.exists():
        pytest.skip("lahman.sqlite not found - run build_lahman_db.py first")

    from src.data.lahman import LahmanRepository
    from src.game.lineup_builder import build_lineup, get_default_starter
    from src.game.team import Team

    with LahmanRepository(str(_DB_PATH)) as repo:
        # Build a game whose away side carries a real, in-place lineup.
        away = Team.load_from_repository(repo, "NYA", 1927)
        home = Team.load_from_repository(repo, "CHN", 1927)
        away_pid = get_default_starter(away, repo)
        home_pid = get_default_starter(home, repo)
        build_lineup(away, repo, pitcher_id=away_pid)
        build_lineup(home, repo, pitcher_id=home_pid)

        snap = make_snapshot()
        snap.away_ref = TeamRef("NYA", 1927)
        snap.home_ref = TeamRef("CHN", 1927)
        snap.away_lineup = away.lineup.to_dict()
        snap.home_lineup = home.lineup.to_dict()
        save = SaveFile(
            kind="single",
            created_at="2026-07-06T12:00:00+00:00",
            label="integration",
            game=snap,
        )

        path = tmp_path / "integration.json"
        save_game(save, path)
        loaded = load_game(path)
        r_away, r_home = loaded.rehydrate_teams(repo)

        fresh_away = Team.load_from_repository(repo, "NYA", 1927)
        # Roster/stats re-hydrate byte-identically from the same DB...
        assert r_away.info == fresh_away.info
        assert r_away.roster == fresh_away.roster
        assert r_away.batting_stats == fresh_away.batting_stats
        assert r_away.pitching_stats == fresh_away.pitching_stats
        # ...and the saved lineup overlay is re-applied (not rebuilt).
        assert r_away.lineup.to_dict() == away.lineup.to_dict()
        assert r_home.lineup.to_dict() == home.lineup.to_dict()


def test_rehydrate_missing_team_fails_loudly(tmp_path):
    if not _DB_PATH.exists():
        pytest.skip("lahman.sqlite not found - run build_lahman_db.py first")

    from src.data.lahman import LahmanRepository

    save = make_save()
    save.game.away_ref = TeamRef("ZZZ", 1901)  # not in any real Lahman DB
    with LahmanRepository(str(_DB_PATH)) as repo:
        with pytest.raises(MissingTeamError, match="ZZZ 1901"):
            save.rehydrate_teams(repo)
