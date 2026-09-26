"""Moon command localization strings.

Phase names live in MOON_NAMES_I18N (in _tides.i18n, shared with the tides
chart's moon labels); this module holds the strings specific to the ``moon``
command plus month names for the full/new moon dates.
"""

from linecast._i18n import LocaleTable, base_language, has_text, lang_of, lookup, plural_category, setting, table_for
from linecast.tides.i18n import MOON_NAMES_I18N, _moon_name  # noqa: F401 — re-export
from linecast.weather.i18n import DAY_NAMES  # re-export for convenience

_MOON_STRINGS = LocaleTable("MOON")


# Abbreviated month names, January..December. CJK and Finnish dates are
# formatted numerically via DATE_MD below, so those entries are unused.
MONTHS_I18N = LocaleTable("MONTHS")

# Date order/format per language: {month} = abbreviated name from
# MONTHS_I18N, {mnum} = month number, {day} = day of month.
_DATE_MD = LocaleTable("MONTH_DAY")
_DATE_MD_DEFAULT = "{day} {month}"


def _ms(key, runtime, **kwargs):
    """Look up a moon-specific localized string. A count of days takes
    the form the language gives that count where the table has one
    (Romanian's "peste 1 zi", "peste 21 de zile")."""
    lang = lang_of(runtime)
    if key == "in_days" and "days" in kwargs:
        # The count arrives written with the language's decimal mark
        count = float(str(kwargs["days"]).replace(",", "."))
        variant = f"in_days_{plural_category(lang, count)}"
        if has_text(_MOON_STRINGS, variant, lang):
            key = variant
    return lookup(_MOON_STRINGS, key, lang, **kwargs)


# Season names for the four events (March equinox, June solstice,
# September equinox, December solstice), by hemisphere.  East Asian
# solar terms (春分, 夏至, …) name the event itself, not the local
# season — Vietnamese Xuân phân and Hạ chí are the same terms — and
# Thai's Sanskrit terms (วสันตวิษุวัต, …) likewise, so those languages
# keep the northern mapping everywhere. Swahili names the months of
# the events, so its labels also stay the same in either hemisphere.
_SEASON_KEYS_NORTH = ("spring_equinox", "summer_solstice",
                      "autumn_equinox", "winter_solstice")
_SEASON_KEYS_SOUTH = ("autumn_equinox", "winter_solstice",
                      "spring_equinox", "summer_solstice")


def _season_label(event, lat, runtime):
    """Localized name for a season event index, seen from latitude *lat*."""
    south = lat is not None and lat < 0
    if south and not setting(lang_of(runtime), "absolute_seasons"):
        return _ms(_SEASON_KEYS_SOUTH[event], runtime)
    return _ms(_SEASON_KEYS_NORTH[event], runtime)


def _fmt_month_day(dt, runtime):
    """Format a month + day date in the runtime language's convention,
    in the civil calendar (astro.calendars.civil): `23 Sep`, or `1 مهر` where
    the dates are Solar Hijri."""
    from linecast.astro.calendars.civil import SOLAR_HIJRI, civil_calendar, solar_hijri_day_month
    lang = lang_of(runtime)
    if civil_calendar(lang) == SOLAR_HIJRI:
        return solar_hijri_day_month(dt, lang)
    return gregorian_month_day(dt, lang)


def gregorian_month_day(dt, lang):
    """`Sep 23`, `23. Sep`, `9月23日`: the Gregorian month and day, whatever
    the civil calendar."""
    fmt = _DATE_MD.get(lang, _DATE_MD.get(base_language(lang), _DATE_MD_DEFAULT))
    months = table_for(MONTHS_I18N, lang)
    return fmt.format(month=months[dt.month - 1], mnum=dt.month, day=dt.day)


def gregorian_date_label(dt, lang):
    """The Gregorian date with its year, for the hovers that set it beside
    a Solar Hijri one: `Sep 23, 2026`, `23 سپتامبر 2026`, `2026年9月23日`."""
    md = gregorian_month_day(dt, lang)
    base = base_language(lang)
    if base in ("ja", "zh", "zh-Hant"):
        return f"{dt.year}年{md}"
    if base == "ko":
        return f"{dt.year}년 {md}"
    if base == "en":
        return f"{md}, {dt.year}"
    return f"{md} {dt.year}"


