"""Tests for role card schema, inference, and the build_roles pipeline."""

from pathlib import Path

import pytest

from src.data.models import BattingStats, PitchingStats, PlayerInfo, TeamSeason
from src.manager.inference import build_role_card
from src.manager.roles import (
    BatterRoleType,
    PitcherRoleType,
    TeamRoleCard,
    load_role_card,
    role_card_path,
    save_role_card,
)

LAHMAN_DB_PATH = Path(__file__).parent.parent / "data" / "lahman.sqlite"


def make_pitching_stats(player_id, **overrides):
    defaults = dict(
        player_id=player_id, year=1950, team_id="TST", games=30, games_started=0,
        wins=5, losses=5, ip_outs=300, hits_allowed=90, runs_allowed=45,
        earned_runs=40, home_runs_allowed=8, walks_allowed=30, strikeouts=60,
        hit_batters=2, batters_faced=420, wild_pitches=3,
    )
    defaults.update(overrides)
    return PitchingStats(**defaults)


def make_batting_stats(player_id, **overrides):
    defaults = dict(
        player_id=player_id, year=1950, team_id="TST", games=140, at_bats=500,
        runs=70, hits=140, doubles=25, triples=5, home_runs=12, rbi=60,
        stolen_bases=8, caught_stealing=4, walks=50, strikeouts=60,
        hit_by_pitch=2, sacrifice_flies=3, sacrifice_hits=4, gidp=10,
    )
    defaults.update(overrides)
    return BattingStats(**defaults)


def make_player(player_id, bats="R", throws="R"):
    return PlayerInfo(
        player_id=player_id, name_first="Test", name_last=player_id.capitalize(),
        bats=bats, throws=throws,
    )


_POSITION_COLS = ["G_c", "G_1b", "G_2b", "G_3b", "G_ss", "G_lf", "G_cf", "G_rf"]


def make_synthetic_team(year=1950, team_games=154):
    """A minimal but complete team: 5 pitchers + 10 position players."""
    team = TeamSeason(
        team_id="TST", year=year, league_id="AL", team_name="Testers", games=team_games,
    )
    roster, batting, pitching, appearances = [], {}, {}, []

    # Pitchers: 3 starters (descending GS), 1 fireman/closer type, 1 mop-up
    pitcher_specs = [
        ("ace", dict(games=36, games_started=32, ip_outs=840, complete_games=20)),
        ("two", dict(games=30, games_started=28, ip_outs=720, complete_games=10)),
        ("three", dict(games=28, games_started=24, ip_outs=600, complete_games=4)),
        ("fireman", dict(games=45, games_started=0, ip_outs=270, saves=12, games_finished=35)),
        ("mopup", dict(games=25, games_started=0, ip_outs=150, games_finished=5)),
    ]
    for pid, spec in pitcher_specs:
        roster.append(make_player(pid))
        pitching[pid] = make_pitching_stats(pid, year=year, **spec)

    # Position players: 8 clear regulars, 1 DH-quality bat, 1 bench player
    position_specs = [
        ("catcher", "G_c", 130), ("first", "G_1b", 150), ("second", "G_2b", 145),
        ("third", "G_3b", 140), ("short", "G_ss", 148), ("left", "G_lf", 135),
        ("center", "G_cf", 152), ("right", "G_rf", 150),
    ]
    for pid, col, games in position_specs:
        roster.append(make_player(pid))
        batting[pid] = make_batting_stats(pid, year=year, games=games)
        row = {"playerID": pid, "G_dh": 0}
        for c in _POSITION_COLS:
            row[c] = games if c == col else 0
        appearances.append(row)

    # Big bat with modest fielding (ends up DH), and a true bench player
    roster.append(make_player("bigbat"))
    batting["bigbat"] = make_batting_stats(
        "bigbat", year=year, games=120, hits=170, home_runs=35, walks=80,
    )
    appearances.append({"playerID": "bigbat", "G_1b": 20, "G_dh": 0,
                        **{c: 0 for c in _POSITION_COLS if c != "G_1b"}})

    roster.append(make_player("benchy"))
    batting["benchy"] = make_batting_stats("benchy", year=year, games=25, at_bats=70, hits=16)
    appearances.append({"playerID": "benchy", "G_lf": 15, "G_dh": 0,
                        **{c: 0 for c in _POSITION_COLS if c != "G_lf"}})

    # In lots of games but rarely in the field: a pinch-hit specialist
    roster.append(make_player("pinchy"))
    batting["pinchy"] = make_batting_stats("pinchy", year=year, games=70, at_bats=110, hits=30)
    appearances.append({"playerID": "pinchy", "G_rf": 8, "G_dh": 0,
                        **{c: 0 for c in _POSITION_COLS if c != "G_rf"}})

    return team, roster, batting, pitching, appearances


