"""Localized strings and weather code labels for the weather dashboard."""

# Nerd Font WMO icons
_WMO_ICONS_NERD = {
    0: "\U000F0599", 1: "\U000F0599", 2: "\U000F0595", 3: "\U000F0590",
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
    0: "\u2600\ufe0f",  1: "\U0001f324\ufe0f",  2: "\u26c5", 3: "\u2601\ufe0f",
    45: "\U0001f32b\ufe0f", 48: "\U0001f32b\ufe0f",
    51: "\U0001f326\ufe0f", 53: "\U0001f326\ufe0f", 55: "\U0001f326\ufe0f",
    56: "\U0001f327\ufe0f", 57: "\U0001f327\ufe0f",
    61: "\U0001f327\ufe0f", 63: "\U0001f327\ufe0f", 65: "\U0001f327\ufe0f",
    66: "\U0001f327\ufe0f", 67: "\U0001f327\ufe0f",
    71: "\U0001f328\ufe0f", 73: "\U0001f328\ufe0f", 75: "\U0001f328\ufe0f", 77: "\U0001f328\ufe0f",
    80: "\U0001f326\ufe0f", 81: "\U0001f326\ufe0f", 82: "\U0001f326\ufe0f",
    85: "\U0001f328\ufe0f", 86: "\U0001f328\ufe0f",
    95: "\u26c8\ufe0f",  96: "\u26c8\ufe0f",  99: "\u26c8\ufe0f",
}


def _wmo_icons(runtime):
    return _WMO_ICONS_EMOJI if runtime.emoji else _WMO_ICONS_NERD


WMO_NAMES = {
    0: "Clear", 1: "Mostly Clear", 2: "Partly Cloudy", 3: "Overcast",
    45: "Fog", 48: "Rime Fog",
    51: "Light Drizzle", 53: "Drizzle", 55: "Heavy Drizzle",
    56: "Freezing Drizzle", 57: "Freezing Drizzle",
    61: "Light Rain", 63: "Rain", 65: "Heavy Rain",
    66: "Freezing Rain", 67: "Freezing Rain",
    71: "Light Snow", 73: "Snow", 75: "Heavy Snow", 77: "Snow Grains",
    80: "Light Showers", 81: "Showers", 82: "Heavy Showers",
    85: "Snow Showers", 86: "Heavy Snow Showers",
    95: "Thunderstorm", 96: "Thunderstorm", 99: "Thunderstorm",
}

DAY_NAMES = {
    "en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
    "fr": ["lun", "mar", "mer", "jeu", "ven", "sam", "dim"],
}

FULL_DAY_NAMES = {
    "en": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
    "fr": ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"],
}

WMO_NAMES_I18N = {
    "fr": {
        0: "Dégagé", 1: "Peu nuageux", 2: "Partiellement nuageux", 3: "Couvert",
        45: "Brouillard", 48: "Brouillard givrant",
        51: "Bruine légère", 53: "Bruine", 55: "Forte bruine",
        56: "Bruine verglaçante", 57: "Bruine verglaçante",
        61: "Pluie légère", 63: "Pluie", 65: "Forte pluie",
        66: "Pluie verglaçante", 67: "Pluie verglaçante",
        71: "Neige légère", 73: "Neige", 75: "Forte neige", 77: "Grains de neige",
        80: "Averses légères", 81: "Averses", 82: "Fortes averses",
        85: "Averses de neige", 86: "Fortes averses de neige",
        95: "Orage", 96: "Orage", 99: "Orage",
    },
}

_PRECIP_DESCS_I18N = {
    "fr": {
        51: "bruine légère", 53: "bruine", 55: "forte bruine",
        56: "bruine verglaçante", 57: "bruine verglaçante",
        61: "pluie légère", 63: "pluie", 65: "forte pluie",
        66: "pluie verglaçante", 67: "pluie verglaçante",
        71: "neige légère", 73: "neige", 75: "forte neige", 77: "grains de neige",
        80: "averses légères", 81: "averses", 82: "fortes averses",
        85: "averses de neige", 86: "fortes averses de neige",
        95: "orages", 96: "orages", 99: "orages",
    },
}

