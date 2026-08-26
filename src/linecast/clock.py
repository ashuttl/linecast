"""Show or set the preferred clock style (12-hour or 24-hour).

Usage: linecast clock [show]
       linecast clock 12
       linecast clock 24
       linecast clock auto

Precedence for every command: --12h/--24h flags > LINECAST_CLOCK env >
saved clock (this command) > default (24-hour).
"""

import argparse

from linecast._runtime import VersionAction
from linecast._config import read_config, save_config, saved_clock


def _cmd_show():
    clock = saved_clock()
    if clock is None:
        print("auto (24-hour; LINECAST_CLOCK still applies)")
        return
    print(f"{clock}-hour  [fixed]")
    print("Run 'linecast clock auto' to return to the default.")


def _cmd_set(clock):
    config = read_config()
    config["clock"] = clock
    save_config(config)
    print(f"Clock set to {clock}-hour")


def _cmd_auto():
    config = read_config()
    if config.pop("clock", None) is not None:
        save_config(config)
    print("Clock set to auto (24-hour by default)")


def main():
    parser = argparse.ArgumentParser(
        prog="linecast clock",
        description="Show or set the preferred clock style (12-hour or 24-hour)",
    )
    parser.add_argument("--version", action=VersionAction)
    sub = parser.add_subparsers(dest="action")
    sub.add_parser("show", help="show the current clock setting (default)")
    sub.add_parser("12", help="12-hour clock everywhere")
    sub.add_parser("24", help="24-hour clock everywhere")
    sub.add_parser("auto", help="clear the saved clock and use the default")
    args = parser.parse_args()

    if args.action in ("12", "24"):
        _cmd_set(args.action)
    elif args.action == "auto":
        _cmd_auto()
    else:
        _cmd_show()


if __name__ == "__main__":
    main()
