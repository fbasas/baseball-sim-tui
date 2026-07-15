"""Unit tests for the per-team season stat page (FRE-114).

DB-free and Pilot-free (house mock-``self`` idiom, mirroring
``tests/test_season_hub_screen.py``): the screen's pure render/dispatch methods
are driven with a ``types.SimpleNamespace`` standing in for ``self``, over a
lightweight fake controller wrapping a *real* ``SeasonState`` / ``SeasonStats``
(no engine, no rosters DB). The ``_FakeTeam`` / ``_FakePlayer`` factories are
copied from the hub test.

Coverage:
- model accessors — ``team_batting`` / ``team_pitching`` return the pid→line
  dict for a team with data and ``{}`` for an unknown/empty team;
- batting table — a row per player, AVG formatting + ``—`` at 0 AB, AB-desc
  sort, every column present and aligned;
- pitching table — a row per pitcher, ERA/IP formatting + ``—`` at 0 outs,
  IP-desc sort;
- name resolution — ids render ``F. Last``, never raw;
- team header — display name + ``(W-L, .pct)`` from standings;
- team cycling — ``←``/``→`` step the index through standings order and wrap;
- empty team — ``No stats yet`` (no table rows).
"""

import re
from types import SimpleNamespace

from src.season.state import LeagueTeam, SeasonGameRecord, SeasonState
from src.season.stats import SeasonStats
from src.tui.screens.team_stats_screen import (
    _NAME_COL_WIDTH,
    _NUM_COL_WIDTH,
    TeamStatsScreen,
)


# ---------------------------------------------------------------------------
# Fixtures / factories (copied from tests/test_season_hub_screen.py)
# ---------------------------------------------------------------------------

_TEAMS = [
    LeagueTeam("NYA", 1927, "1927 Yankees"),
    LeagueTeam("CIN", 1975, "1975 Reds"),
    LeagueTeam("CHN", 2016, "2016 Cubs"),
    LeagueTeam("CHA", 1906, "1906 White Sox"),
]
_TEAMS_BY_KEY = {team.key: team for team in _TEAMS}


class _FakePlayer:
    def __init__(self, first: str, last: str) -> None:
        self.name_first = first
        self.name_last = last


class _FakeTeam:
    """Just enough of ``Team`` for name resolution: ``get_player``."""

    def __init__(self, players: dict) -> None:
        self._players = players  # pid -> _FakePlayer

    def get_player(self, pid: str):
        return self._players.get(pid)


def _make_state(user_key="NYA-1927", games_per_opponent=2):
    return SeasonState.create(list(_TEAMS), games_per_opponent, user_team_key=user_key)


def _play_game(state, game, home_score, away_score):
    state.results.append(
        SeasonGameRecord(
            game_id=game.game_id,
            day=game.day,
            home_key=game.home_key,
            away_key=game.away_key,
            home_score=home_score,
            away_score=away_score,
            innings=9,
        )
    )


def _play_day(state, day, winner_key="NYA-1927"):
    for game in state.schedule[day]:
        if game.home_key == winner_key:
            _play_game(state, game, home_score=5, away_score=2)
        elif game.away_key == winner_key:
            _play_game(state, game, home_score=2, away_score=5)
        else:
            _play_game(state, game, home_score=4, away_score=3)


def _controller(state, stats=None, teams=None):
    stats = stats if stats is not None else SeasonStats()
    teams = teams if teams is not None else {}
    return SimpleNamespace(
        state=state,
        stats=stats,
        teams=teams,
        is_complete=state.is_complete,
        current_day=state.current_day,
        champion=state.champion,
    )


# --- Season stats with a full team of batters + pitchers -------------------

