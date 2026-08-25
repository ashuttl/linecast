"""Tests for the `/` search prompt.

No network and no real timers: the module's `threading` is swapped for a
recorder, so the debounce, the generation check and the auto-commit are
asserted rather than waited out. The fetchers are injected.
"""

import re
import sys
import threading
import types
from pathlib import Path

import pytest

# Ensure the worktree src is preferred over any installed version.
_src = str(Path(__file__).resolve().parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from linecast import _color, _maps_i18n
from linecast import _maps_ui as mu
from linecast._framebuffer import visible_len
from linecast._maps_route import NoRoute, Route, RouteUnavailable
from linecast._maps_search import Result, SearchUnavailable


class FakeTimer:
    """Stand-in for threading.Timer: records instead of scheduling."""

    armed = []

    def __init__(self, delay, fn, args=()):
        self.delay, self.fn, self.args = delay, fn, tuple(args)
        self.cancelled = False
        self.daemon = False
        FakeTimer.armed.append(self)

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True

    def fire(self):
        self.fn(*self.args)


class FakeThread:
    started = []

    def __init__(self, target=None, daemon=False):
        self.target = target
        FakeThread.started.append(self)

    def start(self):
        pass

    def run_now(self):
        self.target()


@pytest.fixture(autouse=True)
def _house_units(monkeypatch):
    """Units come from the language alone here: neither WEATHER_UNITS nor
    a `linecast units` preference saved on this machine may leak in."""
    from linecast import _config
    monkeypatch.delenv("WEATHER_UNITS", raising=False)
    monkeypatch.setattr(_config, "saved_units", lambda: None)


@pytest.fixture(autouse=True)
def _no_real_threads(monkeypatch):
    FakeTimer.armed = []
    FakeThread.started = []
    monkeypatch.setattr(mu, "threading", types.SimpleNamespace(
        Timer=FakeTimer, Thread=FakeThread, Lock=threading.Lock))
    monkeypatch.setattr(_color, "_COLOR_MODE", "truecolor")


def result(name="Portland Head Light", detail="Cape Elizabeth",
           lat=43.623, lon=-70.207, kind="attraction", extent=None):
    return Result(name, detail, lat, lon, kind, extent)


def state(results=(), fail=False, one_shot=None):
    """A SearchState whose fetcher answers from a canned list."""
    calls = []

    def fetch(query, lat, lon, zoom, lang="en"):
        calls.append((query, lat, lon, zoom, lang))
        if fail:
            raise SearchUnavailable("no")
        return list(results)

    st = mu.SearchState(refresh=lambda: pokes.append(1), fetch=fetch,
                        one_shot=one_shot or (lambda q, lang: []))
    pokes = []
    st.calls = calls
    st.pokes = pokes
    return st


def typed(st, text, lat=43.6, lon=-70.2, zoom=12):
    for ch in text:
        st.handle(f"char:{ch}", lat, lon, zoom)


def strip(s):
    return re.sub(r"\033\[[^m]*m", "", s)


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------
class TestLifecycle:
    def test_start_opens_an_empty_field(self):
        st = state()
        st.start()
        assert st.open
        assert st.query == ""
        assert st.results == []

    def test_escape_closes_and_discards_the_query(self):
        # Discarding the query is the only thing esc costs, which is
        # what makes it safe to press.
        st = state([result()])
        st.start()
        typed(st, "por")
        st.handle('escape', 43.6, -70.2, 12)
        assert not st.open
        assert st.query == ""
        assert st.chosen is None

    def test_closing_cancels_the_pending_request(self):
        st = state()
        st.start()
        typed(st, "por")
        st.close()
        assert FakeTimer.armed[-1].cancelled

    def test_a_reply_that_lands_after_closing_is_dropped(self):
        st = state([result()])
        st.start()
        typed(st, "por")
        timer = FakeTimer.armed[-1]
        st.close()
        timer.fire()
        assert st.results == []
        assert st.chosen is None


# ---------------------------------------------------------------------------
# Typing and the debounce
# ---------------------------------------------------------------------------
class TestTyping:
    def test_a_single_character_asks_nothing(self):
        # Below the minimum, asking is noise for both of us.
        st = state()
        st.start()
        typed(st, "p")
        assert FakeTimer.armed == []
        assert st.status == ""

    def test_the_second_character_arms_the_debounce(self):
        st = state()
        st.start()
        typed(st, "po")
        assert len(FakeTimer.armed) == 1
        assert FakeTimer.armed[0].delay == mu.DEBOUNCE
        assert st.status == "pending"

    def test_each_keystroke_re_arms_a_single_timer(self):
        # One live timer, never one thread per keystroke.
        st = state()
        st.start()
        typed(st, "portl")
        assert all(t.cancelled for t in FakeTimer.armed[:-1])
        assert not FakeTimer.armed[-1].cancelled

    def test_only_the_newest_query_reaches_the_screen(self):
        # In-flight requests cannot be cancelled, so the generation
        # check on the way back is the guarantee.
        st = state([result("Stale")])
        st.start()
        typed(st, "po")
        stale = FakeTimer.armed[-1]
        typed(st, "r")
        fresh = FakeTimer.armed[-1]
        stale.fire()
        assert st.results == []
        fresh.fire()
        assert [r.name for r in st.results] == ["Stale"]

    def test_a_reply_repaints_the_screen(self):
        st = state([result()])
        st.start()
        typed(st, "por")
        FakeTimer.armed[-1].fire()
        assert st.pokes

    def test_backspace_and_kill_edit_the_query(self):
        st = state()
        st.start()
        typed(st, "port")
        st.handle('key:backspace', 43.6, -70.2, 12)
        assert st.query == "por"
        st.handle('key:kill', 43.6, -70.2, 12)
        assert st.query == ""
        assert st.status == ""              # and stops asking

    def test_the_query_is_sent_verbatim_with_the_view_context(self):
        st = state([result()])
        st.start()
        typed(st, "head light", lat=43.6, lon=-70.2, zoom=14)
        FakeTimer.armed[-1].fire()
        assert st.calls[-1] == ("head light", 43.6, -70.2, 14, "en")

    def test_an_unreachable_geocoder_degrades_to_a_notice(self):
        st = state(fail=True)
        st.start()
        typed(st, "por")
        FakeTimer.armed[-1].fire()
        assert st.status == "error"
        assert st.results == []

    def test_an_empty_answer_says_so(self):
        st = state([])
        st.start()
        typed(st, "zzzz")
        FakeTimer.armed[-1].fire()
        assert st.status == "none"


# ---------------------------------------------------------------------------
# Selection and commit
# ---------------------------------------------------------------------------
class TestCommit:
    def _listed(self):
        st = state([result("A"), result("B"), result("C")])
        st.start()
        typed(st, "por")
        FakeTimer.armed[-1].fire()
        return st

    def test_arrows_move_the_highlight_with_wraparound(self):
        # live_loop's 'back' is the down arrow: down moves down.
        st = self._listed()
        assert st.sel == 0
        st.handle('back', 43.6, -70.2, 12)
        assert st.sel == 1
        st.handle('fwd', 43.6, -70.2, 12)
        st.handle('fwd', 43.6, -70.2, 12)
        assert st.sel == 2

    def test_the_map_does_not_move_until_enter(self):
        st = self._listed()
        st.handle('back', 43.6, -70.2, 12)
        assert st.chosen is None

    def test_enter_commits_the_highlighted_result_and_closes(self):
        st = self._listed()
        st.handle('back', 43.6, -70.2, 12)
        st.handle('key:enter', 43.6, -70.2, 12)
        assert not st.open
        assert st.chosen.name == "B"

    def test_the_committed_result_is_handed_over_once(self):
        st = self._listed()
        st.handle('key:enter', 43.6, -70.2, 12)
        assert st.take_chosen().name == "A"
        assert st.take_chosen() is None

    def test_enter_while_a_request_is_in_flight_still_goes(self):
        # The intent outlives a slow Photon: when the reply lands, its
        # first result commits itself.
        st = state([result("First"), result("Second")])
        st.start()
        typed(st, "por")
        st.handle('key:enter', 43.6, -70.2, 12)
        assert st.chosen is None
        assert st.submitted
        FakeTimer.armed[-1].fire()
        assert st.chosen.name == "First"
        assert not st.open

    def test_enter_on_an_empty_list_asks_nominatim_once(self):
        seen = []

        def one_shot(query, lang):
            seen.append((query, lang))
            return [result("Found by name")]

        st = state([], one_shot=one_shot)
        st.start()
        typed(st, "obscure")
        FakeTimer.armed[-1].fire()
        assert st.status == "none"
        st.handle('key:enter', 43.6, -70.2, 12)
        assert seen == []                       # not yet — it runs off-thread
        FakeThread.started[-1].run_now()
        assert seen == [("obscure", "en")]
        assert [r.name for r in st.results] == ["Found by name"]

    def test_the_one_shot_lists_rather_than_jumping(self):
        # By the time it answers the user has been waiting; a list they
        # can look at beats a jump they did not choose.
        st = state([], one_shot=lambda q, lang: [result("Guess")])
        st.start()
        typed(st, "obscure")
        FakeTimer.armed[-1].fire()
        st.handle('key:enter', 43.6, -70.2, 12)
        FakeThread.started[-1].run_now()
        assert st.chosen is None
        assert st.open

    def test_nominatim_is_never_asked_per_keystroke(self):
        seen = []
        st = state([result()], one_shot=lambda q, lang: seen.append(q))
        st.start()
        typed(st, "portland")
        for timer in FakeTimer.armed:
            if not timer.cancelled:
                timer.fire()
        assert seen == []

    def test_a_short_query_commits_nothing(self):
        st = state([])
        st.start()
        typed(st, "p")
        st.handle('key:enter', 43.6, -70.2, 12)
        assert FakeThread.started == []
        assert st.chosen is None


# ---------------------------------------------------------------------------
# Chrome
# ---------------------------------------------------------------------------
class TestOverlay:
    def _open(self, results=(), status="", query="por"):
        st = state(list(results))
        st.start()
        st.query = query
        st.results = list(results)
        st.status = status
        return st

    def test_the_field_carries_the_query_and_a_caret(self):
        st = self._open()
        panel = mu.search_overlay(st, 80, 24)
        assert "/ por" in strip(panel)
        assert "\033[7m \033[27m" in panel      # reverse-video caret

    def test_an_empty_field_shows_the_prompt(self):
        st = self._open(query="")
        assert "search places" in strip(mu.search_overlay(st, 80, 24))

    def test_a_pending_request_shows_an_ellipsis_not_a_spinner(self):
        # interval=3600: nothing would animate a spinner anyway.
        st = self._open(status="pending")
        assert strip(mu.search_overlay(st, 80, 24)).count("…") >= 1

    def test_results_are_listed_name_then_detail(self):
        st = self._open([result("Head Light", "Cape Elizabeth")])
        assert "Head Light, Cape Elizabeth" in strip(
            mu.search_overlay(st, 80, 24))

    def test_the_highlight_is_reverse_video(self):
        st = self._open([result("A", ""), result("B", "")])
        st.sel = 1
        panel = mu.search_overlay(st, 80, 24)
        rows = panel.split("\033[")
        highlighted = [r for r in rows if r.startswith("7m")]
        assert len(highlighted) == 2            # the caret and one row
        assert "B" in mu.search_overlay(st, 80, 24)

    def test_a_long_label_truncates_with_an_ellipsis(self):
        st = self._open([result("X" * 200, "Y" * 200)])
        plain = strip(mu.search_overlay(st, 80, 24))
        assert "…" in plain
        assert "X" * 200 not in plain

    def test_the_list_is_capped(self):
        st = self._open([result(f"R{i}", "") for i in range(20)])
        panel = mu.search_overlay(st, 80, 24)
        assert panel.count("\033[") > 0
        placed = [int(m) for m in re.findall(r"\033\[(\d+);1H", panel)]
        assert max(placed) <= mu.MAX_ROWS + 2

    def test_a_short_terminal_drops_rows_rather_than_overflowing(self):
        st = self._open([result(f"R{i}", "") for i in range(20)])
        panel = mu.search_overlay(st, 80, 6)
        placed = [int(m) for m in re.findall(r"\033\[(\d+);1H", panel)]
        assert max(placed) <= 6

    def test_the_empty_and_error_states_each_get_one_row(self):
        for status, text in (("none", "no matches"),
                             ("error", "search unavailable")):
            panel = mu.search_overlay(self._open(status=status), 80, 24)
            assert text in strip(panel)

    def test_the_hint_is_always_the_last_row(self):
        st = self._open([result("A", "")])
        panel = mu.search_overlay(st, 80, 24)
        assert "↑↓ select · enter go · esc close" in strip(panel)
        placed = [int(m) for m in re.findall(r"\033\[(\d+);1H", panel)]
        assert placed == sorted(placed)

    def test_the_panel_stays_inside_a_narrow_terminal(self):
        st = self._open([result("A very long place name indeed", "Maine")])
        for cols in (34, 60, 200):
            panel = mu.search_overlay(st, cols, 24)
            # each row is "ESC[<n>;1H" + body; the body must fit
            for chunk in strip(panel).split("\033")[1:]:
                body = chunk.split("H", 1)[-1]
                assert len(body) <= cols, (cols, body)


# ---------------------------------------------------------------------------
# Directions
# ---------------------------------------------------------------------------
HOME = (43.677, -70.371)
LIGHT = (43.6231, -70.2079)


STEPS = [
    {"distance_m": 106.9, "name": "Main Street", "ref": "ME 25 Business",
     "type": "depart", "modifier": "left", "location": (-70.371, 43.677)},
    {"distance_m": 3200.0, "name": "Spring Street", "ref": None,
     "type": "turn", "modifier": "right", "location": (-70.34, 43.66)},
    {"distance_m": 800.0, "name": "", "ref": "I 295",
     "type": "on ramp", "modifier": "slight left",
     "location": (-70.30, 43.65)},
    {"distance_m": 0.0, "name": "Shore Road", "ref": None,
     "type": "arrive", "modifier": None, "location": (-70.2079, 43.6231)},
]


def fake_route(profile="car", distance=18800.0, duration=1420.0,
               end=LIGHT, steps=None):
    return Route([(-70.371, 43.677), (end[1], end[0])],
                 distance, duration,
                 list(STEPS) if steps is None else steps, profile)


def routes(answer=None, error=None):
    """A RouteState whose client answers from a canned result."""
    calls = []

    def fetch(profile, origin, dest):
        calls.append((profile, origin, dest))
        if error is not None:
            raise error
        return answer if answer is not None else fake_route(profile)

    st = mu.RouteState(refresh=lambda: None, fetch=fetch, home=HOME)
    st.calls = calls
    return st


class TestDirections:
    def test_pressing_d_with_nothing_selected_asks_for_a_destination(self):
        # ...and opens the panel behind the search, so the field rows
        # are on screen the first time a route ever appears.
        st = routes()
        assert st.press() == "search"
        assert st.panel
        assert st.calls == []

    def test_pressing_d_with_a_selection_routes_to_it(self):
        st = routes()
        st.select(*LIGHT, "Portland Head Light")
        assert st.press() is True
        FakeThread.started[-1].run_now()
        assert st.calls == [("car", HOME, LIGHT)]
        assert st.route.distance_m == 18800.0
        assert st.status == ""

    def test_p_cycles_the_profile_and_goes_again(self):
        st = routes()
        st.select(*LIGHT)
        st.press()
        FakeThread.started[-1].run_now()
        for expected in ("bike", "foot", "car"):
            st.cycle_profile()
            FakeThread.started[-1].run_now()
            assert st.profile == expected
            assert st.calls[-1][0] == expected

    def test_p_with_no_destination_only_changes_the_mode(self):
        st = routes()
        st.cycle_profile()
        assert st.profile == "bike"
        assert FakeThread.started == []

    def test_a_press_with_a_standing_route_only_shows_the_panel(self):
        # Opening the panel must never cost a request the cache would
        # have answered anyway — re-aiming happens where a new point
        # is committed, not on the key that shows the panel.
        st = routes()
        st.select(*LIGHT)
        st.press()
        FakeThread.started[-1].run_now()
        assert st.press() is True
        assert len(st.calls) == 1

    def test_a_press_while_a_request_is_in_flight_does_not_double_fetch(self):
        st = routes()
        st.select(*LIGHT)
        st.press()
        assert st.press() is True           # the key visibly did something
        assert len(FakeThread.started) == 1
        assert st.status == "pending"

    def test_the_throttle_never_runs_in_the_keyboard_thread(self):
        # The client's own throttle sleeps; the press must return before
        # anything is fetched.
        st = routes()
        st.select(*LIGHT)
        st.press()
        assert st.calls == []
        FakeThread.started[-1].run_now()
        assert st.calls

    def test_no_route_and_unreachable_read_differently(self):
        for error, status in ((NoRoute("nope"), "none"),
                              (RouteUnavailable("down"), "error")):
            st = routes(error=error)
            st.select(*LIGHT)
            st.press()
            FakeThread.started[-1].run_now()
            assert st.status == status
            assert st.route is None

    def test_clearing_drops_the_route_and_any_late_reply(self):
        st = routes()
        st.select(*LIGHT)
        st.press()
        st.clear()
        FakeThread.started[-1].run_now()
        assert st.route is None
        assert st.dest is None
        assert st.status == ""


class TestOrigin:
    def test_the_origin_defaults_to_home(self):
        st = routes()
        assert st.origin_point() == HOME

    def test_an_edited_origin_re_points_the_next_request(self):
        st = routes()
        st.set_origin(44.1, -70.5, "Poland Spring")
        st.select(*LIGHT)
        st.press()
        FakeThread.started[-1].run_now()
        assert st.calls == [("car", (44.1, -70.5), LIGHT)]

    def test_clearing_reverts_the_origin_to_home(self):
        st = routes()
        st.set_origin(44.1, -70.5, "Poland Spring")
        st.clear()
        assert st.origin is None
        assert st.origin_point() == HOME


class TestDirectionsPanel:
    def _routed(self):
        st = routes()
        st.select(*LIGHT, "Portland Head Light")
        st.press()
        FakeThread.started[-1].run_now()
        return st

    def test_opening_focuses_nothing(self):
        # The map must never move on a key that only shows a panel.
        st = self._routed()
        assert st.panel and st.step is None

    def test_escape_closes_and_drops_the_focus(self):
        st = self._routed()
        st.step_move(1)
        assert st.close_panel() is True
        assert not st.panel and st.step is None

    def test_arrows_enter_the_list_from_either_end(self):
        st = self._routed()
        assert st.step_move(1) is st.route.steps[0]
        st.step = None
        assert st.step_move(-1) is st.route.steps[-1]

    def test_stepping_clamps_rather_than_wrapping(self):
        # Arriving must not wrap around to departing.
        st = self._routed()
        for _ in range(10):
            st.step_move(1)
        assert st.step == len(st.route.steps) - 1
        for _ in range(10):
            st.step_move(-1)
        assert st.step == 0

    def test_a_new_route_re_numbers_its_steps(self):
        st = self._routed()
        st.step_move(1)
        st.select(44.0, -69.0, "Somewhere else")
        st.request()
        FakeThread.started[-1].run_now()
        assert st.step is None

    def test_clearing_closes_the_panel(self):
        st = self._routed()
        st.clear()
        assert not st.panel and st.step is None


class TestDirectionsOverlay:
    def _state(self, route="yes", step=None, origin=None, status="",
               dest=(43.6231, -70.2079, "Portland Head Light"),
               profile="car"):
        st = routes()
        st.origin = origin
        st.dest = dest
        st.route = fake_route(profile) if route == "yes" else route
        st.step = step
        st.status = status
        st.profile = profile
        st.panel = True
        return st

    def _overlay(self, st=None, cols=80, rows=24, home_label="Westbrook",
                 **kwargs):
        st = st if st is not None else self._state(**kwargs)
        return mu.directions_overlay(st, cols, rows, "en",
                                     home_label=home_label)

    def test_the_field_rows_wear_their_labels_and_keys(self):
        plain = strip(self._overlay())
        assert re.search(r"o from +Westbrook", plain)
        assert re.search(r"d to +Portland Head Light", plain)
        assert re.search(r"p mode +driving · 11.7 mi · 24m", plain)

    def test_no_destination_is_a_placeholder_not_a_missing_row(self):
        plain = strip(self._overlay(route=None, dest=None))
        assert re.search(r"d to +…", plain)

    def test_the_routers_status_stands_in_for_absent_steps(self):
        plain = strip(self._overlay(route=None, status="pending"))
        assert "routing…" in plain
        plain = strip(self._overlay(route=None, status="none"))
        assert "no route" in plain

    def test_steps_keep_their_road_names(self):
        # The endpoints' labels live in the field rows now; the depart
        # and arrive rows go back to being roads.
        plain = strip(self._overlay())
        assert "Main Street" in plain
        assert "Spring Street" in plain
        assert "2.0 mi" in plain            # distances in the reader's units

    def test_an_edited_origin_names_itself_not_home(self):
        plain = strip(self._overlay(origin=(44.1, -70.5, "Poland Spring")))
        assert "Poland Spring" in plain
        assert "Westbrook" not in plain

    def test_an_unlabelled_point_falls_back_to_coordinates(self):
        plain = strip(self._overlay(origin=(44.1, -70.5, ""),
                                    home_label=""))
        assert "44.100, -70.500" in plain

    def test_a_ramp_shows_its_ref_when_the_name_is_blank(self):
        assert "I 295" in strip(self._overlay())

    def test_a_ramp_with_no_ref_borrows_the_hover_word(self):
        bare = dict(STEPS[2], ref=None)
        st = self._state()
        st.route = fake_route(steps=[STEPS[0], bare, STEPS[3]])
        assert "ramp" in strip(self._overlay(st=st))

    def test_the_focused_step_is_reverse_video_and_counted(self):
        panel = self._overlay(step=1)
        assert "\033[7m" in panel
        assert "2/4 · " in strip(panel)

    def test_unfocused_panels_count_nothing(self):
        assert "/4" not in strip(self._overlay())

    def test_a_short_terminal_windows_around_the_focus(self):
        # rows=8 leaves the fields + two steps + hint; focus stays
        # visible while the far end of the route drops.
        panel = self._overlay(step=3, rows=8)
        plain = strip(panel)
        assert "Shore Road" in plain
        assert "Main Street" not in plain
        placed = [int(m) for m in re.findall(r"\033\[(\d+);1H", panel)]
        assert max(placed) <= 7             # and the footer row stays free

    def test_the_hint_is_the_last_row(self):
        panel = self._overlay()
        assert "↑↓ step · esc close" in strip(panel)
        placed = [int(m) for m in re.findall(r"\033\[(\d+);1H", panel)]
        assert placed == sorted(placed)

    def test_the_panel_starts_under_the_header(self):
        # The map's own top row — place, mode, readout — stays legible.
        panel = self._overlay()
        placed = [int(m) for m in re.findall(r"\033\[(\d+);1H", panel)]
        assert min(placed) == 2

    def test_only_the_field_rows_take_a_ground(self):
        # The steps are bare ink over the map, the see-through readout
        # treatment: each row claims no more ground than its own text.
        panel = self._overlay()
        rows_ = re.split(r"\033\[\d+;1H", panel)[1:]
        grounded = [r for r in rows_ if "\033[48;" in r]
        assert len(grounded) == 3

    def test_a_terminal_too_short_for_the_fields_gets_none(self):
        st = self._state()
        assert self._overlay(st=st, rows=5) == ""
        assert st.panel_rows is None

    def test_the_row_map_names_what_each_row_holds(self):
        # The map is what lets a mouse click land on a field or a step.
        st = self._state()
        self._overlay(st=st)
        width, acts = st.panel_rows
        assert acts[2] == 'from' and acts[3] == 'to' and acts[4] == 'mode'
        assert acts[5] == ('step', 0) and acts[8] == ('step', 3)
        assert 9 not in acts                # the hint row is not a control
        assert mu.PANEL_MIN <= width <= mu.PANEL_MAX

    def test_the_row_map_follows_the_window(self):
        st = self._state(step=3)
        self._overlay(st=st, rows=8)
        _width, acts = st.panel_rows
        assert set(acts) == {2, 3, 4, 5, 6}
        assert acts[6] == ('step', 3)

    def test_the_panel_stays_inside_a_narrow_terminal(self):
        for cols in (34, 60, 200):
            panel = self._overlay(cols=cols)
            for chunk in strip(panel).split("\033")[1:]:
                body = chunk.split("H", 1)[-1]
                assert len(body) <= cols, (cols, body)


class TestStepsText:
    def test_plain_lines_for_print_mode(self):
        lines = mu.steps_text(fake_route(), "en",
                              origin_label="Westbrook",
                              dest_label="Portland Head Light")
        assert lines[0].startswith(" ●")
        assert "Westbrook" in lines[0]
        assert "Portland Head Light" in lines[-1]
        assert any("Spring Street" in line for line in lines)
        assert "\033[" not in "".join(lines)  # plain: it pipes


class TestRouteSummary:
    def test_the_header_summary(self):
        route = fake_route("car", distance=11700.0, duration=800.0)
        assert mu.route_summary(route, "en") == "7.3 mi · 13m · driving"
        # French takes metric from the language alone; the duration's
        # unit letters stay untranslated, the profile word does not.
        assert mu.route_summary(route, "fr") == "11.7 km · 13m · en voiture"

    def test_hours_are_split_out(self):
        assert mu._fmt_duration(60) == "1m"
        assert mu._fmt_duration(3600) == "1h 00m"
        assert mu._fmt_duration(4920) == "1h 22m"

    def test_short_distances_do_not_pretend_to_precision(self):
        assert mu._fmt_distance(240, "fr") == "240 m"
        assert mu._fmt_distance(2400, "fr") == "2.4 km"
        assert mu._fmt_distance(240, "en") == "787 ft"
        assert mu._fmt_distance(24000, "en") == "14.9 mi"

    def test_the_profile_word_is_localized_but_the_units_are_not(self):
        for profile, word in (("car", "driving"), ("bike", "cycling"),
                              ("foot", "walking")):
            summary = mu.route_summary(fake_route(profile), "en")
            assert summary.endswith(word)
            assert " mi · " in summary

    def test_no_route_is_no_summary(self):
        assert mu.route_summary(None, "en") == ""

    def test_the_note_says_what_the_router_is_doing(self):
        st = routes()
        assert mu.route_note(st) == ""
        st.status = "pending"
        assert mu.route_note(st) == "routing…"
        st.status = "none"
        assert mu.route_note(st) == "no route"
        st.status = "error"
        assert mu.route_note(st) == "directions unavailable"


# ---------------------------------------------------------------------------
# The `?` panel
# ---------------------------------------------------------------------------
LANGS = sorted(_maps_i18n._STRINGS)


def panel_lines(panel):
    """The panel's rows, without their cursor addressing or colour."""
    return [strip(row) for row in re.split(r"\033\[\d+;\d+H", panel)[1:]]


class TestHelpPanel:
    def test_it_lists_every_key_that_does_something(self):
        text = "".join(panel_lines(mu.help_overlay(80, 40, "en")))
        for mark, key in [e for e in mu.HELP_KEYS if e]:
            assert mark in text
            assert _maps_i18n._STRINGS["en"][key] in text

    def test_the_frame_carries_the_way_out(self):
        lines = panel_lines(mu.help_overlay(80, 40, "en"))
        assert "keys" in lines[0]
        assert "esc close" in lines[-1]

    def test_the_glyph_legend_appears_when_there_is_room(self):
        tall = "".join(panel_lines(mu.help_overlay(80, 40, "en")))
        short = "".join(panel_lines(mu.help_overlay(80, 24, "en")))
        for glyph, _key in mu.HELP_GLYPHS:
            assert glyph in tall
        assert "airport" not in short          # dropped first, not squeezed

    def test_attribution_is_imported_never_retyped(self):
        text = "".join(panel_lines(mu.help_overlay(80, 40, "en")))
        assert mu.TILE_ATTRIBUTION in text
        assert mu.ELEV_ATTRIBUTION in text
        assert mu.ROUTE_ATTRIBUTION not in text
        with_route = "".join(panel_lines(mu.help_overlay(80, 40, "en", True)))
        assert mu.ROUTE_ATTRIBUTION in with_route

    @pytest.mark.parametrize("rows", [12, 14, 20, 24, 40])
    @pytest.mark.parametrize("lang", LANGS)
    def test_it_never_overflows_the_terminal(self, rows, lang):
        # Degradation is deterministic and never scrolls: a panel that
        # scrolls is a panel you have to operate.
        panel = mu.help_overlay(80, rows, lang, route=True)
        if not panel:
            # Giving up entirely is a legal rung, but only when the
            # terminal really is too short for the smallest form.
            assert rows <= 14, (lang, rows)
            return
        lines = panel_lines(panel)
        assert len(lines) <= rows - 2, (lang, rows, len(lines))
        for line in lines:
            assert visible_len(line) <= 80, (lang, rows, line)

    def test_a_narrow_terminal_narrows_the_panel(self):
        for cols in (30, 40, 80, 200):
            lines = panel_lines(mu.help_overlay(cols, 40, "en"))
            for line in lines:
                assert visible_len(line) <= cols

    def test_a_terminal_too_short_for_the_panel_gets_none(self):
        assert mu.help_overlay(80, 8, "en") == ""
