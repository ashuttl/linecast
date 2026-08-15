"""Machine-readable JSON payload for `moon --json`.

Builds a plain-dict snapshot of the moon display's astronomy for external
consumers (e.g. a desktop widget). Reuses moon.py's mean-synodic phase math
and low-precision rise/set ephemeris; times are minute-precision local ISO
strings and missing values become None rather than raising.
"""

from datetime import timedelta, timezone

from linecast._sunshine_json import _iso, _local_timezone_name, _location_label

SCHEMA_VERSION = 1


def build_payload(now_local, lat, lng, runtime, location=None):
    """Build the `moon --json` payload dict.

    *now_local* is a timezone-aware local datetime, matching what moon's
    render path uses. *location* overrides the display name (skips the
    geocode lookup).
    """
    from linecast._moon_i18n import _moon_name
    from linecast._tides_render import _moon_altitude_deg
    from linecast.moon import (
        HORIZON_THRESHOLD_DEG,
        moon_illumination,
        upcoming_moon_events,
    )
    from linecast.sunshine import SYNODIC_MONTH, moon_cycle_frac, moon_phase

    idx, _name, icon = moon_phase(now_local, runtime)
    frac = moon_cycle_frac(now_local)
    illumination = moon_illumination(now_local) * 100.0
    age_days = frac * SYNODIC_MONTH

    rise, sset = upcoming_moon_events(now_local, lat, lng)
    events = [
        {"kind": kind, "time": _iso(dt)}
        for dt, kind in sorted(
            ((dt, kind) for dt, kind in ((rise, "rise"), (sset, "set"))
             if dt is not None),
        )
    ]

    days_to_full = ((0.5 - frac) % 1.0) * SYNODIC_MONTH
    days_to_new = ((1.0 - frac) % 1.0) * SYNODIC_MONTH
    next_full = (now_local + timedelta(days=days_to_full)).date().isoformat()
    next_new = (now_local + timedelta(days=days_to_new)).date().isoformat()

    altitude = _moon_altitude_deg(now_local.astimezone(timezone.utc), lat, lng)

    return {
        "schema": SCHEMA_VERSION,
        "location": location if location is not None else _location_label(lat, lng),
        "timezone": _local_timezone_name(),
        "fetched_at": _iso(now_local),
        "phase": _moon_name(idx, runtime),
        "icon": icon,
        "illumination": round(illumination, 1),
        "waxing": frac < 0.5,
        "age_days": round(age_days, 1),
        "events": events,
        "next_full": next_full,
        "next_new": next_new,
        "southern": bool(lat is not None and lat < 0),
        # Extras a widget would want beyond the phase basics:
        "altitude_deg": round(altitude, 1),
        "up_now": altitude > HORIZON_THRESHOLD_DEG,
    }
