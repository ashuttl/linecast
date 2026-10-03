"""Startup deadlines and cancellation must also let the interpreter exit."""

import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest


SETUP = """
import threading
from datetime import datetime
from linecast.weather import live

live._FETCH_CEILING = 0.2
live.reverse_geocode = lambda *a, **k: ("Delhi", "IN", {})
live.fetch_forecast = lambda *a, **k: {"v": 1}
live.fetch_aqi = lambda *a, **k: {"aqi": 1}
live.fetch_historical = lambda *a, **k: "history"
live.fetch_alerts = lambda *a, **k: []
live.fetch_observation = lambda *a, **k: None
live.local_now = lambda data: datetime.now()

started = threading.Event()
def stuck(*a, **k):
    started.set()
    threading.Event().wait()
"""


def _run(code):
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
    # A subprocess catches executor shutdown joins that an in-process test
    # misses. No real network is used, including in the child.
    return subprocess.run(
        [sys.executable, "-c", SETUP + textwrap.dedent(code)],
        env=env, capture_output=True, text=True, timeout=5,
    )


@pytest.mark.parametrize("provider, missing", [
    ("fetch_alerts", "alerts"),
    ("fetch_aqi", "aqi"),
    ("fetch_historical", "historical"),
    ("fetch_forecast", "data"),
    ("reverse_geocode", "geocode"),
])
def test_deadline_preserves_completed_results_and_exits(provider, missing):
    proc = _run(f"""
        live.{provider} = stuck
        result = live.gather(28.61, 77.21, "IN",
                             live.WeatherRuntime.defaults(), geo_label="Delhi")
        assert started.is_set()
        assert result["data"] == {None if missing == 'data' else {'v': 1}!r}
        assert result["aqi"] == {None if missing == 'aqi' else {'aqi': 1}!r}
        assert result["historical"] == {None if missing == 'historical' else 'history'!r}
        assert result["name"] == "Delhi"
        assert result["country_code"] == "IN"
        assert result["alerts"] == []
    """)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == proc.stderr == ""


@pytest.mark.parametrize("mode", ["--print", "--json", "--prose"])
def test_ctrl_c_exits_without_traceback_or_waiting_for_providers(mode):
    proc = _run(f"""
        import concurrent.futures
        import sys

        sys.argv = ["weather-dev", "--location", "delhi", "--lang", "hi", {mode!r}]
        sys.stdout.isatty = lambda: True
        # place_for asks _location for the place when it is called
        from linecast import _location
        _location.resolve_location = lambda *a, **k: (28.61, 77.21, "IN", "Delhi")
        _location.country_for_defaults = lambda *a: ""
        live.fetch_forecast = stuck

        def interrupt_wait(self, timeout=None):
            assert started.wait(1)
            raise KeyboardInterrupt

        concurrent.futures.Future.result = interrupt_wait
        live.main()
    """)
    assert proc.returncode == 130, proc.stderr
    assert proc.stderr == ""
    # text=True translates the spinner's carriage return to a newline.
    assert proc.stdout == ("\n\x1b[K" if mode == "--print" else "")
