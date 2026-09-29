"""Show or set the preferred icon set.

Usage: linecast icons [show]
       linecast icons nerd
       linecast icons emoji
       linecast icons plain
       linecast icons auto

Precedence for every command: --icons/--emoji flags > LINECAST_ICONS env >
saved icons (this command) > detection (Nerd Font glyphs where the
terminal bundles them, emoji on other interactive terminals, plain
Unicode when piped).
"""

from linecast._config import saved_icons
from linecast.settings._command import forget, remember, run, show

_DESCRIBE = {
    "nerd": "Nerd Font glyphs",
    "emoji": "standard emoji",
    "plain": "plain Unicode",
}


def _cmd_show():
    """What the next run will use, and why."""
    import os
    from linecast._runtime import resolve_icons
    icons, source = resolve_icons(None, os.environ)
    show(icons, source,
         ("auto",
          "Detected from the terminal; piped output is always plain.",
          "Run 'linecast icons nerd|emoji|plain' to fix it."),
         "Run 'linecast icons auto' to return to the default.",
         saved_icons())


def _cmd_set(icons):
    remember("icons", icons)
    print(f"Icons set to {icons} ({_DESCRIBE[icons]})")


def _cmd_auto():
    forget("icons")
    print("Icons set to auto (detected from the terminal)")


def main():
    run("linecast icons", "%(prog)s [show | nerd | emoji | plain | auto]",
        "Show or set the preferred icon set",
        (("show", "show the current icons setting (default)"),
         ("nerd", "Nerd Font glyphs everywhere (your font must be a Nerd Font)"),
         ("emoji", "standard emoji everywhere"),
         ("plain", "plain Unicode everywhere"),
         ("auto", "clear the saved icons and detect from the terminal")),
        _cmd_set, _cmd_auto, _cmd_show)


if __name__ == "__main__":
    main()