def _day_abbrev(dt, runtime):
    """Localized three-letter-ish weekday abbreviation."""
    return table_for(DAY_NAMES, lang_of(runtime))[dt.weekday()]


# ---------------------------------------------------------------------------
# The lunisolar calendar's names (see astro/calendars/lunisolar.py for the calendar
# itself). Each calendar reads in its own script for its own language;
# every other UI language gets the customary English renderings, the
# same fallback the string tables use.
# ---------------------------------------------------------------------------

# Solar terms in longitude order, index 0 at the March equinox — the
# indexing current_term() and next_term() use. The terms are common to
# all four calendars; only the writing differs.
SOLAR_TERMS_I18N = LocaleTable("SOLAR_TERMS")

# Festivals dated by the lunar calendar, (month, day) → {lang: name}, per
# calendar: the name in the calendar's own language (Chinese in both its
# scripts) and the customary English one. Japan moved its festivals to
# Gregorian dates in 1873; the two moon-viewing nights are what remains
# on the old calendar. Vietnam's are the public holidays and the days
# every household keeps: the Hùng Kings' day is a holiday by law, and the
# Kitchen Gods' departure a week before Tết opens the new year's rites.
_FESTIVALS = {
    "chinese": {
        (1, 1): {"zh": "春节", "zh-Hant": "春節", "zh-HK": "農曆新年", "en": "Chinese New Year"},
        (1, 15): {"zh": "元宵节", "zh-Hant": "元宵節", "en": "Lantern Festival"},
        (5, 5): {"zh": "端午节", "zh-Hant": "端午節", "en": "Dragon Boat Festival"},
        (7, 7): {"zh": "七夕", "zh-Hant": "七夕", "en": "Qixi"},
        (8, 15): {"zh": "中秋节", "zh-Hant": "中秋節", "en": "Mid-Autumn Festival"},
        (9, 9): {"zh": "重阳节", "zh-Hant": "重陽節", "en": "Double Ninth"},
    },
    "japanese": {
        (8, 15): {"ja": "十五夜", "en": "Tsukimi"},
        (9, 13): {"ja": "十三夜", "en": "Jūsan'ya"},
    },
    "korean": {
        (1, 1): {"ko": "설날", "en": "Seollal"},
        (1, 15): {"ko": "정월대보름", "en": "Daeboreum"},
        (5, 5): {"ko": "단오", "en": "Dano"},
        (8, 15): {"ko": "추석", "en": "Chuseok"},
    },
    "vietnamese": {
        (1, 1): {"vi": "Tết Nguyên Đán", "en": "Tết"},
        (1, 15): {"vi": "Rằm tháng Giêng", "en": "Tết Nguyên Tiêu"},
        (3, 10): {"vi": "Giỗ Tổ Hùng Vương", "en": "Hùng Kings' Day"},
        (5, 5): {"vi": "Tết Đoan Ngọ", "en": "Tết Đoan Ngọ"},
        (7, 15): {"vi": "Lễ Vu Lan", "en": "Vu Lan"},
        (8, 15): {"vi": "Tết Trung Thu", "en": "Mid-Autumn Festival"},
        (12, 23): {"vi": "Ông Táo về trời", "en": "Kitchen Gods' Day"},
    },
}


def festival_table(calendar, lang):
    """(month, day) → name for a calendar's festivals, in *lang* where
    that is the calendar's own language, else the customary English."""
    return {md: names.get(lang) or names.get(base_language(lang), names["en"])
            for md, names in _FESTIVALS[calendar].items()}

# Chinese months and days have names, not numbers: the eleventh and
# twelfth months are 冬月 and 腊月, the first ten days take 初, the
# twenties 廿. The traditional script writes 臘月 and 閏 for a leap month.
_ZH_MONTHS = ["正月", "二月", "三月", "四月", "五月", "六月",
              "七月", "八月", "九月", "十月", "冬月", "腊月"]
_ZH_MONTHS_HANT = [*_ZH_MONTHS[:11], "臘月"]
_ZH_DIGITS = "一二三四五六七八九十"