class TestInferenceSynthetic:
    """Role inference on a fully synthetic team (no DB required)."""

    def test_rotation_ordered_by_games_started(self):
        card = build_role_card(*make_synthetic_team())
        rotation = card.rotation()
        assert [p.player_id for p in rotation] == ["ace", "two", "three"]
        assert [p.rotation_slot for p in rotation] == [1, 2, 3]

    def test_workhorse_has_longer_leash_than_low_cg_starter(self):
        card = build_role_card(*make_synthetic_team())
        ace = card.pitchers["ace"]        # 20 CG in 32 GS
        three = card.pitchers["three"]    # 4 CG in 24 GS
        assert ace.leash_fatigue > three.leash_fatigue
        assert 0.55 <= three.leash_fatigue <= ace.leash_fatigue <= 0.90

    def test_pre_save_era_fireman_is_setup_not_closer(self):
        card = build_role_card(*make_synthetic_team(year=1950))
        assert card.pitchers["fireman"].role == PitcherRoleType.SETUP
        assert all(p.role != PitcherRoleType.CLOSER for p in card.pitchers.values())

    def test_modern_era_closer_by_saves(self):
        team, roster, batting, pitching, apps = make_synthetic_team(year=2016)
        card = build_role_card(team, roster, batting, pitching, apps)
        assert card.pitchers["fireman"].role == PitcherRoleType.CLOSER

    def test_batter_roles_by_start_share(self):
        card = build_role_card(*make_synthetic_team())
        assert card.batters["center"].role == BatterRoleType.REGULAR
        assert card.batters["benchy"].role == BatterRoleType.BENCH
        assert card.batters["pinchy"].role == BatterRoleType.PINCH_SPECIALIST

    def test_batting_order_has_nine_unique_batters_with_positions(self):
        card = build_role_card(*make_synthetic_team())
        assert len(card.batting_order) == 9
        assert len(set(card.batting_order)) == 9
        abbrevs = sorted(card.lineup_positions[pid] for pid in card.batting_order)
        assert abbrevs == sorted(["C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "DH"])

    def test_deterministic(self):
        card1 = build_role_card(*make_synthetic_team())
        card2 = build_role_card(*make_synthetic_team())
        assert card1.to_dict() == card2.to_dict()

    def test_too_few_batters_raises(self):
        team, roster, batting, pitching, apps = make_synthetic_team()
        for pid in ["benchy", "bigbat", "right"]:
            del batting[pid]
        with pytest.raises(ValueError, match="9 batters"):
            build_role_card(team, roster, batting, pitching, apps)


class TestRoleCardSerialization:
    def test_json_round_trip(self, tmp_path):
        card = build_role_card(*make_synthetic_team())
        save_role_card(card, tmp_path)
        loaded = load_role_card("TST", 1950, tmp_path)
        assert loaded.to_dict() == card.to_dict()
        assert loaded.pitchers["ace"].role == PitcherRoleType.STARTER
        assert loaded.rotation()[0].player_id == "ace"

    def test_missing_artifact_raises_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_role_card("XXX", 1900, tmp_path)

    def test_unsupported_schema_version_rejected(self, tmp_path):
        card = build_role_card(*make_synthetic_team())
        path = save_role_card(card, tmp_path)
        content = path.read_text().replace('"schema_version": 1', '"schema_version": 99')
        path.write_text(content)
        with pytest.raises(ValueError, match="schema_version"):
            load_role_card("TST", 1950, tmp_path)

    def test_role_card_path_layout(self, tmp_path):
        assert role_card_path("NYA", 1927, tmp_path) == tmp_path / "NYA-1927.json"


@pytest.fixture
def lahman_repo():
    if not LAHMAN_DB_PATH.exists():
        pytest.skip(f"Lahman database not found at {LAHMAN_DB_PATH}")
    from src.data.lahman import LahmanRepository

    repo = LahmanRepository(str(LAHMAN_DB_PATH))
    yield repo
    repo.close()


def build_card_from_db(repo, team_id, year):
    team_season = repo.get_team_season(team_id, year)
    roster = repo.get_team_roster(team_id, year)
    batting, pitching = {}, {}
    for player in roster:
        b = repo.get_batting_stats(player.player_id, year)
        if b:
            batting[player.player_id] = b
        p = repo.get_pitching_stats(player.player_id, year)
        if p:
            pitching[player.player_id] = p
    appearances = repo.get_appearances(team_id, year)
    return build_role_card(team_season, roster, batting, pitching, appearances)


class TestGoldenTeams:
    """Golden tests: inferred roles match the historical shape of famous teams."""

    def test_1927_yankees(self, lahman_repo):
        card = build_card_from_db(lahman_repo, "NYA", 1927)
        rotation_ids = [p.player_id for p in card.rotation()]

        # 4-man era rotation led by Waite Hoyt
        assert len(rotation_ids) == 4
        assert rotation_ids[0] == "hoytwa01"
        assert set(rotation_ids) == {"hoytwa01", "shockur01", "pennohe01", "ruethdu01"}

        # Workhorse leashes: long, with high fatigue tolerance
        for p in card.rotation():
            assert p.leash_bf >= 28
            assert p.leash_fatigue >= 0.70
            assert p.typical_rest_days == 3

        # No anachronistic closer; Wilcy Moore is the fireman (setup)
        assert all(p.role != PitcherRoleType.CLOSER for p in card.pitchers.values())
        assert card.pitchers["moorewi01"].role == PitcherRoleType.SETUP

        # Ruth and Gehrig are regulars and in the recommended order
        assert card.batters["ruthba01"].role == BatterRoleType.REGULAR
        assert card.batters["gehrilo01"].role == BatterRoleType.REGULAR
        assert "ruthba01" in card.batting_order
        assert "gehrilo01" in card.batting_order

    def test_2016_cubs(self, lahman_repo):
        card = build_card_from_db(lahman_repo, "CHN", 2016)
        rotation_ids = [p.player_id for p in card.rotation()]

        # 5-man modern rotation
        assert len(rotation_ids) == 5
        assert set(rotation_ids) == {
            "lestejo01", "arrieja01", "hendrky01", "hammeja01", "lackejo01"
        }

        # Modern leashes: short, hooked early
        for p in card.rotation():
            assert p.leash_bf <= 28
            assert p.leash_fatigue <= 0.60
            assert p.typical_rest_days == 4

        # Chapman closes, Rondon sets up
        assert card.pitchers["chapmar01"].role == PitcherRoleType.CLOSER
        assert card.pitchers["rondohe01"].role == PitcherRoleType.SETUP

        # Bryant and Rizzo are regulars
        assert card.batters["bryankr01"].role == BatterRoleType.REGULAR
        assert card.batters["rizzoan01"].role == BatterRoleType.REGULAR
