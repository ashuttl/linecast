"""Sunshine localization strings.

Month names and month-day date order come from the moon tables; this
module holds the year view's relative-day phrases and the numeric month
labels for the languages whose month names don't abbreviate.
"""

from linecast._i18n import lang_of, lookup
from linecast._moon_i18n import MONTHS_I18N, _fmt_month_day  # noqa: F401 — re-export

_SUNSHINE_STRINGS = {
    "en": {
        "today": "today",
        "in_day": "in {n} day",
        "in_days": "in {n} days",
        "day_ago": "{n} day ago",
        "days_ago": "{n} days ago",
        "sky_night": "night",
        "sky_astronomical": "astronomical twilight",
        "sky_nautical": "nautical twilight",
        "sky_civil": "civil twilight",
        "sky_day": "daylight",
        "midnight_sun": "midnight sun",
        "polar_night": "polar night",
        "solar_noon": "solar noon",
        "sunrise": "sunrise",
        "sunset": "sunset",
    },
    "fr": {
        "today": "aujourd'hui",
        "in_day": "dans {n} jour",
        "in_days": "dans {n} jours",
        "day_ago": "il y a {n} jour",
        "days_ago": "il y a {n} jours",
        "sky_night": "nuit",
        "sky_astronomical": "crépuscule astronomique",
        "sky_nautical": "crépuscule nautique",
        "sky_civil": "crépuscule civil",
        "sky_astronomical_dawn": "aube astronomique",
        "sky_nautical_dawn": "aube nautique",
        "sky_civil_dawn": "aube civile",
        "sky_day": "jour",
        "midnight_sun": "soleil de minuit",
        "polar_night": "nuit polaire",
        "solar_noon": "midi solaire",
        "sunrise": "lever du soleil",
        "sunset": "coucher du soleil",
    },
    "es": {
        "today": "hoy",
        "in_day": "en {n} día",
        "in_days": "en {n} días",
        "day_ago": "hace {n} día",
        "days_ago": "hace {n} días",
        "sky_night": "noche",
        "sky_astronomical": "crepúsculo astronómico",
        "sky_nautical": "crepúsculo náutico",
        "sky_civil": "crepúsculo civil",
        "sky_astronomical_dawn": "crepúsculo astronómico matutino",
        "sky_nautical_dawn": "crepúsculo náutico matutino",
        "sky_civil_dawn": "crepúsculo civil matutino",
        "sky_day": "día",
        "midnight_sun": "sol de medianoche",
        "polar_night": "noche polar",
        "solar_noon": "mediodía solar",
        "sunrise": "amanecer",
        "sunset": "atardecer",
    },
    "de": {
        "today": "heute",
        "in_day": "in {n} Tag",
        "in_days": "in {n} Tagen",
        "day_ago": "vor {n} Tag",
        "days_ago": "vor {n} Tagen",
        "sky_night": "Nacht",
        "sky_astronomical": "astronomische Dämmerung",
        "sky_nautical": "nautische Dämmerung",
        "sky_civil": "bürgerliche Dämmerung",
        "sky_astronomical_dawn": "astronomische Morgendämmerung",
        "sky_nautical_dawn": "nautische Morgendämmerung",
        "sky_civil_dawn": "bürgerliche Morgendämmerung",
        "sky_astronomical_dusk": "astronomische Abenddämmerung",
        "sky_nautical_dusk": "nautische Abenddämmerung",
        "sky_civil_dusk": "bürgerliche Abenddämmerung",
        "sky_day": "Tag",
        "midnight_sun": "Mitternachtssonne",
        "polar_night": "Polarnacht",
        "solar_noon": "Sonnenhöchststand",
        "sunrise": "Sonnenaufgang",
        "sunset": "Sonnenuntergang",
    },
    "it": {
        "today": "oggi",
        "in_day": "tra {n} giorno",
        "in_days": "tra {n} giorni",
        "day_ago": "{n} giorno fa",
        "days_ago": "{n} giorni fa",
        "sky_night": "notte",
        "sky_astronomical": "crepuscolo astronomico",
        "sky_nautical": "crepuscolo nautico",
        "sky_civil": "crepuscolo civile",
        "sky_astronomical_dawn": "crepuscolo astronomico mattutino",
        "sky_nautical_dawn": "crepuscolo nautico mattutino",
        "sky_civil_dawn": "crepuscolo civile mattutino",
        "sky_day": "giorno",
        "midnight_sun": "sole di mezzanotte",
        "polar_night": "notte polare",
        "solar_noon": "mezzogiorno solare",
        "sunrise": "alba",
        "sunset": "tramonto",
    },
    "pt": {
        "today": "hoje",
        "in_day": "em {n} dia",
        "in_days": "em {n} dias",
        "day_ago": "há {n} dia",
        "days_ago": "há {n} dias",
        "sky_night": "noite",
        "sky_astronomical": "crepúsculo astronômico",
        "sky_nautical": "crepúsculo náutico",
        "sky_civil": "crepúsculo civil",
        "sky_astronomical_dawn": "crepúsculo astronômico matutino",
        "sky_nautical_dawn": "crepúsculo náutico matutino",
        "sky_civil_dawn": "crepúsculo civil matutino",
        "sky_day": "dia",
        "midnight_sun": "sol da meia-noite",
        "polar_night": "noite polar",
        "solar_noon": "meio-dia solar",
        "sunrise": "nascer do sol",
        "sunset": "pôr do sol",
    },
    "nl": {
        "today": "vandaag",
        "in_day": "over {n} dag",
        "in_days": "over {n} dagen",
        "day_ago": "{n} dag geleden",
        "days_ago": "{n} dagen geleden",
        "sky_night": "nacht",
        "sky_astronomical": "astronomische schemering",
        "sky_nautical": "nautische schemering",
        "sky_civil": "burgerlijke schemering",
        "sky_astronomical_dawn": "astronomische ochtendschemering",
        "sky_nautical_dawn": "nautische ochtendschemering",
        "sky_civil_dawn": "burgerlijke ochtendschemering",
        "sky_astronomical_dusk": "astronomische avondschemering",
        "sky_nautical_dusk": "nautische avondschemering",
        "sky_civil_dusk": "burgerlijke avondschemering",
        "sky_day": "dag",
        "midnight_sun": "middernachtzon",
        "polar_night": "poolnacht",
        "solar_noon": "zonnemiddag",
        "sunrise": "zonsopkomst",
        "sunset": "zonsondergang",
    },
    "pl": {
        "today": "dziś",
        "in_day": "za {n} dzień",
        "in_days": "za {n} dni",
        "day_ago": "{n} dzień temu",
        "days_ago": "{n} dni temu",
        "sky_night": "noc",
        "sky_astronomical": "zmierzch astronomiczny",
        "sky_nautical": "zmierzch żeglarski",
        "sky_civil": "zmierzch cywilny",
        "sky_astronomical_dawn": "świt astronomiczny",
        "sky_nautical_dawn": "świt żeglarski",
        "sky_civil_dawn": "świt cywilny",
        "sky_day": "dzień",
        "midnight_sun": "słońce o północy",
        "polar_night": "noc polarna",
        "solar_noon": "południe słoneczne",
        "sunrise": "wschód słońca",
        "sunset": "zachód słońca",
    },
    "no": {
        "today": "i dag",
        "in_day": "om {n} dag",
        "in_days": "om {n} dager",
        "day_ago": "{n} dag siden",
        "days_ago": "{n} dager siden",
        "sky_night": "natt",
        "sky_astronomical": "astronomisk tussmørke",
        "sky_nautical": "nautisk tussmørke",
        "sky_civil": "borgerlig tussmørke",
        "sky_day": "dag",
        "midnight_sun": "midnattssol",
        "polar_night": "mørketid",
        "solar_noon": "solmiddag",
        "sunrise": "soloppgang",
        "sunset": "solnedgang",
    },
    "sv": {
        "today": "i dag",
        "in_day": "om {n} dag",
        "in_days": "om {n} dagar",
        "day_ago": "{n} dag sedan",
        "days_ago": "{n} dagar sedan",
        "sky_night": "natt",
        "sky_astronomical": "astronomisk skymning",
        "sky_nautical": "nautisk skymning",
        "sky_civil": "borgerlig skymning",
        "sky_astronomical_dawn": "astronomisk gryning",
        "sky_nautical_dawn": "nautisk gryning",
        "sky_civil_dawn": "borgerlig gryning",
        "sky_day": "dag",
        "midnight_sun": "midnattssol",
        "polar_night": "polarnatt",
        "solar_noon": "solmiddag",
        "sunrise": "soluppgång",
        "sunset": "solnedgång",
    },
    "da": {
        "today": "i dag",
        "in_day": "om {n} dag",
        "in_days": "om {n} dage",
        "day_ago": "{n} dag siden",
        "days_ago": "{n} dage siden",
        "sky_night": "nat",
        "sky_astronomical": "astronomisk tusmørke",
        "sky_nautical": "nautisk tusmørke",
        "sky_civil": "borgerligt tusmørke",
        "sky_day": "dag",
        "midnight_sun": "midnatssol",
        "polar_night": "polarnat",
        "solar_noon": "solmiddag",
        "sunrise": "solopgang",
        "sunset": "solnedgang",
    },
    "is": {
        "today": "í dag",
        "in_day": "eftir {n} dag",
        "in_days": "eftir {n} daga",
        "day_ago": "fyrir {n} degi",
        "days_ago": "fyrir {n} dögum",
        "sky_night": "nótt",
        "sky_astronomical": "stjörnufræðileg ljósaskipti",
        "sky_nautical": "siglingaljósaskipti",
        "sky_civil": "borgaraleg ljósaskipti",
        "sky_day": "dagur",
        "midnight_sun": "miðnætursól",
        "polar_night": "heimskautanótt",
        "solar_noon": "sólarhádegi",
        "sunrise": "sólarupprás",
        "sunset": "sólsetur",
    },
    "fi": {
        "today": "tänään",
        "in_day": "{n} päivän kuluttua",
        "in_days": "{n} päivän kuluttua",
        "day_ago": "{n} päivä sitten",
        "days_ago": "{n} päivää sitten",
        "sky_night": "yö",
        "sky_astronomical": "astronominen hämärä",
        "sky_nautical": "nauttinen hämärä",
        "sky_civil": "porvarillinen hämärä",
        "sky_day": "päivä",
        "midnight_sun": "yötön yö",
        "polar_night": "kaamos",
        "solar_noon": "aurinkokeskipäivä",
        "sunrise": "auringonnousu",
        "sunset": "auringonlasku",
    },
    "ja": {
        "today": "今日",
        "in_day": "{n}日後",
        "in_days": "{n}日後",
        "day_ago": "{n}日前",
        "days_ago": "{n}日前",
        "sky_night": "夜",
        "sky_astronomical": "天文薄明",
        "sky_nautical": "航海薄明",
        "sky_civil": "市民薄明",
        "sky_day": "昼",
        "midnight_sun": "白夜",
        "polar_night": "極夜",
        "solar_noon": "南中",
        "sunrise": "日の出",
        "sunset": "日の入り",
    },
    "ko": {
        "today": "오늘",
        "in_day": "{n}일 후",
        "in_days": "{n}일 후",
        "day_ago": "{n}일 전",
        "days_ago": "{n}일 전",
        "sky_night": "밤",
        "sky_astronomical": "천문박명",
        "sky_nautical": "항해박명",
        "sky_civil": "시민박명",
        "sky_day": "낮",
        "midnight_sun": "백야",
        "polar_night": "극야",
        "solar_noon": "남중",
        "sunrise": "일출",
        "sunset": "일몰",
    },
    "zh": {
        "today": "今天",
        "in_day": "{n}天后",
        "in_days": "{n}天后",
        "day_ago": "{n}天前",
        "days_ago": "{n}天前",
        "sky_night": "夜晚",
        "sky_astronomical": "天文曙暮光",
        "sky_nautical": "航海曙暮光",
        "sky_civil": "民用曙暮光",
        "sky_astronomical_dawn": "天文晨光",
        "sky_nautical_dawn": "航海晨光",
        "sky_civil_dawn": "民用晨光",
        "sky_astronomical_dusk": "天文昏影",
        "sky_nautical_dusk": "航海昏影",
        "sky_civil_dusk": "民用昏影",
        "sky_day": "白天",
        "midnight_sun": "极昼",
        "polar_night": "极夜",
        "solar_noon": "太阳正午",
        "sunrise": "日出",
        "sunset": "日落",
    },
    "id": {
        "today": "hari ini",
        "in_day": "{n} hari lagi",
        "in_days": "{n} hari lagi",
        "day_ago": "{n} hari lalu",
        "days_ago": "{n} hari lalu",
        "sky_night": "malam",
        "sky_astronomical": "senja astronomi",
        "sky_nautical": "senja nautika",
        "sky_civil": "senja sipil",
        "sky_astronomical_dawn": "fajar astronomi",
        "sky_nautical_dawn": "fajar nautika",
        "sky_civil_dawn": "fajar sipil",
        "sky_day": "siang",
        "midnight_sun": "matahari tengah malam",
        "polar_night": "malam kutub",
        "solar_noon": "tengah hari surya",
        "sunrise": "matahari terbit",
        "sunset": "matahari terbenam",
    },
}

