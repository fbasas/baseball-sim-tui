"""Offline role inference from Lahman season aggregates.

Turns a team-season's raw stats into a TeamRoleCard: who's in the rotation
and in what order, bullpen roles, bench roles, workload leashes, and a
recommended batting order. This is the "role determination pass" — it runs
offline (scripts/build_roles.py), never during a game.

Design constraints:
- May import src.data (shared data models) but NOT src.simulation/src.game.
- Deterministic: same inputs always produce the same card (ties broken by
  player_id, never randomness).
- Historical usage is treated as optimal day-to-day usage: roles describe
  what the team actually did, not what modern analytics would prefer.
"""

from typing import Dict, List, Optional, Tuple

from src.data.models import BattingStats, PitchingStats, PlayerInfo, TeamSeason
from src.manager.roles import (
    BatterRoleCard,
    BatterRoleType,
    PitcherRoleCard,
    PitcherRoleType,
    TeamRoleCard,
)

# Appearances column -> role card position abbreviation
_APPEARANCE_POSITIONS: List[Tuple[str, str]] = [
    ("G_c", "C"),
    ("G_1b", "1B"),
    ("G_2b", "2B"),
    ("G_3b", "3B"),
    ("G_ss", "SS"),
    ("G_lf", "LF"),
    ("G_cf", "CF"),
    ("G_rf", "RF"),
]

# First season the save was an official stat; before this, "closer" is an
# anachronism — the top reliever is a fireman, modeled as SETUP.
_SAVE_RULE_YEAR = 1969

# Minimum pitching workload to be treated as a pitcher at all (filters out
# position players with a mop-up inning).
_MIN_PITCHER_GAMES = 3
_MIN_PITCHER_IP = 9.0


def _rotation_size(year: int) -> int:
    """Era-typical rotation size."""
    if year < 1905:
        return 3
    if year < 1975:
        return 4
    return 5


def _whip(stats: PitchingStats) -> float:
    ip = stats.innings_pitched
    if ip <= 0:
        return 99.0
    return (stats.hits_allowed + stats.walks_allowed) / ip


def _era(stats: PitchingStats) -> float:
    ip = stats.innings_pitched
    if ip <= 0:
        return 99.0
    return stats.earned_runs * 9 / ip


def _obp(stats: BattingStats) -> float:
    denom = stats.at_bats + stats.walks + stats.hit_by_pitch + stats.sacrifice_flies
    if denom <= 0:
        return 0.0
    return (stats.hits + stats.walks + stats.hit_by_pitch) / denom


def _slg(stats: BattingStats) -> float:
    if stats.at_bats <= 0:
        return 0.0
    return (
        stats.singles + 2 * stats.doubles + 3 * stats.triples + 4 * stats.home_runs
    ) / stats.at_bats


def _avg(stats: BattingStats) -> float:
    return stats.hits / stats.at_bats if stats.at_bats > 0 else 0.0


