"""The lookup shared by the per-command string tables.

Each command keeps its own table, {lang: {key: text}}; this module holds
the one way of reading them, so the fallback order lives in one place.
"""

import re

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

# The languages whose weather services and forecasts give wind speeds in
# metres per second: Japan, Korea, the Nordic countries, Russia, Ukraine,
# and the Czech Republic.  The rest of the metric world reads km/h.  The
# Chinese, Greek, and Vietnamese services use the Beaufort scale, which
# is a different thing altogether, so those stay on km/h.
WIND_MS_LANGUAGES = frozenset({"ja", "ko", "da", "no", "sv", "is", "fi", "cs", "ru", "uk"})

# Languages written right to left.  Their strings stay in logical order
# in the tables; the output pass (_bidi) puts each row in display order,
# and the views anchor text and run time charts from the right edge.
RTL_LANGUAGES = frozenset({"fa"})


def is_rtl(lang):
    """Whether `lang` is written right to left."""
    return base_language(lang) in RTL_LANGUAGES


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


# Languages whose sentences can carry a 12-hour time in their own words:
# English's "6pm", Greek's "6 το απόγευμα".  Every other language writes
# the 24-hour clock in running text whatever the country's habit -- a
# French reader looking at Montréal gets "vers 18h", as Environment
# Canada writes it, not an English "6pm".  Swahili has a further reason:
# it counts the hours from dawn, so "saa 1pm" would read as seven in the
# morning; its sentences tell the hour that way, "saa saba mchana".
SENTENCE_12H = frozenset({"en", "el"})


def sentence_24h(runtime):
    """Whether a time inside a sentence takes the 24-hour clock: the
    user's choice in a language of SENTENCE_12H, and always elsewhere."""
    if lang_of(runtime) not in SENTENCE_12H:
        return True
    return bool(getattr(runtime, "use_24h", False))


# Languages that write the percent sign before the number: %40.
PERCENT_FIRST = frozenset({"tr"})
# Languages that set the sign off with a space: 40 %. In Czech "40%"
# reads as the adjective, forty-percent.
PERCENT_SPACED = frozenset({"cs"})


# Languages that write a decimal comma: 11,3 mm.  Latin American Spanish,
# the base "es", keeps the point, as Mexico and most of the region do;
# Spain's variant takes the comma.
DECIMAL_COMMA = frozenset({
    "fr", "fr-CA", "es-ES", "pt", "pt-PT", "it", "ro", "de", "nl", "da", "no",
    "sv", "is", "fi", "cs", "pl", "ru", "uk", "el", "tr", "id", "vi", "eo",
})


def fmt_decimal(value, places, runtime):
    """`value` to `places` decimals with the display language's decimal
    mark: "11.3", "11,3"."""
    text = f"{value:.{places}f}"
    return text.replace(".", ",") if lang_of(runtime) in DECIMAL_COMMA else text


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
