"""What a command runs with: the settings its flags resolve to.

The resolvers settle the units, the wind units, the clock, the first
day of the week, the language and the icons from the flags (parsed by
_parsers.py), the environment, config.json and the country;
RuntimeConfig is what a command's main() makes of them, and
current_runtime() hands it to the helpers called without one."""

from dataclasses import dataclass
import os
import re
import sys

from linecast import _config
from linecast._config import SETTING, chosen, saved
from linecast._i18n import LOCALE_CODES
from linecast._log import UserError, debug_enabled, debug_log, set_debug
from linecast._parsers import base_parser, tides_parser, weather_parser


def install_banner():
    """A one-line install hint shown when running from a temporary venv (get.sh)."""
    if not os.environ.get("LINECAST_TEMP"):
        return ""
    from linecast.terminal.color import fg, RESET
    from linecast.terminal.theme import ensure_contrast, neutral_tone, theme_bg, theme_fg
    text = fg(*ensure_contrast(theme_fg, theme_bg, minimum=4.5))
    muted = fg(*ensure_contrast(neutral_tone(0.48), theme_bg, minimum=2.5))
    sep = f"{muted} · "
    return f" {text}linecast{sep}{muted}pip install linecast{sep}github.com/ashuttl/linecast{RESET}"


def _environ(environ=None):
    return os.environ if environ is None else environ


def env_truthy(value):
    return str(value).lower() in ("1", "true", "yes")


# The terminal answers linecast's probes -- its palette, the width it
# draws a glyph at -- in microseconds when it is the same machine.  Over
# SSH the answer waits on the link, and a probe that gives up too early
# leaves linecast guessing at what it could have known.  Waiting longer
# there costs nothing when the terminal answers: the answer ends the wait.
_SSH_ENV = ("SSH_CONNECTION", "SSH_TTY", "SSH_CLIENT")


def over_ssh(environ=None):
    """Whether this session arrived over SSH."""
    env = _environ(environ)
    return any(str(env.get(name, "")).strip() for name in _SSH_ENV)


def probe_timeout_s(env_var, default_ms, ssh_ms=None, limit_ms=2000, environ=None):
    """Seconds to wait for the terminal to answer a probe."""
    env = _environ(environ)
    default = ssh_ms if (ssh_ms is not None and over_ssh(env)) else default_ms
    raw = str(env.get(env_var, "")).strip()
    try:
        ms = int(raw) if raw else default
    except ValueError:
        ms = default
    return max(10, min(limit_ms, ms)) / 1000.0


# ---------------------------------------------------------------------------
# Units and clock preferences
# ---------------------------------------------------------------------------
_UNSET = object()  # "look the country up yourself" default for the resolvers

# argv[0] as the process started, before dispatch renames it to
# "linecast <command>"; `linecast link` needs the binary's own path.
INVOKED_AS = None


def default_units(country):
    """The units for a user who has expressed no preference."""
    return "imperial" if country == "US" else "metric"


# Countries where the 12-hour clock is the everyday written form: a
# timetable, a shop sign or a weather report there says 6:50 pm, not
# 18:50.  Everywhere else the 24-hour clock is the default.
TWELVE_HOUR_COUNTRIES = frozenset((
    "US", "CA", "AU", "NZ", "PH", "IN", "PK", "BD", "MY", "EG", "SA",
))


def default_clock(country=None):
    """The clock style for a user who has expressed no preference."""
    return "12" if country in TWELVE_HOUR_COUNTRIES else "24"


WEEK_START_WEEKDAY = {"monday": 0, "saturday": 5, "sunday": 6}  # date.weekday()

SUNDAY_FIRST_COUNTRIES = frozenset((
    "US", "CA", "BR", "MX", "IL", "IN", "JP", "KR", "PH", "SA", "TW", "HK", "ZA",
))
SATURDAY_FIRST_COUNTRIES = frozenset((
    "AE", "AF", "BH", "DJ", "DZ", "EG", "IQ", "IR", "JO", "KW", "LY", "OM",
    "QA", "SD", "SY",
))


