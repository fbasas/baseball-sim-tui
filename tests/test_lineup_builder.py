"""Tests for lineup builder module and Appearances repository method.

Tests cover:
- get_appearances() returning correct data from Lahman DB
- build_lineup() producing historically accurate position assignments
- Batting order heuristics
- Position conflict resolution
- Starting pitcher selection
"""

import pytest
from pathlib import Path
from typing import Dict, List, Optional
from unittest.mock import MagicMock, patch

# Database path for integration tests
_DB_PATH = Path(__file__).parent.parent / "data" / "lahman.sqlite"


# ---------------------------------------------------------------------------
# Section 1: get_appearances() tests
# ---------------------------------------------------------------------------

class TestGetAppearances:
    """Tests for LahmanRepository.get_appearances() method."""

    @pytest.fixture
    def repo(self):
        """Open real LahmanRepository for integration tests."""
        if not _DB_PATH.exists():
            pytest.skip("lahman.sqlite not found - run build_lahman_db.py first")
        from src.data.lahman import LahmanRepository
        with LahmanRepository(str(_DB_PATH)) as r:
            yield r

    def test_get_appearances_returns_data_for_known_team_year(self, repo):
        """get_appearances('NYA', 1927) returns non-empty list of rows."""
        rows = repo.get_appearances("NYA", 1927)
        assert len(rows) > 0, "Expected rows for 1927 NYA"

    def test_get_appearances_rows_have_player_id(self, repo):
        """Each row from get_appearances has a playerID key."""
        rows = repo.get_appearances("NYA", 1927)
        for row in rows:
            assert "playerID" in row, "Row missing playerID"

    def test_get_appearances_g_columns_are_integers(self, repo):
        """G_* position columns are integers (not strings) in returned rows."""
        rows = repo.get_appearances("NYA", 1927)
        assert len(rows) > 0
        # Check first row has integer G_* values
        row = rows[0]
        for col in ["G_c", "G_1b", "G_2b", "G_3b", "G_ss", "G_lf", "G_cf", "G_rf"]:
            assert col in row, f"Row missing column {col}"
            val = row[col]
            assert isinstance(val, int), f"{col} should be int, got {type(val).__name__}: {val}"

    def test_get_appearances_returns_empty_for_nonexistent_team(self, repo):
        """get_appearances returns empty list for a team/year that doesn't exist."""
        rows = repo.get_appearances("ZZZ", 1927)
        assert rows == [], "Expected empty list for nonexistent team"

    def test_get_appearances_includes_ruth_for_1927_yankees(self, repo):
        """Babe Ruth (ruthba01) appears in 1927 NYA Appearances data."""
        rows = repo.get_appearances("NYA", 1927)
        player_ids = [r["playerID"] for r in rows]
        assert "ruthba01" in player_ids, "Babe Ruth (ruthba01) not found in 1927 NYA appearances"

    def test_appearances_table_has_index(self, repo):
        """Appearances table has the expected team/year index."""
        cursor = repo.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='appearances_team_year_idx'"
        )
        row = cursor.fetchone()
        assert row is not None, "appearances_team_year_idx index not found in database"

    def test_get_appearances_ruth_has_high_rf_games(self, repo):
        """Babe Ruth should have many games in right field for 1927."""
        rows = repo.get_appearances("NYA", 1927)
        ruth_rows = [r for r in rows if r["playerID"] == "ruthba01"]
        assert len(ruth_rows) == 1
        ruth = ruth_rows[0]
        assert ruth["G_rf"] > 50, f"Ruth should have >50 RF games, got {ruth['G_rf']}"


# ---------------------------------------------------------------------------
# Section 2: build_lineup() tests
# ---------------------------------------------------------------------------

