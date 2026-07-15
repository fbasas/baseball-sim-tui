"""Unit tests for the season hub + league leaders screens (FRE-94).

DB-free and Pilot-free (house mock-``self`` idiom, mirroring
``tests/test_save_select_screen.py`` / ``tests/test_load_resume_flow.py``): the
screens' pure render/dispatch methods are driven with a ``types.SimpleNamespace``
standing in for ``self``, over a lightweight fake controller wrapping a *real*
``SeasonState`` / ``SeasonStats`` (no engine, no rosters DB).

Coverage:
- standings table — rows in standings order, user's team marked;
- day header + today's-matchup line mid-season;
- league leaders — resolved names, qualifiers respected;
- complete-season summary — champion + final standings;
- watch-only hides play/sim-my-game (via ``check_action``);
- action dispatch — each binding surfaces the right ``HubChoice`` to the owner.
"""

import re
from types import SimpleNamespace

from src.season.schedule import ScheduledGame
from src.season.state import LeagueTeam, SeasonGameRecord, SeasonState
from src.season.stats import SeasonStats
from src.tui.screens.season_hub_screen import (
    _TEAM_COL_WIDTH,
    HubChoice,
    LeagueLeadersScreen,
    SeasonHubScreen,
    _build_leader_table,
    _fit,
    _format_gb,
    _format_ip,
    _format_pct,
    _resolve_name,
)
from src.tui.screens.team_stats_screen import TeamStatsScreen


# ---------------------------------------------------------------------------
# Fixtures / factories
# ---------------------------------------------------------------------------

# Four cross-era clubs; keys are "{team_id}-{year}".
_TEAMS = [
    LeagueTeam("NYA", 1927, "1927 Yankees"),
    LeagueTeam("CIN", 1975, "1975 Reds"),
    LeagueTeam("CHN", 2016, "2016 Cubs"),
    LeagueTeam("CHA", 1906, "1906 White Sox"),
]


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
    return SeasonState.create(
        list(_TEAMS), games_per_opponent, user_team_key=user_key
    )


def _play_game(state: SeasonState, game: ScheduledGame, home_score, away_score):
    """Append a finished-game record for ``game`` with the given scores."""
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


def _play_day(state: SeasonState, day: int, winner_key="NYA-1927"):
    """Finish every game on ``day``; ``winner_key`` wins any game it's in."""
    for game in state.schedule[day]:
        if game.home_key == winner_key:
            _play_game(state, game, home_score=5, away_score=2)
        elif game.away_key == winner_key:
            _play_game(state, game, home_score=2, away_score=5)
        else:
            # Deterministic: home wins the neutral games.
            _play_game(state, game, home_score=4, away_score=3)


def _controller(state, stats=None, teams=None):
    """A fake ``SeasonController``: the fields/props the screens read."""
    stats = stats if stats is not None else SeasonStats()
    teams = teams if teams is not None else {}
    return SimpleNamespace(
        state=state,
        stats=stats,
        teams=teams,
        is_complete=state.is_complete,
        current_day=state.current_day,
        champion=state.champion,
        games_for_day=lambda day: (
            state.schedule[day] if 0 <= day < len(state.schedule) else []
        ),
    )


_HUB_HELPERS = (
    "_team_name",
    "_day_header",
    "_champion_line",
    "_build_standings_table",
    "_build_grouped_standings_table",
    "_group_title",
    "_render_standings_rows",
    "_build_pennants",
    "_build_matchups",
    "_build_recent_results",
    "_build_summary_leaders",
)


def _hub_mock(controller):
    """A mock-``self`` for ``SeasonHubScreen`` render methods.

    Binds every sibling render helper the tested methods call back onto the
    mock (house style: ``mock._select_index = lambda ...``).
    """
    mock = SimpleNamespace(_controller=controller)
    for name in _HUB_HELPERS:
        method = getattr(SeasonHubScreen, name)
        setattr(mock, name, (lambda m=method: lambda *a, **k: m(mock, *a, **k))())
    return mock