def default_week_start(country=None):
    """The first day of the week for a user who has expressed no preference."""
    if country in SUNDAY_FIRST_COUNTRIES:
        return "sunday"
    if country in SATURDAY_FIRST_COUNTRIES:
        return "saturday"
    return "monday"


def resolve_units(namespace=None, environ=None, legacy_env="WEATHER_UNITS",
                  country=_UNSET):
    """The units for this run, and where they came from.

    Returns ("metric" | "imperial", source); source is "flag", the
    winning env var's name, "config", or "auto".  Precedence:
    --metric/--imperial flags, the command's own env var (WEATHER_UNITS /
    TIDES_UNITS), LINECAST_UNITS, the `units` key in config.json, then
    the default for *country* -- the user's own, looked up offline via
    own_country() unless the caller already knows it.
    """
    env = _environ(environ)
    if namespace is not None:
        if getattr(namespace, "imperial", False):
            return "imperial", "flag"
        if getattr(namespace, "metric", False):
            return "metric", "flag"
    value, source = chosen("units", env, before=legacy_env)
    if value is not None:
        return value, source
    if country is _UNSET:
        from linecast._location import own_country
        country = own_country()
    return default_units(country), "auto"


def resolve_clock(namespace=None, environ=None, country=_UNSET):
    """The clock style for this run, and where it came from.

    Returns ("12" | "24", source); source is "flag", "LINECAST_CLOCK",
    "config", or "auto".  Precedence: --12h/--24h flags, LINECAST_CLOCK,
    the `clock` key in config.json (`linecast clock 12|24`), then the
    default for *country*, looked up as resolve_units does.
    """
    env = _environ(environ)
    if namespace is not None and getattr(namespace, "clock", None) in SETTING["clock"].choices:
        return namespace.clock, "flag"
    value, source = chosen("clock", env)
    if value is not None:
        return value, source
    if country is _UNSET:
        from linecast._location import own_country
        country = own_country()
    return default_clock(country), "auto"


def default_wind_unit(metric, lang):
    """The wind unit for a user who has asked for none: mph with
    imperial units, else m/s in the languages whose forecasts give wind
    that way (Japanese, Korean, the Nordic languages, Russian,
    Ukrainian, Czech, Slovak), else km/h."""
    if not metric:
        return "mph"
    from linecast._i18n import setting
    return setting(lang, "metric_wind")


def resolve_wind_units(namespace=None, environ=None, metric=True, lang="en"):
    """The unit wind speeds are fetched and shown in, and where it came
    from.

    Returns ("km/h" | "m/s" | "mph" | "kn", source); source is "flag",
    "LINECAST_WIND_UNITS", "config", or "auto".  Precedence:
    --wind-units, LINECAST_WIND_UNITS, the `wind` key in config.json
    (`linecast wind kn`), then default_wind_unit for the units and the
    language.
    """
    unit = SETTING["wind"].read(getattr(namespace, "wind_units", None))
    if unit is not None:
        return unit, "flag"
    unit, source = chosen("wind", _environ(environ))
    if unit is not None:
        return unit, source
    return default_wind_unit(metric, lang), "auto"


def resolve_week_start(namespace=None, environ=None, country=_UNSET):
    """The first day of the week for this run, and where it came from.

    Returns ("monday" | "sunday" | "saturday", source); source is "flag",
    "LINECAST_WEEK_START", "config", or "auto".  Precedence: --week-start,
    LINECAST_WEEK_START, the `week` key in config.json (`linecast week
    monday|sunday|saturday`), then the default for *country*, looked up
    as resolve_units does.
    """
    env = _environ(environ)
    if namespace is not None and getattr(namespace, "week_start", None) in SETTING["week"].choices:
        return namespace.week_start, "flag"
    value, source = chosen("week", env)
    if value is not None:
        return value, source
    if country is _UNSET:
        from linecast._location import own_country
        country = own_country()
    return default_week_start(country), "auto"


