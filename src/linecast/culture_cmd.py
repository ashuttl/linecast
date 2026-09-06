"""Show or set the sky culture the sky command draws.

Usage: linecast culture [show]
       linecast culture chinese | hawaiian | norse | … (see --help)
       linecast culture none
       linecast culture auto

Precedence: sky's --culture flag > this setting > the culture native to
the UI language (--lang zh) > the IAU sky.
"""

import argparse

from linecast._config import (
    CULTURE_CHOICES, read_config, save_config, saved_culture,
)
from linecast._runtime import VersionAction

_NATURAL = "chinese with --lang zh; the IAU sky otherwise"


def _cmd_show():
    saved = saved_culture()
    if saved == "none":
        print("none  [fixed]")
        print("Run 'linecast culture auto' to follow the language again.")
    elif saved is not None:
        print(f"{saved}  [fixed]")
        print("Run 'linecast culture auto' to follow the language instead.")
    else:
        print(f"auto  [{_NATURAL}]")
        print("Run 'linecast culture NAME' to fix one; 'linecast culture --help' "
              "lists them.")


def _cmd_set(choice):
    from linecast._runtime import resolve_lang
    from linecast._sky_catalogue import culture_title
    lang = resolve_lang()[0]
    config = read_config()
    config["culture"] = choice
    save_config(config)
    if choice == "none":
        print("Culture turned off; the sky keeps the IAU constellations and names")
    else:
        print(f"Culture set to {choice}: the sky draws the {culture_title(choice, lang)} "
              f"constellations and star names in every language")


def _cmd_auto():
    config = read_config()
    if config.pop("culture", None) is not None:
        save_config(config)
    print(f"Culture set to auto ({_NATURAL})")


def main():
    from linecast._runtime import resolve_lang
    from linecast._sky_catalogue import culture_title
    lang = resolve_lang()[0]
    parser = argparse.ArgumentParser(
        prog="linecast culture",
        description="Show or set the sky culture the sky command draws: whose "
                    "constellations and star names it uses",
    )
    parser.add_argument("--version", action=VersionAction)
    sub = parser.add_subparsers(dest="action")
    sub.add_parser("show", help="show the current culture setting (default)")
    for choice in CULTURE_CHOICES:
        if choice != "none":
            sub.add_parser(choice, help=culture_title(choice, lang))
    sub.add_parser("none", help="the IAU sky, whatever the language")
    sub.add_parser("auto", help="follow the language (the default)")
    args = parser.parse_args()
    if args.action in (None, "show"):
        _cmd_show()
    elif args.action == "auto":
        _cmd_auto()
    else:
        _cmd_set(args.action)


if __name__ == "__main__":
    main()