def zh_month_label(month, leap, lang):
    """The Chinese month's name, 正月, 闰六月, 臘月, in either script."""
    if base_language(lang) == "zh-Hant":
        return ("閏" if leap else "") + _ZH_MONTHS_HANT[month - 1]
    return ("闰" if leap else "") + _ZH_MONTHS[month - 1]


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


# Vietnamese months are numbered but for the first and the last, tháng
# Giêng and tháng Chạp; a leap month takes nhuận after its number. The
# first ten days are mùng, the fifteenth is rằm, the full-moon day.
_VI_MONTHS = {1: "Giêng", 12: "Chạp"}


def vi_month_label(month, leap, short=False):
    """tháng Giêng, tháng 8, tháng 6 nhuận, tháng Chạp — or, for the
    grid's cells, the printed calendars' thg 8."""
    name = _VI_MONTHS.get(month, str(month))
    word = "thg" if short and name.isdigit() else "tháng"
    label = name if short and not name.isdigit() else f"{word} {name}"
    return f"{label} nhuận" if leap else label


def lunar_date_label(month, day, leap, lang):
    """The lunar date as its own calendar writes it, English otherwise."""
    if lang == "vi":
        if day <= 10:
            day_name = f"mùng {day}"
        elif day == 15:
            day_name = "rằm"
        else:
            day_name = f"ngày {day}"
        return f"{day_name} {vi_month_label(month, leap)} âm lịch"
    if lang == "zh":
        return f"农历{zh_month_label(month, leap, lang)}{_zh_day_name(day)}"
    if base_language(lang) == "zh-Hant":
        return f"農曆{zh_month_label(month, leap, lang)}{_zh_day_name(day)}"
    if lang == "ja":
        leap_mark = "閏" if leap else ""
        return f"旧暦{leap_mark}{month}月{day}日"
    if lang == "ko":
        leap_mark = "윤" if leap else ""
        return f"음력 {leap_mark}{month}월 {day}일"
    leap_mark = "leap " if leap else ""
    return f"{leap_mark}month {month} day {day}"


def term_label(index, lang):
    """The name of solar term *index* (0 = March equinox)."""
    return table_for(SOLAR_TERMS_I18N, lang)[index]


# Japan names the nights, not just the phases: after the full moon the
# names narrate the lengthening wait for moonrise — stand and wait,
# sit and wait, lie down, wait past midnight. The named nights are the
# traditional ones; the days between take the plain counted form.
_JA_NIGHT_NAMES = (
    "新月", "二日月", "三日月", "四日月", "五日月",
    "六日月", "七日月", "八日月", "九日月", "十日夜",
    "十一日月", "十二日月", "十三夜", "小望月", "十五夜",
    "十六夜", "立待月", "居待月", "寝待月", "更待月",
    "二十一日月", "二十二日月", "二十三夜", "二十四日月", "二十五日月",
    "二十六夜", "二十七日月", "二十八日月", "二十九日月", "三十日月",
)


def ja_night_name(day):
    """The Japanese name of the old calendar's night *day* (1-30)."""
    return _JA_NIGHT_NAMES[day - 1]


# ---------------------------------------------------------------------------
# The Thai calendar's names (see astro/calendars/thai_lunar.py for the calendar
# itself). Thai lunar dates are traditionally printed in Thai numerals
# — ขึ้น ๘ ค่ำ เดือน ๓ — so the native labels keep them; the rest of
# the UI stays with Arabic digits, as modern Thai print does.
# ---------------------------------------------------------------------------

_TH_DIGITS = "๐๑๒๓๔๕๖๗๘๙"


def _th_num(n):
    return "".join(_TH_DIGITS[ord(c) - 48] for c in str(n))


def thai_month_label(month, doubled, lang):
    """เดือนอ้าย, เดือนยี่, เดือน ๓ … เดือน ๘๘ — the months as the
    printed calendars name them: the first two by their archaic names,
    the doubled eighth by its doubled numeral."""
    if lang == "th":
        if doubled:
            return "เดือน ๘๘"
        if month == 1:
            return "เดือนอ้าย"
        if month == 2:
            return "เดือนยี่"
        return f"เดือน {_th_num(month)}"
    return f"month {'8/8' if doubled else month}"