# The locale variables, in the order gettext consults them.  LANGUAGE is
# a colon-separated list of preferences; the other three name one locale.
LOCALE_VARS = ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG")


def language_of(value):
    """The language a locale-style value names, as the tables know it, or
    None.

    "fr", "fr-FR", "de_DE.UTF-8", and "EN_us" name their language in the
    leading letters; "nb_NO" and "nn_NO" name Norwegian.  A region names
    its variant where linecast has one: "pt_PT" is "pt-PT" and "fr_CA"
    is "fr-CA", while "pt_BR" and "fr_BE" are the base "pt" and "fr".
    Chinese is two scripts, told apart by the subtags: "zh_TW", "zh_HK",
    "zh_MO", and "zh-Hant" name the traditional, "zh", "zh_CN", "zh_SG",
    and "zh-Hans" the simplified.  "C", "POSIX", "C.UTF-8", and
    three-letter codes such as "fil_PH" name none linecast could act on,
    and neither does junk.
    """
    from linecast._i18n import canonical_language
    m = re.match(r"([a-z]+)((?:[-_][a-z0-9]+)*)", (value or "").strip().lower())
    if m is None or len(m.group(1)) != 2:
        return None
    return canonical_language(m.group(0))


def resolve_lang(namespace=None, environ=None):
    """The language for this run, and where it came from.

    Returns (code, source); source is "flag", "LINECAST_LANG", "config",
    the name of the locale variable that decided it (one of LOCALE_VARS),
    or "default".  Precedence: --lang, LINECAST_LANG, the `language` key
    in config.json (`linecast language fr`), the terminal's locale, then
    English.  A value that does not name a language is ignored.
    """
    env = _environ(environ)
    var = SETTING["language"].env
    candidates = (
        (getattr(namespace, "lang", None) if namespace is not None else None, "flag"),
        (env.get(var, ""), var),
    )
    # The flag and the variable are read as a locale is, "de_DE.UTF-8"
    # for de; config.json holds a code, as `linecast language` saves it
    for value, source in candidates:
        code = language_of(value)
        if code is not None:
            return code, source
    code = saved("language")
    if code is not None:
        return code, "config"
    # The first of LC_ALL, LC_MESSAGES, and LANG that is set is the
    # locale, as POSIX has it, so LC_ALL=C over a German LANG is English.
    # gettext reads the LANGUAGE list ahead of it, unless the locale is C
    # or POSIX, which ask for no language at all.
    name = next((var for var in LOCALE_VARS[1:] if env.get(var, "").strip()), None)
    locale = env[name].strip() if name else ""
    if not re.fullmatch(r"(c|posix)(\..*)?", locale.lower()):
        # The list is in order of preference, and gettext reads down it to
        # the first language it has words in: "ca:es" is Spanish.  One
        # linecast has no words in still stands ahead of English, for the
        # providers that publish in it: "hi:en" is Hindi.
        unspoken = None
        for value in env.get("LANGUAGE", "").split(":"):
            code = language_of(value)
            if code is None:
                continue
            if code in LOCALE_CODES:
                return (unspoken if code == "en" and unspoken else code), "LANGUAGE"
            unspoken = unspoken or code
        if unspoken is not None:
            return unspoken, "LANGUAGE"
    code = language_of(locale)
    if code is not None:
        return code, name
    return "en", "default"


def units_pref(env_var="WEATHER_UNITS", environ=None):
    """The user's explicit units preference, or None if they have none.

    Precedence: the command's env var (WEATHER_UNITS / TIDES_UNITS), then
    LINECAST_UNITS, then the `units` key in config.json
    (`linecast units metric|imperial`).
    """
    value, source = resolve_units(None, environ, env_var, country=None)
    return None if source == "auto" else value


