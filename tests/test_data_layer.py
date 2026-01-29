"""Tests for data layer: models and repository."""

import os
from pathlib import Path

import pytest

from src.data.models import (
    BattingStats,
    PitchingStats,
    PlayerInfo,
    TeamSeason,
)


# Path to Lahman database - tests skip if not present
LAHMAN_DB_PATH = Path(__file__).parent.parent / "data" / "lahman.sqlite"


class TestBattingStats:
    """Tests for BattingStats dataclass."""

    def test_singles_calculation(self):
        """Singles = hits - doubles - triples - home_runs."""
        stats = BattingStats(
            player_id="test01",
            year=2023,
            team_id="NYA",
            games=150,
            at_bats=500,
            runs=80,
            hits=140,
            doubles=25,
            triples=3,
            home_runs=30,
            rbi=90,
            stolen_bases=10,
            caught_stealing=3,
            walks=60,
            strikeouts=120,
            hit_by_pitch=5,
            sacrifice_flies=4,
            sacrifice_hits=2,
            gidp=12,
        )
        # 140 - 25 - 3 - 30 = 82
        assert stats.singles == 82

    def test_plate_appearances_calculation(self):
        """PA = AB + BB + HBP + SF + SH."""
        stats = BattingStats(
            player_id="test01",
            year=2023,
            team_id="NYA",
            games=150,
            at_bats=500,
            runs=80,
            hits=140,
            doubles=25,
            triples=3,
            home_runs=30,
            rbi=90,
            stolen_bases=10,
            caught_stealing=3,
            walks=60,
            strikeouts=120,
            hit_by_pitch=5,
            sacrifice_flies=4,
            sacrifice_hits=2,
            gidp=12,
        )
        # 500 + 60 + 5 + 4 + 2 = 571
        assert stats.plate_appearances == 571

    def test_zero_extras_all_singles(self):
        """Player with no extra-base hits has singles = hits."""
        stats = BattingStats(
            player_id="test01",
            year=2023,
            team_id="NYA",
            games=50,
            at_bats=100,
            runs=10,
            hits=25,
            doubles=0,
            triples=0,
            home_runs=0,
            rbi=10,
            stolen_bases=5,
            caught_stealing=2,
            walks=10,
            strikeouts=20,
            hit_by_pitch=1,
            sacrifice_flies=1,
            sacrifice_hits=0,
            gidp=2,
        )
        assert stats.singles == 25
        assert stats.plate_appearances == 112  # 100 + 10 + 1 + 1 + 0


class TestPitchingStats:
    """Tests for PitchingStats dataclass."""

    def test_innings_pitched_calculation(self):
        """IP = IPouts / 3."""
        stats = PitchingStats(
            player_id="test02",
            year=2023,
            team_id="NYA",
            games=30,
            games_started=30,
            wins=15,
            losses=8,
            ip_outs=600,  # 200 innings
            hits_allowed=180,
            runs_allowed=80,
            earned_runs=75,
            home_runs_allowed=20,
            walks_allowed=50,
            strikeouts=200,
            hit_batters=5,
            batters_faced=800,
            wild_pitches=5,
        )
        assert stats.innings_pitched == 200.0

    def test_partial_innings(self):
        """IP handles partial innings correctly."""
        stats = PitchingStats(
            player_id="test02",
            year=2023,
            team_id="NYA",
            games=10,
            games_started=5,
            wins=3,
            losses=2,
            ip_outs=200,  # 66.67 innings
            hits_allowed=60,
            runs_allowed=30,
            earned_runs=28,
            home_runs_allowed=8,
            walks_allowed=20,
            strikeouts=60,
            hit_batters=2,
            batters_faced=280,
            wild_pitches=2,
        )
        assert abs(stats.innings_pitched - 66.67) < 0.01


class TestPlayerInfo:
    """Tests for PlayerInfo dataclass."""

    def test_creation(self):
        """PlayerInfo can be created with all fields."""
        player = PlayerInfo(
            player_id="ruthba01",
            name_first="Babe",
            name_last="Ruth",
            bats="L",
            throws="L",
        )
        assert player.player_id == "ruthba01"
        assert player.name_first == "Babe"
        assert player.name_last == "Ruth"
        assert player.bats == "L"
        assert player.throws == "L"