def thai_lunar_label(month, day, doubled, lang):
    """The Thai lunar date as the printed calendars write it."""
    if lang == "th":
        phase, d = ("ขึ้น", day) if day <= 15 else ("แรม", day - 15)
        return f"{phase} {_th_num(d)} ค่ำ {thai_month_label(month, doubled, lang)}"
    phase, d = ("waxing", day) if day <= 15 else ("waning", day - 15)
    return f"{thai_month_label(month, doubled, lang)} · {phase} {d}"


# The twelve-animal cycle, indexed as year_animal_index counts it
# (0 = ชวด, the rat).
_TH_ANIMALS = ("ชวด", "ฉลู", "ขาล", "เถาะ", "มะโรง", "มะเส็ง",
               "มะเมีย", "มะแม", "วอก", "ระกา", "จอ", "กุน")
_TH_ANIMALS_EN = ("Rat", "Ox", "Tiger", "Rabbit", "Dragon", "Snake",
                  "Horse", "Goat", "Monkey", "Rooster", "Dog", "Pig")


def thai_year_label(animal_index, lang):
    """ปีมะเมีย — the lunar year named by its animal."""
    if lang == "th":
        return "ปี" + _TH_ANIMALS[animal_index]
    return f"Year of the {_TH_ANIMALS_EN[animal_index]}"


def wan_phra_label(today, lang):
    """The Buddhist holy day, named — today's, or the coming one's."""
    if lang == "th":
        return "วันนี้วันพระ" if today else "วันพระ"
    return "Wan Phra today" if today else "Wan Phra"


# Festival names by the keys thai_lunar's next_thai_festival returns,
# (native, customary English).
_TH_FESTIVALS = {
    "makha": ("มาฆบูชา", "Makha Bucha"),
    "visakha": ("วิสาขบูชา", "Visakha Bucha"),
    "asalha": ("อาสาฬหบูชา", "Asalha Bucha"),
    "khao_phansa": ("เข้าพรรษา", "Khao Phansa"),
    "ok_phansa": ("ออกพรรษา", "Ok Phansa"),
    "loy_krathong": ("ลอยกระทง", "Loy Krathong"),
    "songkran": ("สงกรานต์", "Songkran"),
}


def thai_festival_name(key, lang):
    native, english = _TH_FESTIVALS[key]
    return native if lang == "th" else english


# Hawaiʻi names the nights too — the pō mahina, as the WPRFMC's annual
# Kaulana Mahina prints them (after Clarice Taylor's Hawaiian Almanac,
# Oʻahu). Proper nouns with no customary English renderings, so every
# UI language reads them in Hawaiian. Three ten-night anahulu: the four
# waxing ʻOle nights, then three waning ones, keep the count at thirty.
_PO_MAHINA = (
    "Hilo", "Hoaka", "Kūkahi", "Kūlua", "Kūkolu",
    "Kūpau", "ʻOlekūkahi", "ʻOlekūlua", "ʻOlekūkolu", "ʻOlepau",
    "Huna", "Mōhalu", "Hua", "Akua", "Hoku",
    "Māhealani", "Kulu", "Lāʻaukūkahi", "Lāʻaukūlua", "Lāʻaupau",
    "ʻOlekūkahi", "ʻOlekūlua", "ʻOlepau", "Kāloakūkahi", "Kāloakūlua",
    "Kāloapau", "Kāne", "Lono", "Mauli", "Muku",
)

_ANAHULU = ("hoʻonui", "poepoe", "hōʻemi")


# American Samoa names its nights too — the masina, as the Council's
# annual American Samoa lunar calendar prints them, the same thirty in
# every edition since 2021. Two nights carry a second name on the
# page, the first and the full moon, written here as printed.
_MASINA = (
    "Masina Fou/Faatoavaaia", "Masina Tofilofilo", "Masina Tolu",
    "Masina Faalao", "Masina Salefuga", "Masina Tulalupe",
    "Masina Motuega", "Masina Aufasa", "Masina Matuatua",
    "Masina Loloatai",
    "Masina Malupeaua", "Masina Mātofitofi", "Masina Aiaina",
    "Masina Punifaga", "Masina Atoa/Atoa Liʻo le Masina",
    "Masina Leʻaleʻa", "Masina Feetetele", "Masina Ataatatai",
    "Masina Fagaeleele", "Masina Sulutele",
    "Masina Nauna", "Masina Usunoa", "Masina Motusaga",
    "Masina Tatelega", "Masina Faasagafulu", "Masina Tāfaleu",
    "Masina Fataleu", "Masina Mitiloa", "Masina Fanoloa", "Masina Maunā",
)