class TestBuildLineup:
    """Tests for lineup_builder.build_lineup() with real 1927 NYA data."""

    @pytest.fixture
    def yankees_1927(self):
        """Load 1927 Yankees team for integration tests."""
        if not _DB_PATH.exists():
            pytest.skip("lahman.sqlite not found - run build_lahman_db.py first")
        from src.data.lahman import LahmanRepository
        from src.game.team import Team
        with LahmanRepository(str(_DB_PATH)) as repo:
            team = Team.load_from_repository(repo, "NYA", 1927)
            # Store repo ref for use in build_lineup
            yield team, repo

    def test_build_lineup_assigns_ruth_to_right_field(self, yankees_1927):
        """build_lineup assigns Babe Ruth (ruthba01) to RIGHT_FIELD for 1927 NYA."""
        from src.game.lineup_builder import build_lineup
        from src.game.positions import Position
        team, repo = yankees_1927
        build_lineup(team, repo)
        assert team.lineup is not None
        # Find Ruth in lineup
        ruth_slot = None
        for slot in team.lineup.slots:
            if slot.player_id == "ruthba01":
                ruth_slot = slot
                break
        assert ruth_slot is not None, "Babe Ruth not found in lineup"
        assert ruth_slot.position == Position.RIGHT_FIELD, (
            f"Ruth should be RF, got {ruth_slot.position}"
        )

    def test_build_lineup_assigns_gehrig_to_first_base(self, yankees_1927):
        """build_lineup assigns Lou Gehrig to FIRST_BASE for 1927 NYA."""
        from src.game.lineup_builder import build_lineup
        from src.game.positions import Position
        team, repo = yankees_1927
        build_lineup(team, repo)
        # Find Gehrig in lineup (playerID: gehrig01)
        gehrig_slot = None
        for slot in team.lineup.slots:
            if slot.player_id == "gehrilo01":
                gehrig_slot = slot
                break
        assert gehrig_slot is not None, "Lou Gehrig (gehrilo01) not found in lineup"
        assert gehrig_slot.position == Position.FIRST_BASE, (
            f"Gehrig should be 1B, got {gehrig_slot.position}"
        )

    def test_build_lineup_no_duplicate_positions(self, yankees_1927):
        """No two fielders occupy the same position in the lineup."""
        from src.game.lineup_builder import build_lineup
        from src.game.positions import Position
        team, repo = yankees_1927
        build_lineup(team, repo)
        positions = [slot.position for slot in team.lineup.slots
                     if isinstance(slot.position, Position)]
        assert len(positions) == len(set(positions)), (
            f"Duplicate positions found: {positions}"
        )

    def test_build_lineup_batting_order_has_9_slots(self, yankees_1927):
        """Batting order contains exactly 9 players."""
        from src.game.lineup_builder import build_lineup
        team, repo = yankees_1927
        build_lineup(team, repo)
        assert len(team.lineup.slots) == 9

    def test_build_lineup_default_pitcher_is_most_games_started(self, yankees_1927):
        """Default starting pitcher is the one with most games started."""
        from src.game.lineup_builder import build_lineup, get_default_starter
        team, repo = yankees_1927
        default_pitcher = get_default_starter(team, repo)
        # Verify it's the pitcher with most GS
        max_gs = max(stats.games_started for stats in team.pitching_stats.values())
        pitcher_gs = team.pitching_stats[default_pitcher].games_started
        assert pitcher_gs == max_gs, (
            f"Default pitcher {default_pitcher} has {pitcher_gs} GS, but max is {max_gs}"
        )

    def test_build_lineup_pitcher_id_override(self, yankees_1927):
        """Passing pitcher_id to build_lineup uses that pitcher instead of default."""
        from src.game.lineup_builder import build_lineup
        team, repo = yankees_1927
        # Find any pitcher with pitching stats
        all_pitchers = list(team.pitching_stats.keys())
        assert len(all_pitchers) >= 2, "Need at least 2 pitchers for override test"
        override_pitcher = all_pitchers[1]  # Use second pitcher, not default
        build_lineup(team, repo, pitcher_id=override_pitcher)
        assert team.lineup.starting_pitcher_id == override_pitcher

    def test_build_lineup_batting_slot_4_is_high_power(self, yankees_1927):
        """Cleanup hitter (slot 4) is a high power/SLG batter."""
        from src.game.lineup_builder import build_lineup
        team, repo = yankees_1927
        build_lineup(team, repo)
        # Slot 4 (index 3) should have high HR
        cleanup_batter = team.lineup.slots[3]
        cleanup_stats = cleanup_batter.batting_stats
        # Cleanup hitter for 1927 Yankees should have significant HR
        assert cleanup_stats.home_runs > 20, (
            f"Cleanup hitter should have >20 HR, got {cleanup_stats.home_runs} "
            f"({cleanup_batter.player_id})"
        )


# ---------------------------------------------------------------------------
# Section 3: Position conflict resolution and edge cases
# ---------------------------------------------------------------------------