# NYA-1927 batting: two regulars (Gehrig 22 AB, Ruth 20 AB), a pinch bat
# (2 AB), and a pinch-runner with no AB (0 AB -> AVG "—"). AB-desc sort puts
# them Gehrig, Ruth, Paschal, Durst.
_BATTING = {
    "gehri01": {"AB": 22, "R": 8, "H": 10, "2B": 2, "3B": 0, "HR": 3, "RBI": 12, "BB": 5, "K": 6},
    "ruth01": {"AB": 20, "R": 10, "H": 12, "2B": 3, "3B": 1, "HR": 6, "RBI": 18, "BB": 8, "K": 5},
    "pasch01": {"AB": 2, "R": 1, "H": 1, "2B": 0, "3B": 0, "HR": 0, "RBI": 1, "BB": 0, "K": 1},
    "durst01": {"AB": 0, "R": 2, "H": 0, "2B": 0, "3B": 0, "HR": 0, "RBI": 0, "BB": 1, "K": 0},
}
# NYA-1927 pitching: a workhorse (45 outs = 15.0 IP), a starter (27 outs =
# 9.0 IP), and a reliever with 0 outs (ERA/IP -> "—"). IP-desc sort orders them
# Hoyt, Pennock, Moore.
_PITCHING = {
    "hoytwa01": {"outs": 45, "H": 12, "R": 6, "ER": 5, "BB": 4, "K": 30},
    "pennoh01": {"outs": 27, "H": 10, "R": 5, "ER": 4, "BB": 3, "K": 15},
    "moore01": {"outs": 0, "H": 2, "R": 2, "ER": 2, "BB": 1, "K": 0},
}
_ROSTER = {
    "NYA-1927": _FakeTeam(
        {
            "gehri01": _FakePlayer("Lou", "Gehrig"),
            "ruth01": _FakePlayer("Babe", "Ruth"),
            "pasch01": _FakePlayer("Ben", "Paschal"),
            "durst01": _FakePlayer("Cedric", "Durst"),
            "hoytwa01": _FakePlayer("Waite", "Hoyt"),
            "pennoh01": _FakePlayer("Herb", "Pennock"),
            "moore01": _FakePlayer("Wilcy", "Moore"),
        }
    )
}


def _full_stats():
    return SeasonStats(
        batting={"NYA-1927": {k: dict(v) for k, v in _BATTING.items()}},
        pitching={"NYA-1927": {k: dict(v) for k, v in _PITCHING.items()}},
        games_played={"NYA-1927": 5},
    )


# ---------------------------------------------------------------------------
# Mock-``self`` for the screen's pure methods
# ---------------------------------------------------------------------------

# Instance methods bound onto the mock (each may call its siblings back).
_SCREEN_METHODS = (
    "_current_key",
    "_team_name",
    "_standings_row",
    "_is_empty",
    "_team_header",
    "_build_batting_table",
    "_build_pitching_table",
    "_step",
    "action_prev_team",
    "action_next_team",
)


def _screen_mock(controller, initial_key="NYA-1927"):
    """A mock-``self`` for ``TeamStatsScreen`` render/dispatch methods.

    Seeds ``_keys`` / ``_index`` exactly as ``__init__`` would, binds every
    sibling method onto the mock, and stubs ``_render_current`` (which touches
    mounted widgets) to a no-op so index-stepping can be tested pure.
    """
    keys = [row.key for row in controller.state.standings]
    try:
        index = keys.index(initial_key)
    except ValueError:
        index = 0
    mock = SimpleNamespace(_controller=controller, _keys=keys, _index=index)
    for name in _SCREEN_METHODS:
        method = getattr(TeamStatsScreen, name)
        setattr(mock, name, (lambda m=method: lambda *a, **k: m(mock, *a, **k))())
    # Static helpers: no ``self`` — bind the underlying functions directly.
    mock._batting_cells = TeamStatsScreen._batting_cells
    mock._pitching_cells = TeamStatsScreen._pitching_cells
    mock._render_current = lambda: None
    return mock


def _strip_markup(line: str) -> str:
    """Remove Rich markup tags; player/column text is ASCII with no brackets."""
    return re.sub(r"\[/?[^\]]*\]", "", line)


