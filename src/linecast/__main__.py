"""python -m linecast / linecast CLI entry point."""

import os
import sys
from linecast._completion import available_shells, completion_help, render_completion

HELP = """\
linecast {version} — weather, sunlight, the moon, tides, radar, and maps for the terminal

  linecast weather     Conditions now, the day's temperature curve, the forecast, and alerts
  linecast sunshine    The sun's arc across the sky, dawn to dusk, or the whole year
  linecast moon        The moon as it looks tonight, its rise and set, and a month calendar
  linecast tides       Tide chart from the nearest station, or a global model where there is none
  linecast radar       Weather radar over a map, the last hour and the next
  linecast maps        Street maps, hillshaded terrain, and routes

Settings (run alone to show, give a value to set):
  linecast location    A fixed place, instead of the one your IP address suggests
  linecast language    en, fr, es, de, it, pt, nl, pl, no, sv, is, da, fi, ja, ko, zh, th, or id
  linecast units       metric or imperial
  linecast clock       12-hour or 24-hour
  linecast icons       nerd, emoji, or plain
  linecast calendar    Which calendar the moon follows: chinese, japanese, korean, thai,
                       hawaiian, samoan, chamorro, refaluwasch, islamic, hebrew, almanac, or none
  For one run, a flag: --location "Québec" or 41.88,-87.63, --lang fr, --imperial, --24h

Housekeeping:
  linecast link        Make weather, moon, … short commands beside linecast
  linecast doctor      Where files live, what the terminal supports, which providers answer
  linecast completion  Shell completion script for bash, zsh, fish, or nushell

Run any command with --help for options.
"""


def sky_now():
    """The Moon tonight, in one line, for the foot of the help page.

    The help page is where linecast introduces itself, and this is the
    one thing it can say about the sky without a place or a network:
    the phase is arithmetic on the clock. Nothing here is worth failing
    the help page over, so any trouble returns an empty string.
    """
    try:
        from datetime import datetime, timezone
        from types import SimpleNamespace
        from linecast._runtime import resolve_icons
        from linecast._ephemeris import moon_illuminated_fraction
        from linecast.sunshine import moon_phase
        now = datetime.now(timezone.utc)
        icons, _source = resolve_icons()
        _idx, name, icon = moon_phase(now, SimpleNamespace(icons=icons))
        return f"{icon} {name}, {moon_illuminated_fraction(now) * 100:.0f}% lit"
    except Exception:
        return ""


COMMANDS = {
    "weather": "linecast.weather",
    "sunshine": "linecast.sunshine",
    "moon": "linecast.moon",
    "tides": "linecast.tides",
    "radar": "linecast.radar",
    "maps": "linecast.maps",
    "location": "linecast.location",
    "language": "linecast.language",
    "units": "linecast.units",
    "clock": "linecast.clock",
    "icons": "linecast.icons",
    # calendar_cmd, not calendar: running any file in this package as a
    # script (python src/linecast/moon.py) puts the package directory
    # first on sys.path, where a calendar.py would shadow the standard
    # library module the rest of the code imports.
    "calendar": "linecast.calendar_cmd",
    "link": "linecast.link",
    "doctor": "linecast.doctor",
}

# The commands that answer to their own name as argv[0], for users and
# distro packages that link or copy the binary under a short name. Only
# these dispatch: the utility commands (location, units, doctor) have no
# standalone spelling to honour.
STANDALONE = ("weather", "sunshine", "moon", "tides", "radar", "maps")


def _run(cmd, args):
    # Shift argv so the subcommand sees itself as argv[0], keeping the
    # original where `linecast link` can find the binary.
    from linecast import _runtime
    _runtime.INVOKED_AS = sys.argv[0]
    sys.argv = [f"linecast {cmd}"] + list(args)
    import importlib
    mod = importlib.import_module(COMMANDS[cmd])
    mod.main()


def main():
    # A binary named for a command is that command: a symlink or copy
    # of the linecast binary called `weather` runs the weather command,
    # arguments untouched.  Distro packages ship the short commands as
    # symlinks to this binary, so a name some other package owns can be
    # left out without losing the command.  lower() and splitext cover
    # Windows, where the copy is weather.exe.
    prog = os.path.splitext(os.path.basename(sys.argv[0] or ""))[0].lower()
    if prog in STANDALONE:
        _run(prog, sys.argv[1:])
        return

    args = sys.argv[1:]

    # The version comes from importlib.metadata, which costs more than
    # the rest of this dispatch put together, so only the branches that
    # print it look it up.
    if not args or args[0] in ("-h", "--help"):
        from linecast import __version__
        print(HELP.format(version=__version__).rstrip())
        sky = sky_now()
        if sky:
            print()
            print(sky)
        sys.exit(0)

    if args[0] in ("-v", "--version"):
        from linecast import __version__
        print(f"linecast {__version__}")
        sys.exit(0)

    if args[0] == "completion":
        completion_args = args[1:]
        if not completion_args or completion_args[0] in ("-h", "--help"):
            print(completion_help())
            sys.exit(0)
        try:
            print(render_completion(completion_args[0]), end="")
        except ValueError:
            print(f"linecast completion: unknown shell '{completion_args[0]}'", file=sys.stderr)
            print(f"Expected one of: {', '.join(available_shells())}", file=sys.stderr)
            sys.exit(2)
        sys.exit(0)

    cmd = args[0]
    if cmd not in COMMANDS:
        print(f"linecast: unknown command '{cmd}'", file=sys.stderr)
        print("Run 'linecast --help' for usage.", file=sys.stderr)
        sys.exit(1)

    _run(cmd, args[1:])


if __name__ == "__main__":
    main()
