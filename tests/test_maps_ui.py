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

from linecast import _color
from linecast import _maps_ui as mu
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
