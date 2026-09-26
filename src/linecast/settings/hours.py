"""Show or set the system of hours the sunshine command reads the day in.

Usage: linecast hours [show]
       linecast hours halachic | halachic-mga
       linecast hours roman
       linecast hours japanese
       linecast hours islamic
       linecast hours swahili
       linecast hours none
       linecast hours auto

Precedence: sunshine's --hours flag > this setting > the language's
own (swahili with --lang sw) > none.
"""

import argparse

from linecast._config import read_config, save_config, saved_hours
from linecast._commands import formatter_class
from linecast._runtime import HOURS_CHOICES, VersionAction

_SET = {
    "halachic": "the zmanim by the Gr\"a: twelve hours from sunrise "
                "to sunset, and the day's marks from alot to tzeit",
    "halachic-mga": "the zmanim by the Magen Avraham: twelve hours from "
                    "alot to tzeit, seventy-two minutes either side of "
                    "the Sun",
    "roman": "the twelve horae of the day and the four vigiliae of the "
             "night",
    "japanese": "the six koku of day and night, 明六つ to 暮六つ, as the "
                "Edo bells struck them",
    "islamic": "the prayer times, Fajr to Isha, by the country's "
               "convention, and the fast in Ramadan",
    "swahili": "Swahili time: twelve hours from six in the morning and "
               "twelve from six in the evening, saa 1 asubuhi at seven",
    "islamic-hanafi": "the prayer times with the Hanafi school's later Asr",
    "islamic-shafii": "the prayer times with the Shafi'i school's Asr, "
                      "whatever the country",
}


def _islamic_set(choice):
    from linecast.astro.hours.prayer_times import METHODS
    method = choice.partition("-")[2]
    if method in METHODS:
        return (f"the prayer times by the {METHODS[method][0]} convention, "
                f"whatever the country")
    return _SET[choice]


def _cmd_show():
    saved = saved_hours()
    if saved == "none":
        print("none  [fixed]")
        print("Run 'linecast hours auto' to clear the setting.")
    elif saved is not None:
        print(f"{saved}  [fixed]")
        print("Run 'linecast hours auto' to clear the setting.")
    else:
        print("auto  [swahili with --lang sw, else none]")
        print("Run 'linecast hours halachic', 'halachic-mga', 'roman', "
              "'japanese', 'islamic', or 'swahili' to read the day in one.")


def _cmd_set(choice):
    config = read_config()
    config["hours"] = choice
    save_config(config)
    if choice == "none":
        print("Hours turned off; sunshine keeps the civil clock")
    elif choice.startswith("islamic"):
        print(f"Hours set to {choice}: sunshine reads the day in {_islamic_set(choice)}")
    else:
        print(f"Hours set to {choice}: sunshine reads the day in {_SET[choice]}")


def _cmd_auto():
    config = read_config()
    if config.pop("hours", None) is not None:
        save_config(config)
    print("Hours set to auto (swahili with --lang sw, else none)")


def main():
    parser = argparse.ArgumentParser(
        prog="linecast hours",
        usage="%(prog)s [show | <hours> | auto]",
        description="Show or set the system of hours sunshine reads the day in",
        formatter_class=formatter_class(),
    )
    parser.add_argument("--version", action=VersionAction)
    sub = parser.add_subparsers(dest="action", metavar="<hours>")
    sub.add_parser("show", help="show the current hours setting (default)")
    sub.add_parser("halachic",
                   help="the zmanim by the Gr\"a: sunrise to sunset in "
                        "twelve, with the day's marks")
    sub.add_parser("halachic-mga",
                   help="the zmanim by the Magen Avraham: alot to tzeit, "
                        "seventy-two minutes either side")
    sub.add_parser("roman", help="twelve horae by day, four vigiliae by night")
    sub.add_parser("japanese",
                   help="不定時法 — six koku of day and six of night, by "
                        "the Edo bells")
    sub.add_parser("islamic",
                   help="the prayer times, Fajr to Isha, by the country's "
                        "convention, and the fast in Ramadan")
    from linecast.astro.hours.prayer_times import METHODS
    for key, (name, _fajr, _isha, _maghrib) in METHODS.items():
        sub.add_parser(f"islamic-{key}", help=f"the prayer times by the {name} convention")
    sub.add_parser("swahili",
                   help="Swahili time: saa 1 asubuhi at seven, saa 1 usiku "
                        "at seven in the evening")
    sub.add_parser("islamic-hanafi", help="the prayer times with the Hanafi Asr")
    sub.add_parser("islamic-shafii", help="the prayer times with the Shafi'i Asr")
    sub.add_parser("none", help="no hours, whatever the language")
    sub.add_parser("auto", help="clear the saved hours")
    args = parser.parse_args()

    if args.action in HOURS_CHOICES:
        _cmd_set(args.action)
    elif args.action == "auto":
        _cmd_auto()
    else:
        _cmd_show()


if __name__ == "__main__":
    main()
