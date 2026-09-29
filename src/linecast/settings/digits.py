"""Show or set the digits numbers are written in.

Usage: linecast digits [show]
       linecast digits latin
       linecast digits native
       linecast digits auto

Precedence: LINECAST_DIGITS env > saved digits (this command) > default
(the language's own digits where it has them, which is Persian today;
0-9 otherwise). JSON output keeps ASCII digits whatever this says.
"""

import os

from linecast.terminal.bidi import resolve_digits
from linecast._config import saved_digits
from linecast._runtime import resolve_lang
from linecast.settings._command import forget, remember, run, show

_NATURAL = "the language's own digits where it has them, 0-9 otherwise"
_SET = {
    "latin": "Digits set to 0-9 in every language",
    "native": "Digits set to each language's own, where it has them",
}


def _cmd_show():
    """What the next run will use, and why."""
    lang, _source = resolve_lang(None, os.environ)
    choice, source = resolve_digits(lang)
    show(choice, source,
         (f"auto: {_NATURAL}",
          "Run 'linecast digits latin' or 'linecast digits native' to fix it."),
         "Run 'linecast digits auto' to follow the language again.",
         saved_digits())


def _cmd_set(choice):
    remember("digits", choice)
    print(_SET[choice])


def _cmd_auto():
    forget("digits")
    print(f"Digits set to auto ({_NATURAL})")


def main():
    run("linecast digits", "%(prog)s [show | latin | native | auto]",
        "Show or set the digits numbers are written in",
        (("show", "show the current digits setting (default)"),
         ("latin", "0-9 in every language"),
         ("native", "the language's own digits (Persian ۰-۹ in Persian); "
                    "languages without their own are unaffected"),
         ("auto", "clear the saved setting and follow the language")),
        _cmd_set, _cmd_auto, _cmd_show)


if __name__ == "__main__":
    main()