# Localized UI strings
_STRINGS = {
    "en": {
        "today": "Today",
        "today_short": "Tod",
        "feels": "feels",
        "wind": "Wind",
        "gusts": "gusts",
        # Comparative line
        "same_temp": "about the same temperature as {ref_day}",
        "bit_warmer": "a bit warmer than {ref_day}",
        "bit_cooler": "a bit cooler than {ref_day}",
        "warmer": "warmer than {ref_day}",
        "cooler": "cooler than {ref_day}",
        "much_warmer": "much warmer than {ref_day}",
        "much_cooler": "much cooler than {ref_day}",
        "today_subj": "Today",
        "tomorrow_subj": "Tomorrow",
        "yesterday": "yesterday",
        "today_ref": "today",
        "will_be": "{subject} will be {comparison}",
        # Precipitation line
        "ending": "{desc} ending {time}",
        "continuing": "{desc} continuing through the day",
        "starting": "{desc} likely starting {time}",
        "shortly": "shortly",
        "in_about_an_hour": "in about an hour",
        "in_a_couple_hours": "in a couple hours",
        "around": "around {time}",
        "tomorrow_morning": "tomorrow morning",
        "tomorrow_afternoon": "tomorrow afternoon",
        "tomorrow_evening": "tomorrow evening",
        "on_day": "on {day}",
        # Past precip
        "past_precip": "{amt} of {ptype} in the last 24h",
        "snow": "snow",
        "rain": "rain",
        "mixed_precip": "mixed precipitation",
        # Daily precip types
        "Snow": "Snow",
        "Rain": "Rain",
        "Mix": "Mix",
        # Alert modal hints
        "q_to_close": "q to close",
        "o_to_open": "o to open in browser",
        "scroll": "scroll",
    },
    "fr": {
        "today": "aujourd'hui",
        "today_short": "auj",
        "feels": "ressenti",
        "wind": "Vent",
        "gusts": "rafales",
        # Comparative line
        "same_temp": "\u00e0 peu pr\u00e8s la m\u00eame temp\u00e9rature {subject} qu'{ref_day}",
        "bit_warmer": "un peu plus chaud {subject} qu'{ref_day}",
        "bit_cooler": "un peu plus frais {subject} qu'{ref_day}",
        "warmer": "plus chaud {subject} qu'{ref_day}",
        "cooler": "plus frais {subject} qu'{ref_day}",
        "much_warmer": "beaucoup plus chaud {subject} qu'{ref_day}",
        "much_cooler": "beaucoup plus frais {subject} qu'{ref_day}",
        "today_subj": "Aujourd'hui",
        "tomorrow_subj": "Demain",
        "yesterday": "hier",
        "today_ref": "aujourd'hui",
        "will_be": "Il fera {comparison}",
        # Precipitation line
        "ending": "{desc} se terminant {time}",
        "continuing": "{desc} se poursuivant toute la journ\u00e9e",
        "starting": "{desc} probable {time}",
        "shortly": "tr\u00e8s bient\u00f4t",
        "in_about_an_hour": "dans environ une heure",
        "in_a_couple_hours": "dans quelques heures",
        "around": "vers {time}",
        "tomorrow_morning": "demain matin",
        "tomorrow_afternoon": "demain apr\u00e8s-midi",
        "tomorrow_evening": "demain soir",
        "on_day": "{day}",
        # Past precip
        "past_precip": "{amt} de {ptype} au cours des derni\u00e8res 24 h",
        "snow": "neige",
        "rain": "pluie",
        "mixed_precip": "pr\u00e9cipitations mixtes",
        # Daily precip types
        "Snow": "Neige",
        "Rain": "Pluie",
        "Mix": "Mixte",
        # Alert modal hints
        "q_to_close": "q pour fermer",
        "o_to_open": "o pour ouvrir dans le navigateur",
        "scroll": "défiler",
    },
}


def _s(key, runtime, **kwargs):
    """Look up a localized string, with optional format substitution."""
    lang = getattr(runtime, "lang", "en")
    template = _STRINGS.get(lang, _STRINGS["en"]).get(key, _STRINGS["en"].get(key, key))
    return template.format(**kwargs) if kwargs else template
