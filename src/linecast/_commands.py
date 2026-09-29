"""The commands, and the one line the help pages say about each.

`linecast --help` lists them, and each view command's own --help opens
with its line, so both come from here.  The page itself is laid out by
argparse's help formatter, which is what colours and wraps every other
help page: the names go in as positional metavars, which argparse
never parses, only prints.
"""

from linecast._i18n import LANGUAGE_CODES

VIEWS = (
    ("weather", "Conditions now, the day's temperature curve, the forecast, and alerts"),
    ("sunshine", "The sun's arc across the sky, dawn to dusk, or the whole year"),
    ("moon", "The moon as it looks tonight, its rise and set, and a month calendar"),
    ("sky", "The stars, planets, and Milky Way over you, as you would see them"),
    ("tides", "Tide chart from the nearest station, or a global model where there is none"),
    ("radar", "Weather radar over a map, the last hour and the next"),
    ("maps", "Street maps, hillshaded terrain, and routes"),
)

SETTINGS = (
    ("location", "A fixed place, instead of the one your IP address suggests"),
    ("language", ", ".join(LANGUAGE_CODES)),
    ("units", "metric or imperial"),
    ("clock", "12-hour or 24-hour"),
    ("week", "monday, sunday, or saturday: where the week opens in the moon's "
             "month view"),
    ("dates", "gregorian or solar-hijri, for writing dates (solar-hijri is the "
              "default in Persian)"),
    ("digits", "latin (0-9) or native, for writing numbers (native, ۰-۹, is "
               "the default in Persian)"),
    ("icons", "nerd, emoji, or plain"),
    ("calendar", "chinese, japanese, korean, vietnamese, thai, hawaiian, samoan, "
                 "chamorro, refaluwasch, islamic, hebrew, icelandic, almanac, or "
                 "none: the traditional calendar the moon follows"),
    ("culture", "chinese, hawaiian, norse, maori, boorong, and seventeen more, or "
                "none: whose constellations the sky draws"),
    ("hours", "halachic, halachic-mga, roman, japanese, islamic, swahili, or "
              "none: the hours sunshine reads the day in"),
)

HOUSEKEEPING = (
    ("link", "Make weather, moon, … short commands beside linecast"),
    ("doctor", "Where files live, what the terminal supports, which providers answer"),
    ("completion", "Shell completion script for bash, zsh, fish, or nushell"),
)

BLURB = dict(VIEWS + SETTINGS + HOUSEKEEPING)
# The names alone: the views are the commands with a short name of their
# own (linecast link), and all three are what the completions offer.
VIEW_NAMES = tuple(name for name, _blurb in VIEWS)
COMMAND_NAMES = tuple(BLURB)


def formatter_class():
    """argparse's help formatter, keeping hyphenated words whole.

    The stock one wraps at hyphens, which cuts fr-CA and zh-Hant in two
    at the end of a line.  A newline in a flag's help starts a new line,
    so a long list of choices can stand apart from what they do.  A
    command's subcommands are listed without argparse's {show,set,…}
    line over them, which only repeats their names.  It is fetched, not
    imported, so this module, which every run of `linecast` loads, loads
    without argparse: a run that parses no flags, `linecast --version`
    say, never imports it.
    """
    import argparse
    import textwrap

    class Formatter(argparse.HelpFormatter):
        def add_argument(self, action):
            if isinstance(action, argparse._SubParsersAction):
                for sub in action._get_subactions():
                    super().add_argument(sub)
            else:
                super().add_argument(action)

        def _split_lines(self, text, width):
            return [line for part in text.split("\n")
                    for line in textwrap.wrap(part, width, break_on_hyphens=False)]

        def _fill_text(self, text, width, indent):
            return textwrap.fill(text, width, initial_indent=indent,
                                 subsequent_indent=indent, break_on_hyphens=False)

    return Formatter


def parser_class():
    """argparse's parser, taking "-33.87,151.21" for a value.

    Before Python 3.14 argparse read anything that starts with a dash
    and is not a plain number as an option, so a place south of the
    equator or west of Greenwich, given as coordinates, was refused:
    "--location: expected one argument".  This is the rule 3.14 uses.
    Subcommands made from it are made from it too.
    """
    import argparse
    import re

    class Parser(argparse.ArgumentParser):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._negative_number_matcher = re.compile(r"-\.?\d")

    return Parser


def help_text(version):
    """The `linecast --help` page, formatted like every command's own."""
    import argparse
    parser = argparse.ArgumentParser(
        prog="linecast", usage="%(prog)s <command> [options]", add_help=False,
        formatter_class=formatter_class(),
        description=f"linecast {version} — weather, sunlight, the moon, the sky, "
                    "tides, radar, and maps for the terminal",
        epilog="For one run, a flag stands in for a setting: --location \"Québec\" "
               "or 41.88,-87.63, --lang fr, --imperial, --24h. Run any command with "
               "--help for options.")
    sections = (("commands", VIEWS),
                ("settings (run alone to show, give a value to set)", SETTINGS),
                ("housekeeping", HOUSEKEEPING))
    for title, rows in sections:
        group = parser.add_argument_group(title)
        for name, blurb in rows:
            group.add_argument(name, metavar=f"linecast {name}", help=blurb)
    return parser.format_help().rstrip()
