"""The child interpreter the live map builds its flat views on
(maps.worker): the pipe protocol, the state the child takes up, and the
loaders falling through to building in-process when there is no child.
"""

import os
import pickle
import threading

import pytest

from linecast.maps import loaders, worker
from linecast.terminal import textwidth, theme


class TestTheProtocol:
    def _serve(self):
        """A serve() on in-process pipes; returns (request, close)."""
        req_r, req_w = os.pipe()
        rep_r, rep_w = os.pipe()
        inp = os.fdopen(req_r, "rb")
        out = os.fdopen(rep_w, "wb", buffering=0)
        t = threading.Thread(target=worker.serve, args=(inp, out), daemon=True)
        t.start()
        to_child = os.fdopen(req_w, "wb")
        from_child = os.fdopen(rep_r, "rb")
        lock = threading.Lock()
        state = worker.snapshot()

        def request(rid, kind, *args):
            worker._write(to_child, lock, (rid, kind, args, state))
            return worker._read(from_child)

        def close():
            to_child.close()
            t.join(2.0)
            from_child.close()
            out.close()
        return request, close

    def test_a_build_is_answered_under_its_own_id(self):
        request, close = self._serve()
        try:
            assert request(7, "echo", 1, "two") == (7, True, (1, "two"))
            assert request(8, "echo") == (8, True, ())
        finally:
            close()

    def test_a_failed_build_comes_back_as_its_message(self):
        request, close = self._serve()
        try:
            rid, ok, text = request(1, "no such build")
            assert (rid, ok) == (1, False)
            assert "no such build" in text
        finally:
            close()

    def test_the_child_exits_when_the_pipe_closes(self):
        req_r, req_w = os.pipe()
        rep_r, rep_w = os.pipe()
        inp = os.fdopen(req_r, "rb")
        out = os.fdopen(rep_w, "wb", buffering=0)
        t = threading.Thread(target=worker.serve, args=(inp, out), daemon=True)
        t.start()
        os.close(req_w)
        t.join(2.0)
        assert not t.is_alive()
        os.close(rep_r)
        out.close()

    def test_a_frame_is_a_length_and_a_pickle(self):
        r, w = os.pipe()
        wf, rf = os.fdopen(w, "wb"), os.fdopen(r, "rb")
        worker._write(wf, threading.Lock(), {"a": [1, 2]})
        wf.close()
        assert worker._read(rf) == {"a": [1, 2]}
        assert worker._read(rf) is None      # EOF, not an error
        rf.close()


class TestTheChild:
    def test_the_real_child_builds_and_stops(self, monkeypatch):
        monkeypatch.setenv("LINECAST_MAPS_WORKER", "1")   # off for the suite
        b = worker.Builder()
        b.start()
        try:
            assert b.alive()
            assert b.run("echo", "round", "trip") == ("round", "trip")
            with pytest.raises(RuntimeError):
                b.run("nothing of the kind")
        finally:
            b.stop()
        assert not b.alive()
        with pytest.raises(worker.Unavailable):
            b.run("echo")

    def test_a_disabled_worker_never_starts(self, monkeypatch):
        monkeypatch.setenv("LINECAST_MAPS_WORKER", "0")
        b = worker.Builder()
        b.start()
        assert not b.alive()
        with pytest.raises(worker.Unavailable):
            b.run("echo")

    def test_the_child_is_told_what_the_terminal_said(self, monkeypatch):
        # the child's stdout is a pipe and its size in pixels nobody's:
        # asked itself it would bake the no-colour palette into fills a
        # sixth too wide.  It is given the parent's answers instead.
        from linecast.terminal import color, framebuffer
        monkeypatch.delenv("LINECAST_COLOR", raising=False)
        monkeypatch.delenv("LINECAST_CELL_ASPECT", raising=False)
        monkeypatch.setattr(color, "_COLOR_MODE", "256")
        monkeypatch.setattr(framebuffer, "cell_aspect",
                            lambda fallback=2.0: 1.6)
        env = worker.child_env()
        assert env["LINECAST_COLOR"] == "256"
        assert float(env["LINECAST_CELL_ASPECT"]) == pytest.approx(1.6)
        assert env["PATH"] == os.environ["PATH"]    # the rest is inherited

    def test_the_snapshot_pickles(self):
        snap = worker.snapshot()
        back = pickle.loads(pickle.dumps(snap, protocol=pickle.HIGHEST_PROTOCOL))
        assert back["theme"] == snap["theme"]
        assert back["widths"] == snap["widths"]


class TestWhatTheChildTakesUp:
    def test_the_theme_is_adopted_hooks_and_all(self, monkeypatch):
        before = theme.state()
        ran = []
        monkeypatch.setattr(theme, "_reload_hooks", [lambda: ran.append(1)])
        gen = theme.generation
        try:
            fg, bg, ansi, _avail, _legacy = before
            other = ((fg[0] ^ 1,) + tuple(fg[1:]), bg, ansi, True, False)
            assert theme.adopt(other) is True
            assert theme.theme_fg == other[0]
            assert theme.generation == gen + 1
            assert ran == [1]
            # the same state again changes nothing
            assert theme.adopt(other) is False
            assert ran == [1]
        finally:
            theme.adopt(before)

    def test_the_text_widths_are_adopted(self):
        before = textwidth.state()
        try:
            textwidth.adopt(({"emoji": 2}, True))
            assert textwidth.state() == ({"emoji": 2}, True)
            assert textwidth._CALIBRATED is True
        finally:
            textwidth.adopt(before)


class TestTheLoadersDoor:
    def test_a_build_runs_here_without_a_child(self, monkeypatch):
        monkeypatch.setattr(worker, "alive", lambda: False)
        monkeypatch.setitem(loaders._BUILDS, "probe", lambda *a: ("here",) + a)
        assert loaders._build("probe", 1) == ("here", 1)
        assert loaders.builds_off_thread() is False

    def test_a_build_goes_to_the_child_when_there_is_one(self, monkeypatch):
        monkeypatch.setattr(worker, "alive", lambda: True)
        monkeypatch.setattr(worker, "run", lambda kind, *a: ("there", kind) + a)
        monkeypatch.setitem(loaders._BUILDS, "probe", lambda *a: ("here",) + a)
        assert loaders._build("probe", 1) == ("there", "probe", 1)
        assert loaders.builds_off_thread() is True

    def test_a_child_that_goes_is_not_an_error(self, monkeypatch):
        monkeypatch.setattr(worker, "alive", lambda: True)

        def gone(kind, *a):
            raise worker.Unavailable()
        monkeypatch.setattr(worker, "run", gone)
        monkeypatch.setitem(loaders._BUILDS, "probe", lambda *a: ("here",) + a)
        assert loaders._build("probe", 2) == ("here", 2)

    def test_the_pure_builds_are_the_ones_on_the_door(self):
        assert loaders._BUILDS == {"terrain": loaders.build_terrain,
                                   "street": loaders.build_street}