def use_metric():
    """The resolved units of the running command, for render helpers
    called without a runtime (radar and maps)."""
    return current_runtime().metric


def _log_startup():
    """The first line of a --debug transcript: which build, and where
    its files live."""
    import platform
    from linecast import __version__
    from linecast._paths import cache_root
    debug_log(f"linecast {__version__}, python {platform.python_version()}, "
              f"{sys.platform} {platform.machine()}; cache {cache_root()}; "
              f"settings {_config.config_file()}")


# ---------------------------------------------------------------------------
# Live mode resolution
# ---------------------------------------------------------------------------
def _resolve_live(ns):
    """Live mode is on by default when stdout is a TTY.

    --print, --oneline, --prose and --json force static single-shot output.
    --live is accepted for backwards compatibility but is no longer needed.
    """
    if ns.print_mode or ns.oneline or ns.json_mode or getattr(ns, "prose", False):
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
def _interactive_utf8(stream):
    """Whether *stream* is an interactive UTF-8 terminal — the setting
    emoji are known to render in."""
    try:
        if not stream.isatty():
            return False
        return "utf" in (getattr(stream, "encoding", "") or "").lower()
    except Exception:
        return False


def default_icons(env, stream=None):
    """The icon set to assume when nothing was asked for.

    A terminal cannot be asked which font it renders with, so "does this
    user have a Nerd Font?" is unanswerable in general.  What is knowable:
    WezTerm, kitty (since 0.32) and Ghostty ship the Nerd Font symbols as
    a built-in fallback font, so the icons render there regardless of the
    configured font.

    Every other modern terminal draws emoji from a system fallback font,
    so an interactive UTF-8 stream gets the emoji set.  Plain Unicode is
    kept for the cases emoji cannot be trusted: output that is piped or
    redirected (stable single-cell widths, greppable), a stream whose
    encoding cannot carry emoji, TERM=dumb, and a console where no
    terminal identifies itself at all — TERM, TERM_PROGRAM and
    WT_SESSION all unset is the legacy Windows console, whose fonts
    have no emoji.
    """
    # A terminal's identity can remain in the environment after stdout is
    # redirected, so the stream wins first: automatic piped output is plain
    # regardless of which terminal launched the command.
    stream = sys.stdout if stream is None else stream
    if not _interactive_utf8(stream):
        return "plain"
    if env.get("TERM", "").lower() == "dumb":
        return "plain"

    # tmux and screen replace TERM_PROGRAM with their own name, so the
    # terminals' private variables, which the shell inherited before the
    # multiplexer started, are checked as well.
    if env.get("TERM_PROGRAM", "").lower() in ("wezterm", "ghostty"):
        return "nerd"
    if env.get("KITTY_WINDOW_ID") or env.get("WEZTERM_PANE") \
            or env.get("GHOSTTY_RESOURCES_DIR"):
        return "nerd"
    if not (env.get("TERM") or env.get("TERM_PROGRAM")
            or env.get("WT_SESSION")):
        return "plain"
    return "emoji"


def resolve_icons(namespace=None, environ=None):
    """The icon set for this run, and where it came from.

    Returns (set, source); source is "flag", "LINECAST_ICONS", "config"
    or "auto".  Precedence: --icons (and --emoji), LINECAST_ICONS, the
    `icons` key in config.json (`linecast icons nerd|emoji|plain`), then
    terminal detection.
    """
    env = _environ(environ)
    explicit = getattr(namespace, "icons", None)
    if explicit in SETTING["icons"].choices:
        return explicit, "flag"
    if getattr(namespace, "emoji", False):
        return "emoji", "flag"
    value, source = chosen("icons", env)
    if value is not None:
        return value, source
    return default_icons(env), "auto"


def _resolve_icons(namespace, env):
    return resolve_icons(namespace, env)[0]


