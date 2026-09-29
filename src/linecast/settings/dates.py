"""Show or set the calendar dates are written in.

Usage: linecast dates [show]
       linecast dates gregorian
       linecast dates solar-hijri
       linecast dates auto

Precedence: LINECAST_DATES env > saved dates (this command) > default
(the Solar Hijri calendar with --lang fa, the Gregorian otherwise).
JSON output keeps ISO Gregorian dates whatever this says.
"""

import os

from linecast.astro.calendars.civil import SOLAR_HIJRI, resolve_dates
from linecast._config import saved_dates
from linecast._runtime import resolve_lang
from linecast.settings._command import forget, remember, run, show

_NATURAL = "solar-hijri with --lang fa, gregorian otherwise"


def _spelling(calendar):
    return "solar-hijri" if calendar == SOLAR_HIJRI else "gregorian"


def _cmd_show():
    """What the next run will use, and why."""
    lang, _source = resolve_lang(None, os.environ)
    calendar, source = resolve_dates(lang)
    show(_spelling(calendar), source,
         (f"auto: {_NATURAL}",
          "Run 'linecast dates gregorian' or 'linecast dates solar-hijri' to fix it."),
         "Run 'linecast dates auto' to follow the language again.",
         saved_dates())


def _cmd_set(choice):
    remember("dates", choice)
    print(f"Dates set to the {choice} calendar in every language")


def _cmd_auto():
    forget("dates")
    print(f"Dates set to auto ({_NATURAL})")


def main():
    run("linecast dates", "%(prog)s [show | gregorian | solar-hijri | auto]",
        "Show or set the calendar dates are written in",
        (("show", "show the current dates setting (default)"),
         ("gregorian", "Gregorian dates in every language"),
         ("solar-hijri", "Solar Hijri dates, Iran's civil calendar, in every language"),
         ("auto", "clear the saved setting and follow the language")),
        _cmd_set, _cmd_auto, _cmd_show)


if __name__ == "__main__":
    main()
