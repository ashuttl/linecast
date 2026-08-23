"""Snapshot tests for rendering output.

These tests render with fixed data, fixed terminal size, and a pinned clock,
then compare the ANSI-stripped text output against a stored reference.  If the
reference file doesn't exist yet, the first run creates it (test passes).

To regenerate snapshots after an intentional rendering change:
    rm tests/snapshots/*.txt && pytest tests/test_render_snapshots.py
"""

import json
import math
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
        # Pin the UTC offset so the snapshot is hermetic. solar_times() reads
        # the host's live offset via _tz_offset_hours(), which otherwise makes
        # this test depend on both the machine's timezone and the current DST
        # state. doy=64 (March 5) is in standard time for US Eastern, so -5.
        with patch("linecast.sunshine.get_terminal_size", return_value=(80, 24)), \
             patch("linecast.sunshine._tz_offset_hours", return_value=-5):
            output = render(
                lat=43.7, lng=-79.4, doy=64,
                now_hour=14.5, fullscreen=False,
                runtime=runtime,
            )
        stripped = _strip_ansi(output)
        _compare_or_create("sunshine_80x24.txt", stripped)


# -----------------------------------------------------------------------
# Moon rendering snapshot
# -----------------------------------------------------------------------
class TestMoonSnapshot:
    # A fixed-offset zone keeps the rise/set times hermetic regardless of
    # the host machine's timezone. 2026-03-05 is a waning full-ish moon.
    def _now(self):
        from datetime import timedelta, timezone
        return datetime(2026, 3, 5, 14, 30,
                        tzinfo=timezone(timedelta(hours=-5)))

    def _render(self, lang):
        from linecast.moon import render
        from linecast._runtime import RuntimeConfig

        runtime = RuntimeConfig(live=False, emoji=True, lang=lang, oneline=False)
        with patch("linecast.moon.get_terminal_size", return_value=(80, 24)):
            output = render(self._now(), 43.7, -79.4, runtime)
        return _strip_ansi(output)

    def test_moon_80x24(self):
        _compare_or_create("moon_80x24.txt", self._render("en"))

    def test_moon_80x24_french(self):
        _compare_or_create("moon_fr_80x24.txt", self._render("fr"))

    def test_moon_scrubbed_shows_simulated_time(self):
        """Scrubbing must label the simulated moment and the way back."""
        from linecast.moon import render
        from linecast._runtime import RuntimeConfig

        runtime = RuntimeConfig(live=False, emoji=True, lang="en", oneline=False)
        with patch("linecast.moon.get_terminal_size", return_value=(80, 24)):
            output = _strip_ansi(
                render(self._now(), 43.7, -79.4, runtime, offset_minutes=2880)
            )
        assert "Thu Mar 5" in output
        assert "space to return to now" in output
        assert "Up now" not in output

    def test_moon_southern_hemisphere_mirrors_disc(self):
        """A waxing moon lights the east limb in the north, west in the south."""
        from linecast._framebuffer import Framebuffer
        from linecast.moon import _draw_moon_disc

        def side_brightness(southern):
            fb = Framebuffer(40, 20)
            _draw_moon_disc(fb, 20, 20, 15, 0.25, southern)
            left = sum(sum(fb.fb[20][x]) for x in range(6, 18))
            right = sum(sum(fb.fb[20][x]) for x in range(23, 35))
            return left, right

        n_left, n_right = side_brightness(southern=False)
        s_left, s_right = side_brightness(southern=True)
        assert n_right > n_left
        assert s_left > s_right
        assert (n_left, n_right) == (s_right, s_left)


