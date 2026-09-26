"""The lookup shared by the per-command string tables.

The strings live in linecast/locales, one file per language, and each
command reads its own table from them as {lang: {key: text}}; this
module holds the one way of reading them, so the fallback order lives
in one place.
"""

import importlib
import re
from collections.abc import MutableMapping

# The display order shared by help, `linecast language`, and completions;
# keep both READMEs in step. English first, then loose regional clusters:
# Romance, German/Dutch, Nordic, Slavic, Greek, Turkish, Persian, Swahili, East Asian,
# Southeast Asian, and Esperanto last. Keep both Chinese scripts together.
LANGUAGES = (
    ("en", "English"),
    ("fr", "French"), ("es", "Spanish"), ("pt", "Portuguese"),
    ("it", "Italian"), ("ro", "Romanian"),
    ("de", "German"), ("nl", "Dutch"),
    ("da", "Danish"), ("no", "Norwegian"), ("sv", "Swedish"),
    ("is", "Icelandic"), ("fi", "Finnish"),
    ("cs", "Czech"), ("pl", "Polish"), ("ru", "Russian"), ("uk", "Ukrainian"),
    ("el", "Greek"), ("tr", "Turkish"), ("fa", "Persian"), ("sw", "Swahili"),
    ("zh", "Simplified Chinese"), ("zh-Hant", "Traditional Chinese"),
    ("ja", "Japanese"), ("ko", "Korean"),
    ("th", "Thai"), ("vi", "Vietnamese"), ("id", "Indonesian"),
    ("eo", "Esperanto"),
)
LANGUAGE_CODES = tuple(code for code, _name in LANGUAGES)
LANGUAGE_NAMES = dict(LANGUAGES)

def is_rtl(lang):
    """Whether `lang` is written right to left."""
    return setting(lang, "rtl")


# Regional variants: a code whose strings are a base language's with the
# words that differ by country changed.  The base is what most readers of
# the language get: Portuguese is Brazilian, Spanish is Latin American,
# French is the French of France, and Traditional Chinese is Taiwan's;
# Hong Kong's is the variant, and Macau reads it too.  A variant's table holds only the keys
# it changes; `lookup` reads through to the base and then to English.
VARIANTS = {"pt-PT": "pt", "es-ES": "es", "fr-CA": "fr", "zh-HK": "zh-Hant"}
VARIANT_NAMES = {
    "pt-PT": "European Portuguese",
    "es-ES": "European Spanish",
    "fr-CA": "Canadian French",
    "zh-HK": "Hong Kong Chinese",
}

# Codes that name a language above by another name, lower-cased.  A
# Norwegian machine's locale is nb_NO or nn_NO (glibc has no no_NO), and
# the strings are Bokmål, so both read as "no".  Chinese is two scripts:
# Taiwan, Hong Kong, and Macau write the traditional characters, so their
# locales name zh-Hant (Hong Kong's and Macau's its zh-HK variant), and
# the mainland's and Singapore's the simplified.
# A region tag names its variant where there is one (pt_PT, es_ES, fr_CA);
# any other region falls to the base language, so pt_BR, es_AR, fr_BE,
# and fr_CH need no entry.  Where the variant has a fuller country list
# (Spain's Spanish is Spain's alone, Canada's French is Canada's alone),
# the base is what the rest of the world gets.
LANGUAGE_ALIASES = {
    "nb": "no", "nn": "no",
    "zh-hant": "zh-Hant", "zh-tw": "zh-Hant",
    "zh-hk": "zh-HK", "zh-mo": "zh-HK", "zh-hant-hk": "zh-HK", "zh-hant-mo": "zh-HK",
    "zh-hans": "zh", "zh-cn": "zh", "zh-sg": "zh",
    "pt-pt": "pt-PT", "es-es": "es-ES", "fr-ca": "fr-CA",
}

# Every code with a file in linecast/locales.
LOCALE_CODES = LANGUAGE_CODES + tuple(VARIANTS)
_locales = {}


def _locale(code):
    """The locale module for `code`, imported the first time it is asked
    for, or None for a code with no file."""
    if code not in _locales:
        if code not in LOCALE_CODES:
            return None
        _locales[code] = importlib.import_module(f"linecast.locales.{code.replace('-', '_')}")
    return _locales[code]


