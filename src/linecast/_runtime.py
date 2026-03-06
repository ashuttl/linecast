"""Shared CLI/runtime option helpers."""

from dataclasses import dataclass
import os
import sys


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


@dataclass(frozen=True)
class RuntimeConfig:
    live: bool
    emoji: bool

    @classmethod
    def from_sources(cls, argv=None, environ=None):
        args = _argv(argv)
        env = _environ(environ)
        return cls(
            live="--live" in args,
            emoji="--emoji" in args or env.get("LINECAST_ICONS", "").lower() == "emoji",
        )


@dataclass(frozen=True)
class WeatherRuntime(RuntimeConfig):
    metric: bool
    shading: bool

    @classmethod
    def from_sources(cls, argv=None, environ=None):
        args = _argv(argv)
        env = _environ(environ)
        base = RuntimeConfig.from_sources(args, env)
        return cls(
            live=base.live,
            emoji=base.emoji,
            metric=(
                "--celsius" in args
                or "--metric" in args
                or env.get("WEATHER_UNITS", "").lower() == "metric"
            ),
            shading="--shading" in args or env_truthy(env.get("WEATHER_SHADING", "")),
        )

    @property
    def temp_unit(self):
        return "°C" if self.metric else "°F"

    @property
    def wind_unit(self):
        return "km/h" if self.metric else "mph"

    @property
    def precip_unit(self):
        return "mm" if self.metric else "in"
