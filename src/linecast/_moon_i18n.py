"""Moon command localization strings.

Phase names live in MOON_NAMES_I18N (in _tides_i18n, shared with the tides
chart's moon labels); this module holds the strings specific to the ``moon``
command plus month names for the full/new moon dates.
"""

from linecast._i18n import lang_of, lookup
from linecast._tides_i18n import MOON_NAMES_I18N, _moon_name  # noqa: F401 — re-export
from linecast._weather_i18n import DAY_NAMES  # re-export for convenience

_MOON_STRINGS = {
    "en": {
        "illuminated": "{pct}% illuminated",
        "age": "day {age} of {total}",
        "up_now": "Up now",
        "above_horizon": "{alt}° above the horizon",
        "below_horizon": "Below the horizon",
        "moonrise": "Moonrise",
        "moonset": "Moonset",
        "in_days": "in {days}d",
        "year_day": "Day {n} of {total}",
        "spring_equinox": "Spring equinox",
        "summer_solstice": "Summer solstice",
        "autumn_equinox": "Autumn equinox",
        "winter_solstice": "Winter solstice",
    },
    "fr": {
        "illuminated": "{pct} % éclairée",
        "age": "jour {age} sur {total}",
        "up_now": "Levée",
        "above_horizon": "{alt}° au-dessus de l'horizon",
        "below_horizon": "Sous l'horizon",
        "moonrise": "Lever de lune",
        "moonset": "Coucher de lune",
        "in_days": "dans {days} j",
        "year_day": "Jour {n} sur {total}",
        "spring_equinox": "Équinoxe de printemps",
        "summer_solstice": "Solstice d'été",
        "autumn_equinox": "Équinoxe d'automne",
        "winter_solstice": "Solstice d'hiver",
    },
    "es": {
        "illuminated": "{pct} % iluminada",
        "age": "día {age} de {total}",
        "up_now": "Visible ahora",
        "above_horizon": "{alt}° sobre el horizonte",
        "below_horizon": "Bajo el horizonte",
        "moonrise": "Salida de la luna",
        "moonset": "Puesta de la luna",
        "in_days": "en {days} d",
        "year_day": "Día {n} de {total}",
        "spring_equinox": "Equinoccio de primavera",
        "summer_solstice": "Solsticio de verano",
        "autumn_equinox": "Equinoccio de otoño",
        "winter_solstice": "Solsticio de invierno",
    },
    "de": {
        "illuminated": "{pct} % beleuchtet",
        "age": "Tag {age} von {total}",
        "up_now": "Jetzt sichtbar",
        "above_horizon": "{alt}° über dem Horizont",
        "below_horizon": "Unter dem Horizont",
        "moonrise": "Mondaufgang",
        "moonset": "Monduntergang",
        "in_days": "in {days} T",
        "year_day": "Tag {n} von {total}",
        "spring_equinox": "Frühlingsanfang",
        "summer_solstice": "Sommeranfang",
        "autumn_equinox": "Herbstanfang",
        "winter_solstice": "Winteranfang",
    },
    "it": {
        "illuminated": "{pct}% illuminata",
        "age": "giorno {age} di {total}",
        "up_now": "Visibile ora",
        "above_horizon": "{alt}° sopra l'orizzonte",
        "below_horizon": "Sotto l'orizzonte",
        "moonrise": "Sorgere della luna",
        "moonset": "Tramonto della luna",
        "in_days": "tra {days} g",
        "year_day": "Giorno {n} di {total}",
        "spring_equinox": "Equinozio di primavera",
        "summer_solstice": "Solstizio d'estate",
        "autumn_equinox": "Equinozio d'autunno",
        "winter_solstice": "Solstizio d'inverno",
    },
    "pt": {
        "illuminated": "{pct}% iluminada",
        "age": "dia {age} de {total}",
        "up_now": "Visível agora",
        "above_horizon": "{alt}° acima do horizonte",
        "below_horizon": "Abaixo do horizonte",
        "moonrise": "Nascer da lua",
        "moonset": "Pôr da lua",
        "in_days": "em {days} d",
        "year_day": "Dia {n} de {total}",
        "spring_equinox": "Equinócio de primavera",
        "summer_solstice": "Solstício de verão",
        "autumn_equinox": "Equinócio de outono",
        "winter_solstice": "Solstício de inverno",
    },
    "nl": {
        "illuminated": "{pct}% verlicht",
        "age": "dag {age} van {total}",
        "up_now": "Nu zichtbaar",
        "above_horizon": "{alt}° boven de horizon",
        "below_horizon": "Onder de horizon",
        "moonrise": "Maanopkomst",
        "moonset": "Maanondergang",
        "in_days": "over {days} d",
        "year_day": "Dag {n} van {total}",
        "spring_equinox": "Lente-equinox",
        "summer_solstice": "Zomerzonnewende",
        "autumn_equinox": "Herfstequinox",
        "winter_solstice": "Winterzonnewende",
    },
    "pl": {
        "illuminated": "{pct}% oświetlenia",
        "age": "dzień {age} z {total}",
        "up_now": "Nad horyzontem",
        "above_horizon": "{alt}° nad horyzontem",
        "below_horizon": "Pod horyzontem",
        "moonrise": "Wschód księżyca",
        "moonset": "Zachód księżyca",
        "in_days": "za {days} d",
        "year_day": "Dzień {n} z {total}",
        "spring_equinox": "Równonoc wiosenna",
        "summer_solstice": "Przesilenie letnie",
        "autumn_equinox": "Równonoc jesienna",
        "winter_solstice": "Przesilenie zimowe",
    },
    "no": {
        "illuminated": "{pct} % belyst",
        "age": "dag {age} av {total}",
        "up_now": "Oppe nå",
        "above_horizon": "{alt}° over horisonten",
        "below_horizon": "Under horisonten",
        "moonrise": "Måneoppgang",
        "moonset": "Månenedgang",
        "in_days": "om {days} d",
        "year_day": "Dag {n} av {total}",
        "spring_equinox": "Vårjevndøgn",
        "summer_solstice": "Sommersolverv",
        "autumn_equinox": "Høstjevndøgn",
        "winter_solstice": "Vintersolverv",
    },
    "sv": {
        "illuminated": "{pct} % belyst",
        "age": "dag {age} av {total}",
        "up_now": "Uppe nu",
        "above_horizon": "{alt}° över horisonten",
        "below_horizon": "Under horisonten",
        "moonrise": "Månuppgång",
        "moonset": "Månnedgång",
        "in_days": "om {days} d",
        "year_day": "Dag {n} av {total}",
        "spring_equinox": "Vårdagjämning",
        "summer_solstice": "Sommarsolstånd",
        "autumn_equinox": "Höstdagjämning",
        "winter_solstice": "Vintersolstånd",
    },
    "da": {
        "illuminated": "{pct} % belyst",
        "age": "dag {age} af {total}",
        "up_now": "Oppe nu",
        "above_horizon": "{alt}° over horisonten",
        "below_horizon": "Under horisonten",
        "moonrise": "Måneopgang",
        "moonset": "Månenedgang",
        "in_days": "om {days} d",
        "year_day": "Dag {n} af {total}",
        "spring_equinox": "Forårsjævndøgn",
        "summer_solstice": "Sommersolhverv",
        "autumn_equinox": "Efterårsjævndøgn",
        "winter_solstice": "Vintersolhverv",
    },
    "is": {
        "illuminated": "{pct}% upplýst",
        "age": "dagur {age} af {total}",
        "up_now": "Á lofti núna",
        "above_horizon": "{alt}° yfir sjóndeildarhring",
        "below_horizon": "Undir sjóndeildarhring",
        "moonrise": "Tunglris",
        "moonset": "Tunglsetur",
        "in_days": "eftir {days} d",
        "year_day": "Dagur {n} af {total}",
        "spring_equinox": "Vorjafndægur",
        "summer_solstice": "Sumarsólstöður",
        "autumn_equinox": "Haustjafndægur",
        "winter_solstice": "Vetrarsólstöður",
    },
    "fi": {
        "illuminated": "{pct} % valaistunut",
        "age": "päivä {age} / {total}",
        "up_now": "Näkyvissä nyt",
        "above_horizon": "{alt}° horisontin yläpuolella",
        "below_horizon": "Horisontin alapuolella",
        "moonrise": "Kuunnousu",
        "moonset": "Kuunlasku",
        "in_days": "{days} pv kuluttua",
        "year_day": "Päivä {n} / {total}",
        "spring_equinox": "Kevätpäiväntasaus",
        "summer_solstice": "Kesäpäivänseisaus",
        "autumn_equinox": "Syyspäiväntasaus",
        "winter_solstice": "Talvipäivänseisaus",
    },
    "ja": {
        "illuminated": "輝面比 {pct}%",
        "age": "月齢 {age} / {total}",
        "up_now": "現在昇っています",
        "above_horizon": "高度 {alt}°",
        "below_horizon": "地平線の下",
        "moonrise": "月の出",
        "moonset": "月の入り",
        "in_days": "{days}日後",
        "year_day": "今年 {n} 日目 / {total} 日",
        "spring_equinox": "春分",
        "summer_solstice": "夏至",
        "autumn_equinox": "秋分",
        "winter_solstice": "冬至",
    },
    "ko": {
        "illuminated": "{pct}% 밝음",
        "age": "월령 {age} / {total}",
        "up_now": "지금 떠 있음",
        "above_horizon": "고도 {alt}°",
        "below_horizon": "지평선 아래",
        "moonrise": "월출",
        "moonset": "월몰",
        "in_days": "{days}일 후",
        "year_day": "올해 {n}일째 / {total}일",
        "spring_equinox": "춘분",
        "summer_solstice": "하지",
        "autumn_equinox": "추분",
        "winter_solstice": "동지",
    },
    "zh": {
        "illuminated": "亮面 {pct}%",
        "age": "月龄 {age} / {total}",
        "up_now": "现在已升起",
        "above_horizon": "高度 {alt}°",
        "below_horizon": "在地平线下",
        "moonrise": "月出",
        "moonset": "月落",
        "in_days": "{days}天后",
        "year_day": "今年第 {n} 天 / {total} 天",
        "spring_equinox": "春分",
        "summer_solstice": "夏至",
        "autumn_equinox": "秋分",
        "winter_solstice": "冬至",
    },
    "id": {
        "illuminated": "{pct}% diterangi",
        "age": "hari {age} dari {total}",
        "up_now": "Di atas cakrawala",
        "above_horizon": "{alt}° di atas cakrawala",
        "below_horizon": "Di bawah cakrawala",
        "moonrise": "Bulan terbit",
        "moonset": "Bulan terbenam",
        "in_days": "dalam {days} hr",
        "year_day": "Hari ke-{n} dari {total}",
        "spring_equinox": "Ekuinoks musim semi",
        "summer_solstice": "Solstis musim panas",
        "autumn_equinox": "Ekuinoks musim gugur",
        "winter_solstice": "Solstis musim dingin",
    },
}


