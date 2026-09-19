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
from linecast import weather

weather._FETCH_CEILING = 0.2
weather._reverse_geocode = lambda *a, **k: ("Delhi", "IN", {})
weather.fetch_forecast = lambda *a, **k: {"v": 1}
weather.fetch_aqi = lambda *a, **k: {"aqi": 1}
weather.fetch_historical = lambda *a, **k: "history"
weather.fetch_alerts = lambda *a, **k: []
weather._local_now_for_data = lambda data: datetime.now()

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
    ("_reverse_geocode", "geocode"),
])
def test_deadline_preserves_completed_results_and_exits(provider, missing):
    proc = _run(f"""
        weather.{provider} = stuck
        result = weather.gather(28.61, 77.21, "IN",
                                weather.WeatherRuntime.defaults(), geo_label="Delhi")
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


@pytest.mark.parametrize("mode", ["--print", "--json"])
def test_ctrl_c_exits_without_traceback_or_waiting_for_providers(mode):
    proc = _run(f"""
        import concurrent.futures
        import sys

        sys.argv = ["weather-dev", "--location", "delhi", "--lang", "hi", {mode!r}]
        sys.stdout.isatty = lambda: True
        weather.resolve_location = lambda *a, **k: (28.61, 77.21, "IN", "Delhi")
        weather.country_for_defaults = lambda *a: ""
        weather.fetch_forecast = stuck

        def interrupt_wait(self, timeout=None):
            assert started.wait(1)
            raise KeyboardInterrupt

        concurrent.futures.Future.result = interrupt_wait
        weather.main()
    """)
    assert proc.returncode == 130, proc.stderr
    assert proc.stderr == ""
    # text=True translates the spinner's carriage return to a newline.
    assert proc.stdout == ("\n\x1b[K" if mode == "--print" else "")
