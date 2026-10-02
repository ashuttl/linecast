"""Every command's flags: the argparse parser each command's main() reads.

The view commands' parsers share _base_parser, which lays their help
pages out in sections; the settings and housekeeping commands build
their own beside their code, from VersionAction here and _commands'
formatter.  The shell completions are read from these parsers
(_completion.py), which is why they live together rather than in each
command's package: listing a command's flags does not import the
command.  Nothing imports this module until a command parses its
arguments, so `linecast` alone loads no argparse."""

import argparse
import sys

from linecast import _config
from linecast._commands import BLURB, formatter_class, parser_class
from linecast._config import HOURS_CHOICES, ICON_SETS, WEEK_STARTS
from linecast._i18n import LANGUAGE_CODES, VARIANTS


class VersionAction(argparse.Action):
    """`--version` that looks the package version up only when asked.

    argparse's stock action wants the string at parser-build time, which
    would resolve importlib.metadata on every run of every command.
    """

    def __init__(self, option_strings, dest, **kwargs):
        super().__init__(option_strings, dest=argparse.SUPPRESS,
                         default=argparse.SUPPRESS, nargs=0,
                         help="show program's version number and exit")

    def __call__(self, parser, namespace, values, option_string=None):
        from linecast import __version__
        # `linecast weather --version` is linecast's version; a parser
        # under another name (a symlink's) says whose it is.
        if parser.prog.split()[0] == "linecast":
            sys.stdout.write(f"linecast {__version__}\n")
        else:
            sys.stdout.write(f"{parser.prog} (linecast {__version__})\n")
        parser.exit()


def zoom_degrees(text):
    """A --zoom: degrees of latitude, a finite number above zero.  The
    views divide by it."""
    try:
        value = float(text)
    except ValueError:
        value = float("nan")
    if not 0 < value < float("inf"):
        raise argparse.ArgumentTypeError(f"expected degrees above 0, got {text!r}")
    return value


def _base_parser(prog, description, units=None, clock=False, json=False,
                 temperature_scale=False, oneline=True,
                 location_help="location as 'lat,lng' or place name"):
    """A view command's parser, with its help page in sections.

    --location opens the first section, "options", with *location_help*
    under it, and the command adds its own flags after it.  The flags
    every view shares follow in sections of their own, made here because
    argparse prints sections in the order they are made.  *units* is the
    pair of help strings for --metric and --imperial; *temperature_scale*
    adds --celsius and --fahrenheit beside them; *clock* adds --24h and
    --12h; *json* adds --json to the output section; *oneline* offers
    --oneline, for the views that have a line to give.
    """
    p = parser_class()(prog=prog, usage="%(prog)s [options]",
                       description=description, add_help=False,
                       formatter_class=formatter_class(),
                       epilog="In a live view, press ? for controls; Esc closes help.")
    title = {(True, True): "units, clock, and language",
             (True, False): "units and language",
             (False, True): "clock and language",
             (False, False): "language"}[(bool(units), clock)]
    locale = p.add_argument_group(title)
    if units:
        metric_help, imperial_help = units
        g = locale.add_mutually_exclusive_group()
        g.add_argument("--metric", action="store_true", help=metric_help)
        g.add_argument("--imperial", action="store_true", help=imperial_help)
    if temperature_scale:
        locale.add_argument("--celsius", action="store_true",
                            help="celsius temperatures, whatever the other units")
        locale.add_argument("--fahrenheit", action="store_true",
                            help="fahrenheit temperatures, whatever the other units")
    if clock:
        # explicit dest: "12h" is not a Python identifier
        g = locale.add_mutually_exclusive_group()
        g.add_argument("--24h", dest="clock", action="store_const", const="24",
                       default=None, help="24-hour clock")
        g.add_argument("--12h", dest="clock", action="store_const", const="12",
                       help="12-hour clock")
    locale.add_argument("--lang", metavar="CODE", default=None,
                        help=f"{', '.join(LANGUAGE_CODES)}; or a regional "
                             f"variant: {', '.join(VARIANTS)}\n"
                             "The language linecast speaks. Default: the terminal's; "
                             "'linecast language' saves one")
    looks = p.add_argument_group("icons and colours")
    looks.add_argument("--icons", choices=ICON_SETS, default=None,
                       help="Nerd Font glyphs, standard emoji, or plain "
                            "Unicode. Default: what the terminal can show; "
                            "'linecast icons' saves one")
    looks.add_argument("--emoji", action="store_true",
                       help="same as --icons emoji")
    looks.add_argument("--classic-colors", action="store_true",
                       help="a fixed palette, instead of one matched to the "
                            "terminal's colours")
    # the old name, still taken, not offered
    looks.add_argument("--legacy-colors", action="store_true",
                       help=argparse.SUPPRESS)
    output = p.add_argument_group("output")
    output.add_argument("--print", dest="print_mode", action="store_true",
                        help="print once, instead of the live view")
    # live is the default in a terminal; the flag is still taken
    output.add_argument("--live", action="store_true", help=argparse.SUPPRESS)
    if oneline:
        output.add_argument("--oneline", action="store_true",
                            help="a single line, for a status bar or prompt")
    else:
        p.set_defaults(oneline=False)
    if json:
        output.add_argument("--json", dest="json_mode", action="store_true",
                            help="machine-readable JSON output (implies --print)")
    else:
        p.set_defaults(json_mode=False)
    other = p.add_argument_group("other")
    other.add_argument("-h", "--help", action="help", default=argparse.SUPPRESS,
                       help="show this help message and exit")
    other.add_argument("--version", action=VersionAction)
    other.add_argument("--debug", action="store_true",
                       help="show diagnostic info on stderr")
    # Last to be added, so the completions list it where they always
    # have; first in "options", which is where the help prints it.
    p.add_argument("--location", metavar="PLACE", default=None, help=location_help)
    return p


