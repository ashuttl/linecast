"""Persistent user settings (config.json under the config root)."""

import json
import os
import sys
from pathlib import Path
from typing import Any

from linecast._paths import config_root
from linecast._log import log_failure


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
    """Save *data* as config.json.

    A config.json that is there but will not read is a hand edit gone
    wrong, and read_config() gave {} for it: writing now would replace
    every setting in it with the one being changed.  It is refused with
    an OSError instead, which the callers already report.
    """
    path = config_file()
    try:
        current = json.loads(path.read_bytes())
    except FileNotFoundError:
        current = {}
    except ValueError as exc:
        raise OSError(f"it could not be read ({exc}); fix or remove it, then try again") from exc
    if not isinstance(current, dict):
        raise OSError("it does not hold a JSON object; fix or remove it, then try again")
    # A config.json linked in from a dotfiles repository is written
    # where the link points; replacing the link would leave the repo's
    # copy behind, and the link gone
    path = Path(os.path.realpath(path))
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


def _choice(value, choices):
    """*value* as *choices* spells it, or None. The case and the spaces
    around a hand-edited value are forgiven: " Metric" is metric."""
    if not isinstance(value, str):
        return None
    value = value.strip().lower()
    return value if value in choices else None


def _saved_choice(key, choices):
    """The setting saved under *key*, as *choices* spells it, or None."""
    return _choice(read_config().get(key), choices)


UNITS_CHOICES = ("metric", "imperial")


def saved_units() -> str | None:
    """Return 'metric' or 'imperial' saved via `linecast units`, or None."""
    return _saved_choice("units", UNITS_CHOICES)


CLOCK_CHOICES = ("12", "24")


def saved_clock() -> str | None:
    """Return '12' or '24' saved via `linecast clock`, or None. A hand
    edit may write the number itself, 24 rather than "24"."""
    return _choice(str(read_config().get("clock")), CLOCK_CHOICES)


# The day a printed calendar opens the week on. Monday nearly
# everywhere; Sunday and Saturday where the wall calendars say so,
# after CLDR's week data. Australia and China are left on Monday,
# where their calendars mostly are whatever CLDR says.
WEEK_STARTS = ("monday", "sunday", "saturday")


def saved_week_start() -> str | None:
    """Return 'monday', 'sunday' or 'saturday' saved via `linecast week`, or None."""
    return _saved_choice("week", WEEK_STARTS)


DATES_CHOICES = ("gregorian", "solar-hijri")


def dates_choice(value):
    """A setting's value as DATES_CHOICES spells it, or None.

    Case and the separator are forgiven: solar_hijri, Solar-Hijri."""
    return _choice(value.replace("_", "-") if isinstance(value, str) else None,
                   DATES_CHOICES)


def saved_dates() -> str | None:
    """Return 'gregorian' or 'solar-hijri' saved via `linecast dates`, or None."""
    return dates_choice(read_config().get("dates"))


DIGITS_CHOICES = ("latin", "native")


def digits_choice(value):
    """A setting's value as DIGITS_CHOICES spells it, or None."""
    return _choice(value, DIGITS_CHOICES)


def saved_digits() -> str | None:
    """Return 'latin' or 'native' saved via `linecast digits`, or None."""
    return _saved_choice("digits", DIGITS_CHOICES)


ICON_SETS = ("nerd", "emoji", "plain")


def saved_icons() -> str | None:
    """Return 'nerd', 'emoji' or 'plain' saved via `linecast icons`, or None."""
    return _saved_choice("icons", ICON_SETS)


def saved_language() -> str | None:
    """Return the language code saved via `linecast language`, or None."""
    from linecast._i18n import canonical_language, is_language_code
    lang = read_config().get("language")
    if isinstance(lang, str) and is_language_code(lang.strip()):
        return canonical_language(lang.strip().lower())
    return None


CALENDAR_CHOICES = ("chinese", "japanese", "korean", "vietnamese", "thai",
                    "hawaiian", "samoan", "chamorro", "refaluwasch",
                    "islamic", "hebrew", "icelandic", "almanac", "none")


def saved_calendar() -> str | None:
    """Return the calendar saved via `linecast calendar`, or None.

    A calendar name — 'chinese', 'japanese', 'korean', 'vietnamese',
    'thai', 'hawaiian', 'samoan', 'chamorro', 'refaluwasch',
    'islamic', 'hebrew', 'icelandic', or 'almanac' —
    pins that calendar in every language; 'none' turns the calendar
    lines off even where the language would show them.
    """
    return _saved_choice("calendar", CALENDAR_CHOICES)


# The systems of hours sunshine can read the day in, by the names
# `linecast hours` and `sunshine --hours` take. A hyphen separates a
# tradition from an opinion or method within it: halachic-mga is the
# Magen Avraham's day, alot to tzeit, where halachic is the Gr"a's.
# islamic-<method> pins a prayer-time convention where the place's
# country would pick one, and islamic-hanafi or -shafii the school
# whose Asr is listed. swahili is the one a language brings: `auto`
# reads the day in it with --lang sw.
HOURS_CHOICES = ("halachic", "halachic-mga", "roman", "japanese", "islamic",
                 "swahili",
                 "islamic-mwl", "islamic-isna", "islamic-egypt", "islamic-makkah",
                 "islamic-karachi", "islamic-tehran", "islamic-turkey",
                 "islamic-singapore", "islamic-jakim", "islamic-kemenag",
                 "islamic-france", "islamic-russia", "islamic-kuwait",
                 "islamic-qatar", "islamic-dubai", "islamic-jordan",
                 "islamic-morocco", "islamic-algeria", "islamic-tunisia",
                 "islamic-oman", "islamic-hanafi", "islamic-shafii", "none")


def saved_hours() -> str | None:
    """Return the system of hours saved via `linecast hours`, or None.

    A name from HOURS_CHOICES pins that system in every language;
    'none' keeps the hours off.
    """
    return _saved_choice("hours", HOURS_CHOICES)


# The sky's cultures, by the short names `linecast culture` and `sky
# --culture` take; the data behind them is sky.catalogue's.
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
    return _saved_choice("culture", CULTURE_CHOICES)


def saved_tidecheck_key() -> str | None:
    """Return the TideCheck API key under `tidecheck_key`, or None.

    No command saves it: a key given on a command line would stay in
    the shell's history, so it is written into config.json by hand.
    """
    key = read_config().get("tidecheck_key")
    return (key.strip() or None) if isinstance(key, str) else None


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


def save_location(lat: float, lng: float, label: str, country: str = "") -> None:
    """Save a place as the location every view starts from, in the shape
    saved_location() reads back.  An OSError from write_config is left
    to the caller, which says so in its own way."""
    config = read_config()
    config["location"] = dict(lat=lat, lng=lng, label=label, country=country)
    write_config(config)
