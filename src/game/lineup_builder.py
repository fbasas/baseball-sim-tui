"""Historically accurate lineup construction from Lahman Appearances data.

Assigns players to defensive positions based on games played at each position,
orders the batting lineup using a stat-based heuristic (OBP leadoff, power in
3-4 hole), and selects the default starting pitcher by games started.
"""

from typing import Dict, List, Optional, Tuple, Union

from src.data.lahman import LahmanRepository
from src.data.models import BattingStats
from src.game.positions import DesignatedHitter, Position
from src.game.team import Team, create_lineup


# Map Appearances column names to Position enum values
_POSITION_COLUMNS: List[Tuple[str, Position]] = [
    ("G_c", Position.CATCHER),
    ("G_1b", Position.FIRST_BASE),
    ("G_2b", Position.SECOND_BASE),
    ("G_3b", Position.THIRD_BASE),
    ("G_ss", Position.SHORTSTOP),
    ("G_lf", Position.LEFT_FIELD),
    ("G_cf", Position.CENTER_FIELD),
    ("G_rf", Position.RIGHT_FIELD),
]

# Speed positions for leadoff heuristic
_SPEED_POSITIONS = {Position.CENTER_FIELD, Position.SHORTSTOP, Position.SECOND_BASE}

# Zero-stat placeholder for players without batting data
_ZERO_STATS = None  # Lazily created


def _zero_stats() -> BattingStats:
    return BattingStats(
        player_id="", year=0, team_id="", games=0, at_bats=0, runs=0,
        hits=0, doubles=0, triples=0, home_runs=0, rbi=0, stolen_bases=0,
        caught_stealing=0, walks=0, strikeouts=0, hit_by_pitch=0,
        sacrifice_flies=0, sacrifice_hits=0, gidp=0,
    )


def _calc_obp(stats: BattingStats) -> float:
    denom = stats.at_bats + stats.walks
    return (stats.hits + stats.walks) / denom if denom > 0 else 0.0


def _calc_slg(stats: BattingStats) -> float:
    if stats.at_bats == 0:
        return 0.0
    return (stats.singles + 2 * stats.doubles + 3 * stats.triples + 4 * stats.home_runs) / stats.at_bats


def _calc_avg(stats: BattingStats) -> float:
    return stats.hits / stats.at_bats if stats.at_bats > 0 else 0.0


def _get_stats(stats_map: Dict[str, BattingStats], pid: str) -> BattingStats:
    return stats_map.get(pid) or _zero_stats()


def get_default_starter(team: Team, repo: LahmanRepository) -> str:
    """Return the pitcher_id with the most games started for this team/year."""
    pitchers = team.get_available_pitchers()
    if not pitchers:
        raise ValueError(f"No pitchers available for {team.info.team_name}")

    best_id = pitchers[0].player_id
    best_gs = 0
    for p in pitchers:
        ps = team.pitching_stats.get(p.player_id)
        if ps and ps.games_started > best_gs:
            best_gs = ps.games_started
            best_id = p.player_id
    return best_id


