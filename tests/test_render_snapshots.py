"""Snapshot tests for rendering output.

These tests render with fixed data, fixed terminal size, and a pinned clock,
then compare the ANSI-stripped text output against a stored reference
(conftest.assert_snapshot).  A missing reference is written by the first
run, and fails under CI.

To regenerate snapshots after an intentional rendering change:
    rm tests/snapshots/*.txt && pytest tests/test_render_snapshots.py

The text alone is compared here, except on the maps, where colour is the
picture. scripts/golden.py checks every byte, colour included.
"""

import json
import math
import re
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from conftest import assert_snapshot
from linecast.maps import paint as _paint
from linecast.maps import loaders as _loaders


FIXTURES = Path(__file__).parent / "fixtures"

# Fixed "now" for deterministic rendering
FIXED_NOW = datetime(2026, 3, 5, 14, 30)


def _strip_ansi(text):
    """Remove all ANSI escape sequences for stable comparison."""
    text = re.sub(r"\x1b\][^\x1b]*\x1b\\", "", text)  # OSC
    text = re.sub(r"\x1b\[[^a-zA-Z]*[a-zA-Z]", "", text)  # CSI
    text = re.sub(r"\x1b[()][0-9A-Za-z]", "", text)  # charset
    return text


def _load_fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _weather_render(cols, rows, runtime, fixture="open_meteo_forecast.json",
                     location_name="Toronto, Ontario", historical=None):
    """Render weather dashboard with mocked terminal size and clock."""
    from linecast.weather.view import render_from_data

    data = _load_fixture(fixture)

    with patch("linecast.weather.view.get_terminal_size", return_value=(cols, rows)), \
         patch("linecast.weather.view.local_now", return_value=FIXED_NOW), \
         patch("linecast.weather.hourly.local_now", return_value=FIXED_NOW):
        output, _ = render_from_data(
            data, alerts=[], runtime=runtime,
            location_name=location_name, historical=historical,
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
            live=False, icons="emoji", lang="en", oneline=False,
            celsius=False, metric=False, shading=False,
        )
        defaults.update(overrides)
        return WeatherRuntime(**defaults)

    def test_weather_80x24(self):
        output = _weather_render(80, 24, self._make_runtime())
        assert_snapshot("weather_80x24.txt", output)

    def test_weather_120x40(self):
        output = _weather_render(120, 40, self._make_runtime())
        assert_snapshot("weather_120x40.txt", output)

    def _toronto_archive(self):
        # A typical Toronto year's extremes, in the fixture's units.
        from linecast.weather.historical import HistoricalAverages
        return HistoricalAverages(avg_high=41.2, avg_low=26.7, avg_precip=0.11,
                                  years=10, year_high=91.3, year_low=-3.6)

    def test_weather_80x24_climate(self):
        output = _weather_render(80, 24, self._make_runtime(temp_range="climate"),
                                 historical=self._toronto_archive())
        assert_snapshot("weather_80x24_climate.txt", output)

    def test_weather_auto_adapts_to_the_graph_height(self):
        # Reuse the runtime across resizes, as the live dashboard does.
        for live in (False, True):
            runtime = self._make_runtime(live=live)
            for rows, mode in ((24, "forecast"), (40, "climate"), (24, "forecast")):
                auto = _weather_render(80, rows, runtime, historical=self._toronto_archive())
                expected = _weather_render(
                    80, rows, self._make_runtime(live=live, temp_range=mode),
                    historical=self._toronto_archive(),
                )
                other = _weather_render(
                    80, rows, self._make_runtime(
                        live=live, temp_range="climate" if mode == "forecast" else "forecast"),
                    historical=self._toronto_archive(),
                )
                assert auto == expected
                assert auto != other

    def test_weather_80x24_climate_without_archive_is_the_forecast(self):
        # No archive answer: the graph falls back to the forecast's own range.
        output = _weather_render(80, 24, self._make_runtime(temp_range="climate"))
        assert_snapshot("weather_80x24.txt", output)

    def test_weather_80x24_world(self):
        output = _weather_render(80, 24, self._make_runtime(temp_range="world"))
        assert_snapshot("weather_80x24_world.txt", output)

    def test_weather_metric_french(self):
        runtime = self._make_runtime(lang="fr", celsius=True, metric=True)
        output = _weather_render(80, 24, runtime)
        assert_snapshot("weather_metric_fr_80x24.txt", output)

    def test_weather_metric_french_climate(self):
        runtime = self._make_runtime(lang="fr", celsius=True, metric=True,
                                     temp_range="climate")
        output = _weather_render(80, 24, runtime, historical=self._toronto_archive())
        assert_snapshot("weather_metric_fr_80x24_climate.txt", output)

