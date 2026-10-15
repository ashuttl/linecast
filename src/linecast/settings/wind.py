"""Show or set the unit for wind speeds.

Usage: linecast wind [show]
       linecast wind km/h
       linecast wind m/s
       linecast wind mph
       linecast wind kn
       linecast wind auto

Precedence for weather and radar: --wind-units flag >
LINECAST_WIND_UNITS env > saved wind units (this command) > default
(mph with imperial units; with metric, m/s in the languages whose
forecasts give it, km/h in the rest).  The other spellings the flag
takes are taken here too: kmh, ms, knots.
"""

import os
import sys

from linecast._config import saved_wind_units, wind_unit_of
from linecast.settings._command import forget, remember, run, show


def _cmd_show():
    """What the next run will use, and why."""
    from linecast._location import own_country
    from linecast._runtime import resolve_lang, resolve_units, resolve_wind_units
    units, _source = resolve_units(None, os.environ, "WEATHER_UNITS", own_country())
    lang, _source = resolve_lang(None, os.environ)
    wind, source = resolve_wind_units(None, os.environ, units == "metric", lang)
    show(wind, source,
         (f"auto: {units} units, {lang}",
          "Run 'linecast wind km/h', 'linecast wind m/s', 'linecast wind mph', "
          "or 'linecast wind kn' to fix it."),
         "Run 'linecast wind auto' to return to the default.",
         saved_wind_units())


def _cmd_set(unit):
    remember("wind", unit)
    print(f"Wind speeds set to {unit}")


def _cmd_auto():
    forget("wind")
    print("Wind speeds set to auto (follows the units and the language)")


def main():
    run("linecast wind", "%(prog)s [show | km/h | m/s | mph | kn | auto]",
        "Show or set the unit for wind speeds in weather and radar",
        (("show", "show the current wind setting (default)"),
         ("km/h", "kilometers per hour, whatever the other units"),
         ("m/s", "meters per second, whatever the other units"),
         ("mph", "miles per hour, whatever the other units"),
         ("kn", "knots, whatever the other units"),
         ("auto", "clear the saved wind units and follow the units and the language")),
        _cmd_set, _cmd_auto, _cmd_show,
        argv=[wind_unit_of(arg) or arg for arg in sys.argv[1:]])


if __name__ == "__main__":
    main()
