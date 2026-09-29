#!/usr/bin/env python3
"""Every view's output, byte for byte, to show that a change left it alone.

    uv run python scripts/golden.py capture DIR [--only TEXT]
    uv run python scripts/golden.py diff A B
    uv run python scripts/golden.py check [REV] [--only TEXT]

`capture` renders each scene below -- the printed frames, the live
frames with their tooltips and panels open, the one-line summaries and
the JSON -- in four languages and three themes, from data made up here
and a clock stopped at one moment, and writes each to DIR as the bytes a
terminal would be sent, escapes and all.  Nothing reaches the network or
the home directory.  Every scene is rendered twice, and a scene that
comes out differently the second time is reported: a harness that is
not deterministic proves nothing.

`check` captures the working tree and REV (HEAD by default) and diffs
the two.  REV is captured by its own copy of this script, in a temporary
worktree, so a change that moves a function the scenes call compares
against the scenes as they were written for REV; when REV has no copy,
this one renders it.

The tests compare text with the escapes stripped, and several views
have no snapshot at all.  This is the check that a refactor changed no
byte.  It is a tool, not a test: what it writes is not kept.
"""

import argparse
import atexit
import difflib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LANGS = ("en", "ja", "th", "fa")
THEMES = ("stock", "dark", "light")

# 2026-03-05 14:30 in Toronto, where the weather fixture was fetched.
ZONE = "America/Toronto"
LAT, LNG = 43.70, -79.40
PLACE = "Toronto, Ontario"


# ---------------------------------------------------------------------------
# The world the scenes run in
# ---------------------------------------------------------------------------
def _hermetic(src):
    """A private home, no network, truecolor, a fixed zone and clock."""
    tmp = Path(tempfile.mkdtemp(prefix="linecast-golden-"))
    atexit.register(shutil.rmtree, tmp, True)
    for name in list(os.environ):
        if name.startswith(("LINECAST_", "WEATHER_", "TIDE")) or name in (
                "LANGUAGE", "LC_ALL", "LC_MESSAGES", "NO_COLOR", "CLICOLOR",
                "CLICOLOR_FORCE", "COLORTERM", "TERM_PROGRAM", "TMUX",
                "KITTY_WINDOW_ID", "SSH_CONNECTION", "SSH_TTY", "SSH_CLIENT"):
            del os.environ[name]
        elif name.lower().endswith("_proxy"):
            del os.environ[name]
    os.environ.update({
        "HOME": str(tmp / "home"),
        "XDG_CACHE_HOME": str(tmp / "cache"),
        "XDG_CONFIG_HOME": str(tmp / "config"),
        "LINECAST_CACHE_DIR": str(tmp / "cache" / "linecast"),
        "LINECAST_CONFIG_DIR": str(tmp / "config" / "linecast"),
        "LINECAST_COLOR": "truecolor",
        "LINECAST_CELL_ASPECT": "2.0",
        "LINECAST_FRAME_SYNC": "0",
        "LANG": "en_US.UTF-8",
        "TERM": "xterm-256color",
        "TZ": ZONE,
        "COLUMNS": "80",
        "LINES": "24",
    })
    time.tzset()
    sys.path.insert(0, str(src))

    import socket

    def refuse(*args, **kwargs):
        raise OSError("golden.py: no network")
    socket.socket.connect = refuse
    socket.socket.connect_ex = refuse
    socket.create_connection = refuse


def _import_everything():
    """Import every linecast module, so the clock can be stopped in all."""
    import importlib
    import pkgutil

    import linecast
    for info in pkgutil.walk_packages(linecast.__path__, "linecast."):
        if info.name.endswith("__main__") or ".locales." in info.name:
            continue
        importlib.import_module(info.name)


