"""The moon's traditional calendars, one module each.

Each answers the same question, what this civil date is in that
calendar and what comes next: lunisolar (Chinese, Japanese, Korean,
and Vietnamese, from the ephemeris at each calendar's meridian),
thai_lunar (the Suriyayart arithmetic), pacific (Hawaiʻi, American
Samoa, and the Marianas, from the first visible crescent), hijri (the
Umm al-Qura rule, from the ephemeris at Mecca), hebrew (the fixed
arithmetic), and icelandic (the old Icelandic weeks and months,
counted from the first day of summer). lunisolar.resolve_calendar
picks which one the moon shows, from the flag, the saved setting, or
the language. The sun's hours are the same shape in astro.hours.
"""