def _leaders_mock(controller):
    return SimpleNamespace(_controller=controller)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def test_format_pct_drops_leading_zero_but_keeps_thousand():
    assert _format_pct(0.75) == ".750"
    assert _format_pct(0.0) == ".000"
    assert _format_pct(1.0) == "1.000"


def test_format_gb_leader_is_dash():
    assert _format_gb(0) == "—"
    assert _format_gb(2.0) == "2.0"
    assert _format_gb(2.5) == "2.5"


def test_format_ip_renders_thirds():
    assert _format_ip(10.0) == "10.0"      # 30 outs
    assert _format_ip(12.0 + 1 / 3) == "12.1"  # 37 outs
    assert _format_ip(6.0 + 2 / 3) == "6.2"    # 20 outs


# ---------------------------------------------------------------------------
# Standings table
# ---------------------------------------------------------------------------


def test_standings_rows_in_order_with_user_marked():
    state = _make_state(user_key="NYA-1927")
    _play_day(state, 0, winner_key="NYA-1927")
    mock = _hub_mock(_controller(state))

    table = SeasonHubScreen._build_standings_table(mock)
    lines = table.splitlines()

    # Header + one row per team.
    assert len(lines) == 1 + len(_TEAMS)
    # Body rows appear in the same order the state ranks them.
    order = [row.key for row in state.standings]
    body = lines[1:]
    for key, line in zip(order, body):
        assert _TEAMS_BY_KEY[key].display_name in line
    # The user's team (a winner) is marked with the caret and bolded.
    user_line = next(l for l in body if "1927 Yankees" in l)
    assert "►" in user_line
    assert user_line.startswith("[bold]")


def test_standings_marks_no_team_when_watch_only():
    state = _make_state(user_key=None)
    _play_day(state, 0, winner_key="CIN-1975")
    mock = _hub_mock(_controller(state))

    table = SeasonHubScreen._build_standings_table(mock)

    assert "►" not in table
    assert "[bold]" not in table


# --- Long-name alignment + truncation (the FRE-101 bug) --------------------

# Real display names are "{year} {full franchise name}" and routinely exceed
# the 20-char cell the old renderer used. Include names longer than, equal to,
# and shorter than _TEAM_COL_WIDTH so both the truncation and padding paths run.
_LONG_TEAMS = [
    LeagueTeam("PHI", 1927, "1927 Philadelphia Phillies"),  # 26 > width -> clipped
    LeagueTeam("LAN", 1998, "1998 Los Angeles Dodgers"),    # 24 == width -> exact
    LeagueTeam("CIN", 1927, "1927 Reds"),                   # 9 < width -> padded
    LeagueTeam("NYA", 1927, "1927 Yankees"),                # 12 < width -> padded
]


def _strip_markup(line: str) -> str:
    """Remove Rich markup tags (``[bold]``, ``[/]``, ``[#hex]``) — franchise
    names are ASCII with no brackets, so this leaves the visible cells intact."""
    return re.sub(r"\[/?[^\]]*\]", "", line)


def _long_name_state(user_key="PHI-1927"):
    return SeasonState.create(list(_LONG_TEAMS), 2, user_team_key=user_key)


def test_fit_pads_short_and_ellipsizes_long_to_exact_width():
    assert _fit("Reds", 10) == "Reds      "          # padded
    assert len(_fit("Reds", 10)) == 10
    clipped = _fit("Philadelphia Phillies", 10)      # 21 chars -> clipped
    assert len(clipped) == 10
    assert clipped == "Philadelp" + "…"              # first 9 chars + ellipsis
    # A name exactly at the width is untouched (no ellipsis).
    assert _fit("abcdefghij", 10) == "abcdefghij"


def test_standings_columns_align_for_long_names():
    state = _long_name_state(user_key="PHI-1927")
    _play_day(state, 0, winner_key="PHI-1927")
    mock = _hub_mock(_controller(state))

    lines = SeasonHubScreen._build_standings_table(mock).splitlines()
    stripped = [_strip_markup(l) for l in lines]

    # Every line (header + each row) is the same visible length, and the team
    # cell occupies exactly _TEAM_COL_WIDTH columns, so the W L Pct GB RS RA
    # columns start at the same offset on every line.
    assert len(set(len(s) for s in stripped)) == 1
    sep = 3 + _TEAM_COL_WIDTH  # 3-char row prefix + fixed team cell
    for s in stripped:
        assert s[sep] == " "  # the separator before the numeric columns