def _stop_the_clock():
    """Every datetime.now() and date.today() in linecast answers FIXED."""
    import datetime as dt
    import types
    from zoneinfo import ZoneInfo

    fixed = dt.datetime(2026, 3, 5, 14, 30, tzinfo=ZoneInfo(ZONE))

    class _Meta(type):
        def __instancecheck__(cls, obj):
            return isinstance(obj, cls.__bases__[0])

        def __subclasscheck__(cls, sub):
            return issubclass(sub, cls.__bases__[0])

    class FrozenDatetime(dt.datetime, metaclass=_Meta):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return fixed.astimezone().replace(tzinfo=None)
            return fixed.astimezone(tz)

        @classmethod
        def today(cls):
            return cls.now()

        @classmethod
        def utcnow(cls):
            return fixed.astimezone(dt.timezone.utc).replace(tzinfo=None)

    class FrozenDate(dt.date, metaclass=_Meta):
        @classmethod
        def today(cls):
            return fixed.date()

    shim = types.ModuleType("datetime")
    shim.__dict__.update(dt.__dict__)
    shim.datetime, shim.date = FrozenDatetime, FrozenDate
    swap = {id(dt.datetime): FrozenDatetime, id(dt.date): FrozenDate, id(dt): shim}
    for name, mod in list(sys.modules.items()):
        if name != "linecast" and not name.startswith("linecast."):
            continue
        for attr, value in list(vars(mod).items()):
            if id(value) in swap:
                setattr(mod, attr, swap[id(value)])
    return fixed


# The terminal's colours, as a probe would have them: the ANSI sixteen
# after the background, then the foreground (tests/test_theme_reload.py).
def _ansi(fg, bg):
    ansi = [(205, 0, 0), (0, 205, 0), (205, 205, 0), (0, 0, 205),
            (205, 0, 205), (0, 205, 205)]
    return tuple([bg] + ansi + [fg] + [(128, 128, 128)] + ansi + [fg])


PALETTES = {
    "dark": ((210, 210, 220), (18, 18, 24), _ansi((210, 210, 220), (18, 18, 24))),
    "light": ((20, 20, 24), (250, 250, 248), _ansi((20, 20, 24), (250, 250, 248))),
}


class _Tty:
    """A stream that says it is a terminal, as print_frame's target is."""

    def __init__(self):
        self.parts = []

    def isatty(self):
        return True

    def write(self, text):
        self.parts.append(text)

    def flush(self):
        pass

    def getvalue(self):
        return "".join(self.parts)


# ---------------------------------------------------------------------------
# What the scenes share
# ---------------------------------------------------------------------------
class Ctx:
    """One language in one theme at one size: runtimes and writers."""

    def __init__(self, lang, theme, size):
        self.lang, self.theme, self.size = lang, theme, size

    def runtime(self, cls_name="RuntimeConfig", live=False, **flags):
        from dataclasses import replace

        from linecast import _runtime
        cls = getattr(_runtime, cls_name)
        parser = {"RuntimeConfig": _runtime.sunshine_parser,
                  "WeatherRuntime": _runtime.weather_parser,
                  "TidesRuntime": _runtime.tides_parser}[cls_name]
        argv = ["--print", "--lang", self.lang, "--icons", "emoji"]
        for key, value in flags.items():
            argv += [f"--{key.replace('_', '-')}"] + ([] if value is True else [str(value)])
        runtime = cls.from_sources(parser().parse_args(argv), environ={})
        runtime = replace(runtime, live=live)
        _runtime.set_current(runtime)
        return runtime

    def printed(self, frame):
        """The frame as `--print` writes it to a terminal."""
        from linecast.terminal.live import print_frame
        out = _Tty()
        print_frame(frame, stream=out)
        return out.getvalue()

    def live(self, output, help_panel=None):
        """The frame as the live loop paints it, overlay and all."""
        from linecast.terminal.live import frame_paint
        if isinstance(output, tuple):
            output = output[0]
        body, _, floating = output.partition("\x00")
        if help_panel is not None:
            help_panel.open = True
            floating = "\033[?1003l" + help_panel.render(*self.size)
        return frame_paint(body, floating)


def _mirror(on):
    from linecast.terminal import bidi
    bidi.set_mirror(on)


def _fixture(name):
    return json.loads((ROOT / "tests" / "fixtures" / name).read_text(encoding="utf-8"))


def _json(payload):
    return json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


SCENES = []


def scene(name, langs=LANGS, themes=THEMES, size=(80, 24)):
    def add(fn):
        SCENES.append((name, fn, langs, themes, size))
        return fn
    return add


