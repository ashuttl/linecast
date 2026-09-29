"""Machine-readable JSON payload for `moon --json`.

Builds a plain-dict snapshot of the moon display's astronomy for external
consumers (e.g. a desktop widget). Reuses moon/phase.py's mean-synodic phase math
and low-precision rise/set ephemeris; times are minute-precision local ISO
strings and missing values become None rather than raising.
"""

# The build_payload argument named `calendar` would shadow the stdlib
# module inside the function, so just the function comes in.
from calendar import isleap
from datetime import timezone

from linecast.astro.seasons import full_moon_name, next_season_event
from linecast._timefmt import iso_minutes
from linecast.sunshine.json import _local_timezone_name, _location_label

SCHEMA_VERSION = 1


def build_payload(now_local, lat, lng, runtime, location=None, calendar=None,
                  israel=False):
    """Build the `moon --json` payload dict.

    *now_local* is a timezone-aware local datetime, matching what moon's
    render path uses. *location* overrides the display name (skips the
    geocode lookup). *calendar* is the --calendar flag, resolved against
    the saved setting and language the same way the panel resolves it.
    """
    from linecast._i18n import moon_name
    from linecast.astro.ephemeris import (
        _moon_altitude_deg, _moon_azimuth_deg, moon_age_days,
    )
    from linecast.moon.phase import (
        HORIZON_THRESHOLD_DEG, SYNODIC_MONTH, moon_cycle_frac, moon_illumination,
        moon_phase, next_phase_local, upcoming_moon_events,
    )

    idx, _name, icon = moon_phase(now_local, runtime)
    frac = moon_cycle_frac(now_local)
    illumination = moon_illumination(now_local) * 100.0
    moment_utc = now_local.astimezone(timezone.utc)
    age_days = moon_age_days(moment_utc)

    rise, sset = upcoming_moon_events(now_local, lat, lng)
    events = [
        {"kind": kind, "time": iso_minutes(dt)}
        for dt, kind in sorted(
            ((dt, kind) for dt, kind in ((rise, "rise"), (sset, "set"))
             if dt is not None),
        )
    ]

    # The same searched moments the panel prints, so the two agree.
    full_dt = next_phase_local(moment_utc, 0.5, now_local)
    next_full = full_dt.date().isoformat()
    next_new = next_phase_local(moment_utc, 0.0, now_local).date().isoformat()

    event, event_utc = next_season_event(now_local)
    event_kind = ("march_equinox", "june_solstice",
                  "september_equinox", "december_solstice")[event]

    altitude = _moon_altitude_deg(moment_utc, lat, lng)
    azimuth = _moon_azimuth_deg(moment_utc, lat, lng)

    # The traditional calendar, resolved exactly as the panel resolves
    # it, so the two agree; null when no calendar is in effect.
    from linecast._i18n import lang_of
    from linecast.astro.calendars.lunisolar import resolve_calendar
    from linecast.moon.readings import context, reading
    cal, _source = resolve_calendar(calendar, lang_of(runtime))
    found = reading(cal)
    calendar_block = (found.json_block(context(now_local, lat, lng, runtime, cal, israel))
                      if found else None)

    return {
        "schema": SCHEMA_VERSION,
        "location": location if location is not None else _location_label(lat, lng),
        "timezone": (getattr(now_local.tzinfo, "key", None)
                     or _local_timezone_name()),
        "fetched_at": iso_minutes(now_local),
        "phase": moon_name(idx, runtime),
        "icon": icon,
        "illumination": round(illumination, 1),
        "waxing": frac < 0.5,
        "age_days": round(age_days, 1),
        "events": events,
        "next_full": next_full,
        # Traditional Old Farmer's Almanac name for that full moon,
        # e.g. "Harvest" or "Blue"
        "next_full_name": full_moon_name(full_dt, SYNODIC_MONTH),
        "next_new": next_new,
        "day_of_year": now_local.timetuple().tm_yday,
        "days_in_year": 366 if isleap(now_local.year) else 365,
        "next_season_event": {
            "kind": event_kind,
            "time": iso_minutes(event_utc.astimezone(now_local.tzinfo)),
        },
        "southern": bool(lat is not None and lat < 0),
        "calendar": calendar_block,
        # Extras a widget would want beyond the phase basics:
        "altitude_deg": round(altitude, 1),
        "azimuth_deg": round(azimuth, 1),
        "up_now": altitude > HORIZON_THRESHOLD_DEG,
    }
