"""Localized strings and weather code labels for the weather dashboard."""

import re
from linecast._i18n import LocaleTable, base_language, fallbacks, has_text, lang_of, lookup
from linecast.weather.cover import MOSTLY_CLOUDY

# Nerd Font WMO icons
_WMO_ICONS_NERD = {
    0: "\U000F0599", 1: "\U000F0599", 2: "\U000F0595", 3: "\U000F0590",
    MOSTLY_CLOUDY: "\U000F0590",
    45: "\U000F0591", 48: "\U000F0591",
    51: "\U000F0597", 53: "\U000F0597", 55: "\U000F0597",
    56: "\U000F0597", 57: "\U000F0597",
    61: "\U000F0596", 63: "\U000F0596", 65: "\U000F0596",
    66: "\U000F0596", 67: "\U000F0596",
    71: "\U000F0F36", 73: "\U000F0F36", 75: "\U000F0F36", 77: "\U000F0F36",
    80: "\U000F0596", 81: "\U000F0596", 82: "\U000F0596",
    85: "\U000F0F36", 86: "\U000F0F36",
    95: "\U000F0593", 96: "\U000F0593", 99: "\U000F0593",
}

# Emoji fallback WMO icons (no Nerd Font required)
_WMO_ICONS_EMOJI = {
    0: "☀\ufe0f",  1: "\U0001f324\ufe0f",  2: "⛅", 3: "☁\ufe0f",
    MOSTLY_CLOUDY: "\U0001f325\ufe0f",
    45: "\U0001f32b\ufe0f", 48: "\U0001f32b\ufe0f",
    51: "\U0001f326\ufe0f", 53: "\U0001f326\ufe0f", 55: "\U0001f326\ufe0f",
    56: "\U0001f327\ufe0f", 57: "\U0001f327\ufe0f",
    61: "\U0001f327\ufe0f", 63: "\U0001f327\ufe0f", 65: "\U0001f327\ufe0f",
    66: "\U0001f327\ufe0f", 67: "\U0001f327\ufe0f",
    71: "\U0001f328\ufe0f", 73: "\U0001f328\ufe0f", 75: "\U0001f328\ufe0f", 77: "\U0001f328\ufe0f",
    80: "\U0001f326\ufe0f", 81: "\U0001f326\ufe0f", 82: "\U0001f326\ufe0f",
    85: "\U0001f328\ufe0f", 86: "\U0001f328\ufe0f",
    95: "⛈\ufe0f",  96: "⛈\ufe0f",  99: "⛈\ufe0f",
}


# Plain Unicode WMO icons: text-presentation glyphs with wide font
# coverage, single-cell everywhere.  Partly cloudy, mostly cloudy and
# overcast share a cloud; the label beside the icon keeps them apart.
_WMO_ICONS_PLAIN = {
    0: "☀", 1: "☀", 2: "☁", 3: "☁", MOSTLY_CLOUDY: "☁",
    45: "≡", 48: "≡",
    51: "☂", 53: "☂", 55: "☂",
    56: "☂", 57: "☂",
    61: "☂", 63: "☂", 65: "☂",
    66: "☂", 67: "☂",
    71: "❄", 73: "❄", 75: "❄", 77: "❄",
    80: "☂", 81: "☂", 82: "☂",
    85: "❄", 86: "❄",
    95: "☈", 96: "☈", 99: "☈",
}


def _wmo_icons(runtime):
    return {"nerd": _WMO_ICONS_NERD, "emoji": _WMO_ICONS_EMOJI,
            "plain": _WMO_ICONS_PLAIN}[runtime.icons]


WMO_NAMES = {
    0: "Clear", 1: "Mostly clear", 2: "Partly cloudy", 3: "Overcast",
    MOSTLY_CLOUDY: "Mostly cloudy",
    45: "Fog", 48: "Rime fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle",
    56: "Freezing drizzle", 57: "Freezing drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain",
    66: "Freezing rain", 67: "Freezing rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow", 77: "Snow grains",
    80: "Light showers", 81: "Showers", 82: "Heavy showers",
    85: "Snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm", 99: "Thunderstorm",
}

DAY_NAMES = LocaleTable("DAY_NAMES")

FULL_DAY_NAMES = LocaleTable("FULL_DAY_NAMES")

WMO_NAMES_I18N = LocaleTable("CONDITIONS")

_PRECIP_DESCS_I18N = LocaleTable("PRECIP")

# The precipitation nouns in the form a template needs after a verb or
# preposition, where that is not the bare noun: French with its article
# after "then" or "with" ("puis des orages", "avec de fortes pluies"),
# Finnish in the partitive ("iltapäivällä ukkosta"), Russian and
# Ukrainian in the instrumental after "turns to" ("сменится дождём"),
# Polish and Czech in the accusative after it ("przejdzie w mżawkę",
# with Czech's preposition, which turns to "ve" before some nouns: "ve
# sněžení").  A template asks for the turn's noun as {peak_art} and the
# run's own as {desc_art}; a code or language without one reads the
# bare noun.
_PRECIP_PARTITIVES_I18N = LocaleTable("PRECIP_PARTITIVES")

# The precipitation nouns with the definite article, where a sentence
# needs the thing itself rather than some of it: French "fin des averses",
# "retour de la bruine"; Romanian "ploaia încetează".  A template asks
# for them as {desc_def}; a code or language without one reads the bare
# noun.  French contracts its "de les" to "des" after formatting.
_PRECIP_DEFINITES_I18N = LocaleTable("PRECIP_DEFINITES")

# The preposition before a weekday changes shape in Russian and Czech
# before some days, and keeps it before their abbreviations: "во вт",
# "ve st", "ve čt". Greek Saturday takes the neuter article "το".
# Keyed by weekday() where it differs from `on_day`.
ON_DAY_FORMS = LocaleTable("ON_DAY")