@dataclass(frozen=True)
class RuntimeConfig:
    live: bool
    icons: str
    lang: str
    oneline: bool
    json_mode: bool = False  # machine-readable JSON output
    metric: bool = True      # resolved units, every command
    use_24h: bool = True     # resolved clock, every command
    week_start: str = "monday"  # resolved first day of the week
    width: str | None = None   # print viewport: cells or percentage
    height: str | None = None
    # --wind-units, LINECAST_WIND_UNITS or `linecast wind`; None leaves
    # wind_unit to the units and the language
    wind_choice: str | None = None

    # the parser whose defaults stand in before a main() has run
    _parser = staticmethod(lambda: base_parser("linecast", ""))
    # the command's own units env var, before LINECAST_UNITS; the
    # weather and tides runtimes name theirs, the rest have none
    _legacy_units_env = None

    @classmethod
    def from_sources(cls, namespace, environ=None, country=_UNSET):
        """Build the runtime from a parsed argparse namespace and the
        environment (os.environ unless *environ* is given).

        *country* feeds the units default; mains that have resolved the
        user's location call again with it (see resolve_units).
        """
        env = _environ(environ)
        if namespace.debug and not debug_enabled():
            set_debug(True)
            _log_startup()
        lang, _source = resolve_lang(namespace, env)
        units, _source = resolve_units(namespace, env, cls._legacy_units_env,
                                       country)
        clock, _source = resolve_clock(namespace, env, country)
        week_start, _source = resolve_week_start(namespace, env, country)
        wind, wind_source = resolve_wind_units(namespace, env, units == "metric", lang)
        return cls(
            live=_resolve_live(namespace),
            icons=_resolve_icons(namespace, env),
            lang=lang,
            oneline=namespace.oneline,
            json_mode=namespace.json_mode,
            metric=units == "metric",
            use_24h=clock == "24",
            week_start=week_start,
            width=namespace.width,
            height=namespace.height,
            wind_choice=None if wind_source == "auto" else wind,
        )

    @classmethod
    def defaults(cls, environ=None):
        """The runtime with no flags given."""
        return cls.from_sources(cls._parser().parse_args([]), environ)

    @property
    def wind_unit(self):
        """The unit wind speeds are fetched and shown in: the one asked
        for, else default_wind_unit's for the units and the language."""
        return self.wind_choice or default_wind_unit(self.metric, self.lang)

    @property
    def wind_unit_param(self):
        """`wind_unit` as Open-Meteo's wind_speed_unit parameter names it."""
        return {"km/h": "kmh", "m/s": "ms", "mph": "mph", "kn": "kn"}[self.wind_unit]

    def wind_kmh(self, speed):
        """A speed in the runtime's wind unit, in km/h: the thresholds
        that decide what is worth showing are written in km/h."""
        return speed * _KMH_PER[self.wind_unit]

    def wind_from_kmh(self, kmh):
        """A speed in km/h, in the runtime's wind unit."""
        return kmh / _KMH_PER[self.wind_unit]


_KMH_PER = {"km/h": 1.0, "m/s": 3.6, "mph": 1.609344, "kn": 1.852}  # km/h in one of each


@dataclass(frozen=True)
class WeatherRuntime(RuntimeConfig):
    _legacy_units_env = "WEATHER_UNITS"
    # Defaults required: the base class ends in defaulted fields.
    celsius: bool = True
    temp_range: str = "auto"
    shading: bool = True
    prose: bool = False

    _parser = staticmethod(weather_parser)

    @classmethod
    def from_sources(cls, namespace, environ=None, country=_UNSET):
        env = _environ(environ)
        base = super().from_sources(namespace, env, country)
        # --celsius / --fahrenheit override temperature independently
        if namespace.fahrenheit:
            celsius = False
        else:
            celsius = namespace.celsius or base.metric
        return cls(
            live=base.live,
            icons=base.icons,
            lang=base.lang,
            oneline=base.oneline,
            celsius=celsius,
            temp_range=namespace.temp_range,
            metric=base.metric,
            use_24h=base.use_24h,
            week_start=base.week_start,
            width=base.width,
            height=base.height,
            shading=(not namespace.no_shading
                     and not env_truthy(env.get("WEATHER_NO_SHADING", ""))),
            json_mode=base.json_mode,
            prose=namespace.prose,
            wind_choice=base.wind_choice,
        )

    @property
    def temp_unit(self):
        return "°C" if self.celsius else "°F"

    @property
    def precip_unit(self):
        return "mm" if self.metric else "″"


