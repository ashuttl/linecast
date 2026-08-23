"""python -m linecast / linecast CLI entry point."""

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
  linecast completion  Print shell completion script (bash, zsh, fish, nushell)

Each command is also installed as a standalone binary (weather, sunshine,
moon, tides, radar, maps). Run any command with --help for options.
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
}


def main():
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
        print(f"Run 'linecast --help' for usage.", file=sys.stderr)
        sys.exit(1)

    # Shift argv so the subcommand sees itself as argv[0]
    sys.argv = [f"linecast {cmd}"] + args[1:]

    import importlib
    mod = importlib.import_module(COMMANDS[cmd])
    mod.main()


if __name__ == "__main__":
    main()