# Month-axis labels for languages whose month names aren't abbreviated in
# MONTHS_I18N (CJK dates are numeric; Finnish months are long words).
# Everything else takes the first letters of the MONTHS_I18N name.
_AXIS_MONTHS = {
    "fi": ["tam", "hel", "maa", "huh", "tou", "kes",
           "hei", "elo", "syy", "lok", "mar", "jou"],
    "ja": [f"{m}月" for m in range(1, 13)],
    "ko": [f"{m}월" for m in range(1, 13)],
    "zh": [f"{m}月" for m in range(1, 13)],
}
_NUMERIC_AXIS_LANGS = frozenset({"ja", "ko", "zh"})


def _ss(key, runtime, **kwargs):
    """Look up a sunshine-specific localized string."""
    return lookup(_SUNSHINE_STRINGS, key, lang_of(runtime), **kwargs)


def sky_phase(elev, runtime, morning=None):
    """Name the sky for a sun elevation: day, the three twilights, night.

    Many languages name the two twilights of a day with different words
    — Polish świt and zmierzch, Indonesian fajar and senja, Swedish
    gryning and skymning — so *morning* tells them apart: True before
    solar noon, False after, None for a language-generic name. Languages
    without the split simply have no _dawn/_dusk entries and keep their
    one word either way.
    """
    if elev >= -0.833:
        key = "sky_day"
    elif elev >= -6:
        key = "sky_civil"
    elif elev >= -12:
        key = "sky_nautical"
    elif elev >= -18:
        key = "sky_astronomical"
    else:
        key = "sky_night"
    if morning is not None and key.startswith("sky_") and key not in (
            "sky_day", "sky_night"):
        table = _SUNSHINE_STRINGS.get(lang_of(runtime), {})
        variant = key + ("_dawn" if morning else "_dusk")
        if variant in table:
            key = variant
    return _ss(key, runtime)