class TestTeamSeason:
    """Tests for TeamSeason dataclass."""

    def test_default_park_factors(self):
        """Park factors default to 100 (neutral)."""
        team = TeamSeason(
            team_id="NYA",
            year=2023,
            league_id="AL",
            team_name="New York Yankees",
        )
        assert team.park_factor_batting == 100
        assert team.park_factor_pitching == 100

    def test_custom_park_factors(self):
        """Park factors can be set to custom values."""
        team = TeamSeason(
            team_id="COL",
            year=2023,
            league_id="NL",
            team_name="Colorado Rockies",
            park_factor_batting=115,
            park_factor_pitching=115,
        )
        assert team.park_factor_batting == 115
        assert team.park_factor_pitching == 115


# Repository tests - require actual database
@pytest.fixture
def lahman_repo():
    """Fixture that provides LahmanRepository if database exists."""
    if not LAHMAN_DB_PATH.exists():
        pytest.skip(f"Lahman database not found at {LAHMAN_DB_PATH}")

    from src.data.lahman import LahmanRepository

    repo = LahmanRepository(str(LAHMAN_DB_PATH))
    yield repo
    repo.close()


class TestLahmanRepository:
    """Integration tests for LahmanRepository (require database)."""

    def test_get_player_info_exists(self, lahman_repo):
        """Can retrieve info for a known player."""
        player = lahman_repo.get_player_info("ruthba01")
        assert player is not None
        assert player.player_id == "ruthba01"
        assert player.name_first == "Babe"
        assert player.name_last == "Ruth"

    def test_get_player_info_not_found(self, lahman_repo):
        """Returns None for non-existent player."""
        player = lahman_repo.get_player_info("notreal99")
        assert player is None

    def test_get_batting_stats_exists(self, lahman_repo):
        """Can retrieve batting stats for known player/year."""
        stats = lahman_repo.get_batting_stats("ruthba01", 1927)
        assert stats is not None
        assert stats.player_id == "ruthba01"
        assert stats.year == 1927
        assert stats.home_runs == 60  # Famous 60 HR season

    def test_get_batting_stats_not_found(self, lahman_repo):
        """Returns None for player with no stats in year."""
        stats = lahman_repo.get_batting_stats("ruthba01", 1950)  # After retirement
        assert stats is None

    def test_get_pitching_stats_exists(self, lahman_repo):
        """Can retrieve pitching stats for known pitcher/year."""
        stats = lahman_repo.get_pitching_stats("johnswa01", 1913)  # Walter Johnson
        assert stats is not None
        assert stats.player_id == "johnswa01"
        assert stats.year == 1913

    def test_get_pitching_stats_not_found(self, lahman_repo):
        """Returns None for non-pitcher or wrong year."""
        stats = lahman_repo.get_pitching_stats("ruthba01", 1927)  # Ruth pitched earlier
        assert stats is None

    def test_get_team_roster(self, lahman_repo):
        """Can retrieve team roster for known team/year."""
        roster = lahman_repo.get_team_roster("NYA", 1927)  # 1927 Yankees
        assert len(roster) > 0
        # Ruth should be on the roster
        player_ids = [p.player_id for p in roster]
        assert "ruthba01" in player_ids

    def test_get_team_roster_empty(self, lahman_repo):
        """Returns empty list for non-existent team/year."""
        roster = lahman_repo.get_team_roster("XXX", 2023)
        assert roster == []

    def test_get_team_season_exists(self, lahman_repo):
        """Can retrieve team season info."""
        team = lahman_repo.get_team_season("NYA", 1927)
        assert team is not None
        assert team.team_id == "NYA"
        assert team.year == 1927

    def test_get_team_season_not_found(self, lahman_repo):
        """Returns None for non-existent team/year."""
        team = lahman_repo.get_team_season("XXX", 2023)
        assert team is None

    def test_context_manager(self):
        """Repository can be used as context manager."""
        if not LAHMAN_DB_PATH.exists():
            pytest.skip(f"Lahman database not found at {LAHMAN_DB_PATH}")

        from src.data.lahman import LahmanRepository

        with LahmanRepository(str(LAHMAN_DB_PATH)) as repo:
            player = repo.get_player_info("ruthba01")
            assert player is not None


class TestLahmanRepositoryImport:
    """Test that repository can be imported without database."""

    def test_import_succeeds(self):
        """Repository class can be imported."""
        from src.data.lahman import LahmanRepository

        assert LahmanRepository is not None