def _infer_pitchers(
    pitching_stats: Dict[str, PitchingStats],
    roster: Dict[str, PlayerInfo],
    team_games: int,
    year: int,
    notes: List[str],
) -> Dict[str, PitcherRoleCard]:
    """Classify pitchers into rotation slots and bullpen roles."""
    real_pitchers = {
        pid: ps
        for pid, ps in pitching_stats.items()
        if ps.games >= _MIN_PITCHER_GAMES or ps.innings_pitched >= _MIN_PITCHER_IP
    }
    if not real_pitchers:
        raise ValueError("No pitchers with meaningful workload found")

    rotation_size = min(_rotation_size(year), len(real_pitchers))
    # Rotation: top by GS (ties: IP desc, then player_id for determinism)
    by_gs = sorted(
        real_pitchers.items(),
        key=lambda kv: (-kv[1].games_started, -kv[1].ip_outs, kv[0]),
    )
    rotation_ids = [pid for pid, ps in by_gs[:rotation_size] if ps.games_started > 0]
    if len(rotation_ids) < rotation_size:
        notes.append(
            f"Only {len(rotation_ids)} pitchers with starts; rotation smaller than "
            f"era-typical {rotation_size}"
        )

    cards: Dict[str, PitcherRoleCard] = {}
    rest_days = max(1, len(rotation_ids) - 1) if rotation_ids else 3

    # --- Rotation members ---
    for slot, pid in enumerate(rotation_ids, start=1):
        ps = real_pitchers[pid]
        gs = ps.games_started
        # Average batters faced per start; for swing types this includes
        # relief innings, which is acceptable at this granularity.
        leash_bf = round((ps.ip_outs + ps.hits_allowed + ps.walks_allowed) / gs)
        leash_bf = max(18, min(45, leash_bf))
        cg_rate = ps.complete_games / gs
        leash_fatigue = round(0.55 + 0.35 * min(1.0, cg_rate * 1.2), 2)
        cards[pid] = PitcherRoleCard(
            player_id=pid,
            role=PitcherRoleType.STARTER,
            rotation_slot=slot,
            leash_bf=leash_bf,
            leash_fatigue=leash_fatigue,
            typical_rest_days=rest_days,
            appearance_share=round(ps.games / team_games, 3) if team_games else 0.0,
            metrics=_pitcher_metrics(ps, roster.get(pid)),
        )

    # --- Bullpen ---
    bullpen = {pid: ps for pid, ps in real_pitchers.items() if pid not in cards}

    closer_id: Optional[str] = None
    if year >= _SAVE_RULE_YEAR and bullpen:
        top_sv_id = min(
            bullpen, key=lambda pid: (-bullpen[pid].saves, pid)
        )
        if bullpen[top_sv_id].saves >= 8:
            closer_id = top_sv_id

    fireman_id: Optional[str] = None
    if closer_id is None and bullpen:
        # Pre-save era (or no save accumulator): the most-trusted reliever is
        # the one who finished the most games — a fireman, modeled as SETUP.
        top_gf_id = min(
            bullpen,
            key=lambda pid: (-(bullpen[pid].games_finished + bullpen[pid].saves), pid),
        )
        if bullpen[top_gf_id].games_finished + bullpen[top_gf_id].saves >= 5:
            fireman_id = top_gf_id
            if year < _SAVE_RULE_YEAR:
                notes.append(
                    f"Pre-{_SAVE_RULE_YEAR} season: no closer role; {top_gf_id} "
                    "classified as setup (fireman) by games finished"
                )

    setup_id: Optional[str] = fireman_id
    if closer_id is not None:
        remaining = {pid: ps for pid, ps in bullpen.items() if pid != closer_id}
        if remaining:
            setup_id = min(
                remaining,
                key=lambda pid: (
                    -(remaining[pid].saves + remaining[pid].games_finished),
                    _whip(remaining[pid]),
                    pid,
                ),
            )

    for pid, ps in bullpen.items():
        if pid == closer_id:
            role = PitcherRoleType.CLOSER
        elif pid == setup_id:
            role = PitcherRoleType.SETUP
        elif ps.games_started >= 3 and (ps.games - ps.games_started) >= 0.25 * ps.games:
            role = PitcherRoleType.SWINGMAN
        elif ps.games > 0 and ps.innings_pitched / ps.games >= 2.0:
            role = PitcherRoleType.LONG_RELIEF
        else:
            role = PitcherRoleType.MIDDLE_RELIEF

        outings = max(ps.games, 1)
        leash_bf = round(
            (ps.ip_outs + ps.hits_allowed + ps.walks_allowed) / outings
        )
        if role == PitcherRoleType.SWINGMAN:
            leash_bf = max(18, min(45, leash_bf * 2))
        else:
            leash_bf = max(3, min(18, leash_bf))

        cards[pid] = PitcherRoleCard(
            player_id=pid,
            role=role,
            rotation_slot=None,
            leash_bf=leash_bf,
            leash_fatigue=0.55,
            typical_rest_days=rest_days if role == PitcherRoleType.SWINGMAN else 0,
            appearance_share=round(ps.games / team_games, 3) if team_games else 0.0,
            metrics=_pitcher_metrics(ps, roster.get(pid)),
        )

    return cards


