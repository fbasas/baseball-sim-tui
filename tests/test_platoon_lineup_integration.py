"""Integration: platoon-aware lineups shift with the opposing starter's hand.

FRE-178's headline definition of done, exercised end-to-end through the real
``play_ai_game`` (the same runner the headless season loop uses) on a fully
constructed fixture — no Lahman database required, so this runs everywhere.

The away team has a genuine L/R platoon at left field: ``lf_lhb`` (bats L) is
the historical starter, ``lf_rhb`` (bats R) is its bench partner. The home team
carries two starters of known, opposite throwing hands; pointing the away side
at each in turn proves the left-handed bat starts vs the RHP and the
right-handed bat starts vs the LHP, that the starting nine is therefore not
constant across the "schedule", and that every game still completes.
"""

from src.data.models import BattingStats, PitchingStats, TeamSeason
from src.game.autoplay import play_ai_game
from src.game.manager_adapter import TeamManagerContext
from src.game.team import Team
from src.manager.manager import ManagerAI
from src.manager.roles import (
    BatterRoleCard,
    BatterRoleType,
    PitcherRoleCard,
    PitcherRoleType,
    TeamRoleCard,
)

YEAR = 1999


def _bat(pid: str) -> BattingStats:
    """An ordinary ~.270/20-HR batting line (enough for games to terminate)."""
    return BattingStats(
        player_id=pid, year=YEAR, team_id="TST", games=150, at_bats=550,
        runs=75, hits=150, doubles=30, triples=3, home_runs=20, rbi=75,
        stolen_bases=5, caught_stealing=2, walks=50, strikeouts=110,
        hit_by_pitch=4, sacrifice_flies=5, sacrifice_hits=0, gidp=12,
    )


def _pit(pid: str) -> PitchingStats:
    """A durable average starter — high enough leash to go the distance so the
    fixture needs no bullpen for a game to complete."""
    return PitchingStats(
        player_id=pid, year=YEAR, team_id="TST", games=34, games_started=34,
        wins=15, losses=10, ip_outs=660, hits_allowed=210, runs_allowed=95,
        earned_runs=88, home_runs_allowed=22, walks_allowed=55, strikeouts=160,
        hit_batters=5, batters_faced=900, wild_pitches=5, complete_games=10,
    )


def _starter_card(pid: str, throws: str) -> PitcherRoleCard:
    # Long leash so the manager never needs a reliever the fixture doesn't have.
    return PitcherRoleCard(
        player_id=pid, role=PitcherRoleType.STARTER, rotation_slot=1,
        leash_bf=99, leash_fatigue=0.99, typical_rest_days=4,
        appearance_share=0.2, metrics={"whip": 1.25, "era": 4.0, "throws": throws},
    )


def _reg(pid: str, pos: str, bats: str = "R") -> BatterRoleCard:
    return BatterRoleCard(
        player_id=pid, role=BatterRoleType.REGULAR, primary_position=pos,
        eligible_positions=[pos], start_share=0.85,
        metrics={"ops": 0.760, "obp": 0.330, "slg": 0.430, "avg": 0.270,
                 "ab": 500, "games": 150, "bats": bats},
    )


# The eight non-LF regulars (position, batting hand).
_OTHERS = [
    ("c_cf", "CF"), ("c_ss", "SS"), ("c_1b", "1B"), ("c_rf", "RF"),
    ("c_3b", "3B"), ("c_2b", "2B"), ("c_c", "C"), ("c_dh", "DH"),
]


def _away_team_and_card():
    """Away team + card whose LF is an L/R platoon pair (lf_lhb / lf_rhb)."""
    batters = {pid: _reg(pid, pos) for pid, pos in _OTHERS}
    batters["lf_lhb"] = BatterRoleCard(
        player_id="lf_lhb", role=BatterRoleType.PLATOON, primary_position="LF",
        eligible_positions=["LF"], start_share=0.35,
        platoon_partner="lf_rhb", platoon_side="R",
        metrics={"ops": 0.770, "obp": 0.340, "slg": 0.430, "avg": 0.275,
                 "ab": 260, "games": 95, "bats": "L"},
    )
    batters["lf_rhb"] = BatterRoleCard(
        player_id="lf_rhb", role=BatterRoleType.PLATOON, primary_position="LF",
        eligible_positions=["LF"], start_share=0.30,
        platoon_partner="lf_lhb", platoon_side="L",
        metrics={"ops": 0.750, "obp": 0.325, "slg": 0.425, "avg": 0.268,
                 "ab": 230, "games": 80, "bats": "R"},
    )
    order = [pid for pid, _ in _OTHERS[:4]] + ["lf_lhb"] + [pid for pid, _ in _OTHERS[4:]]
    positions = {pid: pos for pid, pos in _OTHERS}
    positions["lf_lhb"] = "LF"
    card = TeamRoleCard(
        team_id="AWY", year=YEAR,
        pitchers={"awy_sp": _starter_card("awy_sp", "R")},
        batters=batters, batting_order=order, lineup_positions=positions,
        depth_chart={"LF": ["lf_lhb", "lf_rhb"]},
    )
    batting_stats = {pid: _bat(pid) for pid in batters}
    team = Team(
        info=TeamSeason(team_id="AWY", year=YEAR, league_id="NL",
                        team_name="Away", games=150),
        roster=[], batting_stats=batting_stats,
        pitching_stats={"awy_sp": _pit("awy_sp")},
    )
    return team, card


