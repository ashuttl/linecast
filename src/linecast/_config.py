"""Persistent user settings (config.json under the config root)."""

import json
import sys
from pathlib import Path
from typing import Any

from linecast._paths import config_root
from linecast._runtime import HOURS_CHOICES, WEEK_STARTS, log_failure


def config_file() -> Path:
    return config_root() / "config.json"


def read_config() -> dict[str, Any]:
    """Return the parsed config dict, or {} if missing or corrupt.

    Corrupt covers a file that is not JSON, not UTF-8, or JSON that is
    not an object: the file is the user's to edit, and a hand edit
    that went wrong should cost the settings, not the command.
    """
    try:
        data = json.loads(config_file().read_bytes())
    except FileNotFoundError:
        return {}  # nothing saved yet: the usual case
    except (OSError, ValueError) as exc:
        # ValueError: JSONDecodeError, and UnicodeDecodeError for bytes
        # that are not UTF-8, which json.loads raises before parsing.
        log_failure("config", "read of config.json", exc, fallback="defaults used")
        return {}
    if not isinstance(data, dict):
        log_failure("config", "read of config.json",
                    TypeError(f"expected an object, got {type(data).__name__}"),
                    fallback="defaults used")
        return {}
    return data


def write_config(data: dict[str, Any]) -> None:
    path = config_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    from linecast._cache import write_bytes_atomic
    write_bytes_atomic(path, (json.dumps(data, indent=2) + "\n").encode())


def save_config(data: dict[str, Any]) -> None:
    """write_config for the settings commands.

    A config directory that cannot be written is a fact about the
    machine, not a bug, so the command ends with one line naming the
    file and the reason rather than a traceback.
    """
    try:
        write_config(data)
    except OSError as exc:
        sys.exit(f"Could not save settings to {config_file()}: {exc.strerror or exc}")


def saved_units() -> str | None:
    """Return 'metric' or 'imperial' saved via `linecast units`, or None."""
    units = read_config().get("units")
    if isinstance(units, str) and units.strip().lower() in ("metric", "imperial"):
        return units.strip().lower()
    return None


def saved_clock() -> str | None:
    """Return '12' or '24' saved via `linecast clock`, or None."""
    clock = read_config().get("clock")
    if str(clock).strip() in ("12", "24"):
        return str(clock).strip()
    return None


def saved_week_start() -> str | None:
    """Return 'monday', 'sunday' or 'saturday' saved via `linecast week`, or None."""
    week = read_config().get("week")
    if isinstance(week, str) and week.strip().lower() in WEEK_STARTS:
        return week.strip().lower()
    return None


def saved_dates() -> str | None:
    """Return 'gregorian' or 'solar-hijri' saved via `linecast dates`, or None."""
    from linecast.astro.calendars.civil import dates_choice
    return dates_choice(read_config().get("dates"))


def saved_digits() -> str | None:
    """Return 'latin' or 'native' saved via `linecast digits`, or None."""
    from linecast.terminal.bidi import digits_choice
    return digits_choice(read_config().get("digits"))


def saved_icons() -> str | None:
    """Return 'nerd', 'emoji' or 'plain' saved via `linecast icons`, or None."""
    icons = read_config().get("icons")
    if isinstance(icons, str) and icons.strip().lower() in ("nerd", "emoji", "plain"):
        return icons.strip().lower()
    return None


def saved_language() -> str | None:
    """Return the language code saved via `linecast language`, or None."""
    from linecast._i18n import canonical_language, is_language_code
    lang = read_config().get("language")
    if isinstance(lang, str) and is_language_code(lang.strip()):
        return canonical_language(lang.strip().lower())
    return None


CALENDAR_CHOICES = ("chinese", "japanese", "korean", "vietnamese", "thai",
                    "hawaiian", "samoan", "chamorro", "refaluwasch",
                    "islamic", "hebrew", "almanac", "none")


def saved_calendar() -> str | None:
    """Return the calendar saved via `linecast calendar`, or None.

    A calendar name — 'chinese', 'japanese', 'korean', 'vietnamese',
    'thai', 'hawaiian', 'samoan', 'chamorro', 'refaluwasch',
    'islamic', 'hebrew', or 'almanac' —
    pins that calendar in every language; 'none' turns the calendar
    lines off even where the language would show them.
    """
    cal = read_config().get("calendar")
    if isinstance(cal, str) and cal.strip().lower() in CALENDAR_CHOICES:
        return cal.strip().lower()
    return None


def saved_hours() -> str | None:
    """Return the system of hours saved via `linecast hours`, or None.

    A name from HOURS_CHOICES pins that system in every language;
    'none' keeps the hours off.
    """
    hours = read_config().get("hours")
    if isinstance(hours, str) and hours.strip().lower() in HOURS_CHOICES:
        return hours.strip().lower()
    return None


# The sky's cultures, by the short names `linecast culture` and `sky
# --culture` take; the data behind them is _sky.catalogue's.
CULTURE_CHOICES = ("anutan", "belarusian", "blackfoot", "boorong", "bugis",
                   "chinese", "chinese-modern", "hawaiian", "indian", "japanese",
                   "mandar", "maori", "mongolian", "norse", "romanian", "ruelle",
                   "sami", "siberian", "tongan", "tukano", "snt", "rey", "none")


def saved_culture() -> str | None:
    """Return the sky culture saved via `linecast culture`, or None.

    A culture name pins that culture's constellations and star names in
    every language; 'none' keeps the IAU sky even where the language
    would bring a culture with it.
    """
    culture = read_config().get("culture")
    if isinstance(culture, str) and culture.strip().lower() in CULTURE_CHOICES:
        return culture.strip().lower()
    return None


def saved_location() -> dict[str, Any] | None:
    """Return the location saved via `linecast location set`, or None.

    Shape: {"lat": float, "lng": float, "label": str, "country": str}.
    Resolved to coordinates at set time, so reading it never hits the network.
    """
    loc = read_config().get("location")
    if (isinstance(loc, dict)
            and all(isinstance(loc.get(k), (int, float))
                    and not isinstance(loc.get(k), bool) for k in ("lat", "lng"))
            and -90 <= loc["lat"] <= 90 and -180 <= loc["lng"] <= 180):
        return loc
    return None
