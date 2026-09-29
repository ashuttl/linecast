"""Show or set the preferred clock style (12-hour or 24-hour).

Usage: linecast clock [show]
       linecast clock 12
       linecast clock 24
       linecast clock auto

Precedence for every command: --12h/--24h flags > LINECAST_CLOCK env >
saved clock (this command) > default (12-hour in the countries that
write it, judged by the saved location or the machine's IP; 24-hour
elsewhere).
"""

import os

from linecast._runtime import resolve_clock
from linecast._config import saved_clock
from linecast.settings._command import forget, remember, run, show


def _cmd_show():
    """What the next run will use, and why."""
    from linecast._location import own_country
    country = own_country()
    clock, source = resolve_clock(None, os.environ, country)
    saved = saved_clock()
    show(f"{clock}-hour", source,
         (f"auto: {country or 'country unknown, so 24-hour'}",
          "Run 'linecast clock 12' or 'linecast clock 24' to fix it."),
         "Run 'linecast clock auto' to return to the default.",
         saved and f"{saved}-hour")


def _cmd_set(clock):
    remember("clock", clock)
    print(f"Clock set to {clock}-hour")


def _cmd_auto():
    forget("clock")
    print("Clock set to auto (follows the country)")


def main():
    run("linecast clock", "%(prog)s [show | 12 | 24 | auto]",
        "Show or set the preferred clock style (12-hour or 24-hour)",
        (("show", "show the current clock setting (default)"),
         ("12", "12-hour clock everywhere"),
         ("24", "24-hour clock everywhere"),
         ("auto", "clear the saved clock and use your country's")),
        _cmd_set, _cmd_auto, _cmd_show)


if __name__ == "__main__":
    main()
