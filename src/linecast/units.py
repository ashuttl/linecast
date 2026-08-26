"""Show or set the preferred measurement units.

Usage: linecast units [show]
       linecast units metric
       linecast units imperial
       linecast units auto

Precedence for every command: --metric/--imperial (and weather's
--celsius/--fahrenheit) flags > WEATHER_UNITS / TIDES_UNITS env >
LINECAST_UNITS env > saved units (this command) > default (metric;
imperial in the United States, judged by the saved location or the
machine's IP).
"""

import argparse
import os

from linecast._runtime import VersionAction, resolve_units
from linecast._config import read_config, save_config, saved_units


def _cmd_show():
    """What the next run will use, and why."""
    from linecast._location import own_country
    country = own_country()
    units, source = resolve_units(None, os.environ, "WEATHER_UNITS", country)
    if source == "auto":
        where = country or "country unknown, so metric"
        print(f"{units}  [auto: {where}]")
        print("Run 'linecast units metric' or 'linecast units imperial' "
              "to fix it.")
    elif source == "config":
        print(f"{units}  [fixed]")
        print("Run 'linecast units auto' to return to the default.")
    else:
        print(f"{units}  [{source}]")
        saved = saved_units()
        if saved is not None:
            print(f"The saved setting ({saved}) is overridden by {source}.")


def _cmd_set(units):
    config = read_config()
    config["units"] = units
    save_config(config)
    if units == "metric":
        print("Units set to metric (celsius, km/h, mm, metres)")
    else:
        print("Units set to imperial (fahrenheit, mph, inches, feet)")


def _cmd_auto():
    config = read_config()
    if config.pop("units", None) is not None:
        save_config(config)
    print("Units set to auto (metric; imperial in the US)")


def main():
    parser = argparse.ArgumentParser(
        prog="linecast units",
        description="Show or set the preferred measurement units",
    )
    parser.add_argument("--version", action=VersionAction)
    sub = parser.add_subparsers(dest="action")
    sub.add_parser("show", help="show the current units setting (default)")
    sub.add_parser("metric", help="celsius, km/h, mm, and metres everywhere")
    sub.add_parser("imperial", help="fahrenheit, mph, inches, and feet everywhere")
    sub.add_parser("auto", help="clear the saved units and use the default")
    args = parser.parse_args()

    if args.action in ("metric", "imperial"):
        _cmd_set(args.action)
    elif args.action == "auto":
        _cmd_auto()
    else:
        _cmd_show()


if __name__ == "__main__":
    main()
