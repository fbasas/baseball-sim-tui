"""Unit tests for the historical-season setup flow (FRE-119).

DB-free and Pilot-free, in the house callback-driven idiom (mirrors
``test_season_setup_flow``): a fake app records each ``push_screen(screen,
callback)`` so the test can inspect the pushed screen and invoke the callback
with the value a real screen would dismiss. The league builder
(``build_historical_season``, tested in ``test_season_historical``) and team
loads are monkeypatched; role cards are written into a tmp dir.

Coverage (the Part-4 DoD):

- the year picker offers only years with both roster and schedule data
  (``get_available_years`` ∩ ``has_schedule``), and no such year returns to the
  mode menu;
- backing out of the year picker returns to the mode menu (``on_cancel``);
- a league-build failure or a team-load failure names the teams and returns to
  the year picker;
- the your-team screen lists every league team (``"{year} {name}"``) plus
  watch-only; watch-only yields ``user_team_key is None``;
- the happy path builds a ``SeasonController`` over a grouped historical
  ``SeasonState`` with the chosen user team and a context per team;
- the role-card pass (shared helper): a missing card is built and the season
  starts; an unbuildable team blocks it, named;
- backing out of the your-team screen returns to the year picker.
"""

from types import SimpleNamespace

import src.tui.role_card_pass as role_card_pass_module
from src.game.team import Team
from src.manager.roles import TeamRoleCard, save_role_card
from src.season.schedule import ScheduledGame
from src.season.state import LeagueTeam, SeasonState
from src.tui.historical_setup_flow import HistoricalSeasonSetupFlow
from src.tui.screens.choice_screen import ChoiceScreen
import src.tui.historical_setup_flow as historical_flow_module
from src.season.historical import HistoricalSeasonError


YEAR = 1927

# Four teams: TA/TB in the AL East, TC/TD in the NL (pre-division, divID None).
_LEAGUE = [
    LeagueTeam("TA", YEAR, "TA Club", league="AL", division="E"),
    LeagueTeam("TB", YEAR, "TB Club", league="AL", division="E"),
    LeagueTeam("TC", YEAR, "TC Club", league="NL", division=None),
    LeagueTeam("TD", YEAR, "TD Club", league="NL", division=None),
]
_KEYS = [t.key for t in _LEAGUE]


class FakeApp:
    """Records pushed screens/callbacks, notifies, and runs workers inline."""

    def __init__(self):
        self.pushed = []
        self.notes = []

    def push_screen(self, screen, callback=None):
        self.pushed.append((screen, callback))

    def notify(self, message, **kwargs):
        self.notes.append((message, kwargs))

    def run_worker(self, work, **kwargs):
        work()

    def call_from_thread(self, fn, *args, **kwargs):
        return fn(*args, **kwargs)

    @property
    def last_screen(self):
        return self.pushed[-1][0]

    @property
    def last_callback(self):
        return self.pushed[-1][1]


def _fake_state():
    """A grouped historical ``SeasonState`` (no user team) over the 4 teams."""
    schedule = [
        [
            ScheduledGame(0, 0, "TA-1927", "TB-1927"),
            ScheduledGame(1, 0, "TC-1927", "TD-1927"),
        ]
    ]
    return SeasonState.from_schedule(list(_LEAGUE), schedule)


def _repo(years=(2016, YEAR, 1906), has={2016, YEAR}):
    """Repo double: year availability + the role-card gather methods."""
    return SimpleNamespace(
        get_available_years=lambda: list(years),
        has_schedule=lambda y: y in has,
        get_team_season=lambda tid, yr: SimpleNamespace(team_id=tid, year=yr),
        get_team_roster=lambda tid, yr: [],
        get_batting_stats=lambda pid, yr: None,
        get_pitching_stats=lambda pid, yr: None,
        get_appearances=lambda tid, yr: [],
    )


def _install_team_loader(monkeypatch, raise_for=()):
    def fake_load(repo, team_id, year):
        if (team_id, year) in raise_for:
            raise ValueError("sparse roster")
        return SimpleNamespace(
            info=SimpleNamespace(team_id=team_id, year=year, team_name=f"{team_id} Club")
        )

    monkeypatch.setattr(Team, "load_from_repository", staticmethod(fake_load))


def _install_builder(monkeypatch, state=None, raises=None):
    def fake_build(repo, year, user_team_key=None):
        if raises is not None:
            raise raises
        return state if state is not None else _fake_state()

    monkeypatch.setattr(historical_flow_module, "build_historical_season", fake_build)


def _write_card(roles_dir, team_id, year):
    save_role_card(TeamRoleCard(team_id, year, {}, {}, [], {}), roles_dir)


def _make_flow(app, repo, roles_dir, captured):
    return HistoricalSeasonSetupFlow(
        app,
        repo,
        on_complete=lambda controller: captured.update(controller=controller),
        on_cancel=lambda: captured.update(cancel=True),
        roles_dir=roles_dir,
    )