def build_lineup(
    team: Team,
    repo: LahmanRepository,
    pitcher_id: Optional[str] = None,
) -> None:
    """Build a historically accurate lineup and set it on the team.

    Position assignment uses a greedy algorithm based on games played at each
    position from the Appearances table. Batting order uses a stat-based
    heuristic (OBP leadoff, power in 3-4 hole).

    Args:
        team: Team to build lineup for. team.lineup will be set.
        repo: LahmanRepository for Appearances data.
        pitcher_id: Override starting pitcher. Defaults to most games started.
    """
    if pitcher_id is None:
        pitcher_id = get_default_starter(team, repo)

    # Get appearances data
    appearances = repo.get_appearances(team.info.team_id, team.info.year)
    app_by_player: Dict[str, dict] = {row["playerID"]: row for row in appearances}

    # Get available batters (excluding the starting pitcher)
    available_ids = {
        b.player_id for b in team.get_available_batters()
        if b.player_id != pitcher_id
    }

    # --- Position assignment (greedy, scarcity-first) ---
    assigned: Dict[str, Union[Position, type]] = {}
    filled_positions: set = set()

    # Build candidate lists per position
    position_candidates: List[Tuple[Position, List[Tuple[str, int]]]] = []
    for col, pos in _POSITION_COLUMNS:
        candidates = []
        for pid in available_ids:
            app = app_by_player.get(pid, {})
            games = app.get(col, 0) or 0
            if games > 0:
                candidates.append((pid, games))
        candidates.sort(key=lambda x: (-x[1], -team.batting_stats.get(x[0], _zero_stats()).at_bats))
        position_candidates.append((pos, candidates))

    # Assign greedily: positions with fewer candidates first (scarcity)
    position_candidates.sort(key=lambda x: len(x[1]))

    for pos, candidates in position_candidates:
        if pos in filled_positions:
            continue
        for pid, games in candidates:
            if pid not in assigned:
                assigned[pid] = pos
                filled_positions.add(pos)
                break

    # Fill unfilled positions with remaining players sorted by at_bats
    unfilled = set(p for _, p in _POSITION_COLUMNS) - filled_positions
    unassigned = sorted(
        [pid for pid in available_ids if pid not in assigned],
        key=lambda pid: team.batting_stats.get(pid, _zero_stats()).at_bats,
        reverse=True,
    )

    for pos in sorted(unfilled, key=lambda p: p.value):
        if unassigned:
            assigned[unassigned.pop(0)] = pos
            filled_positions.add(pos)

    # Need 9 batters: 8 fielders + 1 DH
    if len(assigned) < 9 and unassigned:
        assigned[unassigned.pop(0)] = DesignatedHitter

    while len(assigned) < 9 and unassigned:
        pid = unassigned.pop(0)
        remaining_pos = set(p for _, p in _POSITION_COLUMNS) - filled_positions
        if remaining_pos:
            pos = min(remaining_pos, key=lambda p: p.value)
            assigned[pid] = pos
            filled_positions.add(pos)
        else:
            assigned[pid] = DesignatedHitter

    starters = list(assigned.keys())
    if len(starters) < 9:
        raise ValueError(f"Not enough batters for {team.info.team_name}: got {len(starters)}")

    # --- Batting order heuristic ---
    stats_map: Dict[str, BattingStats] = {
        pid: team.batting_stats[pid] for pid in starters if pid in team.batting_stats
    }

    remaining = set(starters)
    batting_order: List[str] = []

    def pick_best(pool, key_fn):
        best = max(pool, key=lambda pid: key_fn(_get_stats(stats_map, pid)))
        batting_order.append(best)
        remaining.remove(best)

    # Slot 1: highest OBP among speed positions (CF, SS, 2B)
    speed = [pid for pid in remaining if assigned.get(pid) in _SPEED_POSITIONS]
    if speed:
        pick_best(speed, _calc_obp)
    else:
        pick_best(remaining, _calc_obp)

    # Slot 2: second highest OBP overall
    pick_best(remaining, _calc_obp)

    # Slot 3: highest batting average
    pick_best(remaining, _calc_avg)

    # Slot 4: highest SLG (cleanup)
    pick_best(remaining, _calc_slg)

    # Slot 5: next highest SLG
    pick_best(remaining, _calc_slg)

    # Slots 6-8: sorted by avg descending; slot 9: worst hitter (lowest OBP)
    rest = sorted(remaining, key=lambda pid: _calc_avg(_get_stats(stats_map, pid)), reverse=True)
    if len(rest) >= 4:
        batting_order.extend(rest[:3])
        batting_order.append(rest[3])
    else:
        batting_order.extend(rest)

    positions: Dict[str, Union[Position, type]] = {
        pid: assigned[pid] for pid in batting_order
    }

    team.lineup = create_lineup(team, batting_order, positions, pitcher_id)