# The CHamoru nights — the pulan — as the Council's Guam calendar
# prints them, and as its CNMI calendar has printed them since 2025.
# Pulan Gualåffon, the sixteenth, is the full moon.
_PULAN = (
    "Sinahen Håcha", "Sinahen Hugua", "Sinahen Tulu", "Sumahi I Pilan",
    "Sinahen Lima", "Sinahen Gunum", "Sinahen Fiti", "Kuåtto",
    "Kuåtto Kosiente", "E’egeng",
    "Dengnga", "Luma’annok", "Gumofatanon", "Pånglao Tunas/Echong",
    "Atahguen Atdao", "Pulan Gualåffon", "Mumalilingu Empe’",
    "Ketai’ Empe’", "Sumenhomhom", "Kuåtto Mangguånte",
    "Humunaohuyong Pulan", "Humomhom", "Tunas Talo’", "Hihot Talo’",
    "Halomsahguan", "Sinahen Ulu", "Finaloffan Puti’on", "Dalalai Pulan",
    "Kumaninifes", "Sinahi",
)

# The Refaluwasch (Carolinian) names the CNMI calendar sets beside the
# CHamoru ones, keyed by position in the thirty: eleven nights, the
# same eleven in the 2025 and 2026 editions. The 2022–2024 editions
# printed a Refaluwasch name for every night; the Council trimmed the
# list, and these are the names it kept.
_REFALUWASCH = {
    1: "Sighauru", 2: "Eling", 3: "Meseling", 9: "Eschúw",
    14: "Emmasch", 15: "Úúr", 16: "Letiw", 17: "Ghiney", 18: "Ara",
    21: "Arosan Efnágh", 27: "Arofú",
}

_PACIFIC_NIGHTS = {
    "hawaiian": _PO_MAHINA, "samoan": _MASINA,
    "chamorro": _PULAN, "refaluwasch": _PULAN,
}


def _night_index(night, nights):
    """Where *night* of a month of *nights* (29 or 30) sits in the thirty.

    A 29-night month drops the twenty-ninth name, never the last — the
    convention of every published 29-night month in all three
    calendars: Mauli goes and Muku closes, Masina Fanoloa goes and
    Masina Maunā closes, Kumaninifes goes and Sinahi closes.
    """
    if night >= nights:
        return 29                            # the last name closes the month
    if night == nights - 1 and nights >= 30:
        return 28                            # the twenty-ninth keeps its place
    return min(night, 28) - 1


def pacific_night_name(cal, night, nights):
    """The name of *night* in a month of *nights*, in *cal*'s tradition."""
    return _PACIFIC_NIGHTS[cal][_night_index(night, nights)]


def po_mahina_name(night, nights):
    """The Hawaiian name of *night* in a month of *nights* (29 or 30)."""
    return pacific_night_name("hawaiian", night, nights)


def refaluwasch_name(night, nights):
    """The Refaluwasch name of *night*, or None on a night without one."""
    return _REFALUWASCH.get(_night_index(night, nights) + 1)


def pacific_night_label(cal, night, nights):
    """The headline for a night: its name, with the Refaluwasch beside
    the CHamoru where the CNMI calendar prints one."""
    name = pacific_night_name(cal, night, nights)
    if cal == "refaluwasch":
        other = refaluwasch_name(night, nights)
        if other:
            return f"{name} · {other}"
    return name


