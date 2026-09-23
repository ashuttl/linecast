"""The names the traditional hours go by, in each language.

The zmanim are transliterated in every language, as the Hebrew months
are, with the Hebrew itself kept for `--json`. Latin is Latin
everywhere. The Edo hours keep their kanji in Japanese and take the
bell count and the animal's hour elsewhere. The prayer names are
transliterated, with Indonesian's own spellings, as the Hijri months
have theirs, Turkish's own names, İmsak to Yatsı, as the Diyanet
prints them, and Persian's, اذان صبح to اذان مغرب, as Iranian
timetables print them; sunrise reads in each language's own word. Swahili time
reads in Swahili everywhere, as Latin does.

Each mark has a short name for the line under the chart and a full
name for `--json` and the help. Names that are the same in every
language live in the English table and fall through `lookup`.
"""

from linecast._i18n import lang_of, lookup

# key → (short, full, hebrew)
_ZMANIM = {
    "alot": ("alot", "alot hashachar", "עלות השחר"),
    "misheyakir": ("misheyakir", "misheyakir", "משיכיר"),
    "sunrise": ("sunrise", "sunrise", "הנץ החמה"),
    "shema": ("Shema", "sof zman Shema", "סוף זמן קריאת שמע"),
    "tefillah": ("Tefillah", "sof zman Tefillah", "סוף זמן תפילה"),
    "chatzot": ("chatzot", "chatzot", "חצות"),
    "mincha_gedola": ("mincha gedola", "mincha gedola", "מנחה גדולה"),
    "mincha_ketana": ("mincha ketana", "mincha ketana", "מנחה קטנה"),
    "plag": ("plag", "plag hamincha", "פלג המנחה"),
    "candles": ("candles", "candle lighting", "הדלקת נרות"),
    "sunset": ("sunset", "sunset", "שקיעה"),
    "tzeit": ("tzeit", "tzeit hakochavim", "צאת הכוכבים"),
    "chatzot_halayla": ("chatzot halayla", "chatzot halayla", "חצות הלילה"),
}

# The Roman marks: key → (short, full). Latin in every language.
_ROMAN = {
    "hora_tertia": ("tertia", "hora tertia"),
    "hora_sexta": ("sexta", "hora sexta"),
    "hora_nona": ("nona", "hora nona"),
    "vigilia_secunda": ("vigilia II", "vigilia secunda"),
    "vigilia_tertia": ("vigilia III", "vigilia tertia"),
    "vigilia_quarta": ("vigilia IV", "vigilia quarta"),
}

# The Edo koku: key → (Japanese, English short, English full). The
# Japanese name stands in every language but the ones with their own
# column; the animal's hour is the branch's, as the wall calendars
# still print the 子の刻.
_EDO = {
    "ake_mutsu": ("明六つ", "dawn six", "dawn six, the hour of the Rabbit"),
    "asa_itsutsu": ("朝五つ", "morning five", "morning five, the hour of the Dragon"),
    "asa_yotsu": ("朝四つ", "morning four", "morning four, the hour of the Snake"),
    "hiru_kokonotsu": ("昼九つ", "noon nine", "noon nine, the hour of the Horse"),
    "hiru_yatsu": ("昼八つ", "day eight", "day eight, the hour of the Goat"),
    "yuu_nanatsu": ("夕七つ", "evening seven", "evening seven, the hour of the Monkey"),
    "kure_mutsu": ("暮六つ", "dusk six", "dusk six, the hour of the Rooster"),
    "yoru_itsutsu": ("夜五つ", "night five", "night five, the hour of the Dog"),
    "yoru_yotsu": ("夜四つ", "night four", "night four, the hour of the Pig"),
    "yoru_kokonotsu": ("夜九つ", "midnight nine", "midnight nine, the hour of the Rat"),
    "yoru_yatsu": ("夜八つ", "night eight", "night eight, the hour of the Ox"),
    "akatsuki_nanatsu": ("暁七つ", "daybreak seven", "daybreak seven, the hour of the Tiger"),
}