class TestBuildLineupConflictResolution:
    """Tests for position conflict resolution using mock data."""

    def _make_mock_team(self, batting_stats_map, pitching_stats_map, appearances_data):
        """Create a mock team with specified stats and appearances."""
        from unittest.mock import MagicMock
        from src.data.models import PlayerInfo, BattingStats, PitchingStats, TeamSeason
        from src.game.team import Team

        team_info = TeamSeason(
            team_id="TST", year=1920, league_id="AL",
            team_name="Test Team"
        )

        roster = []
        batting = {}
        pitching = {}

        for pid, bstats in batting_stats_map.items():
            roster.append(PlayerInfo(
                player_id=pid, name_first="Test", name_last=pid,
                bats="R", throws="R"
            ))
            batting[pid] = bstats

        for pid, pstats in pitching_stats_map.items():
            if pid not in batting_stats_map:
                roster.append(PlayerInfo(
                    player_id=pid, name_first="Test", name_last=pid,
                    bats="R", throws="R"
                ))
            pitching[pid] = pstats

        team = Team(
            info=team_info,
            roster=roster,
            batting_stats=batting,
            pitching_stats=pitching
        )

        mock_repo = MagicMock()
        mock_repo.get_appearances.return_value = appearances_data
        mock_repo.get_batting_stats.side_effect = lambda pid, yr: batting.get(pid)
        mock_repo.get_pitching_stats.side_effect = lambda pid, yr: pitching.get(pid)

        return team, mock_repo

    def _make_batting_stats(self, pid, ab=100, h=30, hr=5, bb=10, doubles=5, triples=1):
        """Helper to create BattingStats."""
        from src.data.models import BattingStats
        return BattingStats(
            player_id=pid, year=1920, team_id="TST",
            games=50, at_bats=ab, runs=15, hits=h,
            doubles=doubles, triples=triples, home_runs=hr,
            rbi=20, stolen_bases=2, caught_stealing=1,
            walks=bb, strikeouts=20, hit_by_pitch=1,
            sacrifice_flies=1, sacrifice_hits=1, gidp=2
        )

    def _make_pitching_stats(self, pid, gs=10):
        """Helper to create PitchingStats."""
        from src.data.models import PitchingStats
        return PitchingStats(
            player_id=pid, year=1920, team_id="TST",
            games=15, games_started=gs, wins=6, losses=4,
            ip_outs=150, hits_allowed=60, runs_allowed=25,
            earned_runs=20, home_runs_allowed=3,
            walks_allowed=20, strikeouts=50, hit_batters=2,
            batters_faced=200, wild_pitches=3
        )

    def test_conflict_resolution_assigns_unique_positions(self):
        """When two players both excel at same position, each gets a unique position."""
        from src.game.lineup_builder import build_lineup
        from src.game.positions import Position

        # Two players both have most games at SS
        appearances = [
            {"playerID": "p1", "G_c": 0, "G_1b": 0, "G_2b": 5,
             "G_3b": 0, "G_ss": 80, "G_lf": 0, "G_cf": 0, "G_rf": 0, "G_dh": 0},
            {"playerID": "p2", "G_c": 0, "G_1b": 0, "G_2b": 80,
             "G_3b": 0, "G_ss": 70, "G_lf": 0, "G_cf": 0, "G_rf": 0, "G_dh": 0},
            {"playerID": "p3", "G_c": 0, "G_1b": 80, "G_2b": 0,
             "G_3b": 0, "G_ss": 0, "G_lf": 0, "G_cf": 0, "G_rf": 0, "G_dh": 0},
            {"playerID": "p4", "G_c": 0, "G_1b": 0, "G_2b": 0,
             "G_3b": 80, "G_ss": 0, "G_lf": 0, "G_cf": 0, "G_rf": 0, "G_dh": 0},
            {"playerID": "p5", "G_c": 80, "G_1b": 0, "G_2b": 0,
             "G_3b": 0, "G_ss": 0, "G_lf": 0, "G_cf": 0, "G_rf": 0, "G_dh": 0},
            {"playerID": "p6", "G_c": 0, "G_1b": 0, "G_2b": 0,
             "G_3b": 0, "G_ss": 0, "G_lf": 80, "G_cf": 0, "G_rf": 0, "G_dh": 0},
            {"playerID": "p7", "G_c": 0, "G_1b": 0, "G_2b": 0,
             "G_3b": 0, "G_ss": 0, "G_lf": 0, "G_cf": 80, "G_rf": 0, "G_dh": 0},
            {"playerID": "p8", "G_c": 0, "G_1b": 0, "G_2b": 0,
             "G_3b": 0, "G_ss": 0, "G_lf": 0, "G_cf": 0, "G_rf": 80, "G_dh": 0},
            {"playerID": "p9", "G_c": 0, "G_1b": 0, "G_2b": 0,
             "G_3b": 0, "G_ss": 0, "G_lf": 0, "G_cf": 0, "G_rf": 0, "G_dh": 80},
            {"playerID": "pitcher1", "G_c": 0, "G_1b": 0, "G_2b": 0,
             "G_3b": 0, "G_ss": 0, "G_lf": 0, "G_cf": 0, "G_rf": 0, "G_dh": 0},
        ]

        batting_stats = {f"p{i}": self._make_batting_stats(f"p{i}") for i in range(1, 10)}
        pitching_stats = {"pitcher1": self._make_pitching_stats("pitcher1")}

        team, mock_repo = self._make_mock_team(batting_stats, pitching_stats, appearances)
        build_lineup(team, mock_repo)

        assert team.lineup is not None
        # No duplicate positions
        positions = [slot.position for slot in team.lineup.slots
                     if isinstance(slot.position, Position)]
        assert len(positions) == len(set(positions)), "Duplicate positions found"

    def test_build_lineup_fallback_when_position_zero(self):
        """When all players have 0 games at a position, fallback assigns unassigned player."""
        from src.game.lineup_builder import build_lineup

        # All players have 0 games at certain positions - they'll get assigned via fallback
        appearances = [
            {"playerID": f"p{i}", "G_c": 0, "G_1b": 0, "G_2b": 0,
             "G_3b": 0, "G_ss": 0, "G_lf": 0, "G_cf": 0, "G_rf": 0, "G_dh": 0}
            for i in range(1, 10)
        ] + [
            {"playerID": "pitcher1", "G_c": 0, "G_1b": 0, "G_2b": 0,
             "G_3b": 0, "G_ss": 0, "G_lf": 0, "G_cf": 0, "G_rf": 0, "G_dh": 0}
        ]

        batting_stats = {f"p{i}": self._make_batting_stats(f"p{i}") for i in range(1, 10)}
        pitching_stats = {"pitcher1": self._make_pitching_stats("pitcher1")}

        team, mock_repo = self._make_mock_team(batting_stats, pitching_stats, appearances)
        # Should not raise; fallback should handle all-zero appearances
        build_lineup(team, mock_repo)
        assert team.lineup is not None
        assert len(team.lineup.slots) == 9