def anahulu_name(night):
    """The anahulu (ten-night span) that *night* falls in."""
    return _ANAHULU[min((night - 1) // 10, 2)]


# ---------------------------------------------------------------------------
# The Islamic calendar's names (see astro/calendars/hijri.py for the calendar itself).
# Arabic is not a UI language, so the months are transliterated for
# most readers; Indonesian gets the spellings its dictionary
# standardizes, and Persian the names Iranian calendars print, with the
# era as ق (qamari, lunar).
# ---------------------------------------------------------------------------

_HIJRI_MONTHS = LocaleTable("HIJRI_MONTHS")

_HIJRI_ERA = LocaleTable("HIJRI_ERA")

# Observance names by the keys hijri's next_observance returns.
_HIJRI_OBSERVANCES = {
    "new_year": {"en": "Islamic New Year", "id": "Tahun Baru Islam", "fa": "آغاز سال قمری"},
    "ashura": {"en": "Ashura", "id": "Asyura", "fa": "عاشورا"},
    "mawlid": {"en": "Mawlid", "id": "Maulid Nabi", "fa": "میلاد پیامبر"},
    "ramadan": {"en": "Ramadan begins", "id": "Awal Ramadan", "fa": "آغاز ماه رمضان"},
    "qadr": {"en": "Laylat al-Qadr", "id": "Lailatulqadar", "fa": "شب قدر"},
    "eid_fitr": {"en": "Eid al-Fitr", "id": "Idulfitri", "fa": "عید فطر"},
    "arafah": {"en": "Day of Arafah", "id": "Hari Arafah", "fa": "روز عرفه"},
    "eid_adha": {"en": "Eid al-Adha", "id": "Iduladha", "fa": "عید قربان"},
}


def hijri_lang(lang):
    """The language the Islamic calendar's names are written in."""
    base = base_language(lang)
    return base if base in _HIJRI_MONTHS else "en"


def hijri_era(lang):
    """The era the Hijri year is written with: AH, H, ق."""
    return _HIJRI_ERA[hijri_lang(lang)]


def hijri_month_name(month, lang):
    return _HIJRI_MONTHS[hijri_lang(lang)][month - 1]


def hijri_date_label(year, month, day, lang):
    """23 Ramadan 1447 AH — the Hijri date as it is customarily written."""
    return f"{day} {hijri_month_name(month, lang)} {year} {hijri_era(lang)}"


def hijri_observance_name(key, lang):
    return _HIJRI_OBSERVANCES[key][hijri_lang(lang)]


# Iran fixes the lunar months by its own sighting of the crescent, so its
# Hijri dates can sit a day from Umm al-Qura's. Said once, in the grid's
# hover, where the reader is looking at a single day.
_HIJRI_SIGHTING_NOTE = LocaleTable("HIJRI_SIGHTING_NOTE")


def hijri_sighting_note(lang):
    """The caveat the grid's hover sets under a Hijri date, or None."""
    return _HIJRI_SIGHTING_NOTE.get(base_language(lang))


# ---------------------------------------------------------------------------
# The Solar Hijri observances (see astro/calendars/solar_hijri.py), by the keys
# its next_observance returns: Persian names for Persian, the customary
# English transliterations for everyone else. Nowruz is also counted
# down to the moment of the equinox, تحویل سال, the turn of the year.
# ---------------------------------------------------------------------------

_SOLAR_HIJRI_OBSERVANCES = {
    "nowruz": {"fa": "نوروز", "en": "Nowruz"},
    "sizdah_bedar": {"fa": "سیزده‌بدر", "en": "Sizdah Bedar"},
    "tirgan": {"fa": "جشن تیرگان", "en": "Tirgan"},
    "mehregan": {"fa": "جشن مهرگان", "en": "Mehregan"},
    "yalda": {"fa": "شب یلدا", "en": "Yalda Night"},
    "sadeh": {"fa": "جشن سده", "en": "Sadeh"},
    "chaharshanbe_suri": {"fa": "چهارشنبه‌سوری", "en": "Chaharshanbe Suri"},
}

_YEAR_TURN = LocaleTable("YEAR_TURN")


def _solar_hijri_lang(lang):
    return "fa" if base_language(lang) == "fa" else "en"


def solar_hijri_observance_name(key, lang):
    return _SOLAR_HIJRI_OBSERVANCES[key][_solar_hijri_lang(lang)]


def year_turn_label(year, lang):
    """`تحویل سال 1406`: the moment Nowruz is counted down to."""
    return _YEAR_TURN[_solar_hijri_lang(lang)].format(year=year)


# ---------------------------------------------------------------------------
# The Hebrew calendar's names (see astro/calendars/hebrew.py for the calendar itself).
# Hebrew is not a UI language and terminals lay its script out
# unreliably, so the months and holidays are transliterated, one
# spelling for every reader: Tishrei, Cheshvan, Pesach.
# ---------------------------------------------------------------------------

_HEBREW_MONTHS = ("Nisan", "Iyar", "Sivan", "Tammuz", "Av", "Elul",
                  "Tishrei", "Cheshvan", "Kislev", "Tevet", "Shevat",
                  "Adar", "Adar II")
_HEBREW_MONTHS_HE = ("ניסן", "אייר", "סיון", "תמוז", "אב", "אלול",
                     "תשרי", "חשון", "כסלו", "טבת", "שבט",
                     "אדר", "אדר ב׳")

# The letter numerals: units, tens, and hundreds each have a letter,
# read by adding them up; 15 and 16 are written ט״ו and ט״ז rather
# than with the letters of the divine name.
_GEMATRIA = ((400, "ת"), (300, "ש"), (200, "ר"), (100, "ק"), (90, "צ"),
             (80, "פ"), (70, "ע"), (60, "ס"), (50, "נ"), (40, "מ"),
             (30, "ל"), (20, "כ"), (10, "י"), (9, "ט"), (8, "ח"),
             (7, "ז"), (6, "ו"), (5, "ה"), (4, "ד"), (3, "ג"),
             (2, "ב"), (1, "א"))
_GERESH, _GERSHAYIM = "׳", "״"

# Holiday names by the keys hebrew's next_holiday returns.
_HEBREW_HOLIDAYS = {
    "rosh_hashanah": "Rosh Hashanah",
    "yom_kippur": "Yom Kippur",
    "sukkot": "Sukkot",
    "shemini_atzeret": "Shemini Atzeret",
    "simchat_torah": "Simchat Torah",
    # One day in Israel, so a printed calendar names it with both.
    "shemini_atzeret_simchat_torah": "Shemini Atzeret / Simchat Torah",
    "hanukkah": "Hanukkah",
    "tu_bishvat": "Tu BiShvat",
    "purim": "Purim",
    "pesach": "Pesach",
    "shavuot": "Shavuot",
    "tisha_bav": "Tisha B'Av",
}


def hebrew_month_name(year, month):
    """The month's name; the twelfth is Adar I in a year with two Adars."""
    from linecast.astro.calendars.hebrew import is_leap_year
    if month == 12 and is_leap_year(year):
        return "Adar I"
    return _HEBREW_MONTHS[month - 1]


def hebrew_date_label(year, month, day):
    """23 Tishrei 5787 — the Hebrew date as it is customarily written."""
    return f"{day} {hebrew_month_name(year, month)} {year}"


def hebrew_holiday_name(key):
    return _HEBREW_HOLIDAYS[key]


def hebrew_numeral(n):
    """*n* in Hebrew letters: כ׳ for 20, כ״ג for 23, ט״ו for 15."""
    letters = ""
    while n:
        for value, letter in _GEMATRIA:
            if value <= n:
                letters += letter
                n -= value
                break
    letters = letters.replace("יה", "טו").replace("יו", "טז")
    if len(letters) == 1:
        return letters + _GERESH
    return letters[:-1] + _GERSHAYIM + letters[-1]


def hebrew_year_numeral(year):
    """The year as it is written, without its thousands: תשפ״ו for 5786.

    A round thousand has nothing left to write, so the thousands
    stand alone: ו׳ for 6000.
    """
    rest = year % 1000
    return hebrew_numeral(rest if rest else year // 1000)


def hebrew_date_hebrew(year, month, day):
    """כ״ג תשרי תשפ״ז — the date in Hebrew letters, for --json."""
    from linecast.astro.calendars.hebrew import is_leap_year
    name = _HEBREW_MONTHS_HE[month - 1]
    if month == 12 and is_leap_year(year):
        name = "אדר א׳"
    return f"{hebrew_numeral(day)} {name} {hebrew_year_numeral(year)}"


def rosh_chodesh_label(year, month):
    return f"Rosh Chodesh {hebrew_month_name(year, month)}"