def test_standings_truncates_overlong_name_with_ellipsis():
    state = _long_name_state(user_key="PHI-1927")
    mock = _hub_mock(_controller(state))

    lines = SeasonHubScreen._build_standings_table(mock).splitlines()
    phi_line = _strip_markup(next(l for l in lines if "Philadelphia" in l))

    # The overlong name is clipped with a trailing ellipsis and the full name
    # is not shown; the cell is still exactly _TEAM_COL_WIDTH columns.
    cell = phi_line[3 : 3 + _TEAM_COL_WIDTH]
    assert cell.endswith("…")
    assert "Phillies" not in phi_line
    assert len(cell) == _TEAM_COL_WIDTH


# --- Grouped standings + pennants (FRE-118) --------------------------------

# Two leagues, two divisions each; keys are "{team_id}-2000".
_GROUPED_TEAMS = [
    LeagueTeam("AE1", 2000, "AL East One", league="AL", division="E"),
    LeagueTeam("AE2", 2000, "AL East Two", league="AL", division="E"),
    LeagueTeam("AW1", 2000, "AL West One", league="AL", division="W"),
    LeagueTeam("AW2", 2000, "AL West Two", league="AL", division="W"),
    LeagueTeam("NL1", 2000, "NL One", league="NL", division="E"),
    LeagueTeam("NL2", 2000, "NL Two", league="NL", division="E"),
]


def _grouped_state(user_key="AE1-2000"):
    """A league-tagged season (no round-robin schedule) with hand-set results:
    AE1 beats AW1 (so AE1 leads AL East, AW1 leads AL West on its own game)."""
    state = SeasonState(
        teams=list(_GROUPED_TEAMS), games_per_opponent=None, schedule=[],
        user_team_key=user_key,
    )
    state.results = [
        SeasonGameRecord(0, 0, "AE1-2000", "AE2-2000", 5, 2, 9),  # AE1 1-0
        SeasonGameRecord(1, 0, "AW1-2000", "AW2-2000", 5, 2, 9),  # AW1 1-0
        SeasonGameRecord(2, 0, "NL1-2000", "NL2-2000", 5, 2, 9),  # NL1 1-0
    ]
    return state


def test_grouped_standings_renders_a_block_per_group():
    mock = _hub_mock(_controller(_grouped_state()))

    table = SeasonHubScreen._build_standings_table(mock)
    stripped = _strip_markup(table)

    # A titled header for each league/division group, in (league, division) order.
    for title in ("AL E", "AL W", "NL E"):
        assert title in stripped
    assert stripped.index("AL E") < stripped.index("AL W") < stripped.index("NL E")
    # Every club appears under some group.
    for team in _GROUPED_TEAMS:
        assert team.display_name in stripped


def test_grouped_standings_gb_is_within_group():
    # AE1 leads AL East (GB 0 / "—"); AE2 sits behind within that group only.
    mock = _hub_mock(_controller(_grouped_state()))
    lines = _strip_markup(SeasonHubScreen._build_standings_table(mock)).splitlines()

    ae1 = next(l for l in lines if "AL East One" in l)
    aw1 = next(l for l in lines if "AL West One" in l)
    # Both division leaders show the em-dash GB even though neither trails the
    # other in a flat league-wide table.
    assert "—" in ae1
    assert "—" in aw1


def test_grouped_standings_marks_user_team():
    mock = _hub_mock(_controller(_grouped_state(user_key="AE1-2000")))
    lines = SeasonHubScreen._build_standings_table(mock).splitlines()

    user_line = next(l for l in lines if "AL East One" in l)
    assert "►" in user_line
    assert user_line.startswith("[bold]")