# Abbreviated month names, January..December. CJK and Finnish dates are
# formatted numerically via DATE_MD below, so those entries are unused.
MONTHS_I18N = {
    "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
            "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
    "fr": ["janv", "févr", "mars", "avr", "mai", "juin",
            "juil", "août", "sept", "oct", "nov", "déc"],
    "es": ["ene", "feb", "mar", "abr", "may", "jun",
            "jul", "ago", "sep", "oct", "nov", "dic"],
    "de": ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun",
            "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"],
    "it": ["gen", "feb", "mar", "apr", "mag", "giu",
            "lug", "ago", "set", "ott", "nov", "dic"],
    "pt": ["jan", "fev", "mar", "abr", "mai", "jun",
            "jul", "ago", "set", "out", "nov", "dez"],
    "nl": ["jan", "feb", "mrt", "apr", "mei", "jun",
            "jul", "aug", "sep", "okt", "nov", "dec"],
    "pl": ["sty", "lut", "mar", "kwi", "maj", "cze",
            "lip", "sie", "wrz", "paź", "lis", "gru"],
    "no": ["jan", "feb", "mar", "apr", "mai", "jun",
            "jul", "aug", "sep", "okt", "nov", "des"],
    "sv": ["jan", "feb", "mar", "apr", "maj", "jun",
            "jul", "aug", "sep", "okt", "nov", "dec"],
    "da": ["jan", "feb", "mar", "apr", "maj", "jun",
            "jul", "aug", "sep", "okt", "nov", "dec"],
    "is": ["jan", "feb", "mar", "apr", "maí", "jún",
            "júl", "ágú", "sep", "okt", "nóv", "des"],
    "id": ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun",
            "Jul", "Agu", "Sep", "Okt", "Nov", "Des"],
}

