"""Show or set the language linecast speaks.

Usage: linecast language [show]
       linecast language fr
       linecast language auto

Precedence for every command: --lang flag > LINECAST_LANG env > saved
language (this command) > the terminal's locale (LANGUAGE, LC_ALL,
LC_MESSAGES, LANG) > English.
"""

import argparse
import os

from linecast._i18n import (
    LANGUAGES, LANGUAGE_NAMES, VARIANT_NAMES, VARIANTS, canonical_language, is_language_code,
)
from linecast._commands import formatter_class
from linecast._runtime import LOCALE_VARS, VersionAction, resolve_lang
from linecast._config import read_config, save_config, saved_language


def _describe(code):
    if code in VARIANT_NAMES:
        return VARIANT_NAMES[code]
    return LANGUAGE_NAMES.get(code, "not one linecast speaks, so English "
                                    "except where a provider has it")


def _list_languages():
    print("Run 'linecast language <code>' to pick one of:")
    print("  " + ", ".join(f"{code} {name}" for code, name in LANGUAGES))
    print("  or a regional variant: "
          + ", ".join(f"{code} {name}" for code, name in VARIANT_NAMES.items()))


def _cmd_show():
    """What the next run will use, and why."""
    lang, source = resolve_lang(None, os.environ)
    if source == "default":
        print(f"{lang}  {_describe(lang)}  [default]")
        _list_languages()
    elif source in LOCALE_VARS:
        print(f"{lang}  {_describe(lang)}  [auto: {source}={os.environ[source]}]")
        _list_languages()
    elif source == "config":
        print(f"{lang}  {_describe(lang)}  [fixed]")
        print("Run 'linecast language auto' to follow the terminal's language.")
    else:
        print(f"{lang}  {_describe(lang)}  [{source}]")
        saved = saved_language()
        if saved is not None:
            print(f"The saved setting ({saved}) is overridden by {source}.")


def _cmd_set(lang):
    lang = canonical_language(lang)
    config = read_config()
    config["language"] = lang
    save_config(config)
    print(f"Language set to {lang} ({_describe(lang)})")


def _cmd_auto():
    config = read_config()
    if config.pop("language", None) is not None:
        save_config(config)
    lang, source = resolve_lang(None, os.environ)
    if source in LOCALE_VARS:
        print(f"Language set to auto ({lang} {_describe(lang)}, from {source})")
    else:
        print("Language set to auto (English)")


def main():
    codes = ", ".join(code for code, _name in LANGUAGES)
    variants = ", ".join(VARIANTS)
    parser = argparse.ArgumentParser(
        prog="linecast language",
        usage="%(prog)s [show | <code> | auto]",
        description="Show or set the language linecast speaks",
        formatter_class=formatter_class(),
        epilog=f"Languages: {codes}; the regional variants {variants}. A "
               "locale's name works too (zh-TW is zh-Hant, pt_BR is pt), and "
               "another two-letter code is kept for the providers that "
               "publish in it (India's alerts, for one) while the rest stays "
               "in English.",
    )
    parser.add_argument("--version", action=VersionAction)
    parser.add_argument("action", nargs="?", default="show",
                        metavar="show | <code> | auto",
                        help="show the current language (default), save a "
                             "language code, or auto to follow the "
                             "terminal's language")
    args = parser.parse_args()

    action = args.action.strip().lower()
    if action == "show":
        _cmd_show()
    elif action == "auto":
        _cmd_auto()
    elif is_language_code(action):
        _cmd_set(action)
    else:
        parser.error(f"'{args.action}' is not a language code; "
                     f"choose from {codes}")


if __name__ == "__main__":
    main()
