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

from linecast._config import saved_hours
from linecast.settings._command import forget, remember, run, show

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
    show(saved or "auto", "config" if saved else "auto",
         ("swahili with --lang sw, else none",
          "Run 'linecast hours halachic', 'halachic-mga', 'roman', "
          "'japanese', 'islamic', or 'swahili' to read the day in one."),
         "Run 'linecast hours auto' to clear the setting.")


def _cmd_set(choice):
    remember("hours", choice)
    if choice == "none":
        print("Hours turned off; sunshine keeps the civil clock")
    elif choice.startswith("islamic"):
        print(f"Hours set to {choice}: sunshine reads the day in {_islamic_set(choice)}")
    else:
        print(f"Hours set to {choice}: sunshine reads the day in {_SET[choice]}")


def _cmd_auto():
    forget("hours")
    print("Hours set to auto (swahili with --lang sw, else none)")


def main():
    from linecast.astro.hours.prayer_times import METHODS
    run("linecast hours", "%(prog)s [show | <hours> | auto]",
        "Show or set the system of hours sunshine reads the day in",
        (("show", "show the current hours setting (default)"),
         ("halachic", "the zmanim by the Gr\"a: sunrise to sunset in "
                      "twelve, with the day's marks"),
         ("halachic-mga", "the zmanim by the Magen Avraham: alot to tzeit, "
                          "seventy-two minutes either side"),
         ("roman", "twelve horae by day, four vigiliae by night"),
         ("japanese", "不定時法 — six koku of day and six of night, by "
                      "the Edo bells"),
         ("islamic", "the prayer times, Fajr to Isha, by the country's "
                     "convention, and the fast in Ramadan"),
         ("islamic-hanafi", "the same, with the Hanafi Asr"),
         ("islamic-shafii", "the same, with the Shafi'i Asr"),
         *((f"islamic-{key}", f"the {name} convention")
           for key, (name, _fajr, _isha, _maghrib) in METHODS.items()),
         ("swahili", "Swahili time: saa 1 asubuhi at seven, saa 1 usiku "
                     "at seven in the evening"),
         ("none", "no hours, whatever the language"),
         ("auto", "clear the saved hours and follow the language")),
        _cmd_set, _cmd_auto, _cmd_show, metavar="<hours>")


if __name__ == "__main__":
    main()