def refuse_view_flag(parser, flag, runtime, describes="today"):
    """End the run with a usage error when *flag*, which opens on another
    view (--year, --month), comes with --json or --oneline.  Those give
    one moment and have no form of the other view, so the pair is a
    mistake worth naming rather than a flag to drop on the floor."""
    if runtime.json_mode or runtime.oneline:
        mode = "--json" if runtime.json_mode else "--oneline"
        parser.error(f"{flag} has no {mode} output "
                     f"({flag} is a view; {mode} describes {describes})")


# What the weather temperature graph spans; the first is the default.
TEMP_RANGES = ("auto", "climate", "forecast", "world")


def weather_parser():
    p = _base_parser("linecast weather", BLURB["weather"],
                      units=("metric units: celsius, km/h (m/s in the languages "
                             "that use it), mm",
                             "imperial units: fahrenheit, mph, inches"),
                      temperature_scale=True, clock=True, json=True)
    p.add_argument("--search", metavar="QUERY", default=None,
                    help="search for a location and exit")
    p.add_argument("--temp-range", dest="temp_range",
                    choices=TEMP_RANGES, default=TEMP_RANGES[0],
                    help="the temperature graph's scale: a typical year here "
                         "(climate), this forecast alone (forecast), or -40 "
                         "to 50°C (world). Default: auto, which is climate "
                         "when the window is tall enough for it")
    p.add_argument("--no-shading", action="store_true",
                    help="no day and night shading behind the hourly graph")
    p.add_argument("--year", action="store_true",
                    help="open on the year view: this year's highs, lows, "
                         "and precipitation against the past ten years "
                         "(v flips between the views)")
    return p


def tides_parser():
    p = _base_parser("linecast tides", BLURB["tides"],
                      units=("heights in meters", "heights in feet"),
                      clock=True, json=True,
                      location_help="find the nearest station to 'lat,lng' or a "
                                    "place name instead of your location")
    p.add_argument("--station", default=None,
                    help="station ID or name (any provider)")
    p.add_argument("--search", metavar="QUERY", nargs="?", const="", default=None,
                    help="search for a station and exit "
                         "(no query: list nearest stations)")
    p.add_argument("--nearby", action="store_true",
                    help="list the nearest tide stations and exit")
    views = p.add_mutually_exclusive_group()
    views.add_argument("--month", dest="view", action="store_const", const="month",
                       default="day",
                       help="open on the month view: a row for each day's tides "
                            "(v cycles through the views)")
    views.add_argument("--year", dest="view", action="store_const", const="year",
                       help="open on the year view: predicted daily ranges and "
                            "measured extremes, where available; requires a "
                            "source with year-round predictions")
    views.add_argument("--makeup", dest="view", action="store_const", const="makeup",
                       help="open on what moves the tide: its causes through "
                            "the month, year, and Moon's long cycle; requires a "
                            "source with year-round predictions")
    return p


def sunshine_parser():
    p = _base_parser("linecast sunshine", BLURB["sunshine"], clock=True, json=True)
    p.add_argument("--year", action="store_true",
                    help="open on the year view: each day of the year as "
                         "a column of day and night sky (v flips between "
                         "the views)")
    p.add_argument("--dst", action="store_true",
                    help="in the year view, show clock changes as steps, "
                         "each day in its own UTC offset (default: today's "
                         "offset all year)")
    p.add_argument("--hours", metavar="SYSTEM", choices=HOURS_CHOICES, default=None,
                    help="halachic, halachic-mga, roman, japanese, islamic, "
                         "swahili, or none\n"
                         "Reads the day in a tradition's hours. The prayer "
                         "times by a named convention or school, such as "
                         "islamic-mwl, are listed in 'linecast hours --help'. "
                         "Default: your language's own, if any; 'linecast "
                         "hours' saves one")
    return p


