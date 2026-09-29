"""Show or set the traditional calendar the moon command follows.

Usage: linecast calendar [show]
       linecast calendar chinese | japanese | korean | vietnamese | thai
       linecast calendar almanac
       linecast calendar hawaiian | samoan | chamorro | refaluwasch
       linecast calendar islamic | hebrew | icelandic
       linecast calendar none
       linecast calendar auto

Precedence: moon's --calendar flag > this setting > the calendar
native to the UI language (--lang zh, ja, ko, vi, th, fa, or is) >
none.
"""

from linecast._config import saved_calendar
from linecast.settings._command import forget, remember, run, show

_NATURAL = ("chinese with --lang zh, japanese with ja, "
            "korean with ko, vietnamese with vi, thai with th, islamic "
            "with fa, icelandic with is; none otherwise")

# What the moon shows once a calendar is set; the lunisolar four
# (chinese, japanese, korean, vietnamese) share _LUNISOLAR.
_SET = {
    "hawaiian": "the moon names each night — the pō mahina, its anahulu, "
                "and its counsel — in every language",
    "samoan": "the moon names each night by the American Samoa lunar "
              "calendar — Masina Fou to Masina Maunā — in every language",
    "chamorro": "the moon names each night by the Guam lunar calendar — "
                "Sinahen Håcha to Sinahi — in every language",
    "refaluwasch": "the moon names each night by the CNMI lunar calendar, "
                   "the CHamoru name with the Refaluwasch beside it, in "
                   "every language",
    "islamic": "the moon shows the Hijri date by the Umm al-Qura calendar, "
               "the coming month, and the next observance in every language",
    "hebrew": "the moon shows the Hebrew date, the coming month, and the "
              "next holiday in every language",
    "icelandic": "the moon shows the week of summer or winter, the month, "
                 "and the named days and moons of the old Icelandic "
                 "calendar in every language",
    "thai": "the moon shows its lunar date, the coming วันพระ, and the next "
            "festival in every language",
    "almanac": "the moon shows the Old Farmer's gardening rule and the "
               "day's solunar periods in every language",
}
_LUNISOLAR = ("the moon shows its lunar date, solar term, and next festival "
              "in every language")


def _cmd_show():
    saved = saved_calendar()
    show(saved or "auto", "config" if saved else "auto",
         (_NATURAL,
          "Run 'linecast calendar chinese', 'japanese', 'korean', "
          "'vietnamese', 'thai', 'hawaiian', 'samoan', 'chamorro', "
          "'refaluwasch', "
          "'islamic', 'hebrew', 'icelandic', or 'almanac' to fix one."),
         "Run 'linecast calendar auto' to follow the language again." if saved == "none"
         else "Run 'linecast calendar auto' to follow the language instead.")


def _cmd_set(choice):
    remember("calendar", choice)
    if choice == "none":
        print("Calendar turned off; the moon panel keeps the phase lines only")
    else:
        print(f"Calendar set to {choice}: {_SET.get(choice, _LUNISOLAR)}")


def _cmd_auto():
    forget("calendar")
    print(f"Calendar set to auto ({_NATURAL})")


def main():
    run("linecast calendar", "%(prog)s [show | <calendar> | auto]",
        "Show or set the traditional calendar the moon follows",
        (("show", "show the current calendar setting (default)"),
         ("chinese", "农历 — months from new moons at UTC+8"),
         ("japanese", "旧暦 — the same rules at UTC+9"),
         ("korean", "음력 — the same rules at UTC+9"),
         ("vietnamese", "âm lịch — the same rules at UTC+7"),
         ("thai", "จันทรคติไทย — the Suriyayart arithmetic, with "
                  "วันพระ and festivals"),
         ("hawaiian", "Kaulana Mahina — nights counted from the first "
                      "visible crescent over Hawaiʻi"),
         ("samoan", "American Samoa — nights counted from the first "
                    "visible crescent over Pago Pago"),
         ("chamorro", "Guam — nights counted from the first visible "
                      "crescent over Hagåtña"),
         ("refaluwasch", "CNMI — the same nights, CHamoru and Refaluwasch "
                         "names together"),
         ("islamic", "Umm al-Qura — the Hijri date by Saudi Arabia's "
                     "civil rule, with Ramadan, the Eids, and the "
                     "other observances"),
         ("hebrew", "Hebrew — the date by the fixed calendar, with "
                    "Rosh Hashanah, Pesach, and the other holidays"),
         ("icelandic", "Misseristal — the old Icelandic calendar's weeks "
                       "of summer and winter, its months from Harpa to "
                       "Einmánuður, and its named days and moons"),
         ("almanac", "Old Farmer's Almanac — gardening by the moon "
                     "and solunar periods"),
         ("none", "no calendar lines, whatever the language"),
         ("auto", "clear the saved calendar and follow the language")),
        _cmd_set, _cmd_auto, _cmd_show, metavar="<calendar>")


if __name__ == "__main__":
    main()