def _pitcher_metrics(ps: PitchingStats, info: Optional[PlayerInfo]) -> Dict[str, object]:
    return {
        "whip": round(_whip(ps), 3),
        "era": round(_era(ps), 2),
        "ip": round(ps.innings_pitched, 1),
        "g": ps.games,
        "gs": ps.games_started,
        "cg": ps.complete_games,
        "sho": ps.shutouts,
        "sv": ps.saves,
        "gf": ps.games_finished,
        "throws": info.throws if info else "R",
    }


def _infer_batters(
    batting_stats: Dict[str, BattingStats],
    appearances: Dict[str, dict],
    roster: Dict[str, PlayerInfo],
    pitcher_ids: set,
    team_games: int,
) -> Dict[str, BatterRoleCard]:
    """Classify position players into lineup/bench roles."""
    cards: Dict[str, BatterRoleCard] = {}
    for pid, bs in batting_stats.items():
        app = appearances.get(pid, {})
        position_games = {
            abbrev: int(app.get(col, 0) or 0) for col, abbrev in _APPEARANCE_POSITIONS
        }
        dh_games = int(app.get("G_dh", 0) or 0)
        max_position_games = max(position_games.values()) if position_games else 0
        # Field games across all positions (a player split between LF and RF
        # is still an everyday player). Sum can overcount mid-game switches,
        # so cap at team games.
        field_games = min(sum(position_games.values()), team_games or 10**6)

        if pid in pitcher_ids:
            # Two-way edge case (e.g. 1918 Ruth): only give a batter card if
            # they genuinely played the field.
            if field_games < 10:
                continue

        if field_games == 0 and dh_games == 0 and bs.games == 0:
            continue

        if dh_games > max_position_games:
            primary = "DH"
            usage_games = min(field_games + dh_games, team_games or 10**6)
        else:
            primary = max(
                position_games, key=lambda a: (position_games[a], a)
            ) if max_position_games > 0 else "DH"
            usage_games = min(field_games + dh_games, team_games or 10**6)

        eligible = sorted(
            [a for a, g in position_games.items() if g >= 5]
        )
        if dh_games >= 5:
            eligible.append("DH")
        if primary not in eligible:
            eligible.append(primary)

        start_share = round(usage_games / team_games, 3) if team_games else 0.0

        if start_share >= 0.65:
            role = BatterRoleType.REGULAR
        elif start_share >= 0.30:
            role = BatterRoleType.PLATOON
        elif start_share < 0.15 and team_games and bs.games >= 0.25 * team_games:
            # In lots of games but rarely in the field: a pinch-hit specialist
            role = BatterRoleType.PINCH_SPECIALIST
        else:
            role = BatterRoleType.BENCH

        info = roster.get(pid)
        cards[pid] = BatterRoleCard(
            player_id=pid,
            role=role,
            primary_position=primary,
            eligible_positions=eligible,
            start_share=start_share,
            metrics={
                "obp": round(_obp(bs), 3),
                "slg": round(_slg(bs), 3),
                "ops": round(_obp(bs) + _slg(bs), 3),
                "avg": round(_avg(bs), 3),
                "ab": bs.at_bats,
                "games": bs.games,
                "bats": info.bats if info else "R",
            },
        )
    return cards


_SPEED_POSITIONS = {"CF", "SS", "2B"}


