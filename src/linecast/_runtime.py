"""Shared CLI/runtime option helpers."""

import argparse
from dataclasses import dataclass
import os
import sys


# ---------------------------------------------------------------------------
# Debug logging
# ---------------------------------------------------------------------------
_DEBUG = False


def set_debug(value):
    global _DEBUG
    _DEBUG = bool(value)


def debug_log(msg):
    """Print a diagnostic message to stderr when --debug is active."""
    if _DEBUG:
        print(f"[linecast] {msg}", file=sys.stderr)


def install_banner():
    """A one-line install hint shown when running from a temporary venv (get.sh)."""
    if not os.environ.get("LINECAST_TEMP"):
        return ""
    from linecast._color import fg, RESET
    from linecast._theme import ensure_contrast, neutral_tone, theme_bg, theme_fg
    text = fg(*ensure_contrast(theme_fg, theme_bg, minimum=4.5))
    muted = fg(*ensure_contrast(neutral_tone(0.48), theme_bg, minimum=2.5))
    sep = f"{muted} \u00b7 "
    return f" {text}linecast{sep}{muted}pip install linecast{sep}github.com/ashuttl/linecast{RESET}"


# ---------------------------------------------------------------------------
# Legacy argv helpers (still used by _theme.py at import time)
# ---------------------------------------------------------------------------
def _argv(argv=None):
    if argv is None:
        return tuple(sys.argv[1:])
    return tuple(argv)


def _environ(environ=None):
    return os.environ if environ is None else environ


def has_flag(flag, argv=None):
    """Return True if flag appears in argv."""
    return flag in _argv(argv)


def arg_value(flag, argv=None):
    """Return the value after --flag or from --flag=value."""
    args = _argv(argv)
    for i, token in enumerate(args):
        if token == flag and i + 1 < len(args):
            return args[i + 1]
        if token.startswith(f"{flag}="):
            return token.split("=", 1)[1]
    return None


def env_truthy(value):
    return str(value).lower() in ("1", "true", "yes")


# ---------------------------------------------------------------------------
# Units preference
# ---------------------------------------------------------------------------
def units_pref(env_var="WEATHER_UNITS", environ=None):
    """The user's explicit units preference, or None if they have none.

    Precedence: the command's env var (WEATHER_UNITS / TIDES_UNITS), then
    the `units` key in config.json (`linecast units metric|imperial`).
    """
    env = _environ(environ)
    value = env.get(env_var, "").strip().lower()
    if value in ("metric", "imperial"):
        return value
    from linecast._config import saved_units
    return saved_units()


def use_metric(lang, environ=None):
    """The house units heuristic, in one place: an explicit preference
    wins; otherwise any non-English UI is metric."""
    pref = units_pref("WEATHER_UNITS", environ)
    if pref is not None:
        return pref == "metric"
    return lang != "en"


# ---------------------------------------------------------------------------
# Argparse parser factories
# ---------------------------------------------------------------------------
def _base_parser(prog, description):
    from linecast import __version__
    p = argparse.ArgumentParser(prog=prog, description=description)
    p.add_argument("--version", action="version",
                    version=f"{prog} (linecast {__version__})")
    p.add_argument("--print", dest="print_mode", action="store_true",
                    help="single static snapshot (no live mode)")
    p.add_argument("--live", action="store_true",
                    help="force live mode (default when interactive)")
    p.add_argument("--oneline", action="store_true",
                    help="compact single-line output")
    p.add_argument("--emoji", action="store_true",
                    help="use standard emoji instead of Nerd Font icons")
    p.add_argument("--lang", default=None,
                    help="UI language code (en, fr, es, de, it, pt, nl, pl, "
                         "no, sv, is, da, fi, id, ja, ko, zh)")
    p.add_argument("--classic-colors", action="store_true",
                    help="use pre-theme fixed color palette")
    p.add_argument("--legacy-colors", action="store_true",
                    help="alias for --classic-colors")
    p.add_argument("--debug", action="store_true",
                    help="show diagnostic info on stderr")
    return p


def weather_parser():
    p = _base_parser("weather",
                      "Terminal weather dashboard with braille temperature "
                      "curve and alerts")
    p.add_argument("--location", default=None,
                    help="location as 'lat,lng' or place name")
    p.add_argument("--search", default=None,
                    help="search for a location and exit")
    p.add_argument("--metric", action="store_true",
                    help="metric units: celsius, km/h, mm")
    p.add_argument("--celsius", action="store_true",
                    help="celsius temperatures only")
    p.add_argument("--fahrenheit", action="store_true",
                    help="fahrenheit temperatures")
    p.add_argument("--no-shading", action="store_true",
                    help="disable daylight shading on hourly chart")
    p.add_argument("--json", dest="json_mode", action="store_true",
                    help="machine-readable JSON output (implies --print)")
    return p