# ---------------------------------------------------------------------------
# Weather
# ---------------------------------------------------------------------------
ALERTS = [
    {"event": "Winter Storm Warning",
     "headline": "Winter Storm Warning until Friday 7 AM",
     "description": "Heavy snow expected. Total snow accumulations of 8 to 12 "
                    "inches. Winds gusting as high as 40 mph.\n\nTravel could "
                    "be very difficult.",
     "effective": "2026-03-05T12:00:00-05:00", "expires": "2026-03-06T07:00:00-05:00",
     "severity": "Severe", "url": "https://example.org/alert/1"},
    {"event": "Wind Advisory", "headline": "Wind Advisory until 6 PM",
     "description": "West winds 25 to 35 mph with gusts up to 50 mph.",
     "effective": "2026-03-05T10:00:00-05:00", "expires": "2026-03-05T18:00:00-05:00",
     "severity": "Moderate", "url": ""},
]


def _history():
    from linecast.weather.historical import HistoricalAverages
    return HistoricalAverages(avg_high=41.2, avg_low=26.7, avg_precip=0.11,
                              years=10, year_high=91.3, year_low=-3.6)


def _units(ctx):
    """The fixture was fetched in Fahrenheit and mph, as an American's
    would be; in the other languages the labels are metric, as theirs
    would be, over the same numbers."""
    return {"imperial": True, "fahrenheit": True} if ctx.lang == "en" else {}


def _weather(ctx, live=False, **kw):
    from linecast.weather.view import render_from_data
    _mirror(True)
    runtime = ctx.runtime("WeatherRuntime", live=live, **_units(ctx))
    return render_from_data(_fixture("open_meteo_forecast.json"), kw.pop("alerts", ALERTS),
                            runtime, location_name=PLACE, historical=_history(),
                            country_code="CA", **kw)


@scene("weather-print")
def _(ctx):
    return ctx.printed(_weather(ctx)[0])


@scene("weather-print-wide", size=(120, 40))
def _(ctx):
    return ctx.printed(_weather(ctx)[0])


@scene("weather-print-narrow", size=(44, 20), themes=("stock",))
def _(ctx):
    return ctx.printed(_weather(ctx, alerts=[])[0])


@scene("weather-hover", size=(100, 30))
def _(ctx):
    frames = [ctx.live(_weather(ctx, live=True, mouse_pos=pos))
              for pos in ((20, 9), (50, 12), (80, 16), (30, 22), (60, 26))]
    return "\n----\n".join(frames)


@scene("weather-alert", size=(100, 30))
def _(ctx):
    return ctx.live(_weather(ctx, live=True, active_alert=0))


@scene("weather-app", size=(100, 30))
def _(ctx):
    from linecast.weather import view as weather
    _mirror(True)
    runtime = ctx.runtime("WeatherRuntime", live=True, **_units(ctx))
    for name in ("_start_climate", "_start_year", "_start_refresh"):
        setattr(weather.WeatherApp, name, lambda self, *a, **k: None)
    app = weather.WeatherApp(_fixture("open_meteo_forecast.json"), ALERTS, None,
                             LAT, LNG, runtime, location_name=PLACE,
                             historical=_history(), country="CA")
    app.fetched = time.monotonic()
    frames = [ctx.live(app.render()), ctx.live(app.render(), app.help_panel())]
    app.locations.start()
    frames.append(ctx.live(app.render()))
    return "\n----\n".join(frames)


def _year_data():
    from datetime import date, timedelta
    from linecast.weather import year

    def archive(first, last):
        days = [first + timedelta(days=k) for k in range((last - first).days + 1)]
        season = [__import__("math").cos((d.timetuple().tm_yday - 200) / 58.1) for d in days]
        wobble = [((d.toordinal() * 7919) % 17 - 8) / 2 for d in days]
        return {"daily": {
            "time": [d.isoformat() for d in days],
            "temperature_2m_max": [55 + 28 * s + w for s, w in zip(season, wobble)],
            "temperature_2m_min": [38 + 25 * s + w / 2 for s, w in zip(season, wobble)],
            "precipitation_sum": [((d.toordinal() * 31) % 11) / 20 for d in days],
            "snowfall_sum": [0.4 if d.month in (1, 2) and d.day % 5 == 0 else 0.0
                             for d in days],
            "weather_code": [71 if d.month in (1, 2) and d.day % 5 == 0 else 3
                             for d in days],
        }}

    today = date(2026, 3, 5)
    climate = year.climate_from_archive(archive(date(2016, 1, 1), date(2025, 12, 31)),
                                        (2016, 2025))
    days = year.year_days(archive(date(2026, 1, 1), today - timedelta(days=1)), None, today)
    return climate, days


