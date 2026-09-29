"""Show or set the sky culture the sky command draws.

Usage: linecast culture [show]
       linecast culture chinese | hawaiian | norse | … (see --help)
       linecast culture none
       linecast culture auto

Precedence: sky's --culture flag > this setting > the culture native to
the UI language (--lang zh) > the IAU sky.
"""

from linecast._config import CULTURE_CHOICES, saved_culture
from linecast.settings._command import forget, remember, run, show

_NATURAL = "chinese with --lang zh; the IAU sky otherwise"


def _cmd_show():
    saved = saved_culture()
    show(saved or "auto", "config" if saved else "auto",
         (_NATURAL,
          "Run 'linecast culture NAME' to fix one; 'linecast culture --help' "
          "lists them."),
         "Run 'linecast culture auto' to follow the language again." if saved == "none"
         else "Run 'linecast culture auto' to follow the language instead.")


def _cmd_set(choice):
    from linecast._runtime import resolve_lang
    from linecast.sky.catalogue import culture_title
    lang = resolve_lang()[0]
    remember("culture", choice)
    if choice == "none":
        print("Culture turned off; the sky keeps the IAU constellations and names")
    else:
        print(f"Culture set to {choice}: the sky draws the {culture_title(choice, lang)} "
              f"constellations and star names in every language")


def _cmd_auto():
    forget("culture")
    print(f"Culture set to auto ({_NATURAL})")


def main():
    from linecast._runtime import resolve_lang
    from linecast.sky.catalogue import culture_title
    lang = resolve_lang()[0]
    run("linecast culture", "%(prog)s [show | <culture> | auto]",
        "Show or set the sky culture the sky command draws: whose "
        "constellations and star names it uses",
        (("show", "show the current culture setting (default)"),
         *((choice, culture_title(choice, lang))
           for choice in CULTURE_CHOICES if choice != "none"),
         ("none", "the IAU sky, whatever the language"),
         ("auto", "clear the saved culture and follow the language")),
        _cmd_set, _cmd_auto, _cmd_show, metavar="<culture>")


if __name__ == "__main__":
    main()
