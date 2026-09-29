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

import os

from linecast._runtime import resolve_week_start
from linecast._config import saved_week_start
from linecast.settings._command import forget, remember, run, show


def _cmd_show():
    """What the next run will use, and why."""
    from linecast._location import own_country
    country = own_country()
    week, source = resolve_week_start(None, os.environ, country)
    show(week, source,
         (f"auto: {country or 'country unknown, so monday'}",
          "Run 'linecast week monday', 'linecast week sunday', or "
          "'linecast week saturday' to fix it."),
         "Run 'linecast week auto' to return to the default.",
         saved_week_start())


def _cmd_set(week):
    remember("week", week)
    print(f"Week set to open on {week}")


def _cmd_auto():
    forget("week")
    print("Week set to auto (follows the country)")


def main():
    run("linecast week", "%(prog)s [show | monday | sunday | saturday | auto]",
        "Show or set the day the week opens on in the moon's month view",
        (("show", "show the current week setting (default)"),
         ("monday", "open the week on Monday everywhere"),
         ("sunday", "open the week on Sunday everywhere"),
         ("saturday", "open the week on Saturday everywhere"),
         ("auto", "clear the saved week and use your country's")),
        _cmd_set, _cmd_auto, _cmd_show)


if __name__ == "__main__":
    main()
