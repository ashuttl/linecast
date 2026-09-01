"""Machine-readable JSON payload for `moon --json`.

Builds a plain-dict snapshot of the moon display's astronomy for external
consumers (e.g. a desktop widget). Reuses moon.py's mean-synodic phase math
and low-precision rise/set ephemeris; times are minute-precision local ISO
strings and missing values become None rather than raising.
"""

# The build_payload argument named `calendar` would shadow the stdlib
# module inside the function, so just the function comes in.
from calendar import isleap
from datetime import timezone

from linecast._seasons import full_moon_name, next_season_event
from linecast._sunshine_json import _iso, _local_timezone_name, _location_label

SCHEMA_VERSION = 1


def build_payload(now_local, lat, lng, runtime, location=None, calendar=None):
    """Build the `moon --json` payload dict.

    *now_local* is a timezone-aware local datetime, matching what moon's
    render path uses. *location* overrides the display name (skips the
    geocode lookup). *calendar* is the --calendar flag, resolved against
    the saved setting and language the same way the panel resolves it.
    """
    from linecast._moon_i18n import _moon_name
    from linecast._ephemeris import (
        _moon_altitude_deg, _moon_azimuth_deg, moon_age_days,
    )
    from linecast.moon import (
        HORIZON_THRESHOLD_DEG,
        _next_phase_local,
        moon_illumination,
        upcoming_moon_events,
    )
    from linecast.sunshine import SYNODIC_MONTH, moon_cycle_frac, moon_phase

    idx, _name, icon = moon_phase(now_local, runtime)
    frac = moon_cycle_frac(now_local)
    illumination = moon_illumination(now_local) * 100.0
    moment_utc = now_local.astimezone(timezone.utc)
    age_days = moon_age_days(moment_utc)

    rise, sset = upcoming_moon_events(now_local, lat, lng)
    events = [
        {"kind": kind, "time": _iso(dt)}
        for dt, kind in sorted(
            ((dt, kind) for dt, kind in ((rise, "rise"), (sset, "set"))
             if dt is not None),
        )
    ]

    # The same searched moments the panel prints, so the two agree.
    full_dt = _next_phase_local(moment_utc, 0.5, now_local)
    next_full = full_dt.date().isoformat()
    next_new = _next_phase_local(moment_utc, 0.0, now_local).date().isoformat()

    event, event_utc = next_season_event(now_local)
    event_kind = ("march_equinox", "june_solstice",
                  "september_equinox", "december_solstice")[event]

    altitude = _moon_altitude_deg(moment_utc, lat, lng)
    azimuth = _moon_azimuth_deg(moment_utc, lat, lng)

    # The traditional calendar, resolved exactly as the panel resolves
    # it, so the two agree; null when no calendar is in effect.
    from linecast._i18n import lang_of
    from linecast._lunisolar import (
        CALENDAR_MERIDIAN_HOURS, CALENDAR_NATIVE_LANG, current_term,
        lunisolar_date, next_lunar_event, next_term, resolve_calendar,
    )
    from linecast._moon_i18n import (
        festival_table, ja_night_name, lunar_date_label, term_label,
    )
    lang = lang_of(runtime)
    cal = resolve_calendar(calendar, lang)
    calendar_block = None
    if cal == "hawaiian":
        # The Kaulana Mahina has no months-by-number, solar terms, or
        # festivals; its block carries the night and its counsel.
        from linecast._moon_i18n import anahulu_name, po_mahina_name
        from linecast._pacific import (
            ANAHULU_COUNSEL, COUNSEL_ATTRIBUTION, COUNSEL_LINK,
            hawaiian_night, night_note,
        )
        night, nights = hawaiian_night(now_local.date())
        calendar_block = {
            "name": cal,
            "night": night,
            "nights_in_month": nights,
            "night_name": po_mahina_name(night, nights),
            "anahulu": anahulu_name(night),
            "counsel": {
                "night_note": night_note(po_mahina_name(night, nights)),
                "anahulu": ANAHULU_COUNSEL[anahulu_name(night)],
                "source": COUNSEL_ATTRIBUTION,
                "url": COUNSEL_LINK[1],
            },
        }
    elif cal == "almanac":
        # The Old Farmer's reading: which half of the month it is, and
        # the day's solunar periods.
        from linecast._ephemeris import (
            _moon_events_for_local_date, _moon_transits_for_local_date,
        )
        upper, lower = _moon_transits_for_local_date(
            now_local.date(), lng, now_local.tzinfo)
        day_rise, day_set = _moon_events_for_local_date(
            now_local.date(), lat, lng, now_local.tzinfo)
        calendar_block = {
            "name": cal,
            "gardening": "light" if frac < 0.5 else "dark",
            "solunar_major": sorted(_iso(t) for t in (upper, lower)
                                    if t is not None),
            "solunar_minor": sorted(_iso(t) for t in (day_rise, day_set)
                                    if t is not None),
        }
    elif cal is not None:
        cal_tz = CALENDAR_MERIDIAN_HOURS[cal]
        native = CALENDAR_NATIVE_LANG[cal] == lang
        label_lang = lang if native else "en"
        lunar = lunisolar_date(now_local.date(), cal_tz)
        cur_k, _cur_start = current_term(moment_utc)
        nxt_k, nxt_start = next_term(moment_utc)
        fest = next_lunar_event(now_local.date(), cal_tz,
                                festival_table(cal, native))
        calendar_block = {
            "name": cal,
            "month": lunar[0] if lunar else None,
            "day": lunar[1] if lunar else None,
            "leap_month": lunar[2] if lunar else None,
            "label": (lunar_date_label(*lunar, label_lang)
                      if lunar else None),
            # Japan names the night itself; the other calendars don't.
            "night_name": (ja_night_name(lunar[1])
                           if cal == "japanese" and lunar else None),
            "solar_term": term_label(cur_k, label_lang),
            "next_solar_term": {
                "name": term_label(nxt_k, label_lang),
                "date": (nxt_start.astimezone(now_local.tzinfo)
                         .date().isoformat()),
            },
            "next_festival": ({"name": fest[1],
                               "date": fest[0].isoformat()}
                              if fest else None),
        }

    return {
        "schema": SCHEMA_VERSION,
        "location": location if location is not None else _location_label(lat, lng),
        "timezone": (getattr(now_local.tzinfo, "key", None)
                     or _local_timezone_name()),
        "fetched_at": _iso(now_local),
        "phase": _moon_name(idx, runtime),
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
            "time": _iso(event_utc.astimezone(now_local.tzinfo)),
        },
        "southern": bool(lat is not None and lat < 0),
        "calendar": calendar_block,
        # Extras a widget would want beyond the phase basics:
        "altitude_deg": round(altitude, 1),
        "azimuth_deg": round(azimuth, 1),
        "up_now": altitude > HORIZON_THRESHOLD_DEG,
    }
