"""python -m linecast / linecast CLI entry point."""

import sys
from linecast import __version__

HELP = f"""\
linecast {__version__} — terminal weather, solar arc, and tide visualizations

Commands:
  linecast weather     Weather dashboard with braille temperature curve and alerts
  linecast sunshine    Solar arc inspired by the Apple Watch Solar face
  linecast tides       NOAA tide chart with half-block rendering

Each command is also installed as a standalone binary (weather, sunshine, tides).
Run any command with --help for options.
"""

COMMANDS = {
    "weather": "linecast.weather",
    "sunshine": "linecast.sunshine",
    "tides": "linecast.tides",
}


def main():
    args = sys.argv[1:]

    if not args or args[0] in ("-h", "--help"):
        print(HELP.rstrip())
        sys.exit(0)

    if args[0] in ("-v", "--version"):
        print(f"linecast {__version__}")
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