def _home_team_and_cards():
    """Home team carrying two starters (RHP + LHP) and a card selecting each."""
    positions_all = _OTHERS[:4] + [("h_lf", "LF")] + _OTHERS[4:]
    batters = {pid: _reg(pid, pos) for pid, pos in positions_all}
    order = [pid for pid, _ in positions_all]
    positions = {pid: pos for pid, pos in positions_all}
    pitchers = {
        "home_rhp": _starter_card("home_rhp", "R"),
        "home_lhp": _starter_card("home_lhp", "L"),
    }

    def card_for(starter_id: str) -> TeamRoleCard:
        # Only the chosen starter carries a rotation slot, so it is the one
        # ai_pregame resolves and the away side sees its hand.
        picked = {
            pid: PitcherRoleCard(
                player_id=pid, role=p.role,
                rotation_slot=1 if pid == starter_id else None,
                leash_bf=p.leash_bf, leash_fatigue=p.leash_fatigue,
                typical_rest_days=p.typical_rest_days,
                appearance_share=p.appearance_share, metrics=dict(p.metrics),
            )
            for pid, p in pitchers.items()
        }
        return TeamRoleCard(
            team_id="HOM", year=YEAR, pitchers=picked, batters=batters,
            batting_order=order, lineup_positions=positions,
        )

    team = Team(
        info=TeamSeason(team_id="HOM", year=YEAR, league_id="NL",
                        team_name="Home", games=150),
        roster=[], batting_stats={pid: _bat(pid) for pid in batters},
        pitching_stats={"home_rhp": _pit("home_rhp"), "home_lhp": _pit("home_lhp")},
    )
    return team, card_for("home_rhp"), card_for("home_lhp")


def _play(away_team, away_card, home_team, home_card, seed):
    away_ctx = TeamManagerContext(manager=ManagerAI(away_card))
    home_ctx = TeamManagerContext(manager=ManagerAI(home_card))
    return play_ai_game(away_team, home_team, away_ctx, home_ctx, rng_seed=seed)


def test_away_lineup_shifts_with_opposing_hand_and_season_completes():
    away_team, away_card = _away_team_and_card()
    home_team, card_rhp, card_lhp = _home_team_and_cards()

    # A tiny "season": alternate the home starter's hand game to game and record
    # the away side's starting nine each time (deterministic — pregame runs
    # before any at-bat RNG). Every game must complete (a PA-cap failure would
    # raise a RuntimeError out of play_ai_game).
    nines = []
    for seed in range(4):
        card = card_rhp if seed % 2 == 0 else card_lhp
        result = _play(away_team, away_card, home_team, card, seed)
        assert result.innings >= 9  # the game finished normally
        nines.append(frozenset(result.away_batter_starts))

    vs_rhp, vs_lhp = nines[0], nines[1]
    # The left-handed bat starts vs the RHP; the right-handed bat vs the LHP.
    assert "lf_lhb" in vs_rhp and "lf_rhb" not in vs_rhp
    assert "lf_rhb" in vs_lhp and "lf_lhb" not in vs_lhp
    # The starting nine is demonstrably not constant across the schedule.
    assert len(set(nines)) > 1


def test_same_hand_gives_a_stable_platoon_choice():
    """Facing the same hand twice yields the same platooned starter (determinism)."""
    away_team, away_card = _away_team_and_card()
    home_team, card_rhp, _ = _home_team_and_cards()
    first = _play(away_team, away_card, home_team, card_rhp, 1)
    second = _play(away_team, away_card, home_team, card_rhp, 2)
    assert "lf_lhb" in first.away_batter_starts
    assert "lf_lhb" in second.away_batter_starts
