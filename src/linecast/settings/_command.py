"""What the settings commands share: saving a choice, clearing it,
saying what is in force, and reading the command line.

The words are each command's own, in its own module; this is the
plumbing under them.
"""

import argparse

from linecast._commands import formatter_class
from linecast._config import read_config, save_config
from linecast._parsers import VersionAction


def remember(key, value):
    """Save *value* as the setting *key* in config.json."""
    config = read_config()
    config[key] = value
    save_config(config)


def forget(key):
    """Clear the saved setting *key*. config.json is written only when
    it held one."""
    config = read_config()
    if config.pop(key, None) is not None:
        save_config(config)


def show(value, source, auto, fixed, saved=None, defaults=("auto",)):
    """Print what the next run will use, and why.

    The first line is *value* and, in brackets, where it came from;
    the lines under it say how to change it.  *source* is the
    resolver's: one of *defaults* when the default decided, "config"
    when the saved setting did, else the flag or the variable that
    overrides the saved setting.  *auto* is what the brackets hold for
    the default, then the lines printed under it; *fixed* is the line
    printed under a saved setting; *saved* is the saved setting as the
    line about an override names it, or None when nothing is saved.
    """
    if source in defaults:
        tag, *lines = auto
        print(f"{value}  [{tag}]")
        for line in lines:
            print(line)
    elif source == "config":
        print(f"{value}  [fixed]")
        print(fixed)
    else:
        print(f"{value}  [{source}]")
        if saved is not None:
            print(f"The saved setting ({saved}) is overridden by {source}.")


def run(prog, usage, description, commands, on_set, on_auto, on_show, metavar=None):
    """Read `linecast <setting> [show | <choice> | auto]` and do it.

    *commands* is each subcommand's name and help, in the order --help
    lists them: show, the choices, then auto.  A choice is handed to
    *on_set*; auto runs *on_auto*, and show, or nothing, *on_show*.
    """
    parser = argparse.ArgumentParser(
        prog=prog, usage=usage, description=description,
        formatter_class=formatter_class(),
    )
    parser.add_argument("--version", action=VersionAction)
    sub = parser.add_subparsers(dest="action", metavar=metavar)
    for name, help_ in commands:
        sub.add_parser(name, help=help_)
    args = parser.parse_args()
    if args.action in (None, "show"):
        on_show()
    elif args.action == "auto":
        on_auto()
    else:
        on_set(args.action)