# ---------------------------------------------------------------------------
# Model accessors
# ---------------------------------------------------------------------------


def test_team_batting_returns_line_dict_for_known_team():
    stats = _full_stats()
    batting = stats.team_batting("NYA-1927")
    assert set(batting) == set(_BATTING)
    assert batting["ruth01"]["HR"] == 6


def test_team_pitching_returns_line_dict_for_known_team():
    stats = _full_stats()
    pitching = stats.team_pitching("NYA-1927")
    assert set(pitching) == set(_PITCHING)
    assert pitching["hoytwa01"]["outs"] == 45


def test_team_accessors_empty_for_unknown_team():
    stats = _full_stats()
    assert stats.team_batting("CHA-1906") == {}
    assert stats.team_pitching("CHA-1906") == {}
    assert SeasonStats().team_batting("NYA-1927") == {}


# ---------------------------------------------------------------------------
# Batting table
# ---------------------------------------------------------------------------


def test_batting_table_has_a_row_per_player_resolved_to_names():
    mock = _screen_mock(_controller(_make_state(), _full_stats(), _ROSTER))
    table = _strip_markup(TeamStatsScreen._build_batting_table(mock))

    for name in ("L. Gehrig", "B. Ruth", "B. Paschal", "C. Durst"):
        assert name in table
    # Raw ids never leak.
    for pid in _BATTING:
        assert pid not in table


def test_batting_avg_formatted_without_leading_zero_and_dash_at_zero_ab():
    mock = _screen_mock(_controller(_make_state(), _full_stats(), _ROSTER))
    table = TeamStatsScreen._build_batting_table(mock)

    assert ".600" in table  # Ruth 12/20
    assert ".455" in table  # Gehrig 10/22
    assert "0.600" not in table  # no leading zero
    # The pinch-runner has 0 AB -> AVG renders as an em dash, not ".000".
    durst_line = next(
        l for l in _strip_markup(table).splitlines() if "C. Durst" in l
    )
    assert "—" in durst_line


def test_batting_rows_sorted_by_ab_descending():
    mock = _screen_mock(_controller(_make_state(), _full_stats(), _ROSTER))
    table = _strip_markup(TeamStatsScreen._build_batting_table(mock))

    order = [table.index(n) for n in ("L. Gehrig", "B. Ruth", "B. Paschal", "C. Durst")]
    assert order == sorted(order)  # AB 22 > 20 > 2 > 0


def test_batting_columns_present_and_aligned():
    mock = _screen_mock(_controller(_make_state(), _full_stats(), _ROSTER))
    lines = _strip_markup(TeamStatsScreen._build_batting_table(mock)).splitlines()

    header = lines[0]
    for col in ("Player", "AVG", "AB", "R", "H", "2B", "3B", "HR", "RBI", "BB", "K"):
        assert col in header
    # Fixed-width name cell + fixed-width numeric cells -> every line is the
    # same visible length, so columns line up under their headers.
    width = _NAME_COL_WIDTH + len(("AVG", "AB", "R", "H", "2B", "3B", "HR", "RBI", "BB", "K")) * _NUM_COL_WIDTH
    assert all(len(l) == width for l in lines)


def test_batting_has_team_totals_row():
    mock = _screen_mock(_controller(_make_state(), _full_stats(), _ROSTER))
    table = _strip_markup(TeamStatsScreen._build_batting_table(mock))
    totals_line = next(l for l in table.splitlines() if l.startswith("TEAM"))
    # ΣAB = 22+20+2+0 = 44, ΣH = 10+12+1+0 = 23, team AVG = 23/44 = .523.
    assert "44" in totals_line
    assert ".523" in totals_line


# ---------------------------------------------------------------------------
# Pitching table
# ---------------------------------------------------------------------------


