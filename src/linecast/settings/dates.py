"""Show or set the calendar dates are written in.

Usage: linecast dates [show]
       linecast dates gregorian
       linecast dates solar-hijri
       linecast dates auto

Precedence: LINECAST_DATES env > saved dates (this command) > default
(the Solar Hijri calendar with --lang fa, the Gregorian otherwise).
JSON output keeps ISO Gregorian dates whatever this says.
"""

import argparse
import os

from linecast.astro.calendars.civil import DATES_CHOICES, SOLAR_HIJRI, resolve_dates
from linecast._commands import formatter_class
from linecast._config import read_config, save_config, saved_dates
from linecast._runtime import VersionAction, resolve_lang

_NATURAL = "solar-hijri with --lang fa, gregorian otherwise"


def _spelling(calendar):
    return "solar-hijri" if calendar == SOLAR_HIJRI else "gregorian"


def _cmd_show():
    """What the next run will use, and why."""
    lang, _source = resolve_lang(None, os.environ)
    calendar, source = resolve_dates(lang)
    if source == "auto":
        print(f"{_spelling(calendar)}  [auto: {_NATURAL}]")
        print("Run 'linecast dates gregorian' or 'linecast dates solar-hijri' "
              "to fix it.")
    elif source == "config":
        print(f"{_spelling(calendar)}  [fixed]")
        print("Run 'linecast dates auto' to follow the language again.")
    else:
        print(f"{_spelling(calendar)}  [{source}]")
        saved = saved_dates()
        if saved is not None:
            print(f"The saved setting ({saved}) is overridden by {source}.")


def _cmd_set(choice):
    config = read_config()
    config["dates"] = choice
    save_config(config)
    print(f"Dates set to the {choice} calendar in every language")


def _cmd_auto():
    config = read_config()
    if config.pop("dates", None) is not None:
        save_config(config)
    print(f"Dates set to auto ({_NATURAL})")


def main():
    parser = argparse.ArgumentParser(
        prog="linecast dates",
        usage="%(prog)s [show | gregorian | solar-hijri | auto]",
        description="Show or set the calendar dates are written in",
        formatter_class=formatter_class(),
    )
    parser.add_argument("--version", action=VersionAction)
    sub = parser.add_subparsers(dest="action")
    sub.add_parser("show", help="show the current dates setting (default)")
    sub.add_parser("gregorian", help="Gregorian dates in every language")
    sub.add_parser("solar-hijri",
                   help="Solar Hijri dates, Iran's civil calendar, in every "
                        "language")
    sub.add_parser("auto", help="clear the saved setting and follow the language")
    args = parser.parse_args()

    if args.action in DATES_CHOICES:
        _cmd_set(args.action)
    elif args.action == "auto":
        _cmd_auto()
    else:
        _cmd_show()


if __name__ == "__main__":
    main()