@scene("weather-year", size=(100, 30))
def _(ctx):
    from linecast.weather import year
    _mirror(True)
    climate, days = _year_data()
    printed = year.render_year(climate, days, ctx.runtime("WeatherRuntime", **_units(ctx)),
                               location_name=PLACE)
    live = ctx.runtime("WeatherRuntime", live=True, **_units(ctx))
    hovered = year.render_year(climate, days, live, location_name=PLACE,
                               mouse_pos=(30, 12), live=True)
    return ctx.printed(printed) + "\n----\n" + ctx.live(hovered)


@scene("weather-json", themes=("stock",))
def _(ctx):
    from linecast.weather.json import build_payload
    runtime = ctx.runtime("WeatherRuntime", **_units(ctx))
    return _json(build_payload(_fixture("open_meteo_forecast.json"), PLACE, "CA", runtime,
                               alerts=ALERTS, historical=_history()))


@scene("weather-oneline", themes=("stock", "dark"))
def _(ctx):
    from linecast.terminal.oneline import weather_oneline
    return ctx.printed(weather_oneline(_fixture("open_meteo_forecast.json"), PLACE,
                                       ctx.runtime("WeatherRuntime", **_units(ctx))))


# ---------------------------------------------------------------------------
# Sunshine
# ---------------------------------------------------------------------------
def _now():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    return datetime(2026, 3, 5, 14, 30, tzinfo=ZoneInfo(ZONE))


def _sunshine(ctx, hours=None, live=False):
    from linecast.sunshine import view as sun
    _mirror(True)
    now = _now()
    return sun.render(LAT, LNG, now.timetuple().tm_yday, 14.5, fullscreen=live,
                      runtime=ctx.runtime(live=live), tz_offset_h=-5,
                      location_label="Toronto", now=now, hours=hours)


@scene("sunshine-print")
def _(ctx):
    return ctx.printed(_sunshine(ctx))


@scene("sunshine-live", size=(100, 30))
def _(ctx):
    return ctx.live(_sunshine(ctx, live=True))


@scene("sunshine-hours", themes=("stock", "dark"))
def _(ctx):
    from linecast.astro.hours import hours_now
    frames = []
    for system, variant, country in (("halachic", None, None), ("roman", None, None),
                                     ("japanese", None, None), ("islamic", None, "CA"),
                                     ("swahili", None, None)):
        hours = hours_now(system, _now(), LAT, LNG, _now().tzinfo, variant,
                          country=country)[0]
        frames.append(ctx.printed(_sunshine(ctx, hours=hours)))
    return "\n----\n".join(frames)


@scene("sunshine-year", size=(100, 30))
def _(ctx):
    from linecast.sunshine.year import render_year
    _mirror(True)
    now = _now()
    printed = render_year(LAT, LNG, now, ctx.runtime(), tz=now.tzinfo,
                          location_label="Toronto")
    hovered = render_year(LAT, LNG, now, ctx.runtime(live=True), tz=now.tzinfo,
                          fullscreen=True, location_label="Toronto", mouse_pos=(40, 12))
    polar = render_year(78.22, 15.65, now, ctx.runtime(), tz=now.tzinfo,
                        location_label="Longyearbyen")
    return "\n----\n".join((ctx.printed(printed), ctx.live(hovered), ctx.printed(polar)))


@scene("sunshine-json", themes=("stock",), langs=("en",))
def _(ctx):
    from linecast.astro.hours import hours_now
    from linecast.sunshine.json import build_payload
    ctx.runtime()
    hours = hours_now("roman", _now(), LAT, LNG, _now().tzinfo)[0]
    return _json(build_payload(LAT, LNG, now=_now(), location=PLACE, hours=hours))


@scene("sunshine-oneline", themes=("stock", "dark"))
def _(ctx):
    from linecast.terminal.oneline import sunshine_oneline
    now = _now()
    return ctx.printed(sunshine_oneline(LAT, LNG, now.timetuple().tm_yday, ctx.runtime(),
                                        tz_offset_h=-5, now=now))


# ---------------------------------------------------------------------------
# Moon
# ---------------------------------------------------------------------------
CALENDARS = ("chinese", "hawaiian", "islamic", "hebrew", "icelandic", "thai",
             "almanac", "none")


