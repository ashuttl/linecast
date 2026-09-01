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
        "in_time": "in {dur}",
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
        "in_time": "dans {dur}",
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
        "in_time": "en {dur}",
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
        "in_time": "in {dur}",
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
        "in_time": "tra {dur}",
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
        "in_time": "em {dur}",
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
        "in_time": "over {dur}",
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
        "in_time": "za {dur}",
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
        "in_time": "om {dur}",
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
        "in_time": "om {dur}",
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
        "in_time": "om {dur}",
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
        "in_time": "eftir {dur}",
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
        "in_time": "{dur} kuluttua",
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
        "in_time": "{dur}後",
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
        "in_time": "{dur} 후",
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
        "in_time": "{dur}后",
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
        "in_time": "dalam {dur}",
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


# ---------------------------------------------------------------------------
# The lunisolar calendar's names, for the languages whose readers know
# the moon through it (see _lunisolar.py for the calendar itself).
# ---------------------------------------------------------------------------

# Solar terms in longitude order, index 0 at the March equinox — the
# indexing current_term() and next_term() use.
SOLAR_TERMS_I18N = {
    "zh": ["春分", "清明", "谷雨", "立夏", "小满", "芒种",
           "夏至", "小暑", "大暑", "立秋", "处暑", "白露",
           "秋分", "寒露", "霜降", "立冬", "小雪", "大雪",
           "冬至", "小寒", "大寒", "立春", "雨水", "惊蛰"],
    "ja": ["春分", "清明", "穀雨", "立夏", "小満", "芒種",
           "夏至", "小暑", "大暑", "立秋", "処暑", "白露",
           "秋分", "寒露", "霜降", "立冬", "小雪", "大雪",
           "冬至", "小寒", "大寒", "立春", "雨水", "啓蟄"],
    "ko": ["춘분", "청명", "곡우", "입하", "소만", "망종",
           "하지", "소서", "대서", "입추", "처서", "백로",
           "추분", "한로", "상강", "입동", "소설", "대설",
           "동지", "소한", "대한", "입춘", "우수", "경칩"],
}

# Festivals dated by the lunar calendar, (month, day) → name. Japan
# moved its festivals to Gregorian dates in 1873; the two moon-viewing
# nights are what remains on the old calendar.
FESTIVALS_I18N = {
    "zh": {(1, 1): "春节", (1, 15): "元宵节", (5, 5): "端午节",
           (7, 7): "七夕", (8, 15): "中秋节", (9, 9): "重阳节"},
    "ja": {(8, 15): "十五夜", (9, 13): "十三夜"},
    "ko": {(1, 1): "설날", (1, 15): "정월대보름", (5, 5): "단오",
           (8, 15): "추석"},
}

# Chinese months and days have names, not numbers: the eleventh and
# twelfth months are 冬月 and 腊月, the first ten days take 初, the
# twenties 廿.
_ZH_MONTHS = ["正月", "二月", "三月", "四月", "五月", "六月",
              "七月", "八月", "九月", "十月", "冬月", "腊月"]
_ZH_DIGITS = "一二三四五六七八九十"


def _zh_day_name(day):
    if day <= 10:
        return "初" + _ZH_DIGITS[day - 1]
    if day < 20:
        return "十" + _ZH_DIGITS[day - 11]
    if day == 20:
        return "二十"
    if day < 30:
        return "廿" + _ZH_DIGITS[day - 21]
    return "三十"


def lunar_date_label(month, day, leap, lang):
    """The lunar date as its own calendar writes it."""
    if lang == "zh":
        leap_mark = "闰" if leap else ""
        return f"农历{leap_mark}{_ZH_MONTHS[month - 1]}{_zh_day_name(day)}"
    if lang == "ja":
        leap_mark = "閏" if leap else ""
        return f"旧暦{leap_mark}{month}月{day}日"
    if lang == "ko":
        leap_mark = "윤" if leap else ""
        return f"음력 {leap_mark}{month}월 {day}일"
    return f"{month}-{day}" + ("+" if leap else "")


def term_label(index, lang):
    """The localized name of solar term *index* (0 = March equinox)."""
    return SOLAR_TERMS_I18N.get(lang, SOLAR_TERMS_I18N["zh"])[index]