def test_round_robin_still_renders_single_flat_table():
    # A round-robin (ungrouped) season is untouched: one header, no group titles.
    mock = _hub_mock(_controller(_make_state()))
    table = SeasonHubScreen._build_standings_table(mock)
    stripped = _strip_markup(table)

    assert "AL E" not in stripped and "NL" not in stripped
    # Exactly one column header (the flat table), then one row per team.
    assert stripped.count("Team") == 1
    assert len(table.splitlines()) == 1 + len(_TEAMS)


def test_pennants_block_lists_winner_per_league():
    mock = _hub_mock(_controller(_grouped_state()))

    text = _strip_markup(SeasonHubScreen._build_pennants(mock))
    lines = text.splitlines()

    assert len(lines) == 2  # one per league
    assert "AL: AL East One" in text   # AE1 leads the AL
    assert "NL: NL One" in text        # NL1 leads the NL


# ---------------------------------------------------------------------------
# Day header + matchups (mid-season)
# ---------------------------------------------------------------------------


def test_day_header_is_one_indexed_current_day():
    state = _make_state()
    _play_day(state, 0)  # finish day 0 -> current day advances to 1
    mock = _hub_mock(_controller(state))

    # 4 teams, G=2 -> (N-1)*G = 6 days.
    assert SeasonHubScreen._day_header(mock) == "Day 2 of 6"


def test_matchups_mark_the_users_game():
    state = _make_state(user_key="NYA-1927")
    _play_day(state, 0)
    controller = _controller(state)
    mock = _hub_mock(controller)

    text = SeasonHubScreen._build_matchups(mock)
    lines = text.splitlines()

    # One line per game on the current day (each team plays once).
    assert len(lines) == len(_TEAMS) // 2
    user_line = next(l for l in lines if "1927 Yankees" in l)
    assert "← your game" in user_line
    # AI-only games are not marked.
    assert all("← your game" not in l for l in lines if "1927 Yankees" not in l)


def test_matchups_unmarked_in_watch_only():
    state = _make_state(user_key=None)
    mock = _hub_mock(_controller(state))

    text = SeasonHubScreen._build_matchups(mock)

    assert "← your game" not in text


def test_recent_results_newest_first_with_scores():
    state = _make_state()
    _play_day(state, 0, winner_key="NYA-1927")
    mock = _hub_mock(_controller(state))

    text = SeasonHubScreen._build_recent_results(mock)
    lines = text.splitlines()

    assert lines  # something rendered
    # The most-recent record is rendered first.
    last = state.results[-1]
    assert _TEAMS_BY_KEY[last.away_key].display_name in lines[0]
    assert str(last.away_score) in lines[0]


def test_recent_results_empty_before_any_game():
    state = _make_state()
    mock = _hub_mock(_controller(state))
    assert "No games played yet" in SeasonHubScreen._build_recent_results(mock)


# ---------------------------------------------------------------------------
# League leaders — resolved names + qualifiers
# ---------------------------------------------------------------------------


def _stats_with_leaders():
    """A stats object where one batter/pitcher qualifies and one doesn't.

    Team has 5 games played, so AVG qualifies at AB >= 10 and ERA at outs >= 15.
    """
    stats = SeasonStats(
        batting={
            "NYA-1927": {
                "ruth01": {"AB": 20, "H": 12, "HR": 6, "RBI": 18},
                "scrub01": {"AB": 2, "H": 2, "HR": 0, "RBI": 1},
            }
        },
        pitching={
            "NYA-1927": {
                "hoytwa01": {"outs": 45, "ER": 5, "K": 30},
                "reliev01": {"outs": 3, "ER": 0, "K": 2},
            }
        },
        games_played={"NYA-1927": 5},
    )
    return stats


def _leader_teams():
    return {
        "NYA-1927": _FakeTeam(
            {
                "ruth01": _FakePlayer("Babe", "Ruth"),
                "scrub01": _FakePlayer("Benny", "Bench"),
                "hoytwa01": _FakePlayer("Waite", "Hoyt"),
                "reliev01": _FakePlayer("Rex", "Relief"),
            }
        )
    }


