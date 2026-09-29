"""Clock times as text: the compact forms the charts and headers use, and
the hour as each language writes it in a sentence.

A chart's axis says "6a" or "06", a header "2:14p" or "14:14"; the
forecast in words says "around 3pm", "gegen 15 Uhr" or "klo 15", and
Swahili and Hong Kong Chinese count the hours their own way."""

from linecast._i18n import base_language


def fmt_time(hours, use_24h=False):
    """Format decimal hours as h:MMa/p, or HH:MM on a 24-hour clock."""
    # A sunrise the evening before, far enough north, is a negative hour
    hours %= 24
    h = int(hours)
    m = int((hours % 1) * 60)
    if use_24h:
        return f"{h:02d}:{m:02d}"
    h12 = h % 12 or 12
    return f"{h12}:{m:02d}{'a' if h < 12 else 'p'}"


def fmt_hour(h, use_24h=False):
    """Format hour as compact label: 6a, 12p (12h) or 06, 14 (24h)."""
    h = h % 24
    if use_24h:
        return f"{h:02d}"
    if h == 0:
        return "12a"
    if h == 12:
        return "12p"
    if h < 12:
        return f"{h}a"
    return f"{h - 12}p"


# The 24-hour hour as each language writes it in running text: "around
# 15:00", "gegen 15 Uhr", "omkring kl. 15", "noin klo 15", "verso le 15",
# "15시경", "15时左右".  French, Portuguese and Vietnamese write "15h".
_HOUR_24 = {
    "en": "{h:02d}:00", "nl": "{h}\u00a0uur", "eo": "{h:02d}:00",
    "tr": "{h:02d}:00", "sw": "{h:02d}:00",
    # Without the leading zero in running text: "около 9:00", "kolem 9:00"
    "pl": "{h}:00", "cs": "{h}:00", "sk": "{h}:00", "ru": "{h}:00", "uk": "{h}:00",
    "el": "{h}:00",
    "ro": "{h}:00",
    "de": "{h}\u00a0Uhr", "it": "{h}", "da": "kl.\u00a0{h}", "no": "kl.\u00a0{h}",
    "sv": "kl.\u00a0{h}", "is": "kl.\u00a0{h}", "fi": "klo\u00a0{h}", "id": "pukul\u00a0{h}.00",
    "ja": "{h}時", "ko": "{h}시", "zh": "{h}时", "zh-Hant": "{h}時", "th": "{h:02d}.00\u00a0น.",
    # French spaces the h, as Météo-France and Environment Canada write
    # it: "18 h".  The spaces are unbreakable, so a paragraph never parts
    # an hour from its word for it.
    "fr": "{h}\u00a0h",
    # Spanish and Portuguese drop the leading zero in running text: "hacia
    # las 9:00", "por volta das 9h".  One o'clock takes the singular
    # article ("hacia la 1:00", "por volta da 1h"), by the "_one" forms of
    # the templates.
    "es": "{h}:00", "pt": "{h}h",
    # Vietnamese writes the hour without a leading zero: "kho\u1ea3ng 9h".
    "vi": "{h}h",
    # Hungarian says the hour with its word, as HungaroMet writes it, and
    # the word takes the endings a sentence needs: "16 óra körül"
    "hu": "{h}\u00a0óra",
    # Persian names the hour with its word, as IRIMO and the news do:
    # "حدود ساعت ۱۵", "از ساعت ۱۵"
    "fa": "ساعت\u00a0{h}",
}


def fmt_hour_phrase(hour, use_24h=False, lang="en"):
    """Conversational hour: '3pm' (12h), or the 24-hour form the language
    writes in a sentence: '15:00', '15 Uhr', 'kl. 15', '15時'."""
    hour = hour % 24
    if base_language(lang) == "sw":
        return _swahili_hour(hour)
    if lang == "zh-HK":
        return _hong_kong_hour(hour)
    if use_24h:
        form = _HOUR_24.get(lang, _HOUR_24.get(base_language(lang), "{h:02d}h"))
        return form.format(h=hour)
    h12 = hour % 12 or 12
    if lang == "el":
        # Words fit running prose and avoid a full stop after an am/pm
        # abbreviation colliding with the paragraph's sentence punctuation.
        if hour == 0:
            return "12 τα μεσάνυχτα"
        if hour == 12:
            return "12 το μεσημέρι"
        period = ("τη νύχτα" if hour < 5 else "το πρωί" if hour < 12
                  else "το μεσημέρι" if hour < 15 else "το απόγευμα" if hour < 19
                  else "το βράδυ")
        return f"{h12} {period}"
    return f"{h12}{'am' if hour < 12 else 'pm'}"


_SW_HOURS = ("moja", "mbili", "tatu", "nne", "tano", "sita", "saba", "nane",
             "tisa", "kumi", "kumi na moja", "kumi na mbili")


def _swahili_hour(hour):
    """The hour as Swahili tells it, counted from seven in the morning and
    seven at night, with the part of the day that says which: "saba
    mchana" for 13:00, "moja usiku" for 19:00.  The sentence supplies
    the "saa" before it."""
    count = _SW_HOURS[(hour - 7) % 12]
    part = ("usiku" if hour < 4 or hour >= 19 else "alfajiri" if hour < 6
            else "asubuhi" if hour < 12 else "mchana" if hour < 16 else "jioni")
    return f"{count} {part}"


def _hong_kong_hour(hour):
    """The hour as the Hong Kong Observatory writes it, on the 12-hour
    clock with the part of the day before it: "下午3時", "凌晨2時",
    "中午12時", "午夜12時"."""
    if hour == 0:
        return "午夜12時"
    if hour == 12:
        return "中午12時"
    part = ("凌晨" if hour < 6 else "上午" if hour < 12 else "下午" if hour < 18
            else "傍晚" if hour < 19 else "晚上")
    return f"{part}{hour % 12}時"


def fmt_time_dt(dt, use_24h=False):
    """Format a datetime as a compact time string."""
    if use_24h:
        return dt.strftime("%H:%M")
    # %-I is a glibc/BSD extension that Windows' CRT rejects, and %p is
    # locale-dependent; derive both by hand as fmt_time does just above.
    hour = dt.hour % 12 or 12
    return f"{hour}:{dt.minute:02d}{'a' if dt.hour < 12 else 'p'}"
