"""Tides localization strings."""

from linecast._weather_i18n import FULL_DAY_NAMES  # re-export for convenience

_TIDES_STRINGS = {
    "en": {
        "space_to_now": "space to return to now",
        "waves": "Waves",
        "swell": "Swell",
    },
    "fr": {
        "space_to_now": "espace pour revenir",
        "waves": "Vagues",
        "swell": "Houle",
    },
    "es": {
        "space_to_now": "espacio para volver al presente",
        "waves": "Olas",
        "swell": "Oleaje",
    },
    "de": {
        "space_to_now": "Leertaste f\u00fcr jetzt",
        "waves": "Wellen",
        "swell": "D\u00fcnung",
    },
    "it": {
        "space_to_now": "spazio per tornare a ora",
        "waves": "Onde",
        "swell": "Moto ondoso",
    },
    "pt": {
        "space_to_now": "espa\u00e7o para voltar ao presente",
        "waves": "Ondas",
        "swell": "Ondula\u00e7\u00e3o",
    },
    "nl": {
        "space_to_now": "spatie om terug te keren",
        "waves": "Golven",
        "swell": "Deining",
    },
    "pl": {
        "space_to_now": "spacja, aby wr\u00f3ci\u0107",
        "waves": "Fale",
        "swell": "Falowanie",
    },
    "no": {
        "space_to_now": "mellomrom for \u00e5 g\u00e5 tilbake",
        "waves": "B\u00f8lger",
        "swell": "D\u00f8nning",
    },
    "sv": {
        "space_to_now": "mellanslag f\u00f6r att \u00e5terg\u00e5",
        "waves": "V\u00e5gor",
        "swell": "Dyning",
    },
    "da": {
        "space_to_now": "mellemrum for at vende tilbage",
        "waves": "B\u00f8lger",
        "swell": "D\u00f8nning",
    },
    "is": {
        "space_to_now": "bil til a\u00f0 fara til baka",
        "waves": "Bylgjur",
        "swell": "Boði",
    },
    "fi": {
        "space_to_now": "v\u00e4lily\u00f6nti palataksesi",
        "waves": "Aallot",
        "swell": "Maininki",
    },
    "ja": {
        "space_to_now": "\u30b9\u30da\u30fc\u30b9\u3067\u73fe\u5728\u306b\u623b\u308b",
        "waves": "\u6ce2",
        "swell": "\u3046\u306d\u308a",
    },
    "ko": {
        "space_to_now": "\uc2a4\ud398\uc774\uc2a4\ub85c \ud604\uc7ac\ub85c \ub3cc\uc544\uac00\uae30",
        "waves": "\ud30c\ub3c4",
        "swell": "\ub108\uc6b8",
    },
    "zh": {
        "space_to_now": "\u6309\u7a7a\u683c\u8fd4\u56de\u5f53\u524d",
        "waves": "\u6d77\u6d6a",
        "swell": "\u6d8c\u6d6a",
    },
}