class LocaleTable(MutableMapping):
    """One table across the locale files, read as {lang: table}: WEATHER
    is en.py's WEATHER under "en", fr.py's under "fr", and so on.  A
    language's file is imported only when the table is first read in
    that language, so a run in French loads French and English alone.
    A value set here (a test's stand-in) shadows the file's."""

    def __init__(self, name):
        self.name = name
        self._set = {}

    def get(self, code, default=None):
        if code in self._set:
            return self._set[code]
        return getattr(_locale(code), self.name, default)

    def __getitem__(self, code):
        value = self.get(code, _MISSING)
        if value is _MISSING:
            raise KeyError(code)
        return value

    def __contains__(self, code):
        return self.get(code, _MISSING) is not _MISSING

    def __setitem__(self, code, value):
        self._set[code] = value

    def __delitem__(self, code):
        del self._set[code]

    def __iter__(self):
        return (code for code in LOCALE_CODES + tuple(c for c in self._set if c not in LOCALE_CODES)
                if code in self)

    def __len__(self):
        return sum(1 for _code in self)

    def __repr__(self):
        return f"LocaleTable({self.name!r})"


_MISSING = object()


# What a language's SETTINGS leave out: the Latin script's point and
# percent, the 24-hour clock in sentences, the unit letters for a
# duration, one and many for plurals, km/h, the Gregorian calendar, and
# no traditional calendar, hours, or sky of its own.  en.py lists every
# setting with a note on each.
_SETTING_DEFAULTS = {
    "decimal": ".",
    "percent": "{n}%",
    "digits": None,
    "rtl": False,
    "sentence_12h": False,
    "duration": {"d": "{v}d", "h": "{v}h", "m": "{v}m", "s": "{v}s", "join": " ", "pad": True},
    "plural": "one_many",
    "script": None,
    "capitals": True,
    "list_full_day_names": False,
    "numeric_month_axis": False,
    "absolute_seasons": False,
    "metric_wind": "km/h",
    "calendar": None,
    "civil_calendar": "gregorian",
    "hours": None,
    "sky_culture": None,
}
_SETTINGS = LocaleTable("SETTINGS")


def setting(lang, name):
    """One of `lang`'s SETTINGS: its own, or its base's for a regional
    variant, or the default.  English's are not a fallback here, since
    several (the 12-hour clock in sentences) are English's alone."""
    for code in (lang, VARIANTS.get(lang)):
        if code is not None:
            value = _SETTINGS.get(code, {}).get(name, _MISSING)
            if value is not _MISSING:
                return value
    return _SETTING_DEFAULTS[name]


# A language whose strings are another's in a different script: the moon's
# Chinese calendar and the Chinese sky come with zh-Hant as they do with zh.
SCRIPT_OF = {"zh-Hant": "zh"}


def canonical_language(code):
    """`code` as the tables know it: "pt", "pt_BR", "pt-br", and
    "pt_BR.UTF-8" are "pt"; "pt-PT" and "pt_pt" are "pt-PT"; "zh_TW" is
    "zh-Hant".  The longest prefix of the subtags the aliases know wins,
    else the language alone; a bare code with no alias is unchanged."""
    parts = re.split(r"[-_]", code.strip().split(".")[0].split("@")[0].lower())
    for n in range(len(parts), 1, -1):
        tag = "-".join(parts[:n])
        if tag in LANGUAGE_ALIASES:
            return LANGUAGE_ALIASES[tag]
    return LANGUAGE_ALIASES.get(parts[0], parts[0])


def base_language(lang):
    """The language a code's strings are grounded in: "pt" for "pt-PT",
    and `lang` itself elsewhere.  Providers and data keyed by language
    alone (a geocoder's parameter, a tile's name:xx) take this."""
    return VARIANTS.get(lang, lang)


def fallbacks(lang):
    """The codes to read a table by for `lang`, most specific first: the
    code, its base where it is a regional variant, then English."""
    chain = [lang]
    if lang in VARIANTS:
        chain.append(VARIANTS[lang])
    if "en" not in chain:
        chain.append("en")
    return chain