def _recommend_batting_order(
    batters: Dict[str, BatterRoleCard],
    batting_stats: Dict[str, BattingStats],
    appearances: Dict[str, dict],
) -> Tuple[List[str], Dict[str, str]]:
    """Build a 9-man order with positions: 8 fielders + DH.

    Mirrors the greedy scarcity-first assignment and stat-tier order used by
    src.game.lineup_builder, reimplemented here on role card inputs to keep
    this package decoupled from src.game.
    """
    available = set(batters.keys())
    if len(available) < 9:
        raise ValueError(f"Need at least 9 batters with role cards, got {len(available)}")

    def games_at(pid: str, abbrev: str) -> int:
        app = appearances.get(pid, {})
        col = next(c for c, a in _APPEARANCE_POSITIONS if a == abbrev)
        return int(app.get(col, 0) or 0)

    def ab_of(pid: str) -> int:
        bs = batting_stats.get(pid)
        return bs.at_bats if bs else 0

    # Greedy scarcity-first position assignment
    assigned: Dict[str, str] = {}
    filled: set = set()
    candidates_per_pos = []
    for _, abbrev in _APPEARANCE_POSITIONS:
        cands = sorted(
            [pid for pid in available if games_at(pid, abbrev) > 0],
            key=lambda pid: (-games_at(pid, abbrev), -ab_of(pid), pid),
        )
        candidates_per_pos.append((abbrev, cands))
    candidates_per_pos.sort(key=lambda x: (len(x[1]), x[0]))

    for abbrev, cands in candidates_per_pos:
        if abbrev in filled:
            continue
        for pid in cands:
            if pid not in assigned:
                assigned[pid] = abbrev
                filled.add(abbrev)
                break

    unfilled = sorted({a for _, a in _APPEARANCE_POSITIONS} - filled)
    unassigned = sorted(
        [pid for pid in available if pid not in assigned],
        key=lambda pid: (-ab_of(pid), pid),
    )
    for abbrev in unfilled:
        if unassigned:
            assigned[unassigned.pop(0)] = abbrev
            filled.add(abbrev)

    if len(assigned) < 9 and unassigned:
        assigned[unassigned.pop(0)] = "DH"

    if len(assigned) < 9:
        raise ValueError(f"Could not assign 9 lineup positions, got {len(assigned)}")

    starters = set(assigned.keys())

    def metric(pid: str, key: str) -> float:
        return float(batters[pid].metrics.get(key, 0.0))

    remaining = set(starters)
    order: List[str] = []

    def pick(pool, key):
        best = max(sorted(pool), key=lambda pid: (metric(pid, key), pid))
        order.append(best)
        remaining.remove(best)

    speed = [pid for pid in remaining if assigned[pid] in _SPEED_POSITIONS]
    pick(speed if speed else remaining, "obp")   # 1: OBP leadoff (speed pos)
    pick(remaining, "obp")                        # 2: next best OBP
    pick(remaining, "avg")                        # 3: best average
    pick(remaining, "slg")                        # 4: cleanup power
    pick(remaining, "slg")                        # 5: more power
    rest = sorted(remaining, key=lambda pid: (-metric(pid, "avg"), pid))
    order.extend(rest)                            # 6-9: descending average

    return order, {pid: assigned[pid] for pid in order}


def build_role_card(
    team_season: TeamSeason,
    roster: List[PlayerInfo],
    batting_stats: Dict[str, BattingStats],
    pitching_stats: Dict[str, PitchingStats],
    appearances: List[dict],
) -> TeamRoleCard:
    """Infer a complete TeamRoleCard from one team-season's Lahman data."""
    notes: List[str] = []
    roster_by_id = {p.player_id: p for p in roster}
    app_by_id = {row["playerID"]: row for row in appearances}

    team_games = team_season.games
    if team_games <= 0:
        team_games = max((bs.games for bs in batting_stats.values()), default=0)
        notes.append("Team games missing from Teams table; estimated from max player G")

    pitchers = _infer_pitchers(
        pitching_stats, roster_by_id, team_games, team_season.year, notes
    )
    batters = _infer_batters(
        batting_stats, app_by_id, roster_by_id, set(pitchers.keys()), team_games
    )
    batting_order, lineup_positions = _recommend_batting_order(
        batters, batting_stats, app_by_id
    )

    return TeamRoleCard(
        team_id=team_season.team_id,
        year=team_season.year,
        pitchers=pitchers,
        batters=batters,
        batting_order=batting_order,
        lineup_positions=lineup_positions,
        notes=notes,
    )
