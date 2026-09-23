"""Machine-readable JSON payload for `sunshine --json`.

Builds a plain-dict snapshot of the solar arc data for external consumers
(e.g. a desktop widget). Reuses sunshine's NOAA-derived solar math; times
are minute-precision local ISO strings and missing values become None
rather than raising.
"""

import time as _time
from datetime import datetime, timedelta

SCHEMA_VERSION = 1


def _iso(dt):
    """Minute-precision local ISO string, or None."""
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M")


def _hour_to_dt(date, decimal_hour):
    """Decimal local hour → datetime on *date* (spills into adjacent days)."""
    return (datetime(date.year, date.month, date.day)
            + timedelta(hours=decimal_hour))


# Nominatim names a point from the narrowest tier that carries a value:
# the locality if it has one, else the region it sits in, else the
# country. Anywhere with no city, town or village on it -- open water,
# farmland, a hamlet beside a Tasmanian river -- comes back with an empty
# name and a perfectly good address beside it.
_ADDRESS_TIERS = (
    ("city", "town", "village", "hamlet", "suburb", "municipality",
     "locality", "county"),
    ("state", "province", "region", "state_district"),
    ("country",),
)


def _address_label(address):
    """A place name assembled from a Nominatim address dict, or "".

    Two tiers at most, so the result reads like the reverse geocoder's own
    display name: "Tasmania, Australia" rather than the whole hierarchy.
    """
    if not address:
        return ""
    parts = []
    for tier in _ADDRESS_TIERS:
        for key in tier:
            val = str(address.get(key) or "").strip()
            if val:
                if val not in parts:
                    parts.append(val)
                break
        if len(parts) == 2:
            break
    return ", ".join(parts)


def _location_label(lat, lng):
    """Best available display name for the current coordinates.

    Prefers the label saved via `linecast location set`, then the cached
    reverse geocode (same source weather uses), then the address that
    reverse geocode returned beside an empty name, then bare coordinates.
    The geocoder is asked in the running command's language.
    """
    try:
        from linecast._config import saved_location
        saved = saved_location()
        # Only trust the saved label when it describes these coordinates —
        # a --location/WEATHER_LOCATION override points somewhere else.
        if (saved and saved.get("label") and lat is not None
                and abs(saved["lat"] - lat) < 1e-4
                and abs(saved["lng"] - lng) < 1e-4):
            return saved["label"]
    except Exception:
        pass
    try:
        from linecast._i18n import lang_of
        from linecast._runtime import current_runtime
        from linecast.weather.sources import _reverse_geocode
        name, _country, addr = _reverse_geocode(
            lat, lng, lang=lang_of(current_runtime()))
        if name:
            return name
        from_address = _address_label(addr)
        if from_address:
            return from_address
    except Exception:
        pass
    if lat is None or lng is None:
        return ""
    return f"{lat:.4f},{lng:.4f}"


def _local_timezone_name():
    """IANA zone name when resolvable, else the C-library abbreviation."""
    try:
        import os
        path = os.path.realpath("/etc/localtime")
        if "/zoneinfo/" in path:
            return path.split("/zoneinfo/", 1)[1]
    except Exception:
        pass
    try:
        return _time.localtime().tm_zone or None
    except Exception:
        return None


def _hours_block(hours, now):
    """The day in a tradition's hours: the edges, the reading of *now*,
    and every mark with its name, in order. None with no system on."""
    if hours is None:
        return None
    from linecast._hours import elapsed, fmt_duration, next_mark, reading
    from linecast._hours.i18n import (
        mark_name, mark_native, reading_name, variant_name,
    )
    from linecast._runtime import RuntimeConfig, current_runtime
    runtime = current_runtime(RuntimeConfig)

    def local_iso(dt):
        return _iso(dt.astimezone(now.tzinfo) if now.tzinfo else dt.astimezone())

    r = reading(hours, now)
    coming = next_mark(hours, now)
    reading_now = None
    if r is not None:
        reading_now = {
            "label": reading_name(hours.system, r, runtime),
            "night": r.night,
            "hour": r.index,
            "fraction": round(r.fraction, 4),
            "hour_seconds": int(round(r.hour_seconds)),
        }
        # Swahili time, as it is said aloud, for a voice to read.
        if hours.system == "swahili":
            from linecast._hours.swahili import moment, spoken
            reading_now["spoken"] = spoken(moment(r))
    marks = []
    for mark in hours.marks:
        entry = {"key": mark.key,
                 "name": mark_name(hours.system, mark.key, runtime, hours=hours),
                 "time": local_iso(mark.at)}
        native = mark_native(hours.system, mark.key)
        if native:
            entry["native"] = native
        marks.append(entry)
    return {
        "system": hours.system,
        "variant": hours.variant,
        "variant_name": variant_name(hours.system, hours.variant),
        "day_start": local_iso(hours.day_start) if hours.day_start else None,
        "day_end": local_iso(hours.day_end) if hours.day_end else None,
        "divisions": hours.divisions,
        "night_divisions": hours.night_divisions,
        "now": reading_now,
        "next": None if coming is None else {
            "key": coming.key,
            "time": local_iso(coming.at),
            "in": fmt_duration(elapsed(now, coming.at).total_seconds()),
        },
        "fast": None if not hours.fast else {
            "start": local_iso(hours.fast[0]),
            "end": local_iso(hours.fast[1]),
        },
        "marks": marks,
    }