# ---------------------------------------------------------------------------
# Year picker
# ---------------------------------------------------------------------------


def test_year_picker_offers_only_years_with_schedule(monkeypatch, tmp_path):
    _install_team_loader(monkeypatch)
    app, captured = FakeApp(), {}
    flow = _make_flow(app, _repo(), tmp_path, captured)
    flow.begin()

    assert isinstance(app.last_screen, ChoiceScreen)
    assert app.last_screen._title == "⚾ HISTORICAL SEASON"
    year_ids = [cid for cid, _label in app.last_screen._choices]
    assert year_ids == ["2016", "1927"]  # 1906 has no schedule; order preserved


def test_no_buildable_year_returns_to_mode_menu(monkeypatch, tmp_path):
    _install_team_loader(monkeypatch)
    app, captured = FakeApp(), {}
    flow = _make_flow(app, _repo(has=set()), tmp_path, captured)
    flow.begin()

    assert captured.get("cancel") is True
    assert app.pushed == []  # no picker shown
    assert any(kw.get("severity") == "warning" for _m, kw in app.notes)


def test_back_at_year_picker_returns_to_mode_menu(monkeypatch, tmp_path):
    _install_team_loader(monkeypatch)
    app, captured = FakeApp(), {}
    flow = _make_flow(app, _repo(), tmp_path, captured)
    flow.begin()
    app.last_callback(None)

    assert captured.get("cancel") is True


# ---------------------------------------------------------------------------
# League build failures -> back to the year picker
# ---------------------------------------------------------------------------


def test_build_failure_names_teams_and_reprompts_year(monkeypatch, tmp_path):
    _install_team_loader(monkeypatch)
    _install_builder(
        monkeypatch, raises=HistoricalSeasonError(YEAR, ["rX (unresolved Retrosheet id)"])
    )
    app, captured = FakeApp(), {}
    flow = _make_flow(app, _repo(), tmp_path, captured)
    flow.begin()
    app.last_callback(str(YEAR))

    error_notes = [msg for msg, kw in app.notes if kw.get("severity") == "error"]
    assert error_notes and "rX (unresolved Retrosheet id)" in error_notes[-1]
    # Back at the year picker, not the your-team screen.
    assert isinstance(app.last_screen, ChoiceScreen)
    assert app.last_screen._title == "⚾ HISTORICAL SEASON"
    assert "controller" not in captured


def test_team_load_failure_names_team_and_reprompts_year(monkeypatch, tmp_path):
    _install_builder(monkeypatch)
    _install_team_loader(monkeypatch, raise_for={("TC", YEAR)})
    app, captured = FakeApp(), {}
    flow = _make_flow(app, _repo(), tmp_path, captured)
    flow.begin()
    app.last_callback(str(YEAR))

    error_notes = [msg for msg, kw in app.notes if kw.get("severity") == "error"]
    assert error_notes and "1927 TC Club" in error_notes[-1]
    assert app.last_screen._title == "⚾ HISTORICAL SEASON"
    assert "controller" not in captured


# ---------------------------------------------------------------------------
# Your team
# ---------------------------------------------------------------------------


def _drive_to_your_team(app, flow):
    flow.begin()
    app.last_callback(str(YEAR))


def test_your_team_lists_all_teams_and_watch_only(monkeypatch, tmp_path):
    _install_builder(monkeypatch)
    _install_team_loader(monkeypatch)
    app, captured = FakeApp(), {}
    flow = _make_flow(app, _repo(), tmp_path, captured)
    _drive_to_your_team(app, flow)

    assert isinstance(app.last_screen, ChoiceScreen)
    assert app.last_screen._title == "⚾ YOUR TEAM"
    choices = app.last_screen._choices
    assert [cid for cid, _label in choices] == _KEYS + ["watch only"]
    labels = dict(choices)
    assert labels["TA-1927"] == "1927 TA Club"
    assert labels["watch only"] == "Watch-only (commissioner)"


def test_watch_only_yields_no_user_team(monkeypatch, tmp_path):
    _install_builder(monkeypatch)
    _install_team_loader(monkeypatch)
    for t in _LEAGUE:
        _write_card(tmp_path, t.team_id, t.year)
    app, captured = FakeApp(), {}
    flow = _make_flow(app, _repo(), tmp_path, captured)
    _drive_to_your_team(app, flow)
    app.last_callback("watch only")

    controller = captured["controller"]
    assert controller.state.user_team_key is None


def test_back_from_your_team_reprompts_year(monkeypatch, tmp_path):
    _install_builder(monkeypatch)
    _install_team_loader(monkeypatch)
    app, captured = FakeApp(), {}
    flow = _make_flow(app, _repo(), tmp_path, captured)
    _drive_to_your_team(app, flow)
    assert app.last_screen._title == "⚾ YOUR TEAM"
    app.last_callback(None)

    assert app.last_screen._title == "⚾ HISTORICAL SEASON"
    assert "controller" not in captured
    assert "cancel" not in captured