def tides_parser():
    p = _base_parser("tides",
                      "Terminal tide chart with braille rendering")
    p.add_argument("--location", default=None,
                    help="find the nearest station to 'lat,lng' or a "
                         "place name instead of your location")
    p.add_argument("--station", default=None,
                    help="station ID or name (any provider)")
    p.add_argument("--search", nargs="?", const="", default=None,
                    help="search for a station and exit "
                         "(no query: list nearest stations)")
    p.add_argument("--nearby", action="store_true",
                    help="list the nearest tide stations and exit")
    p.add_argument("--metric", action="store_true",
                    help="heights in meters instead of feet")
    p.add_argument("--json", dest="json_mode", action="store_true",
                    help="machine-readable JSON output (implies --print)")
    return p


def sunshine_parser():
    p = _base_parser("sunshine",
                      "Solar arc inspired by the Apple Watch Solar face")
    p.add_argument("--location", default=None,
                    help="location as 'lat,lng' or place name")
    p.add_argument("--json", dest="json_mode", action="store_true",
                    help="machine-readable JSON output (implies --print)")
    return p


def moon_parser():
    p = _base_parser("moon",
                      "Moon phase, illumination, and rise/set times")
    p.add_argument("--location", default=None,
                    help="location as 'lat,lng' or place name")
    p.add_argument("--json", dest="json_mode", action="store_true",
                    help="machine-readable JSON output (implies --print)")
    return p


def radar_parser():
    p = _base_parser("radar",
                      "Terminal weather radar over a braille basemap (US + global)")
    p.add_argument("--location", default=None,
                    help="location as 'lat,lng' or place name")
    p.add_argument("--search", default=None,
                    help="search for a location and exit")
    p.add_argument("--zoom", type=float, default=6.0,
                    help="degrees of latitude shown top-to-bottom (default 6)")
    p.add_argument("--theme", default=None,
                    help="radar colour theme (LibreWXR server-rendered): "
                         "dark-sky (default), universal-blue, rainbow "
                         "(classic radar look), nexrad, original, titan, "
                         "twc, meteored, datameteo, viper, mrms, max-storm, "
                         "black-white; press t in live mode to pick "
                         "interactively")
    p.add_argument("--layer", default=None,
                    help="display layer: radar (default) or satellite "
                         "(hourly cloud mosaic); press s in live mode "
                         "to toggle")
    p.add_argument("--layers", default=None,
                    help="condition layers to show, comma-separated: "
                         "temp (temperature tint), wind (speed/direction "
                         "arrows); press c/w in live mode to toggle")
    return p


def maps_parser():
    p = _base_parser("maps",
                      "Street map and terrain map: vector streets, or "
                      "hillshaded elevation under braille coastlines")
    p.add_argument("--location", default=None,
                    help="location as 'lat,lng' or place name")
    p.add_argument("--search", default=None,
                    help="search for a location and exit")
    # the default is per view and resolved in maps.main(): a street map
    # opens on a neighbourhood, terrain on a region
    p.add_argument("--zoom", type=float, default=None,
                    help="degrees of latitude shown top-to-bottom "
                         "(default 0.05 in street view, 4 in terrain)")
    p.add_argument("--view", choices=("street", "terrain", "now"),
                    default="street",
                    help="vector street map or terrain relief (default "
                         "street); now opens the terrain planet with "
                         "daylight and clouds switched on")
    p.add_argument("--to", default=None,
                    help="route to a place or 'lat,lng' from the origin")
    p.add_argument("--from", dest="from_", metavar="FROM", default=None,
                    help="route from a place or 'lat,lng' "
                         "(default: your location)")
    p.add_argument("--profile", default="car",
                    help="how to travel: car, bike or foot (default car)")
    return p


# ---------------------------------------------------------------------------
# Live mode resolution
# ---------------------------------------------------------------------------
def _resolve_live(args):
    """Live mode is on by default when stdout is a TTY.

    --print forces static single-shot output.
    --oneline forces static single-shot output.
    --json forces static single-shot output.
    --live is accepted for backwards compatibility but is no longer needed.
    """
    if "--print" in args or "--oneline" in args or "--json" in args:
        return False
    if "--live" in args:
        return True
    try:
        return sys.stdout.isatty() and sys.stdin.isatty()
    except Exception:
        return False