def sky_event(key, runtime):
    """'solar noon', 'sunrise', 'sunset'."""
    return _ss(key, runtime)


def polar_name(state, runtime):
    """'midnight sun' or 'polar night' for a polar_state(), else "".

    On a day with no horizon crossing solar_times() returns solar noon
    for both the rise and the set. The phrase goes where those clock
    times would, there being none to give.
    """
    if state == "day":
        return _ss("midnight_sun", runtime)
    if state == "night":
        return _ss("polar_night", runtime)
    return ""


def relative_day(diff, runtime):
    """'today', 'in 3 days', '2 days ago' for a day offset from today."""
    if diff == 0:
        return _ss("today", runtime)
    n = abs(diff)
    if diff > 0:
        return _ss("in_day" if n == 1 else "in_days", runtime, n=n)
    return _ss("day_ago" if n == 1 else "days_ago", runtime, n=n)


def axis_month_labels(runtime, narrow=False):
    """Twelve month labels for the year axis, ordered January..December.

    Wide labels are three-character month abbreviations (CJK: '1月');
    narrow ones are a single letter, or the month number where a letter
    would mean nothing.
    """
    lang = lang_of(runtime)
    if narrow:
        if lang in _NUMERIC_AXIS_LANGS:
            return [str(m) for m in range(1, 13)]
        names = _AXIS_MONTHS.get(lang) or MONTHS_I18N.get(lang, MONTHS_I18N["en"])
        return [name[:1].upper() for name in names]
    names = _AXIS_MONTHS.get(lang) or MONTHS_I18N.get(lang, MONTHS_I18N["en"])
    return [name[:3] for name in names]