@scene("moon-print")
def _(ctx):
    from linecast.moon.view import render
    _mirror(True)
    return ctx.printed(render(_now(), LAT, LNG, ctx.runtime()))


@scene("moon-calendars", size=(100, 30), themes=("stock", "dark"))
def _(ctx):
    from linecast.moon.view import render
    _mirror(True)
    return "\n----\n".join(
        ctx.printed(render(_now(), LAT, LNG, ctx.runtime(), calendar_name=cal))
        for cal in CALENDARS)


@scene("moon-month", size=(100, 32))
def _(ctx):
    from linecast.moon.calendar import render_calendar
    _mirror(True)
    frames = []
    for cal in CALENDARS:
        out = render_calendar(_now(), LAT, LNG, ctx.runtime(live=True), fullscreen=True,
                              mouse_pos=(30, 12), calendar_name=cal)
        frames.append(ctx.live(out))
    return "\n----\n".join(frames)


@scene("moon-json", themes=("stock",), langs=("en", "fa"))
def _(ctx):
    from linecast.moon.json import build_payload
    runtime = ctx.runtime()
    return "".join(_json(build_payload(_now(), LAT, LNG, runtime, location=PLACE,
                                       calendar=cal)) for cal in CALENDARS)


@scene("moon-oneline", themes=("stock", "dark"))
def _(ctx):
    from linecast.terminal.oneline import moon_oneline
    runtime = ctx.runtime()
    return "".join(ctx.printed(moon_oneline(_now(), LAT, LNG, runtime, calendar=cal))
                   for cal in CALENDARS)


# ---------------------------------------------------------------------------
# Sky
# ---------------------------------------------------------------------------
def _night():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    return datetime(2026, 3, 5, 22, 0, tzinfo=ZoneInfo(ZONE))


def _sky(ctx, live=False, mouse_pos=None):
    from datetime import timezone
    from linecast.sky.view import Scene, default_view, render
    _mirror(False)
    now = _night()
    scene_ = Scene(now.astimezone(timezone.utc), LAT, LNG)
    cols, rows = ctx.size
    view = default_view(scene_, cols, rows, 180.0, 110.0)
    return render(now, LAT, LNG, ctx.runtime(live=live), view, fullscreen=live,
                  mouse_pos=mouse_pos, location_label="Toronto", today=now.date())


@scene("sky-print")
def _(ctx):
    return ctx.printed(_sky(ctx))


@scene("sky-hover", size=(100, 30))
def _(ctx):
    return "\n----\n".join(ctx.live(_sky(ctx, live=True, mouse_pos=pos))
                           for pos in ((50, 12), (30, 20), (70, 8)))


@scene("sky-panels", size=(100, 30), themes=("stock", "dark"))
def _(ctx):
    from linecast.sky.picker import CulturePicker, picker_overlay
    from linecast.sky.search import SkySearch, search_overlay
    runtime = ctx.runtime(live=True)
    picker = CulturePicker(ctx.lang)
    picker.start(None)
    search = SkySearch(runtime, refresh=lambda: None)
    search.open, search.query = True, "ve"
    search.results = __import__("linecast.sky.search", fromlist=["search"]).search(
        "ve", search.pool())
    cols, rows = ctx.size
    return "\n----\n".join((picker_overlay(picker, cols, rows, runtime),
                            search_overlay(search, cols, rows, runtime)))


@scene("sky-json", themes=("stock",), langs=("en", "ja"))
def _(ctx):
    from linecast.sky.json import build_payload
    return _json(build_payload(_night(), LAT, LNG, ctx.runtime(), location=PLACE))


@scene("sky-oneline", themes=("stock", "dark"))
def _(ctx):
    from linecast.terminal.oneline import sky_oneline
    return ctx.printed(sky_oneline(_night(), LAT, LNG, ctx.runtime()))