# The same for a full day name, "on Friday" in the week sentence, where a
# language declines the day or picks its preposition by the day.  A
# language without an entry uses its "on_full_day" string.
ON_FULL_DAY_FORMS = LocaleTable("ON_FULL_DAY")

# A run of days in the week sentence, "on Thursday and Friday" and "from
# Saturday to Monday": the form of each day by its place in the phrase,
# for the languages that decline the days there -- "and_first" and
# "and_second" in "on_two_days", "from" and "to" in "from_day_to_day".
# A form may carry its own preposition where the language picks it by the
# day.  A day without an entry is its plain full name.
DAY_SPAN_FORMS = LocaleTable("DAY_SPANS")

# The noun for what falls on several days of the week sentence, where the
# language counts storms and a day's storm is singular: "С пятницы по
# воскресенье грозы".
PRECIP_RUN_DESCS_I18N = LocaleTable("PRECIP_RUNS")

# Localized UI strings
_STRINGS = LocaleTable("WEATHER")


def wmo_label(code, lang, default=""):
    """The WMO weather code's name in `lang`, read through a regional
    variant's base, else the English one, else `default`."""
    for lang_code in fallbacks(lang):
        if lang_code == "en":
            break
        name = WMO_NAMES_I18N.get(lang_code, {}).get(code)
        if name:
            return name
    return WMO_NAMES.get(code, default)


def fmt_wind(speed, runtime):
    """A wind speed with its unit as the display language writes it:
    "12km/h", "12 km/sa", "12m/s", "12 м/с", "12mph", "12 mph"."""
    sep = _s("metric_unit_sep", runtime)
    return f"{speed:.0f}{sep}{runtime.wind_unit_label}"


def _s(key, runtime, **kwargs):
    """Look up a localized string, with optional format substitution."""
    lang = lang_of(runtime)
    if "time" in kwargs and has_text(_STRINGS, key + "_one", lang):
        # One o'clock takes the singular article where the others take
        # the plural: "στη 1" but "στις 2", "hacia la 1:00" but "hacia
        # las 2:00", "por volta da 1h".  Also accept 01:00 and compact
        # tooltip times such as 1:30p. The clock format still follows
        # the user.
        if re.match(r"0?1(?:\D|$)", str(kwargs["time"])):
            key += "_one"
    return lookup(_STRINGS, key, lang, **kwargs)


# Where a forecast template has to agree with its precipitation noun, the
# codes that take a variant of the template, by the suffix of that variant.
# Swahili manyunyu (drizzle) takes ma-class agreement and vipindi (showers)
# ki-vi, where mvua and theluji take i-; French averses and orages are
# plural, as are the Finnish and Czech showers and snow grains, and the
# Polish showers and storms (opady, burze).  Chosen by
# weather code so editing a description does not change its grammar.
_PRECIP_CLASSES = LocaleTable("PRECIP_CLASSES")

# French "de" before a vowel or mute h: "risque d'averses", "risque de pluie"
_FR_ELISION = re.compile(r"\b([dD])e ([aeiouyàâéèêëîïôöûüh])")
# And "de" before the plural article: "fin des averses", not "de les"
_FR_CONTRACTION = re.compile(r"\b([dD])e les\b")


def _precip_s(key, code, runtime, **kwargs):
    """A forecast template agreeing with its precipitation noun: the
    variant for the noun's class where the language has one, else the
    plain template.  The noun with its definite article is there as
    {desc_def} for the languages that have it, and in the form the
    language's partitives table gives it as {desc_art}: Finnish
    "iltapäivällä sadetta".  French contracts and elides its "de"
    afterwards."""
    lang = lang_of(runtime)
    classes = _PRECIP_CLASSES.get(lang, _PRECIP_CLASSES.get(base_language(lang), {}))
    for suffix, codes in classes.items():
        if code in codes and has_text(_STRINGS, key + suffix, lang):
            key += suffix
            break
    if "desc" in kwargs and "desc_def" not in kwargs:
        definites = _PRECIP_DEFINITES_I18N.get(
            lang, _PRECIP_DEFINITES_I18N.get(base_language(lang), {}))
        kwargs["desc_def"] = definites.get(code, kwargs["desc"])
    if "desc" in kwargs and "desc_art" not in kwargs:
        forms = {}
        for lang_code in reversed(fallbacks(lang)):
            forms.update(_PRECIP_PARTITIVES_I18N.get(lang_code, {}))
        kwargs["desc_art"] = forms.get(code, kwargs["desc"])
    text = lookup(_STRINGS, key, lang, **kwargs)
    if base_language(lang) == "fr":
        text = _FR_CONTRACTION.sub(r"\1es", text)
        text = _FR_ELISION.sub(r"\1'\2", text)
    return text


def has_string(key):
    """Whether `key` is a string of the app's, in any language."""
    return key in _STRINGS["en"]


def felt_index(record, runtime, i=None):
    """Canada's humidex or wind chill where they stand in for feels-like:
    ("humidex", 34), ("wind_chill", -25), or None when neither is
    reported.  False when they do not stand in at all -- the place is
    not in Canada, the reader is on Fahrenheit (weather.humidex), or
    the language has no words of its own for them, which English and
    French, the country's two, do.  `record` is the forecast's current
    readings, or its hourly ones with `i` the hour."""
    if "humidex" not in record or not has_text(_STRINGS, "humidex", lang_of(runtime)):
        return False
    for key in ("humidex", "wind_chill"):
        value = record[key] if i is None else _at(record[key], i)
        if value is not None:
            return key, value
    return None


def _at(values, i):
    return values[i] if values is not None and 0 <= i < len(values) else None
