"""Show or set the traditional calendar the moon command follows.

The module is calendar_cmd, not calendar, so that running a file in
this package as a script never shadows the standard library's calendar
module; the command is still `linecast calendar`, via __main__'s map.

Usage: linecast calendar [show]
       linecast calendar chinese | japanese | korean | hawaiian
       linecast calendar none
       linecast calendar auto

Precedence: moon's --calendar flag > this setting > the calendar
native to the UI language (--lang zh, ja, or ko) > none.
"""

import argparse

from linecast._config import read_config, save_config, saved_calendar
from linecast._runtime import VersionAction

_NATURAL = ("chinese with --lang zh, japanese with ja, "
            "korean with ko; none otherwise")


def _cmd_show():
    saved = saved_calendar()
    if saved == "none":
        print("none  [fixed]")
        print("Run 'linecast calendar auto' to follow the language again.")
    elif saved is not None:
        print(f"{saved}  [fixed]")
        print("Run 'linecast calendar auto' to follow the language instead.")
    else:
        print(f"auto  [{_NATURAL}]")
        print("Run 'linecast calendar chinese', 'japanese', 'korean', "
              "or 'hawaiian' to fix one.")


def _cmd_set(choice):
    config = read_config()
    config["calendar"] = choice
    save_config(config)
    if choice == "none":
        print("Calendar turned off; the moon panel keeps the phase lines only")
    elif choice == "hawaiian":
        print("Calendar set to hawaiian: the moon names each night — "
              "the pō mahina and its anahulu — in every language")
    else:
        print(f"Calendar set to {choice}: the moon shows its lunar date, "
              f"solar term, and next festival in every language")


def _cmd_auto():
    config = read_config()
    if config.pop("calendar", None) is not None:
        save_config(config)
    print(f"Calendar set to auto ({_NATURAL})")


def main():
    parser = argparse.ArgumentParser(
        prog="linecast calendar",
        description="Show or set the traditional calendar the moon follows",
    )
    parser.add_argument("--version", action=VersionAction)
    sub = parser.add_subparsers(dest="action")
    sub.add_parser("show", help="show the current calendar setting (default)")
    sub.add_parser("chinese", help="农历 — months from new moons at UTC+8")
    sub.add_parser("japanese", help="旧暦 — the same rules at UTC+9")
    sub.add_parser("korean", help="음력 — the same rules at UTC+9")
    sub.add_parser("hawaiian",
                   help="Kaulana Mahina — nights counted from the first "
                        "visible crescent over Hawaiʻi")
    sub.add_parser("none", help="no calendar lines, whatever the language")
    sub.add_parser("auto", help="clear the saved calendar and follow the language")
    args = parser.parse_args()

    if args.action in ("chinese", "japanese", "korean", "hawaiian", "none"):
        _cmd_set(args.action)
    elif args.action == "auto":
        _cmd_auto()
    else:
        _cmd_show()


if __name__ == "__main__":
    main()