# The prayers: key → (English, Indonesian, Turkish, Persian, Arabic).
# The English transliterations stand in every language but Indonesian,
# which has its own spellings, as it has for the Hijri months, Turkish,
# whose cards read İmsak, Güneş, Öğle, İkindi, Akşam, Yatsı, and
# Persian, whose timetables (اوقات شرعی) name the calls to prayer:
# اذان صبح, اذان ظهر, اذان مغرب.
# The Diyanet's İmsak is the Fajr time, so Turkish reads Fajr as İmsak
# unless the table lists a separate Imsak before it, when Fajr is
# Sabah, the morning prayer. Sunrise reads in each language's own word
# but where the card has one.
_PRAYERS = {
    "imsak": ("Imsak", "Imsak", "İmsak", "امساک", "الإمساك"),
    "fajr": ("Fajr", "Subuh", "İmsak", "اذان صبح", "الفجر"),
    "sunrise": ("Sunrise", "Terbit", "Güneş", "طلوع آفتاب", "الشروق"),
    "dhuhr": ("Dhuhr", "Zuhur", "Öğle", "اذان ظهر", "الظهر"),
    "asr": ("Asr", "Asar", "İkindi", "عصر", "العصر"),
    "maghrib": ("Maghrib", "Magrib", "Akşam", "اذان مغرب", "المغرب"),
    "isha": ("Isha", "Isya", "Yatsı", "عشا", "العشاء"),
}
_PRAYER_COLUMN = {"id": 1, "tr": 2, "fa": 3}

# The strings the hours line and the corner need beyond the names:
# "night" for the night hours, "in {dur}" for the countdown, and the
# unit the corner measures, "1h = 62m", where a system has its own,
# and "fast" for the corner's count of a day of fasting.
_HOURS_STRINGS = {
    "en": {"night": "night", "in_time": "in {dur}", "koku": "1 koku", "fast": "fast"},
    "fr": {"night": "nuit", "in_time": "dans {dur}", "koku": "1 koku", "fast": "jeûne"},
    "es": {"night": "noche", "in_time": "en {dur}", "koku": "1 koku", "fast": "ayuno"},
    "de": {"night": "Nacht", "in_time": "in {dur}", "koku": "1 koku", "fast": "Fasten"},
    "it": {"night": "notte", "in_time": "tra {dur}", "koku": "1 koku", "fast": "digiuno"},
    "pt": {"night": "noite", "in_time": "em {dur}", "koku": "1 koku", "fast": "jejum"},
    "nl": {"night": "nacht", "in_time": "over {dur}", "koku": "1 koku", "fast": "vasten"},
    "pl": {"night": "noc", "in_time": "za {dur}", "koku": "1 koku", "fast": "post"},
    "no": {"night": "natt", "in_time": "om {dur}", "koku": "1 koku", "fast": "faste"},
    "sv": {"night": "natt", "in_time": "om {dur}", "koku": "1 koku", "fast": "fasta"},
    "is": {"night": "nótt", "in_time": "eftir {dur}", "koku": "1 koku", "fast": "fasta"},
    "da": {"night": "nat", "in_time": "om {dur}", "koku": "1 koku", "fast": "faste"},
    "fi": {"night": "yö", "in_time": "{dur} kuluttua", "koku": "1 koku", "fast": "paasto"},
    "ja": {"night": "夜", "in_time": "{dur}後", "koku": "1刻", "fast": "断食"},
    "ko": {"night": "밤", "in_time": "{dur} 후", "koku": "1코쿠", "fast": "금식"},
    "zh": {"night": "夜", "in_time": "{dur}后", "koku": "1刻", "fast": "斋戒"},
    "zh-Hant": {"night": "夜", "in_time": "{dur}後", "koku": "1刻", "fast": "齋戒"},
    "th": {"night": "กลางคืน", "in_time": "อีก {dur}", "koku": "1 โคกุ", "fast": "ถือศีลอด"},
    "id": {"night": "malam", "in_time": "dalam {dur}", "koku": "1 koku", "fast": "puasa"},
    "uk": {"night": "ніч", "in_time": "через {dur}", "koku": "1 коку", "fast": "піст"},
    "vi": {"night": "đêm", "in_time": "còn {dur}", "koku": "1 koku", "fast": "nhịn chay"},
    "eo": {"night": "nokto", "in_time": "post {dur}", "koku": "1 koku", "fast": "fasto"},
    "tr": {"night": "gece", "in_time": "{dur} sonra", "koku": "1 koku", "fast": "oruç"},
    "fa": {"night": "شب", "in_time": "{dur} دیگر", "koku": "۱ کوکو", "fast": "روزه"},
    "ru": {"night": "ночь", "in_time": "через {dur}", "koku": "1 коку", "fast": "пост"},
    "ro": {"night": "noapte", "in_time": "peste {dur}", "koku": "1 koku", "fast": "post"},
    "cs": {"night": "noc", "in_time": "za {dur}", "koku": "1 koku", "fast": "půst"},
    "sw": {
        "night": "usiku",
        "in_time": "baada ya {dur}",
        "koku": "koku 1",
        "fast": "mfungo",
    },
    "el": {
        'night': 'νύχτα',
        'in_time': 'σε {dur}',
        'koku': '1 koku',
        'fast': 'νηστεία',
    },
}