def _resolve_live_ns(ns):
    """Resolve live mode from an argparse namespace."""
    # Not every command's parser defines --json (radar/maps), so getattr.
    if ns.print_mode or ns.oneline or getattr(ns, "json_mode", False):
        return False
    if ns.live:
        return True
    try:
        return sys.stdout.isatty() and sys.stdin.isatty()
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Runtime config dataclasses
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class RuntimeConfig:
    live: bool
    emoji: bool
    lang: str
    oneline: bool
    json_mode: bool = False  # machine-readable JSON output

    @classmethod
    def from_sources(cls, argv=None, environ=None, namespace=None):
        env = _environ(environ)
        if namespace is not None:
            if namespace.debug:
                set_debug(True)
            lang = (
                namespace.lang
                or env.get("LINECAST_LANG", "").strip()
                or "en"
            ).lower()[:2]
            return cls(
                live=_resolve_live_ns(namespace),
                emoji=(getattr(namespace, "emoji", False)
                       or env.get("LINECAST_ICONS", "").lower() == "emoji"),
                lang=lang if len(lang) == 2 and lang.isalpha() else "en",
                oneline=namespace.oneline,
                json_mode=getattr(namespace, "json_mode", False),
            )
        args = _argv(argv)
        if "--debug" in args:
            set_debug(True)
        lang = (
            arg_value("--lang", args)
            or env.get("LINECAST_LANG", "").strip()
            or "en"
        ).lower()[:2]
        return cls(
            live=_resolve_live(args),
            emoji="--emoji" in args or env.get("LINECAST_ICONS", "").lower() == "emoji",
            lang=lang if len(lang) == 2 and lang.isalpha() else "en",
            oneline="--oneline" in args,
            json_mode="--json" in args,
        )

    @property
    def use_24h(self):
        return self.lang != "en"


@dataclass(frozen=True)
class WeatherRuntime(RuntimeConfig):
    # Defaults required: the base class ends in a defaulted field (json_mode).
    celsius: bool = False
    metric: bool = False  # wind (km/h) and precipitation (mm)
    shading: bool = True

    @classmethod
    def from_sources(cls, argv=None, environ=None, namespace=None):
        env = _environ(environ)
        if namespace is not None:
            base = RuntimeConfig.from_sources(environ=env, namespace=namespace)
            all_metric = (
                namespace.metric
                or units_pref("WEATHER_UNITS", env) == "metric"
            )
            if namespace.fahrenheit:
                celsius = False
            elif namespace.celsius or all_metric:
                celsius = True
            else:
                celsius = False
            return cls(
                live=base.live,
                emoji=base.emoji,
                lang=base.lang,
                oneline=base.oneline,
                celsius=celsius,
                metric=namespace.metric or all_metric,
                shading=(not namespace.no_shading
                         and not env_truthy(env.get("WEATHER_NO_SHADING", ""))),
                json_mode=base.json_mode,
            )
        args = _argv(argv)
        base = RuntimeConfig.from_sources(args, env)
        all_metric = (
            "--metric" in args
            or units_pref("WEATHER_UNITS", env) == "metric"
        )
        # --celsius / --fahrenheit override temperature independently
        if "--fahrenheit" in args:
            celsius = False
        elif "--celsius" in args or all_metric:
            celsius = True
        else:
            celsius = False
        return cls(
            live=base.live,
            emoji=base.emoji,
            lang=base.lang,
            oneline=base.oneline,
            celsius=celsius,
            metric="--metric" in args or all_metric,
            shading="--no-shading" not in args and not env_truthy(env.get("WEATHER_NO_SHADING", "")),
            json_mode=base.json_mode,
        )

    @property
    def temp_unit(self):
        return "\u00b0C" if self.celsius else "\u00b0F"

    @property
    def wind_unit(self):
        return "km/h" if self.metric else "mph"

    @property
    def precip_unit(self):
        return "mm" if self.metric else "\u2033"


@dataclass(frozen=True)
class TidesRuntime(RuntimeConfig):
    # Default required: the base class ends in a defaulted field (json_mode).
    metric: bool = False  # heights in meters instead of feet

    @classmethod
    def from_sources(cls, argv=None, environ=None, namespace=None):
        env = _environ(environ)
        if namespace is not None:
            base = RuntimeConfig.from_sources(environ=env, namespace=namespace)
            return cls(
                live=base.live,
                emoji=base.emoji,
                lang=base.lang,
                oneline=base.oneline,
                json_mode=base.json_mode,
                metric=(
                    namespace.metric
                    or units_pref("TIDES_UNITS", env) == "metric"
                ),
            )
        args = _argv(argv)
        base = RuntimeConfig.from_sources(args, env)
        return cls(
            live=base.live,
            emoji=base.emoji,
            lang=base.lang,
            oneline=base.oneline,
            json_mode=base.json_mode,
            metric=(
                "--metric" in args
                or units_pref("TIDES_UNITS", env) == "metric"
            ),
        )

    @property
    def height_unit(self):
        return "m" if self.metric else "\u2032"

    def convert_height(self, ft):
        return ft * 0.3048 if self.metric else ft