# ---------------------------------------------------------------------------
# Tides
# ---------------------------------------------------------------------------
def _tide_data():
    """Four days of a semidiurnal tide at six minutes, and its turns."""
    import math
    from datetime import datetime, timedelta
    start = datetime(2026, 3, 3)
    preds = []
    for k in range(4 * 240):
        t = start + timedelta(minutes=6 * k)
        h = k / 10
        preds.append((t, round(4.6 + 4.4 * math.cos(2 * math.pi * (h - 3.1) / 12.42)
                           + 0.7 * math.cos(2 * math.pi * h / 12.0), 3)))
    hilo = []
    for i in range(1, len(preds) - 1):
        (t, v), a, b = preds[i], preds[i - 1][1], preds[i + 1][1]
        if v > a and v >= b:
            hilo.append((t, v, "H"))
        elif v < a and v <= b:
            hilo.append((t, v, "L"))
    return preds, hilo


def _feet(ctx):
    """The tide below is in feet, NOAA's unit; English reads it so."""
    return {"imperial": True} if ctx.lang == "en" else {}


def _tides(ctx, live=False, **kw):
    from linecast.tides import view as tides
    from linecast.tides.providers import NOAA
    _mirror(True)
    preds, hilo = _tide_data()
    return tides.render("8418150", "Portland, ME", station_meta=None,
                        runtime=ctx.runtime("TidesRuntime", live=live, **_feet(ctx)),
                        fullscreen=live,
                        predictions=preds, hilo=hilo, y_range=(-0.8, 10.4),
                        provider=NOAA, **kw)


@scene("tides-print")
def _(ctx):
    return ctx.printed(_tides(ctx))


@scene("tides-hover", size=(100, 30))
def _(ctx):
    return "\n----\n".join(ctx.live(_tides(ctx, live=True, mouse_pos=pos, offset_minutes=off))
                           for pos, off in (((20, 10), 0), ((60, 14), 90), ((85, 8), -240)))


@scene("tides-json", themes=("stock",), langs=("en",))
def _(ctx):
    from linecast.tides.json import build_payload
    preds, hilo = _tide_data()
    return _json(build_payload("Portland, ME", ctx.runtime("TidesRuntime", **_feet(ctx)),
                               _now().replace(tzinfo=None), preds, hilo,
                               station_id="8418150", source="NOAA", tz_name=ZONE))


@scene("tides-oneline", themes=("stock", "dark"))
def _(ctx):
    from linecast.terminal.oneline import tides_oneline
    _preds, hilo = _tide_data()
    return ctx.printed(tides_oneline("Portland, ME", hilo, _now().replace(tzinfo=None),
                                     ctx.runtime("TidesRuntime", **_feet(ctx))))


# ---------------------------------------------------------------------------
# Radar
# ---------------------------------------------------------------------------
class _Storm:
    """A radar source with one storm over the lake, in every frame."""
    theme = None
    attribution = label = "golden"

    def current_frames(self):
        from datetime import datetime, timedelta, timezone
        from linecast.radar.sources import Frame
        t0 = datetime(2026, 3, 5, 19, 0, tzinfo=timezone.utc)
        return [Frame(t0 + timedelta(minutes=10 * i), i) for i in range(4)]

    def frame_rgba(self, bbox, gw, hc, frame):
        w, h = gw, hc * 2
        rgba = bytearray(w * h * 4)
        cx, cy = w * (0.4 + 0.05 * frame.token), h * 0.55
        for y in range(h):
            for x in range(w):
                d = ((x - cx) ** 2 + ((y - cy) * 1.6) ** 2) ** 0.5 / (w / 5)
                if d < 1.0:
                    i = (y * w + x) * 4
                    rgba[i:i + 4] = ((40, 180, 60, 255) if d > 0.6 else
                                     (230, 200, 40, 255) if d > 0.3 else (220, 40, 40, 255))
                elif d < 1.2:
                    i = (y * w + x) * 4
                    rgba[i:i + 4] = (40, 180, 60, 120)
        return w, h, rgba


def _radar(ctx, **kw):
    from linecast.radar import frames as rf
    from linecast.radar import view as radar
    from linecast.radar import warnings
    _mirror(False)
    rf._source = _Storm()
    warnings.covers = lambda bbox: False
    return radar.render_radar(LAT, LNG, "Toronto", kw.pop("zoom", 6.0), play_frame=0,
                              playing=False, block=True, runtime=ctx.runtime(**kw.pop(
                                  "flags", {})), **kw)


@scene("radar-print")
def _(ctx):
    return ctx.printed(_radar(ctx))