# The sunrise and sunset marks read in the language's own words, since
# the line above the marks names them too; the rest are names.
_SUN_KEYS = {"sunrise": "sunrise", "sunset": "sunset"}


def hs(key, runtime, **kwargs):
    """A string of the hours line's own."""
    return lookup(_HOURS_STRINGS, key, lang_of(runtime), **kwargs)


def mark_name(system, key, runtime, short=False, hours=None):
    """The name of a mark in the display language. *hours* is the
    table the mark is from, where the name depends on its company."""
    lang = lang_of(runtime)
    if key in _SUN_KEYS and (system != "islamic" or lang not in _PRAYER_COLUMN):
        from linecast.sunshine.i18n import sky_event
        return sky_event(_SUN_KEYS[key], runtime)
    if system == "halachic":
        short_name, full, _hebrew = _ZMANIM[key]
        return short_name if short else full
    if system == "roman":
        short_name, full = _ROMAN[key]
        return short_name if short else full
    if system == "japanese":
        japanese, short_name, full = _EDO[key]
        if lang_of(runtime) == "ja":
            return japanese
        return short_name if short else full
    if system == "islamic":
        names = _PRAYERS[key]
        if (lang == "tr" and key == "fajr" and hours is not None
                and any(m.key == "imsak" for m in hours.marks)):
            return "Sabah"
        return names[_PRAYER_COLUMN.get(lang, 0)]
    return key


def mark_native(system, key):
    """The name in the tradition's own script, for `--json`: the Hebrew
    of a zman. None where the display name already is it."""
    if system == "halachic":
        return _ZMANIM[key][2]
    if system == "japanese":
        return _EDO[key][0]
    if system == "islamic":
        return _PRAYERS[key][4]
    return None


def unit_name(system, runtime, night=False):
    """What the corner calls one of the system's hours: '1h', '1刻', or
    at Rome by night '1 vigilia'."""
    if system == "japanese":
        return hs("koku", runtime)
    if system == "roman" and night:
        return "1 vigilia"
    return "1h"


def reading_name(system, r, runtime):
    """The reading of a moment in the system's own terms: '4:20' of the
    halachic hours, 'night 4:20' after sunset; 'hora quarta'; '昼四つ半'."""
    if system == "roman":
        from linecast._hours.roman import hour_name
        return hour_name(r, runtime)
    if system == "japanese":
        from linecast._hours.wadokei import koku_name
        return koku_name(r, runtime)
    if system == "swahili":
        from linecast._hours.swahili import moment, saa
        return saa(moment(r))
    clock = f"{r.index}:{int(r.fraction * 60):02d}"
    return f"{hs('night', runtime)} {clock}" if r.night else clock


def variant_name(system, variant):
    """What the table's opinion or method is called."""
    if system == "halachic":
        from linecast._hours.zmanim import OPINION_NAMES
        return OPINION_NAMES.get(variant)
    if system == "islamic" and variant:
        from linecast._hours.prayer_times import METHOD_SHORT
        method, _hyphen, school = variant.partition("-")
        name = METHOD_SHORT.get(method, method)
        return f"{name} · {school.capitalize()}" if school else name
    return variant
