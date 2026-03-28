"""Shared CLI/runtime option helpers."""

from dataclasses import dataclass
import os
import sys


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


def _resolve_live(args):
    """Live mode is on by default when stdout is a TTY.

    --print forces static single-shot output.
    --oneline forces static single-shot output.
    --live is accepted for backwards compatibility but is no longer needed.
    """
    if "--print" in args or "--oneline" in args:
        return False
    if "--live" in args:
        return True
    try:
        return sys.stdout.isatty() and sys.stdin.isatty()
    except Exception:
        return False


@dataclass(frozen=True)
class RuntimeConfig:
    live: bool
    emoji: bool
    lang: str
    oneline: bool

    @classmethod
    def from_sources(cls, argv=None, environ=None):
        args = _argv(argv)
        env = _environ(environ)
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
        )

    @property
    def use_24h(self):
        return self.lang != "en"


@dataclass(frozen=True)
class WeatherRuntime(RuntimeConfig):
    celsius: bool
    metric: bool  # wind (km/h) and precipitation (mm)
    shading: bool

    @classmethod
    def from_sources(cls, argv=None, environ=None):
        args = _argv(argv)
        env = _environ(environ)
        base = RuntimeConfig.from_sources(args, env)
        all_metric = (
            "--metric" in args
            or env.get("WEATHER_UNITS", "").lower() == "metric"
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
        )

    @property
    def temp_unit(self):
        return "°C" if self.celsius else "°F"

    @property
    def wind_unit(self):
        return "km/h" if self.metric else "mph"

    @property
    def precip_unit(self):
        return "mm" if self.metric else "\u2033"


@dataclass(frozen=True)
class TidesRuntime(RuntimeConfig):
    metric: bool  # heights in meters instead of feet

    @classmethod
    def from_sources(cls, argv=None, environ=None):
        args = _argv(argv)
        env = _environ(environ)
        base = RuntimeConfig.from_sources(args, env)
        return cls(
            live=base.live,
            emoji=base.emoji,
            lang=base.lang,
            oneline=base.oneline,
            metric=(
                "--metric" in args
                or env.get("TIDES_UNITS", "").lower() == "metric"
            ),
        )

    @property
    def height_unit(self):
        return "m" if self.metric else "\u2032"

    def convert_height(self, ft):
        return ft * 0.3048 if self.metric else ft