def test_avg_board_respects_qualifier_and_resolves_name():
    controller = _controller(_make_state(), _stats_with_leaders(), _leader_teams())

    table = _build_leader_table(
        controller, "AVG", "batting_average_leaders", lambda v: f"{v:.3f}"
    )

    assert "B. Ruth" in table          # AB 20 >= 2*5 -> qualifies
    assert "B. Bench" not in table     # AB 2 -> does not qualify
    assert "ruth01" not in table       # raw id never shown
    assert "scrub01" not in table


def test_era_board_respects_qualifier():
    controller = _controller(_make_state(), _stats_with_leaders(), _leader_teams())

    table = _build_leader_table(
        controller, "ERA", "era_leaders", lambda v: f"{v:.2f}"
    )

    assert "W. Hoyt" in table          # 45 outs >= 3*5 -> qualifies
    assert "R. Relief" not in table    # 3 outs -> does not qualify


def test_hr_board_is_counting_and_unqualified():
    controller = _controller(_make_state(), _stats_with_leaders(), _leader_teams())

    table = _build_leader_table(
        controller, "HR", "home_run_leaders", lambda v: str(int(v))
    )

    assert "B. Ruth" in table
    assert "6" in table


def test_resolve_name_falls_back_to_id_without_roster():
    controller = _controller(_make_state(), _stats_with_leaders(), teams={})
    # No team loaded -> defensive fallback to the id (normal play always loads).
    assert _resolve_name(controller, "NYA-1927", "ruth01") == "ruth01"


def test_leaders_screen_builds_both_halves():
    controller = _controller(_make_state(), _stats_with_leaders(), _leader_teams())
    mock = _leaders_mock(controller)

    batting = LeagueLeadersScreen._build_batting_leaders(mock)
    pitching = LeagueLeadersScreen._build_pitching_leaders(mock)

    for title in ("AVG", "HR", "RBI", "H"):
        assert title in batting
    for title in ("ERA", "SO", "IP"):
        assert title in pitching
    assert "B. Ruth" in batting
    assert "W. Hoyt" in pitching


def test_empty_leaderboard_renders_placeholder():
    controller = _controller(_make_state(), SeasonStats(), {})
    table = _build_leader_table(
        controller, "AVG", "batting_average_leaders", lambda v: f"{v:.3f}"
    )
    assert "AVG" in table
    assert "—" in table


# ---------------------------------------------------------------------------
# Complete-season summary
# ---------------------------------------------------------------------------


def _complete_state(user_key="NYA-1927", champion_key="NYA-1927"):
    state = _make_state(user_key=user_key)
    for day in range(len(state.schedule)):
        _play_day(state, day, winner_key=champion_key)
    return state


def test_complete_state_is_recognized():
    state = _complete_state()
    assert state.is_complete is True


def test_champion_line_names_the_winner():
    state = _complete_state(champion_key="NYA-1927")
    mock = _hub_mock(_controller(state))

    line = SeasonHubScreen._champion_line(mock)

    assert "1927 Yankees" in line
    assert "Champions" in line
    # The champion is the team that won all its games.
    assert state.champion == "NYA-1927"


def test_summary_leaders_include_all_boards():
    state = _complete_state()
    controller = _controller(state, _stats_with_leaders(), _leader_teams())
    mock = _hub_mock(controller)

    text = SeasonHubScreen._build_summary_leaders(mock)

    for title in ("AVG", "HR", "RBI", "H", "ERA", "SO", "IP"):
        assert title in text


# ---------------------------------------------------------------------------
# check_action gating
# ---------------------------------------------------------------------------


def _gate_mock(state):
    return SimpleNamespace(_controller=_controller(state))


def test_watch_only_hides_play_and_sim_my_game():
    mock = _gate_mock(_make_state(user_key=None))
    assert SeasonHubScreen.check_action(mock, "play_my_game", ()) is None
    assert SeasonHubScreen.check_action(mock, "sim_my_game", ()) is None
    # Day-level actions stay available.
    assert SeasonHubScreen.check_action(mock, "sim_day", ()) is True
    assert SeasonHubScreen.check_action(mock, "leaders", ()) is True


def test_managed_season_shows_play_and_sim_my_game():
    mock = _gate_mock(_make_state(user_key="NYA-1927"))
    assert SeasonHubScreen.check_action(mock, "play_my_game", ()) is True
    assert SeasonHubScreen.check_action(mock, "sim_my_game", ()) is True


