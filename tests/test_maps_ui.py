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
        st = self._listed()
        assert st.sel == 0
        st.handle('fwd', 43.6, -70.2, 12)
        assert st.sel == 1
        st.handle('back', 43.6, -70.2, 12)
        st.handle('back', 43.6, -70.2, 12)
        assert st.sel == 2

    def test_the_map_does_not_move_until_enter(self):
        st = self._listed()
        st.handle('fwd', 43.6, -70.2, 12)
        assert st.chosen is None

    def test_enter_commits_the_highlighted_result_and_closes(self):
        st = self._listed()
        st.handle('fwd', 43.6, -70.2, 12)
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


def fake_route(profile="car", distance=18800.0, duration=1420.0,
               end=LIGHT):
    return Route([(-70.371, 43.677), (end[1], end[0])],
                 distance, duration, [], profile)


def routes(answer=None, error=None):
    """A RouteState whose client answers from a canned result."""
    calls = []

    def fetch(profile, origin, dest):
        calls.append((profile, origin, dest))
        if error is not None:
            raise error
        return answer if answer is not None else fake_route(profile)

    st = mu.RouteState(refresh=lambda: None, fetch=fetch)
    st.calls = calls
    return st


class TestDirections:
    def test_pressing_d_with_nothing_selected_asks_for_a_destination(self):
        st = routes()
        assert st.press(HOME) == "search"
        assert st.calls == []

    def test_pressing_d_with_a_selection_routes_to_it(self):
        st = routes()
        st.select(*LIGHT, "Portland Head Light")
        assert st.press(HOME) is True
        FakeThread.started[-1].run_now()
        assert st.calls == [("car", HOME, LIGHT)]
        assert st.route.distance_m == 18800.0
        assert st.status == ""

    def test_pressing_d_again_cycles_the_profile(self):
        # One mental model: d = directions to what's selected; press
        # again to change how you're travelling.
        st = routes()
        st.select(*LIGHT)
        st.press(HOME)
        FakeThread.started[-1].run_now()
        for expected in ("bike", "foot", "car"):
            st.press(HOME)
            FakeThread.started[-1].run_now()
            assert st.profile == expected
            assert st.calls[-1][0] == expected

    def test_a_new_selection_re_aims_rather_than_cycling(self):
        st = routes()
        st.select(*LIGHT)
        st.press(HOME)
        FakeThread.started[-1].run_now()
        st.select(44.0, -69.0, "Somewhere else")
        st.press(HOME)
        FakeThread.started[-1].run_now()
        assert st.profile == "car"
        assert st.calls[-1][2] == (44.0, -69.0)

    def test_a_press_while_a_request_is_in_flight_does_not_double_fetch(self):
        st = routes()
        st.select(*LIGHT)
        st.press(HOME)
        assert st.press(HOME) is True       # the key visibly did something
        assert len(FakeThread.started) == 1
        assert st.status == "pending"

    def test_the_throttle_never_runs_in_the_keyboard_thread(self):
        # The client's own throttle sleeps; the press must return before
        # anything is fetched.
        st = routes()
        st.select(*LIGHT)
        st.press(HOME)
        assert st.calls == []
        FakeThread.started[-1].run_now()
        assert st.calls

    def test_no_route_and_unreachable_read_differently(self):
        for error, status in ((NoRoute("nope"), "none"),
                              (RouteUnavailable("down"), "error")):
            st = routes(error=error)
            st.select(*LIGHT)
            st.press(HOME)
            FakeThread.started[-1].run_now()
            assert st.status == status
            assert st.route is None

    def test_clearing_drops_the_route_and_any_late_reply(self):
        st = routes()
        st.select(*LIGHT)
        st.press(HOME)
        st.clear()
        FakeThread.started[-1].run_now()
        assert st.route is None
        assert st.dest is None
        assert st.status == ""


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
