"""python -m linecast / linecast CLI entry point."""

import os
import sys
from linecast._completion import available_shells, completion_help, render_completion

HELP = """\
linecast {version} — weather, sunlight, tides, radar, the Moon, and maps for the terminal

Commands:
  linecast weather     Weather dashboard with braille temperature curve and alerts
  linecast sunshine    Solar arc inspired by the Apple Watch Solar face
  linecast moon        Moon phase, illumination, and rise/set times
  linecast tides       Tide chart with braille rendering (NOAA, CHS, QLD + global model)
  linecast radar       Weather radar over a braille basemap (US + global)
  linecast maps        Street and terrain maps: vector streets or hillshaded relief
  linecast location    Show or set a fixed location (overrides IP geolocation)
  linecast units       Show or set preferred units (metric or imperial)
  linecast clock       Show or set the clock style (12-hour or 24-hour)
  linecast icons       Show or set the icon set (nerd, emoji, or plain)
  linecast calendar    Show or set the moon calendar (chinese, japanese, korean, hawaiian, almanac)
  linecast link        Make the short commands (weather, moon, …) as links to linecast
  linecast doctor      Show where files live, what the terminal supports, and which providers answer
  linecast completion  Print shell completion script (bash, zsh, fish, nushell)

Prefer the short spellings? `linecast link` makes them, or a shell
alias (alias weather='linecast weather') runs the command directly.
Run any command with --help for options.
"""

COMMANDS = {
    "weather": "linecast.weather",
    "sunshine": "linecast.sunshine",
    "moon": "linecast.moon",
    "tides": "linecast.tides",
    "radar": "linecast.radar",
    "maps": "linecast.maps",
    "location": "linecast.location",
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
