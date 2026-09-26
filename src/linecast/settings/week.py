"""Show or set the day the week opens on in the moon's calendar.

Usage: linecast week [show]
       linecast week monday
       linecast week sunday
       linecast week saturday
       linecast week auto

Precedence: --week-start flag > LINECAST_WEEK_START env > saved week
(this command) > default (Sunday in the countries whose printed
calendars open on it, Saturday in Egypt and the Gulf, Monday
everywhere else; judged by the saved location or the machine's IP).
"""

import argparse
import os

from linecast._commands import formatter_class
from linecast._runtime import WEEK_STARTS, VersionAction, resolve_week_start
from linecast._config import read_config, save_config, saved_week_start


def _cmd_show():
    """What the next run will use, and why."""
    from linecast._location import own_country
    country = own_country()
    week, source = resolve_week_start(None, os.environ, country)
    if source == "auto":
        where = country or "country unknown, so monday"
        print(f"{week}  [auto: {where}]")
        print("Run 'linecast week monday', 'linecast week sunday', or "
              "'linecast week saturday' to fix it.")
    elif source == "config":
        print(f"{week}  [fixed]")
        print("Run 'linecast week auto' to return to the default.")
    else:
        print(f"{week}  [{source}]")
        saved = saved_week_start()
        if saved is not None:
            print(f"The saved setting ({saved}) is overridden by {source}.")


def _cmd_set(week):
    config = read_config()
    config["week"] = week
    save_config(config)
    print(f"Week set to open on {week}")


def _cmd_auto():
    config = read_config()
    if config.pop("week", None) is not None:
        save_config(config)
    print("Week set to auto (follows the country)")


def main():
    parser = argparse.ArgumentParser(
        prog="linecast week",
        usage="%(prog)s [show | monday | sunday | saturday | auto]",
        description="Show or set the day the moon calendar's week opens on",
        formatter_class=formatter_class(),
    )
    parser.add_argument("--version", action=VersionAction)
    sub = parser.add_subparsers(dest="action")
    sub.add_parser("show", help="show the current week setting (default)")
    sub.add_parser("monday", help="open the week on Monday everywhere")
    sub.add_parser("sunday", help="open the week on Sunday everywhere")
    sub.add_parser("saturday", help="open the week on Saturday everywhere")
    sub.add_parser("auto", help="clear the saved week and use the default")
    args = parser.parse_args()

    if args.action in WEEK_STARTS:
        _cmd_set(args.action)
    elif args.action == "auto":
        _cmd_auto()
    else:
        _cmd_show()


if __name__ == "__main__":
    main()
