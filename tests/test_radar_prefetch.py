"""The radar prefetcher stands down when the process is leaving.

Its pool threads are joined at interpreter exit, and a queued frame
load would otherwise run to completion before the join saw the
sentinel.  No network: _safe_load is replaced with a sleep.
"""

import datetime
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast import _radar_frames as rf
from linecast._radar_sources import Frame

_src = str(Path(__file__).resolve().parent.parent / "src")


def _frames(n):
    t0 = datetime.datetime(2026, 8, 23, 12, tzinfo=datetime.timezone.utc)
    return [Frame(t0 + datetime.timedelta(minutes=5 * i), i) for i in range(n)]


class TestStandDown:
    def test_queued_frames_are_skipped(self, monkeypatch):
        loaded = []

        def slow(bbox, gw, hc, frame, layer="radar"):
            time.sleep(0.05)
            loaded.append(frame.token)
            return True

        monkeypatch.setattr(rf, "_safe_load", slow)
        monkeypatch.setattr(rf._radar_warnings, "covers", lambda bbox: False)
        monkeypatch.setattr(rf, "_prefetch_key", None)
        rf._ensure_prefetch((0, 0, 1, 1), 80, 20, _frames(40))
        time.sleep(0.12)
        rf.stand_down()
        t0 = time.monotonic()
        seen = -1
        while time.monotonic() - t0 < 2.0:
            if len(loaded) == seen:
                break  # nothing landed for 150 ms: the queue is idle
            seen = len(loaded)
            time.sleep(0.15)
        # in flight when we stood down: at most the four pool loads, each
        # 50 ms — the rest of the window never starts
        assert time.monotonic() - t0 < 0.6
        assert len(loaded) < 40
        assert rf._prefetch_key is None

    def test_bumps_generation_under_the_lock(self, monkeypatch):
        monkeypatch.setattr(rf, "_prefetch_key", ("some", "key"))
        before = rf._prefetch_gen
        rf.stand_down()
        assert rf._prefetch_gen == before + 1
        assert rf._prefetch_key is None

    def test_interpreter_exit_does_not_drain_the_window(self):
        """40 queued frames of 300 ms on four workers is three seconds of
        drain; the process must not wait for it."""
        child = textwrap.dedent("""
            import datetime, time
            from linecast import _radar_frames as rf
            from linecast._radar_sources import Frame
            rf._safe_load = lambda *a, **k: time.sleep(0.3) or True
            rf._radar_warnings.covers = lambda bbox: False
            t0 = datetime.datetime(2026, 8, 23, tzinfo=datetime.timezone.utc)
            frames = [Frame(t0 + datetime.timedelta(minutes=5 * i), i)
                      for i in range(40)]
            rf._ensure_prefetch((0, 0, 1, 1), 80, 20, frames)
            time.sleep(0.5)
        """)
        t0 = time.monotonic()
        proc = subprocess.run([sys.executable, "-c", child], timeout=20,
                              env=dict(os.environ, PYTHONPATH=_src))
        elapsed = time.monotonic() - t0
        assert proc.returncode == 0
        assert elapsed < 2.0, elapsed


class TestStaticRender:
    """A one-shot render shows one frame; it must not warm the window."""

    def test_static_mode_does_not_prefetch(self, monkeypatch):
        from linecast import radar

        class Src:
            theme = None
            attribution = label = "stub"

            def current_frames(self):
                return _frames(3)

            def frame_rgba(self, bbox, gw, hc, frame):
                return 4, 4, bytearray(4 * 4 * 4)

        calls = []
        monkeypatch.setattr(rf, "_source", Src())
        monkeypatch.setattr(rf._radar_warnings, "covers", lambda bbox: False)
        monkeypatch.setattr(radar, "_ensure_prefetch",
                            lambda *a, **k: calls.append(a))
        monkeypatch.setattr(radar, "get_terminal_size", lambda: (40, 12))
        radar.render_radar(43.7, -70.3, "Westbrook", 10.0, play_frame=0,
                           playing=False, block=True)
        assert calls == []
        radar.render_radar(43.7, -70.3, "Westbrook", 10.0, play_frame=0,
                           playing=True, block=False)
        assert len(calls) == 1