@scene("radar-menu", size=(100, 30), themes=("stock", "dark"))
def _(ctx):
    from linecast.radar.sources import THEMES as RADAR_THEMES
    names = list(RADAR_THEMES)
    out = _radar(ctx, theme_menu=(names, 1), mouse_pos=(40, 12),
                 flags={})
    return ctx.live(out)


# ---------------------------------------------------------------------------
# Maps: synthetic ground, as tests/test_render_snapshots.py draws it
# ---------------------------------------------------------------------------
def _maps(ctx, view, zoom, **kw):
    from unittest import mock
    from linecast.maps import globe as _globe
    from linecast.maps import paint, views
    from linecast.maps import view as maps
    _mirror(False)
    lat, lon = 43.66, -70.26

    def elevation(bbox, gw, hc, block, window=None):
        fine = [[(x - gw * 1.4) * 2.0 for x in range(gw * 2)] for _ in range(hc * 4)]
        grid = [[(x - gw * 0.7) * 4.0 for x in range(gw)] for _ in range(hc * 2)]
        return maps.TerrainView(grid, views._coast_dots(fine, gw, hc), None, None, None)

    def synth(lls):
        return [[None if ll is None else (1200.0 if ll[1] > lon else -3200.0)
                 for ll in row] for row in lls]

    def get_globe(lat0, lon0, zoom, gw, hc, block, street=False):
        lls, zs, rhos = _globe.geometry(lat0, lon0, zoom, gw, hc * 2)
        flls, _fz, _fr = _globe.geometry(lat0, lon0, zoom, gw * 2, hc * 4)
        return _globe.GlobeView(synth(lls), views._coast_dots(synth(flls), gw, hc), zs,
                                _globe.atmosphere(rhos, zoom, hc * 2), None,
                                _globe.border_layer(lat0, lon0, zoom, gw, hc,
                                                    paint.BORDER_STROKE))

    with mock.patch.object(maps, "_get_elevation", elevation), \
            mock.patch.object(maps, "_get_globe", get_globe):
        return maps.render_map(lat, lon, "Portland, Maine", zoom,
                               runtime=ctx.runtime(**kw.pop("flags", {})), view=view, **kw)


@scene("maps-terrain", themes=("stock", "dark"))
def _(ctx):
    return ctx.printed(_maps(ctx, "terrain", 0.02))


@scene("maps-globe", themes=("stock", "dark"))
def _(ctx):
    return ctx.printed(_maps(ctx, "terrain", 125.0))


@scene("maps-panels", size=(100, 30), themes=("stock", "dark"))
def _(ctx):
    from linecast.maps import ui
    from linecast.maps.route import _parse
    from linecast.maps.search import Result
    cols, rows = ctx.size
    search = ui.SearchState(refresh=lambda: None, fetch=lambda *a, **k: [])
    search.open, search.query, search.status = True, "portland", ""
    search.results = [Result("Portland", "Maine, United States", 43.66, -70.26, "city"),
                      Result("Portland", "Oregon, United States", 45.52, -122.68, "city")]
    route = _parse(_fixture("osrm_route.json"), "car")
    return "\n----\n".join((
        ui.search_overlay(search, cols, rows, ctx.lang),
        ui.route_summary(route, ctx.lang),
        "\n".join(ui.steps_text(route, ctx.lang, "Portland", "Westbrook")),
        ui.help_overlay(cols, rows, ctx.lang, route=True),
    ))


# ---------------------------------------------------------------------------
# The shared panels
# ---------------------------------------------------------------------------
@scene("help", size=(100, 30), themes=("stock", "dark"))
def _(ctx):
    from linecast.terminal.help import HelpPanel
    ctx.runtime()
    views = ("weather", "weather_year", "sunshine", "sunshine_year", "moon",
             "moon_calendar", "sky", "tides", "radar")
    out = []
    for view in views:
        panel = HelpPanel(view, ctx.lang)
        panel.open = True
        out.append(panel.render(*ctx.size))
    return "\n----\n".join(out)


@scene("menus", size=(60, 20), themes=("stock", "dark"))
def _(ctx):
    from linecast.terminal import live
    ctx.runtime()
    cols, rows = ctx.size
    return "\n----\n".join((
        live.menu_box([" ● one", " two", None, " three"], cols, rows, title="Theme", sel=1),
        live.toast_box("Saved as the default place", cols, rows),
    ))