def build_payload(lat, lng, now=None, location=None, hours=None):
    """Build the `sunshine --json` payload dict for a location.

    *now* is a local datetime (defaults to the current machine-local
    moment). A timezone-aware *now* pins the solar math and the payload's
    timezone to its zone — that's how a pinned location in another time
    zone gets that location's local times. *location* overrides the
    display name (skips the geocode lookup). *hours* is the day read
    in a tradition's hours (a _hours.DayHours), for an `hours` block.
    """
    from linecast.sunshine.solar import polar_state, solar_times, sun_elevation

    if now is None:
        now = datetime.now()
    hours_block = _hours_block(hours, now if now.tzinfo else now.astimezone())
    tz_name = None
    tz_offset_h = None
    if now.tzinfo is not None:
        tz_name = getattr(now.tzinfo, "key", None) or now.tzname()
        tz_offset_h = now.utcoffset().total_seconds() / 3600
        now = now.replace(tzinfo=None)
    today = now.date()
    doy = now.timetuple().tm_yday
    now_hour = now.hour + now.minute / 60 + now.second / 3600

    rise_h, set_h = solar_times(lat, lng, doy, tz_offset_h)
    y_rise_h, y_set_h = solar_times(lat, lng, doy - 1, tz_offset_h)
    t_rise_h, t_set_h = solar_times(lat, lng, doy + 1, tz_offset_h)

    day_len_h = set_h - rise_h
    day_length_seconds = int(round(day_len_h * 3600))
    day_length_delta_seconds = int(round((day_len_h - (y_set_h - y_rise_h)) * 3600))

    # Each day is tested separately: on the boundary dates of a polar
    # season one of the two is clamped and the other is a real crossing.
    polar = polar_state(day_len_h)
    tomorrow_polar = polar_state(t_set_h - t_rise_h)

    solar_noon = _hour_to_dt(today, (rise_h + set_h) / 2)
    tomorrow = today + timedelta(days=1)

    # No horizon crossing on a day: its rise/set are undefined, but noon,
    # day length, and delta remain meaningful.
    sunrise = None if polar else _hour_to_dt(today, rise_h)
    sunset = None if polar else _hour_to_dt(today, set_h)
    tomorrow_sunrise = (None if tomorrow_polar
                        else _hour_to_dt(tomorrow, t_rise_h))
    tomorrow_sunset = (None if tomorrow_polar
                       else _hour_to_dt(tomorrow, t_set_h))

    next_event = None
    for dt, kind in ((sunrise, "sunrise"), (sunset, "sunset"),
                     (tomorrow_sunrise, "sunrise"),
                     (tomorrow_sunset, "sunset")):
        if dt is not None and dt > now:
            next_event = {"kind": kind, "time": _iso(dt)}
            break

    return {
        "schema": SCHEMA_VERSION,
        "location": location if location is not None else _location_label(lat, lng),
        "timezone": tz_name or _local_timezone_name(),
        "fetched_at": _iso(now),
        "sunrise": _iso(sunrise),
        "sunset": _iso(sunset),
        "tomorrow_sunrise": _iso(tomorrow_sunrise),
        "tomorrow_sunset": _iso(tomorrow_sunset),
        "solar_noon": _iso(solar_noon),
        "day_length_seconds": day_length_seconds,
        "day_length_delta_seconds": day_length_delta_seconds,
        "next_event": next_event,
        "elevation_deg": round(sun_elevation(lat, lng, now_hour, doy, tz_offset_h), 2),
        "polar": polar,
        "hours": hours_block,
    }