def moon_parser():
    p = _base_parser("linecast moon", BLURB["moon"], clock=True, json=True)
    p.add_argument("--month", action="store_true",
                    help="open on the month view: a calendar of the "
                         "month's phases (v flips between the views)")
    # the old name, still taken, not offered
    p.add_argument("--grid", dest="month", action="store_true",
                    help=argparse.SUPPRESS)
    calendars = _config.CALENDAR_CHOICES
    p.add_argument("--calendar", metavar="NAME", choices=calendars, default=None,
                    help=f"{', '.join(calendars[:-1])}, or {calendars[-1]}\n"
                         "Adds a traditional calendar and its festivals, or "
                         "the Old Farmer's Almanac. Default: your language's "
                         "own calendar, if any; 'linecast calendar' saves one")
    p.add_argument("--week-start", choices=WEEK_STARTS, default=None,
                    help="the day the month view's week opens on. Default: "
                         "whichever your country's calendars use; "
                         "'linecast week' saves one")
    return p


def sky_parser():
    p = _base_parser("linecast sky", BLURB["sky"], clock=True, json=True)
    p.add_argument("--facing", metavar="DIRECTION", default=None,
                    help="which way to look: a compass point (N, NE, E, …) "
                         "or a bearing in degrees (default: the Moon if it "
                         "is up, else a bright planet, else south)")
    p.add_argument("--at", metavar="OBJECT", default=None,
                    help="open on a sky object by name or catalog ID "
                         "(Vega, Jupiter, Orion, M31), zoomed to frame it")
    p.add_argument("--fov", metavar="DEGREES", type=float, default=None,
                    help="how many degrees of sky across the screen, 6 to "
                         "236 (default 110; zoom live with + and -)")
    p.add_argument("--culture", metavar="NAME", choices=_config.CULTURE_CHOICES, default=None,
                    help=f"{', '.join(_config.CULTURE_CHOICES[:-1])}, or "
                         f"{_config.CULTURE_CHOICES[-1]}\n"
                         "Draws another tradition's constellations and star "
                         "names in place of the IAU's; t steps through them "
                         "live. Default: your language's own sky, if any; "
                         "'linecast culture' saves one")
    return p


def radar_parser():
    p = _base_parser("linecast radar", BLURB["radar"],
                      units=("metric units: celsius, kilometres",
                             "imperial units: fahrenheit, miles"),
                      clock=True, oneline=False)
    p.add_argument("--search", metavar="QUERY", default=None,
                    help="search for a location and exit")
    p.add_argument("--zoom", metavar="DEGREES", type=zoom_degrees, default=6.0,
                    help="degrees of latitude shown top-to-bottom (default 6)")
    from linecast.radar.sources import THEMES
    themes = tuple(THEMES)
    p.add_argument("--theme", metavar="NAME", default=None,
                    help=f"{', '.join(themes[:-1])}, or {themes[-1]}\n"
                         "The radar's colours; t picks one live. Default: "
                         "terminal, in your terminal's own palette")
    p.add_argument("--layer", default=None,
                    help="radar or satellite, the hourly cloud mosaic; S "
                         "switches between them live. Default: radar")
    p.add_argument("--layers", default=None,
                    help="temp, wind, or temp,wind: the temperature as a "
                         "tint and the wind as arrows, over the radar; c "
                         "and W toggle them live")
    p.add_argument("--source", metavar="NAME", default=None,
                    help="librewxr, rainviewer, or iem (NEXRAD, US only): "
                         "one source for the frames, instead of the one "
                         "chosen for the place, to compare what each shows")
    return p


def maps_parser():
    p = _base_parser("linecast maps", BLURB["maps"],
                      units=("metric units: kilometres and metres",
                             "imperial units: miles and feet"),
                      oneline=False)
    p.add_argument("--search", metavar="QUERY", default=None,
                    help="search for a location and exit")
    # the default is per view and resolved in maps.main(): a street map
    # opens on a neighbourhood, terrain on a region
    p.add_argument("--zoom", metavar="DEGREES", type=zoom_degrees, default=None,
                    help="degrees of latitude shown top-to-bottom "
                         "(default 0.05 in street view, 4 in terrain)")
    p.add_argument("--view", choices=("street", "terrain", "now"),
                    default="street",
                    help="a street map, terrain relief, or now: the terrain "
                         "globe with daylight and clouds. Default: street")
    p.add_argument("--to", metavar="PLACE", default=None,
                    help="route to a place or 'lat,lng' from the origin")
    p.add_argument("--from", dest="from_", metavar="PLACE", default=None,
                    help="route from a place or 'lat,lng' "
                         "(default: your location)")
    p.add_argument("--profile", metavar="MODE", default="car",
                    help="car, bike, or foot: how to travel the route "
                         "(default car)")
    return p


def doctor_parser():
    """`linecast doctor` has none of the view flags, so it is not a
    _base_parser; --version is the same action."""
    p = argparse.ArgumentParser(
        prog="linecast doctor", formatter_class=formatter_class(),
        description="Show where linecast keeps its files, what it sees of "
                    "the terminal, and which providers answer")
    p.add_argument("--version", action=VersionAction)
    p.add_argument("--offline", action="store_true",
                    help="skip the provider probes")
    p.add_argument("--json", dest="json_mode", action="store_true",
                    help="the same report as one JSON object, for bug reports")
    p.add_argument("--debug", action="store_true",
                    help="show diagnostic info on stderr")
    return p