# ---------------------------------------------------------------------------
# Running them
# ---------------------------------------------------------------------------
def _set_theme(theme):
    from linecast.terminal import theme as _theme
    if theme != "stock":
        _theme._apply(*PALETTES[theme])


def capture(out_dir, only=None):
    src = Path(os.environ.get("GOLDEN_SRC", ROOT / "src"))
    _hermetic(src)
    _import_everything()
    _stop_the_clock()
    from linecast.terminal import theme as _theme
    stock = (_theme.theme_fg, _theme.theme_bg, _theme.theme_ansi, _theme.theme_available)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    unsteady, failed, written = [], [], 0
    for theme in THEMES:
        if theme == "stock":
            _theme._apply(*stock[:3])
            _theme.theme_available = stock[3]
        else:
            _set_theme(theme)
        for name, fn, langs, themes, size in SCENES:
            if theme not in themes or (only and only not in name):
                continue
            for lang in langs:
                os.environ["COLUMNS"], os.environ["LINES"] = str(size[0]), str(size[1])
                ctx = Ctx(lang, theme, size)
                try:
                    first = fn(ctx)
                    second = fn(Ctx(lang, theme, size))
                except Exception as exc:
                    import traceback
                    failed.append(f"{name}.{lang}.{theme}")
                    first = second = "FAILED\n" + "".join(
                        traceback.format_exception(type(exc), exc, exc.__traceback__))
                if first != second:
                    unsteady.append(f"{name}.{lang}.{theme}")
                (out_dir / f"{name}.{lang}.{theme}.txt").write_text(first, encoding="utf-8")
                written += 1
    print(f"{written} captures in {out_dir}")
    for label, names in (("failed", failed), ("not the same twice", unsteady)):
        if names:
            print(f"{len(names)} {label}: " + ", ".join(names))
    return 1 if failed or unsteady else 0


def _visible(text):
    return text.replace("\033", "␛").replace("\x00", "␀")


def diff(a, b):
    a, b = Path(a), Path(b)
    names = sorted({p.name for p in a.glob("*.txt")} | {p.name for p in b.glob("*.txt")})
    changed = 0
    for name in names:
        pa, pb = a / name, b / name
        if not pa.exists() or not pb.exists():
            print(f"only in {'B' if not pa.exists() else 'A'}: {name}")
            changed += 1
            continue
        ta, tb = pa.read_text(encoding="utf-8"), pb.read_text(encoding="utf-8")
        if ta == tb:
            continue
        changed += 1
        la, lb = _visible(ta).split("\n"), _visible(tb).split("\n")
        print(f"changed: {name}")
        for line in list(difflib.unified_diff(la, lb, "A", "B", n=0, lineterm=""))[2:8]:
            print("   " + line[:240])
    print(f"{len(names) - changed} of {len(names)} the same")
    return 1 if changed else 0


def check(rev, only=None):
    tmp = Path(tempfile.mkdtemp(prefix="linecast-golden-check-"))
    tree = tmp / "rev"
    subprocess.run(["git", "worktree", "add", "--detach", "-q", str(tree), rev],
                   cwd=ROOT, check=True)
    try:
        script = tree / "scripts" / "golden.py"
        env = dict(os.environ)
        if not script.exists():
            script, env["GOLDEN_SRC"] = Path(__file__), str(tree / "src")
        args = ["capture", str(tmp / "a")] + (["--only", only] if only else [])
        code_a = subprocess.run([sys.executable, str(script), *args], cwd=tree, env=env).returncode
        args[1] = str(tmp / "b")
        code_b = subprocess.run([sys.executable, __file__, *args], cwd=ROOT).returncode
        return diff(tmp / "a", tmp / "b") or code_a or code_b
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(tree)], cwd=ROOT)
        shutil.rmtree(tmp, True)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("capture")
    p.add_argument("dir")
    p.add_argument("--only")
    p = sub.add_parser("diff")
    p.add_argument("a")
    p.add_argument("b")
    p = sub.add_parser("check")
    p.add_argument("rev", nargs="?", default="HEAD")
    p.add_argument("--only")
    args = parser.parse_args()
    if args.cmd == "capture":
        return capture(args.dir, args.only)
    if args.cmd == "diff":
        return diff(args.a, args.b)
    return check(args.rev, args.only)


if __name__ == "__main__":
    sys.exit(main())