# -----------------------------------------------------------------------
# Sunshine rendering snapshot
# -----------------------------------------------------------------------
class TestSunshineSnapshot:
    def test_sunshine_80x24(self):
        from linecast.sunshine.view import render
        from linecast._runtime import RuntimeConfig

        runtime = RuntimeConfig(live=False, icons="emoji", lang="en", oneline=False)
        # Pin the UTC offset so the snapshot is hermetic. solar_times() reads
        # the host's live offset via _tz_offset_hours(), which otherwise makes
        # this test depend on both the machine's timezone and the current DST
        # state. doy=64 (March 5) is in standard time for US Eastern, so -5.
        # The arc is drawn for the machine's year, which the declination
        # reads through _local_today; pin that too, or the glyphs drift
        # by a cell or two from one year to the next.
        with patch("linecast.sunshine.view.get_terminal_size", return_value=(80, 24)), \
             patch("linecast.sunshine.solar._tz_offset_hours", return_value=-5), \
             patch("linecast.sunshine.solar._local_today",
                   return_value=datetime(2026, 3, 5).date()):
            output = render(
                lat=43.7, lng=-79.4, doy=64,
                now_hour=14.5, fullscreen=False,
                runtime=runtime,
            )
        stripped = _strip_ansi(output)
        assert_snapshot("sunshine_80x24.txt", stripped)

    def test_sunshine_year_80x24(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from linecast.sunshine.year import render_year
        from linecast._runtime import RuntimeConfig

        runtime = RuntimeConfig(live=False, icons="emoji", lang="en", oneline=False)
        # A named zone rather than the host's: the year's per-day offsets
        # and the sun's placement then depend on nothing but the arguments.
        tz = ZoneInfo("America/Toronto")
        now = datetime(2026, 3, 5, 14, 30, tzinfo=tz)
        # The corner clock names the weekday only on a day that is not
        # the user's; pin the user's day to the rendered one.
        with patch("linecast.sunshine.year.get_terminal_size",
                   return_value=(80, 24)), \
             patch("linecast.sunshine.solar._local_today", return_value=now.date()):
            output = render_year(43.7, -79.4, now, runtime, tz=tz,
                                 location_label="Toronto")
        assert_snapshot("sunshine_year_80x24.txt", _strip_ansi(output))

    def test_sunshine_year_polar_80x24(self):
        """Longyearbyen in March: both polar seasons in one field."""
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from linecast.sunshine.year import render_year
        from linecast._runtime import RuntimeConfig

        runtime = RuntimeConfig(live=False, icons="emoji", lang="en", oneline=False)
        tz = ZoneInfo("Europe/Oslo")
        now = datetime(2026, 3, 5, 14, 30, tzinfo=tz)
        with patch("linecast.sunshine.year.get_terminal_size",
                   return_value=(80, 24)), \
             patch("linecast.sunshine.solar._local_today", return_value=now.date()):
            output = render_year(78.22, 15.65, now, runtime, tz=tz,
                                 location_label="Longyearbyen")
        assert_snapshot("sunshine_year_polar_80x24.txt", _strip_ansi(output))


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
        from linecast.moon.view import render
        from linecast._runtime import RuntimeConfig

        runtime = RuntimeConfig(live=False, icons="emoji", lang=lang, oneline=False)
        with patch("linecast.moon.view.get_terminal_size", return_value=(80, 24)):
            output = render(self._now(), 43.7, -79.4, runtime)
        return _strip_ansi(output)

    def test_moon_80x24(self):
        assert_snapshot("moon_80x24.txt", self._render("en"))

    def test_moon_80x24_french(self):
        assert_snapshot("moon_fr_80x24.txt", self._render("fr"))

    def test_moon_scrubbed_shows_simulated_time(self):
        """Scrubbing must label the simulated moment and the way back."""
        from linecast.moon.view import render
        from linecast._runtime import RuntimeConfig

        runtime = RuntimeConfig(live=False, icons="emoji", lang="en", oneline=False)
        with patch("linecast.moon.view.get_terminal_size", return_value=(80, 24)):
            output = _strip_ansi(
                render(self._now(), 43.7, -79.4, runtime, offset_minutes=2880)
            )
        assert "Thu Mar 5" in output
        assert "space to return to now" in output
        assert "Up now" not in output

# -----------------------------------------------------------------------
# The moon's month, the weather's year, tides and radar
# -----------------------------------------------------------------------
class TestMoonMonthSnapshot:
    def test_moon_month_80x24(self):
        from datetime import timedelta, timezone
        from linecast.moon.calendar import render_calendar
        from linecast._runtime import RuntimeConfig

        runtime = RuntimeConfig(live=False, icons="emoji", lang="en", oneline=False,
                                week_start="sunday")
        now = datetime(2026, 3, 5, 14, 30, tzinfo=timezone(timedelta(hours=-5)))
        with patch("linecast.moon.calendar.get_terminal_size", return_value=(80, 24)):
            output = render_calendar(now, 43.7, -79.4, runtime)
        assert_snapshot("moon_month_80x24.txt", _strip_ansi(output))


class TestWeatherYearSnapshot:
    def test_weather_year_80x24(self):
        from datetime import date, timedelta
        from linecast._runtime import WeatherRuntime
        from linecast.weather import year

        def archive(first, last):
            days = [first + timedelta(days=k) for k in range((last - first).days + 1)]
            season = [math.cos((d.timetuple().tm_yday - 200) / 58.1) for d in days]
            wobble = [((d.toordinal() * 7919) % 17 - 8) / 2 for d in days]
            return {"daily": {
                "time": [d.isoformat() for d in days],
                "temperature_2m_max": [55 + 28 * s + w for s, w in zip(season, wobble)],
                "temperature_2m_min": [38 + 25 * s + w / 2 for s, w in zip(season, wobble)],
                "precipitation_sum": [((d.toordinal() * 31) % 11) / 20 for d in days],
            }}

        today = date(2026, 9, 26)
        climate = year.climate_from_archive(
            archive(date(2016, 1, 1), date(2025, 12, 31)), (2016, 2025))
        days = year.year_days(archive(date(2026, 1, 1), today - timedelta(days=1)),
                              None, today)
        runtime = WeatherRuntime(live=False, icons="plain", lang="en", oneline=False,
                                 celsius=False, metric=False, shading=False, use_24h=False)
        with patch.object(year, "get_terminal_size", return_value=(80, 24)):
            output = year.render_year(climate, days, runtime, location_name="Westbrook")
        assert_snapshot("weather_year_80x24.txt", _strip_ansi(output))


class TestTidesSnapshot:
    def test_tides_80x24(self):
        from datetime import timedelta, timezone
        from linecast._runtime import TidesRuntime
        from linecast.tides import view as tides
        from linecast.tides.providers import NOAA

        # A semidiurnal tide with a small daily inequality, at six minutes.
        start = datetime(2026, 3, 3)
        preds = []
        for k in range(4 * 240):
            h = k / 10
            preds.append((start + timedelta(minutes=6 * k),
                          round(4.6 + 4.4 * math.cos(2 * math.pi * (h - 3.1) / 12.42)
                                + 0.7 * math.cos(2 * math.pi * h / 12.0), 3)))
        hilo = [(t, v, "H" if v > a else "L")
                for (_, a), (t, v), (_, b) in zip(preds, preds[1:], preds[2:])
                if (v > a and v >= b) or (v < a and v <= b)]
        runtime = TidesRuntime(live=False, icons="emoji", lang="en", metric=False,
                               oneline=False)
        # The header reads UTC directly for the Moon's phase, separately
        # from the chart's station clock. Pin both to March 5 in Portland.
        with patch.object(tides, "datetime", wraps=datetime) as clock, \
             patch.object(tides, "_station_now", return_value=FIXED_NOW), \
             patch.object(tides, "get_terminal_size", return_value=(80, 24)):
            clock.now.return_value = datetime(2026, 3, 5, 19, 30, tzinfo=timezone.utc)
            output = tides.render("8418150", "Portland, ME", runtime=runtime,
                                  predictions=preds, hilo=hilo, y_range=(-0.8, 10.4),
                                  provider=NOAA)
        assert_snapshot("tides_80x24.txt", _strip_ansi(output))


class TestRadarSnapshot:
    class Storm:
        """One storm, over the same place in every frame."""
        theme = None
        attribution = label = "stub"

        def current_frames(self):
            from datetime import timedelta, timezone
            from linecast.radar.sources import Frame
            t0 = datetime(2026, 3, 5, 19, 0, tzinfo=timezone.utc)
            return [Frame(t0 + timedelta(minutes=10 * i), i) for i in range(4)]

        def frame_rgba(self, bbox, gw, hc, frame):
            w, h = gw, hc * 2
            rgba = bytearray(w * h * 4)
            for y in range(h):
                for x in range(w):
                    d = ((x - w * 0.4) ** 2 + ((y - h * 0.55) * 1.6) ** 2) ** 0.5 / (w / 5)
                    if d < 1.0:
                        rgba[(y * w + x) * 4:(y * w + x) * 4 + 4] = (
                            (40, 180, 60, 255) if d > 0.6 else
                            (230, 200, 40, 255) if d > 0.3 else (220, 40, 40, 255))
            return w, h, rgba

    def test_radar_80x24(self, monkeypatch, keep_radar_source):
        from zoneinfo import ZoneInfo
        from linecast._runtime import RuntimeConfig
        from linecast._timefmt import fmt_time_dt
        from linecast.radar import frames as rf
        from linecast.radar import view as radar
        from linecast.radar import warnings

        rf.use(self.Storm())
        monkeypatch.setattr(warnings, "covers", lambda bbox: False)
        monkeypatch.setattr(radar, "get_terminal_size", lambda: (80, 24))
        # the frame's time is written in the machine's zone; pin it at the
        # formatter, since Windows has no time.tzset() to make TZ take
        toronto = ZoneInfo("America/Toronto")
        monkeypatch.setattr(radar, "_fmt_local", lambda dt, use_24h=False:
                            fmt_time_dt(dt.astimezone(toronto), use_24h=use_24h))
        runtime = RuntimeConfig(live=False, icons="emoji", lang="en", oneline=False)
        output, _failed = radar.render_radar(43.7, -79.4, "Toronto", 6.0, play_frame=0,
                                             playing=False, block=True, runtime=runtime)
        assert_snapshot("radar_80x24.txt", _strip_ansi(output))


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
        return RuntimeConfig(live=False, icons="emoji", lang="en",
                             oneline=False)

    def _render(self, view, fetch_patch, zoom=0.02):
        from linecast.terminal import color as _color
        from linecast.terminal import theme as _theme
        from linecast.maps import view as maps
        from linecast.maps import style as _maps_style
        stack = [
            patch("linecast.maps.view.get_terminal_size",
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
        from linecast.maps import view as maps

        # the loaders take the window an overscan is built for; a
        # window build passes None
        def elevation(bbox, gw, hc, block, window=None):
            fine = [[(x - gw * 1.4) * 2.0 for x in range(gw * 2)]
                    for _ in range(hc * 4)]
            grid = [[(x - gw * 0.7) * 4.0 for x in range(gw)]
                    for _ in range(hc * 2)]
            # no tile water: the snapshot is the elevation-only map
            return maps.TerrainView(grid, _loaders._coast_dots(fine, gw, hc),
                                    None, None, None)

        output = self._render(
            "terrain", patch.object(maps, "_get_elevation", elevation))
        assert_snapshot("maps_terrain_80x24.txt", output)

    def test_maps_globe_80x24(self):
        # Planet-scale zoom hands terrain to the orthographic globe.  A
        # synthetic hemisphere — dry land east of the centre meridian,
        # deep sea west — pins the disk, the limb falloff, the
        # atmosphere rim and the space around the planet, while the
        # vendored city data pins the projected labels.
        from linecast.maps import view as maps
        from linecast.maps import globe as _globe

        def synth(lls):
            return [[None if ll is None
                     else (1200.0 if ll[1] > self.LON else -3200.0)
                     for ll in row] for row in lls]

        def get_globe(lat0, lon0, zoom, gw, hc, block, street=False):
            lls, zs, rhos = _globe.geometry(lat0, lon0, zoom, gw, hc * 2)
            flls, _fz, _fr = _globe.geometry(lat0, lon0, zoom,
                                             gw * 2, hc * 4)
            return _globe.GlobeView(
                synth(lls), _loaders._coast_dots(synth(flls), gw, hc), zs,
                _globe.atmosphere(rhos, zoom, hc * 2), None,
                _globe.border_layer(lat0, lon0, zoom, gw, hc,
                                    _paint.BORDER_STROKE))

        output = self._render(
            "terrain", patch.object(maps, "_get_globe", get_globe),
            zoom=125.0)
        assert_snapshot("maps_globe_80x24.txt", output)

        # the street register rides the same sphere in the flat street
        # map's own fills and coast ink, with no borders — pinned
        # separately
        output = self._render(
            "street", patch.object(maps, "_get_globe", get_globe),
            zoom=125.0)
        assert_snapshot("maps_globe_street_80x24.txt", output)

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
        from linecast.maps import view as maps
        from test_maps_streets import (
            classed, polyline, rect, tagged_line, tile,
        )

        def street(bbox, gw, hc, block, lang="en", reserved=(),
                   window=None):
            from linecast.maps import streets as st
            band = st.style.band_for(st.style.z_eff(bbox, hc))
            minlon, minlat, maxlon, maxlat = bbox
            midlon = (minlon + maxlon) / 2
            midlat = (minlat + maxlat) / 2
            pad = (maxlon - minlon)
            tiles = {}
            for key in st.tiles_for_bbox(bbox, 12):
                z, tx, ty = key
                def xy(lon, lat, z=z, tx=tx, ty=ty):
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
        assert_snapshot("maps_street_80x24.txt", output)
