"""Show or set the traditional calendar the moon command follows.

The module is calendar_cmd, not calendar, so that running a file in
this package as a script never shadows the standard library's calendar
module; the command is still `linecast calendar`, via __main__'s map.

Usage: linecast calendar [show]
       linecast calendar chinese | japanese | korean | thai | hawaiian | almanac
       linecast calendar none
       linecast calendar auto

Precedence: moon's --calendar flag > this setting > the calendar
native to the UI language (--lang zh, ja, ko, or th) > none.
"""

import argparse

from linecast._config import read_config, save_config, saved_calendar
from linecast._runtime import VersionAction

_NATURAL = ("chinese with --lang zh, japanese with ja, "
            "korean with ko, thai with th; none otherwise")


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
              "'thai', 'hawaiian', or 'almanac' to fix one.")


def _cmd_set(choice):
    config = read_config()
    config["calendar"] = choice
    save_config(config)
    if choice == "none":
        print("Calendar turned off; the moon panel keeps the phase lines only")
    elif choice == "hawaiian":
        print("Calendar set to hawaiian: the moon names each night — "
              "the pō mahina, its anahulu, and its counsel — in every "
              "language")
    elif choice == "thai":
        print("Calendar set to thai: the moon shows its lunar date, "
              "the coming \u0e27\u0e31\u0e19\u0e1e\u0e23\u0e30, and the next festival in every "
              "language")
    elif choice == "almanac":
        print("Calendar set to almanac: the moon shows the Old Farmer's "
              "gardening rule and the day's solunar periods in every "
              "language")
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
    sub.add_parser("thai",
                   help="จันทรคติไทย — the Suriyayart arithmetic, with "
                        "วันพระ and festivals")
    sub.add_parser("hawaiian",
                   help="Kaulana Mahina — nights counted from the first "
                        "visible crescent over Hawaiʻi")
    sub.add_parser("almanac",
                   help="Old Farmer's Almanac — gardening by the moon "
                        "and solunar periods")
    sub.add_parser("none", help="no calendar lines, whatever the language")
    sub.add_parser("auto", help="clear the saved calendar and follow the language")
    args = parser.parse_args()

    if args.action in ("chinese", "japanese", "korean", "thai",
                       "hawaiian", "almanac", "none"):
        _cmd_set(args.action)
    elif args.action == "auto":
        _cmd_auto()
    else:
        _cmd_show()


if __name__ == "__main__":
    main()