# ---------------------------------------------------------------------------
# Section 4: get_default_starter() tests
# ---------------------------------------------------------------------------

class TestGetDefaultStarter:
    """Tests for lineup_builder.get_default_starter()."""

    def test_get_default_starter_returns_pitcher_with_most_gs(self):
        """get_default_starter returns player_id of pitcher with most games started."""
        from src.game.lineup_builder import get_default_starter
        from src.data.models import PitchingStats, TeamSeason, PlayerInfo
        from src.game.team import Team

        # Build mock team with pitchers of varying GS
        def make_pstats(pid, gs):
            return PitchingStats(
                player_id=pid, year=1927, team_id="NYA",
                games=gs + 5, games_started=gs, wins=5, losses=4,
                ip_outs=gs * 27, hits_allowed=50, runs_allowed=20,
                earned_runs=18, home_runs_allowed=2,
                walks_allowed=15, strikeouts=40, hit_batters=1,
                batters_faced=100, wild_pitches=2
            )

        team = Team(
            info=TeamSeason(team_id="NYA", year=1927, league_id="AL", team_name="Yankees"),
            roster=[
                PlayerInfo("p_ace", "Ace", "Starter", "R", "R"),
                PlayerInfo("p_reliever", "Bob", "Reliever", "R", "R"),
                PlayerInfo("p_backup", "Carl", "Backup", "R", "R"),
            ],
            batting_stats={},
            pitching_stats={
                "p_ace": make_pstats("p_ace", 30),
                "p_reliever": make_pstats("p_reliever", 5),
                "p_backup": make_pstats("p_backup", 15),
            }
        )

        mock_repo = MagicMock()
        default = get_default_starter(team, mock_repo)
        assert default == "p_ace", f"Expected p_ace (30 GS), got {default}"
