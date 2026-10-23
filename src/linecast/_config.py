"""Persistent user settings (config.json under the config root)."""

import json
import os
import sys
from collections import namedtuple
from pathlib import Path
from typing import Any

from linecast._i18n import LANGUAGE_CODES, VARIANTS, canonical_language, is_language_code
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
    around a hand-edited value are forgiven, " Metric" is metric, and so
    is a number written as one, 24 for "24"."""
    if isinstance(value, int) and not isinstance(value, bool):
        value = str(value)
    if not isinstance(value, str):
        return None
    value = value.strip().lower()
    return value if value in choices else None


# The units a wind speed is shown in, as the views write them, and the
# other ways they are typed: Open-Meteo's kmh and ms, kph and mps, and
# the knot as kt or by name.
_WIND_SPELLINGS = {"km/h": "km/h", "kmh": "km/h", "kph": "km/h",
                   "m/s": "m/s", "ms": "m/s", "mps": "m/s", "mph": "mph",
                   "kn": "kn", "kt": "kn", "kts": "kn", "knot": "kn", "knots": "kn"}


def _wind(value, _choices):
    """The wind unit *value* names, by any of its spellings."""
    return _WIND_SPELLINGS.get(str(value or "").strip().lower())


def _dates(value, choices):
    """Case and the separator are forgiven: solar_hijri, Solar-Hijri."""
    return _choice(value.replace("_", "-") if isinstance(value, str) else None, choices)


def _language(value, _choices):
    """Any code linecast could act on, not only the ones it has words
    in: another two-letter code still reaches the providers that publish
    in it."""
    if isinstance(value, str) and is_language_code(value.strip()):
        return canonical_language(value.strip().lower())
    return None


def _place(value, _choices):
    """{"lat": float, "lng": float, "label": str, "country": str}, on
    the planet, resolved to coordinates when it was set, so reading it
    never reaches the network."""
    if (isinstance(value, dict)
            and all(isinstance(value.get(k), (int, float))
                    and not isinstance(value.get(k), bool) for k in ("lat", "lng"))
            and -90 <= value["lat"] <= 90 and -180 <= value["lng"] <= 180):
        return value
    return None


class Setting(namedtuple("Setting", "name choices env blurb spell", defaults=(_choice,))):
    """One saved setting, declared once.

    *name* is the command that sets it (`linecast units`) and the key
    config.json keeps it under; *choices* are the values the command
    and the setting's flag take, in the order they are listed; *env* is
    the variable that stands above the saved value, and *blurb* the line
    `linecast --help` gives the command.  *spell* turns a value typed or
    read back into the choice it names, or None: by default one of
    *choices*, case and spaces forgiven.
    """
    __slots__ = ()

    def read(self, value):
        """*value*, from a command line, the environment or config.json,
        as the setting spells it, or None when it names none of the
        choices."""
        return self.spell(value, self.choices)


# Every setting a `linecast <name>` command saves, in the order the help
# page lists them.  The command, its flag's choices, the completions,
# the resolvers and doctor all read the setting from here.
SETTINGS = (
    Setting("location", None, "WEATHER_LOCATION",
            "A fixed place, instead of the one your IP address suggests", _place),
    # the codes linecast has words in; the command takes any code
    Setting("language", (*LANGUAGE_CODES, *VARIANTS), "LINECAST_LANG",
            ", ".join(LANGUAGE_CODES), _language),
    Setting("units", ("metric", "imperial"), "LINECAST_UNITS", "metric or imperial"),
    Setting("wind", ("km/h", "m/s", "mph", "kn"), "LINECAST_WIND_UNITS",
            "km/h, m/s, mph, or kn: the unit for wind speeds, whatever the other units",
            _wind),
    Setting("clock", ("12", "24"), "LINECAST_CLOCK", "12-hour or 24-hour"),
    # The day a printed calendar opens the week on. Monday nearly
    # everywhere; Sunday and Saturday where the wall calendars say so,
    # after CLDR's week data. Australia and China are left on Monday,
    # where their calendars mostly are whatever CLDR says.
    Setting("week", ("monday", "sunday", "saturday"), "LINECAST_WEEK_START",
            "monday, sunday, or saturday: where the week opens in the moon's month view"),
    Setting("dates", ("gregorian", "solar-hijri"), "LINECAST_DATES",
            "gregorian or solar-hijri, for writing dates (solar-hijri is the default "
            "in Persian)", _dates),
    Setting("digits", ("latin", "native"), "LINECAST_DIGITS",
            "latin (0-9) or native, for writing numbers (native, ۰-۹, is the default "
            "in Persian)"),
    Setting("icons", ("nerd", "emoji", "plain"), "LINECAST_ICONS", "nerd, emoji, or plain"),
    # A calendar name pins that calendar in every language; 'none' turns
    # the calendar lines off even where the language would show them.
    Setting("calendar", ("chinese", "japanese", "korean", "vietnamese", "thai",
                         "hawaiian", "samoan", "chamorro", "refaluwasch",
                         "islamic", "hebrew", "icelandic", "almanac", "none"), None,
            "chinese, japanese, korean, vietnamese, thai, hawaiian, samoan, chamorro, "
            "refaluwasch, islamic, hebrew, icelandic, almanac, or none: the traditional "
            "calendar the moon follows"),
    # The sky's cultures, by their short names; the data behind them is
    # sky.catalogue's. A culture pins its constellations and star names
    # in every language; 'none' keeps the IAU sky even where the language
    # would bring a culture with it.
    Setting("culture", ("anutan", "belarusian", "blackfoot", "boorong", "bugis",
                        "chinese", "chinese-modern", "hawaiian", "indian", "japanese",
                        "mandar", "maori", "mongolian", "norse", "romanian", "ruelle",
                        "sami", "siberian", "tongan", "tukano", "snt", "rey", "none"), None,
            "chinese, hawaiian, norse, maori, boorong, and seventeen more, or none: "
            "whose constellations the sky draws"),
    # The systems of hours sunshine can read the day in. A hyphen
    # separates a tradition from an opinion or method within it:
    # halachic-mga is the Magen Avraham's day, alot to tzeit, where
    # halachic is the Gr"a's. islamic-<method> pins a prayer-time
    # convention where the place's country would pick one, and
    # islamic-hanafi or -shafii the school whose Asr is listed. swahili
    # is the one a language brings: `auto` reads the day in it with
    # --lang sw. 'none' keeps the hours off.
    Setting("hours", ("halachic", "halachic-mga", "roman", "japanese", "islamic",
                      "swahili",
                      "islamic-mwl", "islamic-isna", "islamic-egypt", "islamic-makkah",
                      "islamic-karachi", "islamic-tehran", "islamic-turkey",
                      "islamic-singapore", "islamic-jakim", "islamic-kemenag",
                      "islamic-france", "islamic-russia", "islamic-kuwait",
                      "islamic-qatar", "islamic-dubai", "islamic-jordan",
                      "islamic-morocco", "islamic-algeria", "islamic-tunisia",
                      "islamic-oman", "islamic-hanafi", "islamic-shafii", "none"), None,
            "halachic, halachic-mga, roman, japanese, islamic, swahili, or none: the "
            "hours sunshine reads the day in"),
)
SETTING = {setting.name: setting for setting in SETTINGS}


def saved(name):
    """The setting *name* as config.json holds it, spelled as the
    setting spells it, or None when nothing it can read is saved."""
    return SETTING[name].read(read_config().get(name))


def chosen(name, environ=None, before=None):
    """The setting *name* as the user chose it, short of a flag.

    Returns (value, source): from the variable *before*, a command's own
    (WEATHER_UNITS), then the setting's own variable, then config.json,
    with the variable's name or "config" for the source; (None, None)
    when none of them names a choice, and the default decides.
    """
    setting = SETTING[name]
    env = os.environ if environ is None else environ
    for var in (before, setting.env):
        if var:
            value = setting.read(env.get(var, ""))
            if value is not None:
                return value, var
    value = saved(name)
    return (value, "config") if value is not None else (None, None)


# The names the settings had before the table, until each is read from it
CALENDAR_CHOICES = SETTING["calendar"].choices
CULTURE_CHOICES = SETTING["culture"].choices
HOURS_CHOICES = SETTING["hours"].choices


def saved_calendar() -> str | None:
    return saved("calendar")


def saved_hours() -> str | None:
    return saved("hours")


def saved_culture() -> str | None:
    return saved("culture")


def saved_tidecheck_key() -> str | None:
    """Return the TideCheck API key under `tidecheck_key`, or None.

    No command saves it: a key given on a command line would stay in
    the shell's history, so it is written into config.json by hand.
    """
    key = read_config().get("tidecheck_key")
    return (key.strip() or None) if isinstance(key, str) else None


def saved_location() -> dict[str, Any] | None:
    """Return the location saved via `linecast location set`, or None."""
    return saved("location")


def save_location(lat: float, lng: float, label: str, country: str = "") -> None:
    """Save a place as the location every view starts from, in the shape
    saved_location() reads back.  An OSError from write_config is left
    to the caller, which says so in its own way."""
    config = read_config()
    config["location"] = dict(lat=lat, lng=lng, label=label, country=country)
    write_config(config)