def test_complete_season_hides_play_actions_shows_summary_actions():
    mock = _gate_mock(_complete_state())
    for action in ("play_my_game", "sim_my_game", "sim_day", "sim_ahead", "save"):
        assert SeasonHubScreen.check_action(mock, action, ()) is None
    for action in ("new_season", "main_menu"):
        assert SeasonHubScreen.check_action(mock, action, ()) is True
    # Leaders + quit remain available at season end.
    assert SeasonHubScreen.check_action(mock, "leaders", ()) is True
    assert SeasonHubScreen.check_action(mock, "quit_to_menu", ()) is True


def test_active_season_hides_summary_actions():
    mock = _gate_mock(_make_state())
    assert SeasonHubScreen.check_action(mock, "new_season", ()) is None
    assert SeasonHubScreen.check_action(mock, "main_menu", ()) is None


# ---------------------------------------------------------------------------
# Action dispatch -> owner callback
# ---------------------------------------------------------------------------


def _action_mock():
    captured = []
    mock = SimpleNamespace(_on_choice=lambda choice: captured.append(choice))
    mock._emit = lambda choice: SeasonHubScreen._emit(mock, choice)
    return mock, captured


def test_each_action_surfaces_its_choice():
    cases = [
        ("action_play_my_game", HubChoice.PLAY),
        ("action_sim_my_game", HubChoice.SIM_MY_GAME),
        ("action_sim_day", HubChoice.SIM_DAY),
        ("action_sim_ahead", HubChoice.SIM_AHEAD),
        ("action_save", HubChoice.SAVE),
        ("action_new_season", HubChoice.NEW_SEASON),
        ("action_main_menu", HubChoice.MAIN_MENU),
        ("action_quit_to_menu", HubChoice.QUIT),
    ]
    for method_name, expected in cases:
        mock, captured = _action_mock()
        getattr(SeasonHubScreen, method_name)(mock)
        assert captured == [expected], method_name


def test_leaders_action_pushes_leaders_screen_not_owner_callback():
    pushed = []
    controller = _controller(_make_state())
    mock = SimpleNamespace(
        _controller=controller,
        _on_choice=lambda choice: pushed.append(("choice", choice)),
        app=SimpleNamespace(push_screen=lambda screen: pushed.append(screen)),
    )

    SeasonHubScreen.action_leaders(mock)

    assert len(pushed) == 1
    assert isinstance(pushed[0], LeagueLeadersScreen)
    assert pushed[0]._controller is controller


def _team_stats_mock(controller):
    pushed = []
    mock = SimpleNamespace(
        _controller=controller,
        app=SimpleNamespace(push_screen=lambda screen: pushed.append(screen)),
    )
    return mock, pushed


def test_team_stats_action_opens_on_user_team():
    controller = _controller(_make_state(user_key="NYA-1927"))
    mock, pushed = _team_stats_mock(controller)

    SeasonHubScreen.action_team_stats(mock)

    assert len(pushed) == 1
    screen = pushed[0]
    assert isinstance(screen, TeamStatsScreen)
    assert screen._controller is controller
    # Opens on the user's team.
    assert screen._current_key() == "NYA-1927"


def test_team_stats_action_opens_on_leader_when_watch_only():
    state = _make_state(user_key=None)
    controller = _controller(state)
    mock, pushed = _team_stats_mock(controller)

    SeasonHubScreen.action_team_stats(mock)

    # No user team -> the standings leader is the initial team.
    assert pushed[0]._current_key() == state.standings[0].key


def test_team_stats_action_always_available():
    # Mid-season and at season end alike (reviewing final team stats is natural).
    active = _gate_mock(_make_state())
    complete = _gate_mock(_complete_state())
    assert SeasonHubScreen.check_action(active, "team_stats", ()) is True
    assert SeasonHubScreen.check_action(complete, "team_stats", ()) is True


# ---------------------------------------------------------------------------
# Shared lookup used by several tests
# ---------------------------------------------------------------------------

_TEAMS_BY_KEY = {team.key: team for team in _TEAMS}