@dataclass(frozen=True)
class TidesRuntime(RuntimeConfig):
    _parser = staticmethod(tides_parser)
    _legacy_units_env = "TIDES_UNITS"

    @property
    def height_unit(self):
        return "m" if self.metric else "′"

    def convert_height(self, ft):
        return ft * 0.3048 if self.metric else ft


# ---------------------------------------------------------------------------
# The running command's runtime
# ---------------------------------------------------------------------------
_current = None


def print_viewport(size):
    """Apply the running command's print dimensions to an observed size.

    Resolve against the original terminal each time, so rebuilding a
    runtime after locating the user never compounds percentages.
    """
    if _current is None or _current.live:
        return size

    def resolve(value, observed):
        if value is None:
            return observed
        if value.endswith("%"):
            return max(1, int(observed * float(value[:-1]) / 100))
        return int(value)

    return os.terminal_size((resolve(_current.width, size[0]),
                             resolve(_current.height, size[1])))


def set_current(runtime):
    """Record the runtime main() resolved, for current_runtime()."""
    global _current
    _current = runtime
    from linecast.terminal import bidi as _bidi
    _bidi.configure(getattr(runtime, "lang", "en"))


def place_for(args, runtime, unknown="Could not determine location.", zone=False,
              name=False):
    """The place a view is for, as (lat, lng, country, label, runtime).

    It is the place --location names, else the user's own: the one
    saved, WEATHER_LOCATION, or the network's guess.  *label* is the
    geocoder's name for a place named with --location, else "".  With
    no --location the place is the user's own, so the units and the
    clock can follow its country: a runtime that a cold cache left
    without one is resolved again for it, and made current, before
    anything is fetched.  A place that cannot be found is a UserError
    saying *unknown*, which the main ends the run with, after any
    spinner's finally has cleared it.

    *zone* and *name* say the view will ask next for the place's time
    zone (location_tzinfo, for a pinned place) and its name in the
    runtime's language (place_label).  They are looked up here, beside
    the country lookup a first run waits on and beside each other,
    rather than one after another, and the view's own asks then find
    the answers kept: the zone for the run, the name in the reverse
    geocoder's cache, or its failure's hold.  The name is asked after
    the country, so that on a network that has stopped answering the
    hold spares it the same wait."""
    from linecast._location import country_for_defaults, resolve_location
    lat, lng, country, label = resolve_location(
        args.location, lang=runtime.lang, return_label=True)
    if lat is None:
        raise UserError(unknown)
    from linecast._fanout import Fanout
    fanout, lookups = Fanout(), []
    if zone:
        from linecast._location import location_is_pinned, location_tzinfo
        if location_is_pinned(args.location):
            lookups.append(fanout.submit(location_tzinfo, lat, lng))
    own = country_for_defaults(args.location, country, lat, lng)
    if name:
        from linecast._geocode import place_label
        lookups.append(fanout.submit(place_label, lat, lng, label, runtime.lang))
    for lookup in lookups:
        fanout.settle(lookup, "place lookup", tag="location", note="asked again by the view")
    if own:
        runtime = type(runtime).from_sources(args, country=own)
        set_current(runtime)
    return lat, lng, country, label, runtime


def current_runtime(cls=RuntimeConfig):
    """The runtime the running command resolved in main(), for render
    helpers called without one.  Before a main() has run -- the tests, or
    a helper imported on its own -- it is *cls* with no flags given."""
    if isinstance(_current, cls):
        return _current
    return cls.defaults()
