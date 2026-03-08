"""Tides localization strings."""

from linecast._weather_i18n import FULL_DAY_NAMES  # re-export for convenience

_TIDES_STRINGS = {
    "en": {
        "space_to_now": "space to return to now",
    },
    "fr": {
        "space_to_now": "espace pour revenir",
    },
    "es": {
        "space_to_now": "espacio para volver al presente",
    },
    "de": {
        "space_to_now": "Leertaste f\u00fcr jetzt",
    },
    "it": {
        "space_to_now": "spazio per tornare a ora",
    },
    "pt": {
        "space_to_now": "espa\u00e7o para voltar ao presente",
    },
    "nl": {
        "space_to_now": "spatie om terug te keren",
    },
    "pl": {
        "space_to_now": "spacja, aby wr\u00f3ci\u0107",
    },
    "no": {
        "space_to_now": "mellomrom for \u00e5 g\u00e5 tilbake",
    },
    "sv": {
        "space_to_now": "mellanslag f\u00f6r att \u00e5terg\u00e5",
    },
    "da": {
        "space_to_now": "mellemrum for at vende tilbage",
    },
    "is": {
        "space_to_now": "bil til a\u00f0 fara til baka",
    },
    "fi": {
        "space_to_now": "v\u00e4lily\u00f6nti palataksesi",
    },
    "ja": {
        "space_to_now": "\u30b9\u30da\u30fc\u30b9\u3067\u73fe\u5728\u306b\u623b\u308b",
    },
    "ko": {
        "space_to_now": "\uc2a4\ud398\uc774\uc2a4\ub85c \ud604\uc7ac\ub85c \ub3cc\uc544\uac00\uae30",
    },
    "zh": {
        "space_to_now": "\u6309\u7a7a\u683c\u8fd4\u56de\u5f53\u524d",
    },
}


def _ts(key, runtime, **kwargs):
    """Look up a tides-specific localized string."""
    lang = getattr(runtime, "lang", "en") if runtime else "en"
    table = _TIDES_STRINGS.get(lang, _TIDES_STRINGS["en"])
    text = table.get(key, _TIDES_STRINGS["en"].get(key, key))
    return text.format(**kwargs) if kwargs else text