# ---------------------------------------------------------------------------
# Happy path + role-card pass
# ---------------------------------------------------------------------------


def test_happy_path_builds_grouped_controller(monkeypatch, tmp_path):
    _install_builder(monkeypatch)
    _install_team_loader(monkeypatch)
    for t in _LEAGUE:
        _write_card(tmp_path, t.team_id, t.year)
    app, captured = FakeApp(), {}
    flow = _make_flow(app, _repo(), tmp_path, captured)
    _drive_to_your_team(app, flow)
    app.last_callback("TA-1927")

    controller = captured["controller"]
    assert [t.key for t in controller.state.teams] == _KEYS
    assert controller.state.user_team_key == "TA-1927"
    assert controller.state.games_per_opponent is None  # historical, prebuilt
    assert controller.state.is_grouped  # grouped standings apply
    assert set(controller.contexts) == set(_KEYS)
    assert set(controller.teams) == set(_KEYS)
    assert "cancel" not in captured


def test_missing_card_built_and_season_starts(monkeypatch, tmp_path):
    _install_builder(monkeypatch)
    _install_team_loader(monkeypatch)
    for t in _LEAGUE[:-1]:  # TD-1927 card missing -> must build
        _write_card(tmp_path, t.team_id, t.year)

    built = []

    def fake_build_card(*a, **k):
        built.append(True)
        return TeamRoleCard("TD", YEAR, {}, {}, [], {})

    monkeypatch.setattr(role_card_pass_module, "build_role_card", fake_build_card)

    app, captured = FakeApp(), {}
    flow = _make_flow(app, _repo(), tmp_path, captured)
    _drive_to_your_team(app, flow)
    app.last_callback("TA-1927")

    assert built == [True]
    assert (tmp_path / "TD-1927.json").exists()
    assert captured.get("controller") is not None
    assert "cancel" not in captured


def test_unbuildable_team_blocks_season(monkeypatch, tmp_path):
    _install_builder(monkeypatch)
    _install_team_loader(monkeypatch)
    for t in _LEAGUE[:-1]:
        _write_card(tmp_path, t.team_id, t.year)

    def fake_build_card(*a, **k):
        raise ValueError("no usable pitchers")

    monkeypatch.setattr(role_card_pass_module, "build_role_card", fake_build_card)

    app, captured = FakeApp(), {}
    flow = _make_flow(app, _repo(), tmp_path, captured)
    _drive_to_your_team(app, flow)
    app.last_callback("TA-1927")

    assert "controller" not in captured
    assert captured.get("cancel") is True
    error_notes = [msg for msg, kw in app.notes if kw.get("severity") == "error"]
    # The role-card pass names teams by display_name (the whole season is one
    # year, so the historical LeagueTeam display_name omits it).
    assert error_notes and "TD Club" in error_notes[-1]


# ---------------------------------------------------------------------------
# SetupFlow mode routing into the historical flow
# ---------------------------------------------------------------------------


def test_mode_historical_routes_to_select_historical():
    from src.tui.setup_flow import SetupFlow

    calls = {}
    pushed = {}
    app = SimpleNamespace(
        push_screen=lambda screen, callback=None: pushed.update(
            screen=screen, callback=callback
        )
    )
    mock = SimpleNamespace(
        _app=app,
        _on_cancel=lambda: calls.setdefault("cancel", True),
        _select_control=lambda: calls.setdefault("control", True),
        _select_saved_game=lambda: calls.setdefault("saved", True),
        _select_season=lambda: calls.setdefault("season", True),
        _select_historical=lambda: calls.setdefault("historical", True),
    )

    SetupFlow._select_mode(mock)
    pushed["callback"]("historical")

    assert calls == {"historical": True}


def test_select_historical_invokes_on_historical_callback():
    from src.tui.setup_flow import SetupFlow

    calls = {}
    mock = SimpleNamespace(
        _on_historical=lambda: calls.setdefault("historical", True),
        _select_mode=lambda: calls.setdefault("menu", True),
    )
    SetupFlow._select_historical(mock)
    assert calls == {"historical": True}


def test_select_historical_without_callback_returns_to_menu():
    from src.tui.setup_flow import SetupFlow

    calls = {}
    mock = SimpleNamespace(
        _on_historical=None,
        _select_mode=lambda: calls.setdefault("menu", True),
    )
    SetupFlow._select_historical(mock)
    assert calls == {"menu": True}


def test_mode_choices_include_historical():
    from src.tui.setup_flow import _MODE_CHOICES

    ids = [cid for cid, _label in _MODE_CHOICES]
    assert "historical" in ids
    # Ordered after season, before load (the year-based season neighbours).
    assert ids.index("season") < ids.index("historical") < ids.index("load")