def table_for(table, lang):
    """The whole entry for `lang` in a table whose values are not string
    dicts (a list of day names, a tuple of words): the variant's own
    where it has one, else its base's, else English's."""
    for code in fallbacks(lang):
        if code in table:
            return table[code]
    return table["en"]


def has_text(table, key, lang):
    """Whether `lang` has its own text for `key`: in its table, or its
    base's for a regional variant.  English's counts only for a language
    with no table at all, which reads English throughout.  The check for
    an optional sibling key (a plural, a dative, a "_then" form) that a
    language may carry and English may not."""
    codes = [code for code in fallbacks(lang) if code in table]
    own = [code for code in codes if code != "en"] or codes
    return any(key in table[code] for code in own)


def is_language_code(value):
    """A language code linecast could act on, whether or not it has strings
    for it: two letters, a script (zh-Hant), a region (pt-PT, es_MX), or
    an alias of one.  An unlisted code leaves the app in English and still
    reaches the providers that publish in it, as India's alerts do."""
    if not isinstance(value, str) or not value.isascii():
        return False
    return (re.fullmatch(r"[A-Za-z]{2}(-[A-Za-z]{4})?([-_][A-Za-z]{2})?", value) is not None
            or value.lower() in LANGUAGE_ALIASES)


# What the geocoders call a language, where it is not linecast's code.
# Open-Meteo's index knows the traditional script by Taiwan's tag and
# answers "zh-Hant" in English; Nominatim reads an Accept-Language list,
# so it gets the script, the regions that write it, and Chinese at all.
_GEOCODER_LANG = {"zh-Hant": "zh-TW", "zh-HK": "zh-TW"}
_ACCEPT_LANGUAGE = {"zh-Hant": "zh-Hant,zh-TW,zh-HK,zh", "zh-HK": "zh-HK,zh-Hant,zh-TW,zh"}

# Languages Open-Meteo's index has no names in, so a typed place's label
# comes back in English. A view shows a typed place by that label, since
# it names what was asked for where reverse geocoding names whichever
# boundary encloses the point; in these languages Nominatim's name is
# better when it has one, and the label stays the fallback.
GEOCODER_UNTRANSLATED = frozenset({"zh-Hant", "zh-HK"})


def geocoder_language(lang):
    """`lang` as the Open-Meteo geocoder's `language` parameter, which
    takes a language alone: a regional variant asks in its base."""
    return _GEOCODER_LANG.get(lang, base_language(lang))


def accept_language(lang):
    """`lang` as an Accept-Language value for Nominatim: a regional
    variant asks for its own names first (OSM carries some as name:pt-PT
    or name:fr-CA), then the language's."""
    if lang in _ACCEPT_LANGUAGE:
        return _ACCEPT_LANGUAGE[lang]
    return f"{lang},{VARIANTS[lang]}" if lang in VARIANTS else lang


def same_language(lang, other):
    """Whether `lang` is `other` or `other` in another script: zh-Hant
    reads as Chinese wherever the code, not the strings, decides."""
    lang = base_language(lang)
    return lang == other or SCRIPT_OF.get(lang) == other


def lang_of(runtime):
    """The runtime's language, or English when there is no runtime."""
    return getattr(runtime, "lang", "en") if runtime else "en"


def sentence_24h(runtime):
    """Whether a time inside a sentence takes the 24-hour clock: the
    user's choice in a language whose sentence_12h setting allows the
    12-hour clock, and always elsewhere."""
    if not setting(lang_of(runtime), "sentence_12h"):
        return True
    return bool(getattr(runtime, "use_24h", False))


def fmt_decimal(value, places, runtime):
    """`value` to `places` decimals with the display language's decimal
    mark: "11.3", "11,3"."""
    text = f"{value:.{places}f}"
    mark = setting(lang_of(runtime), "decimal")
    return text if mark == "." else text.replace(".", mark)


def fmt_percent(value, runtime):
    """`value` as a whole-number percentage the display language's way:
    "40%", "%40" in Turkish, "40 %" in Czech."""
    return setting(lang_of(runtime), "percent").format(n=f"{value:.0f}")


