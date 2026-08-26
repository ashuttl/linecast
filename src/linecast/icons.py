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

import argparse

from linecast._runtime import ICON_SETS, VersionAction
from linecast._config import read_config, save_config, saved_icons

_DESCRIBE = {
    "nerd": "Nerd Font glyphs",
    "emoji": "standard emoji",
    "plain": "plain Unicode",
}


def _cmd_show():
    icons = saved_icons()
    if icons is None:
        print("auto (nerd where the terminal bundles the glyphs, emoji on "
              "other interactive terminals, plain when piped; "
              "LINECAST_ICONS still applies)")
        return
    print(f"{icons}  [fixed]")
    print("Run 'linecast icons auto' to return to the default.")


def _cmd_set(icons):
    config = read_config()
    config["icons"] = icons
    save_config(config)
    print(f"Icons set to {icons} ({_DESCRIBE[icons]})")


def _cmd_auto():
    config = read_config()
    if config.pop("icons", None) is not None:
        save_config(config)
    print("Icons set to auto (detected from the terminal)")


def main():
    parser = argparse.ArgumentParser(
        prog="linecast icons",
        description="Show or set the preferred icon set",
    )
    parser.add_argument("--version", action=VersionAction)
    sub = parser.add_subparsers(dest="action")
    sub.add_parser("show", help="show the current icons setting (default)")
    sub.add_parser("nerd", help="Nerd Font glyphs everywhere (your font must be a Nerd Font)")
    sub.add_parser("emoji", help="standard emoji everywhere")
    sub.add_parser("plain", help="plain Unicode everywhere")
    sub.add_parser("auto", help="clear the saved icons and detect from the terminal")
    args = parser.parse_args()

    if args.action in ICON_SETS:
        _cmd_set(args.action)
    elif args.action == "auto":
        _cmd_auto()
    else:
        _cmd_show()


if __name__ == "__main__":
    main()