# Date order/format per language: {month} = abbreviated name from
# MONTHS_I18N, {mnum} = month number, {day} = day of month.
_DATE_MD = {
    "en": "{month} {day}",
    "de": "{day}. {month}",
    "fi": "{day}.{mnum}.",
    "ja": "{mnum}月{day}日",
    "zh": "{mnum}月{day}日",
    "ko": "{mnum}월 {day}일",
}
_DATE_MD_DEFAULT = "{day} {month}"


def _ms(key, runtime, **kwargs):
    """Look up a moon-specific localized string."""
    return lookup(_MOON_STRINGS, key, lang_of(runtime), **kwargs)


# Season names for the four events (March equinox, June solstice,
# September equinox, December solstice), by hemisphere.  East Asian
# solar terms (春分, 夏至, …) name the event itself, not the local
# season, so those languages keep the northern mapping everywhere.
_SEASON_KEYS_NORTH = ("spring_equinox", "summer_solstice",
                      "autumn_equinox", "winter_solstice")
_SEASON_KEYS_SOUTH = ("autumn_equinox", "winter_solstice",
                      "spring_equinox", "summer_solstice")
_SEASON_ABSOLUTE_LANGS = frozenset({"ja", "ko", "zh"})


def _season_label(event, lat, runtime):
    """Localized name for a season event index, seen from latitude *lat*."""
    south = lat is not None and lat < 0
    if south and lang_of(runtime) not in _SEASON_ABSOLUTE_LANGS:
        return _ms(_SEASON_KEYS_SOUTH[event], runtime)
    return _ms(_SEASON_KEYS_NORTH[event], runtime)


def _fmt_month_day(dt, runtime):
    """Format a month + day date in the runtime language's convention."""
    lang = lang_of(runtime)
    fmt = _DATE_MD.get(lang, _DATE_MD_DEFAULT)
    months = MONTHS_I18N.get(lang, MONTHS_I18N["en"])
    return fmt.format(month=months[dt.month - 1], mnum=dt.month, day=dt.day)


def _day_abbrev(dt, runtime):
    """Localized three-letter-ish weekday abbreviation."""
    return DAY_NAMES.get(lang_of(runtime), DAY_NAMES["en"])[dt.weekday()]
