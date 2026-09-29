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

import os

from linecast._runtime import resolve_units
from linecast._config import saved_units
from linecast.settings._command import forget, remember, run, show


def _cmd_show():
    """What the next run will use, and why."""
    from linecast._location import own_country
    country = own_country()
    units, source = resolve_units(None, os.environ, "WEATHER_UNITS", country)
    show(units, source,
         (f"auto: {country or 'country unknown, so metric'}",
          "Run 'linecast units metric' or 'linecast units imperial' to fix it."),
         "Run 'linecast units auto' to return to the default.",
         saved_units())


def _cmd_set(units):
    remember("units", units)
    if units == "metric":
        print("Units set to metric (celsius, km/h or m/s, mm, metres)")
    else:
        print("Units set to imperial (fahrenheit, mph, inches, feet)")


def _cmd_auto():
    forget("units")
    print("Units set to auto (metric; imperial in the US)")


def main():
    run("linecast units", "%(prog)s [show | metric | imperial | auto]",
        "Show or set the preferred measurement units",
        (("show", "show the current units setting (default)"),
         ("metric", "celsius, km/h (m/s in some languages), mm, and metres everywhere"),
         ("imperial", "fahrenheit, mph, inches, and feet everywhere"),
         ("auto", "clear the saved units and use your country's")),
        _cmd_set, _cmd_auto, _cmd_show)


if __name__ == "__main__":
    main()
