"""Show or set the digits numbers are written in.

Usage: linecast digits [show]
       linecast digits latin
       linecast digits native
       linecast digits auto

Precedence: LINECAST_DIGITS env > saved digits (this command) > default
(the language's own digits where it has them, which is Persian today;
0-9 otherwise). JSON output keeps ASCII digits whatever this says.
"""

import argparse
import os

from linecast._bidi import DIGITS_CHOICES, resolve_digits
from linecast._commands import formatter_class
from linecast._config import read_config, save_config, saved_digits
from linecast._runtime import VersionAction, resolve_lang

_NATURAL = "the language's own digits where it has them, 0-9 otherwise"
_SET = {
    "latin": "Digits set to 0-9 in every language",
    "native": "Digits set to each language's own, where it has them",
}


def _cmd_show():
    """What the next run will use, and why."""
    lang, _source = resolve_lang(None, os.environ)
    choice, source = resolve_digits(lang)
    if source == "auto":
        print(f"{choice}  [auto: {_NATURAL}]")
        print("Run 'linecast digits latin' or 'linecast digits native' "
              "to fix it.")
    elif source == "config":
        print(f"{choice}  [fixed]")
        print("Run 'linecast digits auto' to follow the language again.")
    else:
        print(f"{choice}  [{source}]")
        saved = saved_digits()
        if saved is not None:
            print(f"The saved setting ({saved}) is overridden by {source}.")


def _cmd_set(choice):
    config = read_config()
    config["digits"] = choice
    save_config(config)
    print(_SET[choice])


def _cmd_auto():
    config = read_config()
    if config.pop("digits", None) is not None:
        save_config(config)
    print(f"Digits set to auto ({_NATURAL})")


def main():
    parser = argparse.ArgumentParser(
        prog="linecast digits",
        usage="%(prog)s [show | latin | native | auto]",
        description="Show or set the digits numbers are written in",
        formatter_class=formatter_class(),
    )
    parser.add_argument("--version", action=VersionAction)
    sub = parser.add_subparsers(dest="action")
    sub.add_parser("show", help="show the current digits setting (default)")
    sub.add_parser("latin", help="0-9 in every language")
    sub.add_parser("native",
                   help="the language's own digits (Persian ۰-۹ in Persian); "
                        "languages without their own are unaffected")
    sub.add_parser("auto", help="clear the saved setting and follow the language")
    args = parser.parse_args()

    if args.action in DIGITS_CHOICES:
        _cmd_set(args.action)
    elif args.action == "auto":
        _cmd_auto()
    else:
        _cmd_show()


if __name__ == "__main__":
    main()