MOON_NAMES_I18N = {
    "en": ["New Moon", "Waxing Crescent", "First Quarter", "Waxing Gibbous",
            "Full Moon", "Waning Gibbous", "Last Quarter", "Waning Crescent"],
    "fr": ["Nouvelle Lune", "Premier Croissant", "Premier Quartier", "Gibbeuse Croissante",
            "Pleine Lune", "Gibbeuse D\u00e9croissante", "Dernier Quartier", "Dernier Croissant"],
    "es": ["Luna Nueva", "Creciente", "Cuarto Creciente", "Gibosa Creciente",
            "Luna Llena", "Gibosa Menguante", "Cuarto Menguante", "Menguante"],
    "de": ["Neumond", "Zunehmende Sichel", "Erstes Viertel", "Zunehmender Mond",
            "Vollmond", "Abnehmender Mond", "Letztes Viertel", "Abnehmende Sichel"],
    "it": ["Luna Nuova", "Falce Crescente", "Primo Quarto", "Gibbosa Crescente",
            "Luna Piena", "Gibbosa Calante", "Ultimo Quarto", "Falce Calante"],
    "pt": ["Lua Nova", "Crescente C\u00f4ncava", "Quarto Crescente", "Crescente Convexa",
            "Lua Cheia", "Minguante Convexa", "Quarto Minguante", "Minguante C\u00f4ncava"],
    "nl": ["Nieuwe Maan", "Wassende Sikkel", "Eerste Kwartier", "Wassende Maan",
            "Volle Maan", "Afnemende Maan", "Laatste Kwartier", "Afnemende Sikkel"],
    "pl": ["N\u00f3w", "Sierp Rosn\u0105cy", "Pierwsza Kwadra", "Garb Rosn\u0105cy",
            "Pe\u0142nia", "Garb Malej\u0105cy", "Ostatnia Kwadra", "Sierp Malej\u0105cy"],
    "no": ["Nym\u00e5ne", "Voksende M\u00e5nesigd", "F\u00f8rste Kvarter", "Voksende M\u00e5ne",
            "Fullm\u00e5ne", "Avtagende M\u00e5ne", "Siste Kvarter", "Avtagende M\u00e5nesigd"],
    "sv": ["Nym\u00e5ne", "Tilltagande Sk\u00e4ra", "F\u00f6rsta Kvarteret", "Tilltagande M\u00e5ne",
            "Fullm\u00e5ne", "Avtagande M\u00e5ne", "Sista Kvarteret", "Avtagande Sk\u00e4ra"],
    "da": ["Nym\u00e5ne", "Tiltagende M\u00e5nesigd", "F\u00f8rste Kvarter", "Tiltagende M\u00e5ne",
            "Fuldm\u00e5ne", "Aftagende M\u00e5ne", "Sidste Kvarter", "Aftagende M\u00e5nesigd"],
    "is": ["N\u00fdtt Tungl", "Vaxandi H\u00e1lfm\u00e1ni", "Fyrsti Fj\u00f3r\u00f0ungur", "Vaxandi Tungl",
            "Fullt Tungl", "\u00deverrandi Tungl", "S\u00ed\u00f0asti Fj\u00f3r\u00f0ungur", "\u00deverrandi H\u00e1lfm\u00e1ni"],
    "fi": ["Uusikuu", "Kasvava Sirppi", "Ensimm\u00e4inen Nelj\u00e4nnes", "Kasvava Kuu",
            "T\u00e4ysikuu", "V\u00e4henev\u00e4 Kuu", "Viimeinen Nelj\u00e4nnes", "V\u00e4henev\u00e4 Sirppi"],
    "ja": ["\u65b0\u6708", "\u4e09\u65e5\u6708", "\u4e0a\u5f26", "\u5341\u4e09\u591c",
            "\u6e80\u6708", "\u5bdd\u5f85\u6708", "\u4e0b\u5f26", "\u6709\u660e\u6708"],
    "ko": ["\uc0ad", "\ucd08\uc2b9\ub2ec", "\uc0c1\ud604", "\ucc28\uc624\ub984",
            "\ubcf4\ub984", "\uae30\uc6b8\uc74c", "\ud558\ud604", "\uadf8\ubfc0"],
    "zh": ["\u65b0\u6708", "\u86fe\u7709\u6708", "\u4e0a\u5f26\u6708", "\u76c8\u51f8\u6708",
            "\u6ee1\u6708", "\u4e8f\u51f8\u6708", "\u4e0b\u5f26\u6708", "\u6b8b\u6708"],
}


def _moon_name(idx, runtime):
    """Return a localized moon phase name for the given index (0-7)."""
    lang = getattr(runtime, "lang", "en") if runtime else "en"
    names = MOON_NAMES_I18N.get(lang, MOON_NAMES_I18N["en"])
    return names[idx]


def _ts(key, runtime, **kwargs):
    """Look up a tides-specific localized string."""
    lang = getattr(runtime, "lang", "en") if runtime else "en"
    table = _TIDES_STRINGS.get(lang, _TIDES_STRINGS["en"])
    text = table.get(key, _TIDES_STRINGS["en"].get(key, key))
    return text.format(**kwargs) if kwargs else text