def has_duration_words(lang):
    """Whether `lang` writes durations in words of its own rather than
    the unit letters."""
    return setting(lang, "duration") != _SETTING_DEFAULTS["duration"]


def fmt_duration_parts(lang, *parts, sign=""):
    """A duration from (unit, value) parts, units "d", "h", "m", "s", in
    the order given: fmt_duration_parts("en", ("h", 6), ("m", 7)) is
    "6h 07m", and in Persian "۶ ساعت و ۷ دقیقه" once the digits are
    drawn.  `sign` goes in front."""
    forms = setting(lang, "duration")
    out = []
    prev = None
    for unit, value in parts:
        text = f"{value:02d}" if (forms["pad"] and unit == "m" and prev == "h") else str(value)
        out.append(forms[unit].format(v=text))
        prev = unit
    return sign + forms["join"].join(out)


def plural_category(lang, n):
    """Which form a count takes in `lang`: "one", "few", or "many", as
    CLDR draws the lines. Russian and Ukrainian count 1, 21, 31 as one,
    2–4 and 22–24 as few, the rest (11–14 among them) as many; Polish
    the same but with only 1 as one; Czech 1, 2–4, and the rest;
    Romanian 1, then few to 19 and again from 101 to 119, with "de"
    before the noun beyond ("21 de zile", "101 zile"). A fraction is many in the
    Slavic languages and few in Romanian. Every other language has one
    and many. A language names its rule in its "plural" setting:
    east_slavic, polish, czech, romanian, or the default one_many."""
    whole = float(n) == int(n)
    n = abs(int(n)) if whole else n
    rule = setting(lang, "plural")
    if rule == "east_slavic":
        if not whole:
            return "many"
        if n % 10 == 1 and n % 100 != 11:
            return "one"
        if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
            return "few"
        return "many"
    if rule == "polish":
        if whole and n == 1:
            return "one"
        if whole and n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
            return "few"
        return "many"
    if rule == "czech":
        if not whole:
            return "many"
        return "one" if n == 1 else "few" if n in (2, 3, 4) else "many"
    if rule == "romanian":
        if whole and n == 1:
            return "one"
        if not whole or n == 0 or n % 100 in range(1, 20):
            return "few"
        return "many"
    return "one" if whole and n == 1 else "many"


# The last word of each number as Turkish reads it aloud, which picks a
# numeral's suffix: 20 is yirmi, 21 yirmi bir, 16 on altı.
_TR_UNITS = ("sıfır", "bir", "iki", "üç", "dört", "beş", "altı", "yedi", "sekiz", "dokuz")
_TR_TENS = ("", "on", "yirmi", "otuz", "kırk", "elli")


def tr_dative(text):
    """`text` ending in a clock time, with the Turkish dative on it:
    "Paz 20:00" is "Paz 20:00'ye", "16:00" "16:00'ya", "21:30" "21:30'a".
    A time on the hour is read as its hour, yirmi; any other by its
    minutes, otuz. The suffix follows the spoken word's last vowel, a
    after a back vowel and e after a front one, with y between two
    vowels. Text that does not end in a time comes back as it is."""
    m = re.search(r"(\d{1,2})[:.](\d{2})$", text)
    if not m:
        return text
    hour, minute = int(m.group(1)), int(m.group(2))
    n = minute or hour
    word = _TR_UNITS[n % 10] if n % 10 or n == 0 else _TR_TENS[n // 10]
    vowel = [c for c in word if c in "aıoueiöü"][-1]
    suffix = "a" if vowel in "aıou" else "e"
    return f"{text}'{'y' if word[-1] in 'aıoueiöü' else ''}{suffix}"


def lookup(table, key, lang, **kwargs):
    """The text for `key` in `lang`, falling back to the base language of
    a regional variant, then to English, then to the key itself.
    Formatted with kwargs only when some are given, so a text with
    literal braces survives a plain lookup."""
    for code in fallbacks(lang):
        strings = table.get(code)
        if strings is not None and key in strings:
            text = strings[key]
            break
    else:
        text = key
    return text.format(**kwargs) if kwargs else text
