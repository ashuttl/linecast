"""Snapshot tests for rendering output.

These tests render with fixed data, fixed terminal size, and a pinned clock,
then compare the ANSI-stripped text output against a stored reference.  If the
reference file doesn't exist yet, the first run creates it (test passes).

To regenerate snapshots after an intentional rendering change:
    rm tests/snapshots/*.txt && pytest tests/test_render_snapshots.py
"""

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

FIXTURES = Path(__file__).parent / "fixtures"
SNAPSHOTS = Path(__file__).parent / "snapshots"

# Ensure the theme system doesn't try to query the terminal
os.environ.setdefault("LINECAST_THEME", "classic")

# Fixed "now" for deterministic rendering
FIXED_NOW = datetime(2026, 3, 5, 14, 30)


def _strip_ansi(text):
    """Remove all ANSI escape sequences for stable comparison."""
    text = re.sub(r"\x1b\][^\x1b]*\x1b\\", "", text)  # OSC
    text = re.sub(r"\x1b\[[^a-zA-Z]*[a-zA-Z]", "", text)  # CSI
    text = re.sub(r"\x1b[()][0-9A-Za-z]", "", text)  # charset
    return text


def _load_fixture(name):
    return json.loads((FIXTURES / name).read_text())


def _read_snapshot(name):
    path = SNAPSHOTS / name
    if path.exists():
        return path.read_text()
    return None


def _write_snapshot(name, content):
    SNAPSHOTS.mkdir(exist_ok=True)
    (SNAPSHOTS / name).write_text(content)


def _compare_or_create(snapshot_name, actual):
    """Compare against stored snapshot, or create it on first run."""
    stored = _read_snapshot(snapshot_name)
    if stored is None:
        _write_snapshot(snapshot_name, actual)
        return  # first run -- snapshot created
    assert actual == stored, (
        f"Snapshot mismatch for {snapshot_name}. "
        f"Delete tests/snapshots/{snapshot_name} and re-run to update."
    )


def _weather_render(cols, rows, runtime, fixture="open_meteo_forecast.json",
                     location_name="Toronto, Ontario"):
    """Render weather dashboard with mocked terminal size and clock."""
    from linecast.weather import render_from_data

    data = _load_fixture(fixture)

    with patch("linecast.weather.get_terminal_size", return_value=(cols, rows)), \
         patch("linecast.weather._local_now_for_data", return_value=FIXED_NOW), \
         patch("linecast._weather_hourly._local_now_for_data", return_value=FIXED_NOW):
        output, _ = render_from_data(
            data, alerts=[], runtime=runtime,
            location_name=location_name,
        )
    return _strip_ansi(output)


# -----------------------------------------------------------------------
# Weather rendering snapshots
# -----------------------------------------------------------------------
class TestWeatherSnapshot:
    """Render the weather dashboard with fixture data and compare output."""

    def _make_runtime(self, **overrides):
        from linecast._runtime import WeatherRuntime
        defaults = dict(
            live=False, emoji=True, lang="en", oneline=False,
            celsius=False, metric=False, shading=False,
        )
        defaults.update(overrides)
        return WeatherRuntime(**defaults)

    def test_weather_80x24(self):
        output = _weather_render(80, 24, self._make_runtime())
        _compare_or_create("weather_80x24.txt", output)

    def test_weather_120x40(self):
        output = _weather_render(120, 40, self._make_runtime())
        _compare_or_create("weather_120x40.txt", output)

    def test_weather_metric_french(self):
        runtime = self._make_runtime(lang="fr", celsius=True, metric=True)
        output = _weather_render(80, 24, runtime)
        _compare_or_create("weather_metric_fr_80x24.txt", output)


# -----------------------------------------------------------------------
# Sunshine rendering snapshot
# -----------------------------------------------------------------------
class TestSunshineSnapshot:
    def test_sunshine_80x24(self):
        from linecast.sunshine import render
        from linecast._runtime import RuntimeConfig

        runtime = RuntimeConfig(live=False, emoji=True, lang="en", oneline=False)
        with patch("linecast.sunshine.get_terminal_size", return_value=(80, 24)):
            output = render(
                lat=43.7, lng=-79.4, doy=64,
                now_hour=14.5, fullscreen=False,
                runtime=runtime,
            )
        stripped = _strip_ansi(output)
        _compare_or_create("sunshine_80x24.txt", stripped)