def test_pitching_table_rows_resolved_and_sorted_by_ip():
    mock = _screen_mock(_controller(_make_state(), _full_stats(), _ROSTER))
    table = _strip_markup(TeamStatsScreen._build_pitching_table(mock))

    order = [table.index(n) for n in ("W. Hoyt", "H. Pennock", "W. Moore")]
    assert order == sorted(order)  # outs 45 > 27 > 0
    for pid in _PITCHING:
        assert pid not in table


def test_pitching_era_and_ip_formatting():
    mock = _screen_mock(_controller(_make_state(), _full_stats(), _ROSTER))
    table = TeamStatsScreen._build_pitching_table(mock)

    assert "3.00" in table  # Hoyt ER 5 / 15 IP * 9
    assert "4.00" in table  # Pennock ER 4 / 9 IP * 9
    assert "15.0" in table  # Hoyt 45 outs
    assert "9.0" in table   # Pennock 27 outs


def test_pitching_dash_at_zero_outs():
    mock = _screen_mock(_controller(_make_state(), _full_stats(), _ROSTER))
    table = _strip_markup(TeamStatsScreen._build_pitching_table(mock))
    moore_line = next(l for l in table.splitlines() if "W. Moore" in l)
    # 0 outs -> both ERA and IP render as em dashes (never a divide-by-zero).
    assert moore_line.count("—") == 2


def test_pitching_columns_aligned():
    mock = _screen_mock(_controller(_make_state(), _full_stats(), _ROSTER))
    lines = _strip_markup(TeamStatsScreen._build_pitching_table(mock)).splitlines()
    header = lines[0]
    for col in ("Pitcher", "ERA", "IP", "H", "R", "ER", "BB", "K"):
        assert col in header
    width = _NAME_COL_WIDTH + 7 * _NUM_COL_WIDTH
    assert all(len(l) == width for l in lines)


# ---------------------------------------------------------------------------
# Team header
# ---------------------------------------------------------------------------


def test_team_header_shows_name_and_record():
    state = _make_state(user_key="NYA-1927")
    _play_day(state, 0, winner_key="NYA-1927")  # NYA wins its day-0 game
    mock = _screen_mock(_controller(state, _full_stats(), _ROSTER), "NYA-1927")

    header = _strip_markup(TeamStatsScreen._team_header(mock))

    assert "1927 Yankees" in header
    row = next(r for r in state.standings if r.key == "NYA-1927")
    assert f"({row.wins}-{row.losses}," in header


# ---------------------------------------------------------------------------
# Team cycling (←/→, wrapping)
# ---------------------------------------------------------------------------


def test_cycling_steps_through_standings_order_and_wraps():
    state = _make_state()  # fresh -> standings ordered by key
    order = [row.key for row in state.standings]
    mock = _screen_mock(_controller(state, _full_stats(), _ROSTER), order[0])
    assert mock._index == 0

    # Right advances forward through the whole list, wrapping back to the start.
    for step in range(1, len(order) + 1):
        TeamStatsScreen.action_next_team(mock)
        assert mock._current_key() == order[step % len(order)]

    # Left from the start wraps to the last team; the header follows the key.
    TeamStatsScreen.action_prev_team(mock)
    assert mock._current_key() == order[-1]
    assert _TEAMS_BY_KEY[order[-1]].display_name in _strip_markup(
        TeamStatsScreen._team_header(mock)
    )


# ---------------------------------------------------------------------------
# Empty team
# ---------------------------------------------------------------------------


def test_empty_team_reports_empty_and_builds_no_rows():
    # CHA-1906 has no accumulated stats in _full_stats().
    mock = _screen_mock(_controller(_make_state(), _full_stats(), _ROSTER), "CHA-1906")
    assert mock._current_key() == "CHA-1906"
    assert TeamStatsScreen._is_empty(mock) is True
    # A team *with* stats is not empty.
    mock._index = mock._keys.index("NYA-1927")
    assert TeamStatsScreen._is_empty(mock) is False
