"""The lookup shared by the per-command string tables.

Each command keeps its own table, {lang: {key: text}}; this module holds
the one way of reading them, so the fallback order lives in one place.
"""

import re

# The display order shared by help, `linecast language`, and completions;
# keep both READMEs in step. English first, then loose regional clusters:
# Romance, German/Dutch, Nordic, Slavic, Greek, Turkish, Swahili, East Asian,
# Southeast Asian, and Esperanto last. Keep both Chinese scripts together.
LANGUAGES = (
    ("en", "English"),
    ("fr", "French"), ("es", "Spanish"), ("pt", "Portuguese"),
    ("it", "Italian"), ("ro", "Romanian"),
    ("de", "German"), ("nl", "Dutch"),
    ("da", "Danish"), ("no", "Norwegian"), ("sv", "Swedish"),
    ("is", "Icelandic"), ("fi", "Finnish"),
    ("cs", "Czech"), ("pl", "Polish"), ("ru", "Russian"), ("uk", "Ukrainian"),
    ("el", "Greek"), ("tr", "Turkish"), ("sw", "Swahili"),
    ("zh", "Simplified Chinese"), ("zh-Hant", "Traditional Chinese"),
    ("ja", "Japanese"), ("ko", "Korean"),
    ("th", "Thai"), ("vi", "Vietnamese"), ("id", "Indonesian"),
    ("eo", "Esperanto"),
)
LANGUAGE_CODES = tuple(code for code, _name in LANGUAGES)
LANGUAGE_NAMES = dict(LANGUAGES)

# Codes that name a language above by another name, lower-cased.  A
# Norwegian machine's locale is nb_NO or nn_NO (glibc has no no_NO), and
# the strings are Bokmål, so both read as "no".  Chinese is two scripts:
# Taiwan, Hong Kong, and Macau write the traditional characters, so their
# locales name zh-Hant, and the mainland's and Singapore's the simplified.
LANGUAGE_ALIASES = {
    "nb": "no", "nn": "no",
    "zh-hant": "zh-Hant", "zh-tw": "zh-Hant", "zh-hk": "zh-Hant", "zh-mo": "zh-Hant",
    "zh-hans": "zh", "zh-cn": "zh", "zh-sg": "zh",
}

# A language whose strings are another's in a different script: the moon's
# Chinese calendar and the Chinese sky come with zh-Hant as they do with zh.
SCRIPT_OF = {"zh-Hant": "zh"}


def canonical_language(code):
    """`code` as the tables know it: an alias resolved, else unchanged."""
    return LANGUAGE_ALIASES.get(code.lower(), code)


def is_language_code(value):
    """A language code linecast could act on, whether or not it has strings
    for it: two letters, two letters and a script (zh-Hant), or an alias
    of one.  An unlisted code leaves the app in English and still reaches
    the providers that publish in it, as India's alerts do."""
    if not isinstance(value, str) or not value.isascii():
        return False
    return (re.fullmatch(r"[A-Za-z]{2}(-[A-Za-z]{4})?", value) is not None
            or value.lower() in LANGUAGE_ALIASES)


# What the geocoders call a language, where it is not linecast's code.
# Open-Meteo's index knows the traditional script by Taiwan's tag and
# answers "zh-Hant" in English; Nominatim reads an Accept-Language list,
# so it gets the script, the regions that write it, and Chinese at all.
_GEOCODER_LANG = {"zh-Hant": "zh-TW"}
_ACCEPT_LANGUAGE = {"zh-Hant": "zh-Hant,zh-TW,zh-HK,zh"}

# Languages Open-Meteo's index has no names in, so a typed place's label
# comes back in English. A view shows a typed place by that label, since
# it names what was asked for where reverse geocoding names whichever
# boundary encloses the point; in these languages Nominatim's name is
# better when it has one, and the label stays the fallback.
GEOCODER_UNTRANSLATED = frozenset({"zh-Hant"})


def geocoder_language(lang):
    """`lang` as the Open-Meteo geocoder's `language` parameter."""
    return _GEOCODER_LANG.get(lang, lang)


def accept_language(lang):
    """`lang` as an Accept-Language value for Nominatim."""
    return _ACCEPT_LANGUAGE.get(lang, lang)


def same_language(lang, other):
    """Whether `lang` is `other` or `other` in another script: zh-Hant
    reads as Chinese wherever the code, not the strings, decides."""
    return lang == other or SCRIPT_OF.get(lang) == other


def lang_of(runtime):
    """The runtime's language, or English when there is no runtime."""
    return getattr(runtime, "lang", "en") if runtime else "en"


# Languages whose sentences read a 12-hour time as another hour. Swahili
# counts the hours from dawn, so "saa 1pm" reads as seven in the
# morning; its screens write 24-hour digits (CLDR's HH:mm, AccuWeather's
# 07:06), which no reader takes for Swahili time.
SENTENCE_24H = frozenset({"sw"})


def sentence_24h(runtime):
    """Whether a time inside a sentence takes the 24-hour clock: the
    user's choice, or always in a language of SENTENCE_24H."""
    return bool(getattr(runtime, "use_24h", False)) or lang_of(runtime) in SENTENCE_24H


# Languages that write the percent sign before the number: %40.
PERCENT_FIRST = frozenset({"tr"})
# Languages that set the sign off with a space: 40 %. In Czech "40%"
# reads as the adjective, forty-percent.
PERCENT_SPACED = frozenset({"cs"})


def fmt_percent(value, runtime):
    """`value` as a whole-number percentage the display language's way:
    "40%", "%40" in Turkish, "40 %" in Czech."""
    text = f"{value:.0f}"
    lang = lang_of(runtime)
    if lang in PERCENT_FIRST:
        return f"%{text}"
    return f"{text} %" if lang in PERCENT_SPACED else f"{text}%"


def plural_category(lang, n):
    """Which form a count takes in `lang`: "one", "few", or "many", as
    CLDR draws the lines. Russian and Ukrainian count 1, 21, 31 as one,
    2–4 and 22–24 as few, the rest (11–14 among them) as many; Polish
    the same but with only 1 as one; Czech 1, 2–4, and the rest;
    Romanian 1, then few to 19 and again from 101 to 119, with "de"
    before the noun beyond ("21 de zile", "101 zile"). A fraction is many in the
    Slavic languages and few in Romanian. Every other language has one
    and many."""
    whole = float(n) == int(n)
    n = abs(int(n)) if whole else n
    if lang in ("ru", "uk"):
        if not whole:
            return "many"
        if n % 10 == 1 and n % 100 != 11:
            return "one"
        if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
            return "few"
        return "many"
    if lang == "pl":
        if whole and n == 1:
            return "one"
        if whole and n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
            return "few"
        return "many"
    if lang == "cs":
        if not whole:
            return "many"
        return "one" if n == 1 else "few" if n in (2, 3, 4) else "many"
    if lang == "ro":
        if whole and n == 1:
            return "one"
        if not whole or n == 0 or n % 100 in range(1, 20):
            return "few"
        return "many"
    return "one" if whole and n == 1 else "many"


def lookup(table, key, lang, **kwargs):
    """The text for `key` in `lang`, falling back to English and then to
    the key itself.  Formatted with kwargs only when some are given, so a
    text with literal braces survives a plain lookup."""
    english = table["en"]
    text = table.get(lang, english).get(key, english.get(key, key))
    return text.format(**kwargs) if kwargs else text
