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
    },
    "fr": {
        "today": "aujourd'hui",
        "in_day": "dans {n} jour",
        "in_days": "dans {n} jours",
        "day_ago": "il y a {n} jour",
        "days_ago": "il y a {n} jours",
    },
    "es": {
        "today": "hoy",
        "in_day": "en {n} día",
        "in_days": "en {n} días",
        "day_ago": "hace {n} día",
        "days_ago": "hace {n} días",
    },
    "de": {
        "today": "heute",
        "in_day": "in {n} Tag",
        "in_days": "in {n} Tagen",
        "day_ago": "vor {n} Tag",
        "days_ago": "vor {n} Tagen",
    },
    "it": {
        "today": "oggi",
        "in_day": "tra {n} giorno",
        "in_days": "tra {n} giorni",
        "day_ago": "{n} giorno fa",
        "days_ago": "{n} giorni fa",
    },
    "pt": {
        "today": "hoje",
        "in_day": "em {n} dia",
        "in_days": "em {n} dias",
        "day_ago": "há {n} dia",
        "days_ago": "há {n} dias",
    },
    "nl": {
        "today": "vandaag",
        "in_day": "over {n} dag",
        "in_days": "over {n} dagen",
        "day_ago": "{n} dag geleden",
        "days_ago": "{n} dagen geleden",
    },
    "pl": {
        "today": "dziś",
        "in_day": "za {n} dzień",
        "in_days": "za {n} dni",
        "day_ago": "{n} dzień temu",
        "days_ago": "{n} dni temu",
    },
    "no": {
        "today": "i dag",
        "in_day": "om {n} dag",
        "in_days": "om {n} dager",
        "day_ago": "{n} dag siden",
        "days_ago": "{n} dager siden",
    },
    "sv": {
        "today": "i dag",
        "in_day": "om {n} dag",
        "in_days": "om {n} dagar",
        "day_ago": "{n} dag sedan",
        "days_ago": "{n} dagar sedan",
    },
    "da": {
        "today": "i dag",
        "in_day": "om {n} dag",
        "in_days": "om {n} dage",
        "day_ago": "{n} dag siden",
        "days_ago": "{n} dage siden",
    },
    "is": {
        "today": "í dag",
        "in_day": "eftir {n} dag",
        "in_days": "eftir {n} daga",
        "day_ago": "fyrir {n} degi",
        "days_ago": "fyrir {n} dögum",
    },
    "fi": {
        "today": "tänään",
        "in_day": "{n} päivän kuluttua",
        "in_days": "{n} päivän kuluttua",
        "day_ago": "{n} päivä sitten",
        "days_ago": "{n} päivää sitten",
    },
    "ja": {
        "today": "今日",
        "in_day": "{n}日後",
        "in_days": "{n}日後",
        "day_ago": "{n}日前",
        "days_ago": "{n}日前",
    },
    "ko": {
        "today": "오늘",
        "in_day": "{n}일 후",
        "in_days": "{n}일 후",
        "day_ago": "{n}일 전",
        "days_ago": "{n}일 전",
    },
    "zh": {
        "today": "今天",
        "in_day": "{n}天后",
        "in_days": "{n}天后",
        "day_ago": "{n}天前",
        "days_ago": "{n}天前",
    },
    "id": {
        "today": "hari ini",
        "in_day": "{n} hari lagi",
        "in_days": "{n} hari lagi",
        "day_ago": "{n} hari lalu",
        "days_ago": "{n} hari lalu",
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