# -----------------------------------------------------------------------
# Maps rendering snapshots
# -----------------------------------------------------------------------
class TestMapsSnapshot:
    """Both map modes over synthetic data.

    No network: the elevation and street-tile fetchers are replaced by
    hand-built data, so what is pinned is everything downstream of the
    fetch — the composer, the marks, the labels, the header and the
    footer.

    These snapshots keep their escape sequences (written `\\e`) rather
    than stripping them. On a map the colour *is* the output: strip it
    and a water fill and a park fill are both a space.
    """

    LAT, LON = 43.66, -70.26
    COLS, ROWS = 80, 24

    def _runtime(self):
        from linecast._runtime import RuntimeConfig
        return RuntimeConfig(live=False, emoji=True, lang="en",
                             oneline=False)

    def _render(self, view, fetch_patch, zoom=0.02):
        from linecast import _color, _maps_style, _theme, maps
        stack = [
            patch("linecast.maps.get_terminal_size",
                  return_value=(self.COLS, self.ROWS)),
            patch.object(_color, "_COLOR_MODE", "truecolor"),
            patch.object(_maps_style, "color_mode", lambda: "truecolor"),
            patch.object(_theme, "theme_bg", (14, 15, 18)),
            patch.dict(maps.compose_map.__globals__,
                       {"color_mode": lambda: "truecolor"}),
            fetch_patch,
        ]
        for ctx in stack:
            ctx.__enter__()
        try:
            out = maps.render_map(
                self.LAT, self.LON, "Portland, Maine", zoom,
                runtime=self._runtime(), view=view)
        finally:
            for ctx in reversed(stack):
                ctx.__exit__(None, None, None)
        return out.replace("\033", "\\e")

    def test_maps_terrain_80x24(self):
        # A synthetic shoreline: elevation rises west to east and the
        # western third is below sea level, so the snapshot carries the
        # bathy ramp, the hypso ramp and a derived coastline.
        from linecast import maps

        def elevation(bbox, gw, hc, block):
            fine = [[(x - gw * 1.4) * 2.0 for x in range(gw * 2)]
                    for _ in range(hc * 4)]
            grid = [[(x - gw * 0.7) * 4.0 for x in range(gw)]
                    for _ in range(hc * 2)]
            # no tile water: the snapshot is the elevation-only map
            return maps.TerrainView(grid, maps._coast_dots(fine, gw, hc),
                                    None, None, None)

        output = self._render(
            "terrain", patch.object(maps, "_get_elevation", elevation))
        _compare_or_create("maps_terrain_80x24.txt", output)

    def test_maps_globe_80x24(self):
        # Planet-scale zoom hands terrain to the orthographic globe.  A
        # synthetic hemisphere — dry land east of the centre meridian,
        # deep sea west — pins the disk, the limb falloff, the
        # atmosphere rim and the space around the planet, while the
        # vendored city data pins the projected labels.
        from linecast import _globe, maps

        def synth(lls):
            return [[None if ll is None
                     else (1200.0 if ll[1] > self.LON else -3200.0)
                     for ll in row] for row in lls]

        def get_globe(lat0, lon0, zoom, gw, hc, block):
            lls, zs, rhos = _globe.geometry(lat0, lon0, zoom, gw, hc * 2)
            flls, _fz, _fr = _globe.geometry(lat0, lon0, zoom,
                                             gw * 2, hc * 4)
            return _globe.GlobeView(
                synth(lls), maps._coast_dots(synth(flls), gw, hc), zs,
                _globe.atmosphere(rhos, zoom, hc * 2), None,
                _globe.border_layer(lat0, lon0, zoom, gw, hc,
                                    maps.BORDER_STROKE))

        output = self._render(
            "terrain", patch.object(maps, "_get_globe", get_globe),
            zoom=125.0)
        _compare_or_create("maps_globe_80x24.txt", output)

        # the street register rides the same sphere: flat fills, the
        # same coastline, borders and labels — pinned separately
        output = self._render(
            "street", patch.object(maps, "_get_globe", get_globe),
            zoom=125.0)
        _compare_or_create("maps_globe_street_80x24.txt", output)

    @staticmethod
    def _tile_xy(lon, lat, z, tx, ty, extent=4096):
        """(lon, lat) -> tile-local coordinates: the projector, inverted,
        so the synthetic geometry actually lands in the view."""
        n = 1 << z
        wx = (lon + 180.0) / 360.0
        sin_lat = math.sin(math.radians(lat))
        wy = 0.5 - math.log((1 + sin_lat) / (1 - sin_lat)) / (4 * math.pi)
        return (round((wx * n - tx) * extent), round((wy * n - ty) * extent))

    def test_maps_street_80x24(self):
        # Hand-encoded tiles placed against the actual view: water over
        # its western half (so the coastline runs down the middle) and a
        # primary road straight across it.
        from linecast import maps
        from test_maps_streets import (
            classed, polyline, rect, tagged_line, tile,
        )

        def street(bbox, gw, hc, block, lang="en", reserved=()):
            from linecast import _maps_streets as st
            band = st.style.band_for(st.style.z_eff(bbox, hc))
            minlon, minlat, maxlon, maxlat = bbox
            midlon = (minlon + maxlon) / 2
            midlat = (minlat + maxlat) / 2
            pad = (maxlon - minlon)
            tiles = {}
            for key in st.tiles_for_bbox(bbox, 12):
                z, tx, ty = key
                def xy(lon, lat):
                    return self._tile_xy(lon, lat, z, tx, ty)
                west = xy(minlon - pad, maxlat + pad)
                east = xy(midlon, minlat - pad)
                road_w = xy(minlon - pad, midlat)
                road_e = xy(maxlon + pad, midlat)
                tiles[key] = tile(
                    classed("water", rect(west[0], west[1], east[0], east[1]),
                            "lake"),
                    tagged_line("transportation",
                                polyline(road_w, road_e),
                                {"class": "primary"}),
                )
            return st.build_street_view(bbox, gw, hc, tiles, band, lang,
                                        reserved)

        output = self._render(
            "street", patch.object(maps, "_get_street", street))
        _compare_or_create("maps_street_80x24.txt", output)
