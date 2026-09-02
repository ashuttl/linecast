"""Machine-readable JSON payload for `moon --json`.

Builds a plain-dict snapshot of the moon display's astronomy for external
consumers (e.g. a desktop widget). Reuses moon.py's mean-synodic phase math
and low-precision rise/set ephemeris; times are minute-precision local ISO
strings and missing values become None rather than raising.
"""

# The build_payload argument named `calendar` would shadow the stdlib
# module inside the function, so just the function comes in.
from calendar import isleap
from datetime import timedelta, timezone

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
    from linecast._pacific import PACIFIC_CALENDARS
    lang = lang_of(runtime)
    cal = resolve_calendar(calendar, lang)
    calendar_block = None
    if cal in PACIFIC_CALENDARS:
        # The Pacific calendars have no months-by-number, solar terms,
        # or festivals; the block carries the night. The Kaulana
        # Mahina adds its anahulu and counsel, the CNMI calendar the
        # night's Refaluwasch name.
        from linecast._moon_i18n import (
            anahulu_name, pacific_night_name, refaluwasch_name,
        )
        from linecast._pacific import (
            ANAHULU_COUNSEL, COUNSEL_ATTRIBUTION, COUNSEL_URL,
            night_note, pacific_night,
        )
        night, nights = pacific_night(cal, now_local.date())
        name = pacific_night_name(cal, night, nights)
        calendar_block = {
            "name": cal,
            "night": night,
            "nights_in_month": nights,
            "night_name": name,
        }
        if cal == "hawaiian":
            calendar_block["anahulu"] = anahulu_name(night)
            calendar_block["counsel"] = {
                "night_note": night_note(name),
                "anahulu": ANAHULU_COUNSEL[anahulu_name(night)],
                "source": COUNSEL_ATTRIBUTION,
                "url": COUNSEL_URL,
            }
        elif cal == "refaluwasch":
            calendar_block["refaluwasch_name"] = refaluwasch_name(night, nights)
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
    elif cal == "islamic":
        # The Umm al-Qura reading: the Hijri date, turned with the
        # reader's sunset as the panel turns it, the month's length,
        # the coming month, and the next observance — today's, once
        # the evening that opens it has come.
        from linecast._hijri import (
            after_sunset, days_in_month, hijri_date, next_month_start,
            next_observance,
        )
        from linecast._moon_i18n import (
            hijri_date_label, hijri_month_name, hijri_observance_name,
        )
        evening = after_sunset(now_local, lat, lng)
        h_day = now_local.date() + timedelta(days=1 if evening else 0)
        h_year, h_month, h_dom = hijri_date(h_day)
        nxt_day, (_nxt_year, nxt_month) = next_month_start(h_day)
        obs_day, obs_key = next_observance(h_day)
        calendar_block = {
            "name": cal,
            "year": h_year,
            "month": h_month,
            "month_name": hijri_month_name(h_month, lang),
            "day": h_dom,
            "days_in_month": days_in_month(h_day),
            "label": hijri_date_label(h_year, h_month, h_dom, lang),
            "after_sunset": evening,
            "next_month": {
                "name": hijri_month_name(nxt_month, lang),
                "date": nxt_day.isoformat(),
            },
            "next_observance": {
                "name": hijri_observance_name(obs_key, lang),
                "date": obs_day.isoformat(),
            },
        }
    elif cal == "hebrew":
        # The Hebrew date, turned with the reader's sunset as the
        # panel turns it, in letters too (the panel keeps to
        # transliteration, since terminals lay Hebrew out unreliably;
        # a JSON consumer can do better), the year's shape, the coming
        # month, the holiday in progress, and the next holiday,
        # diaspora dates.
        from linecast._hebrew import (
            days_in_month, days_in_year, hebrew_date, holiday_key,
            is_leap_year, next_holiday,
        )
        from linecast._hebrew import next_month_start as next_hebrew_month
        from linecast._hijri import after_sunset
        from linecast._moon_i18n import (
            hebrew_date_hebrew, hebrew_date_label, hebrew_holiday_name,
            hebrew_month_name,
        )
        evening = after_sunset(now_local, lat, lng)
        h_day = now_local.date() + timedelta(days=1 if evening else 0)
        h_year, h_month, h_dom = hebrew_date(h_day)
        nxt_day, (nxt_year, nxt_month) = next_hebrew_month(h_day)
        hol_day, hol_key = next_holiday(h_day)
        today_key = holiday_key(h_day)
        calendar_block = {
            "name": cal,
            "year": h_year,
            "leap_year": is_leap_year(h_year),
            "days_in_year": days_in_year(h_year),
            "month": h_month,
            "month_name": hebrew_month_name(h_year, h_month),
            "day": h_dom,
            "days_in_month": days_in_month(h_year, h_month),
            "label": hebrew_date_label(h_year, h_month, h_dom),
            "hebrew_label": hebrew_date_hebrew(h_year, h_month, h_dom),
            "after_sunset": evening,
            "holiday": hebrew_holiday_name(today_key) if today_key else None,
            "next_month": {
                "name": hebrew_month_name(nxt_year, nxt_month),
                "date": nxt_day.isoformat(),
            },
            "next_holiday": {
                "name": hebrew_holiday_name(hol_key),
                "date": hol_day.isoformat(),
            },
        }
    elif cal == "thai":
        # The Thai calendar: the waxing/waning day, the year's animal,
        # the วันพระ, and the coming festival. No solar terms.
        from linecast._moon_i18n import (
            thai_festival_name, thai_lunar_label, thai_year_label,
        )
        from linecast._thai_lunar import (
            cs_year, is_wan_phra, next_thai_festival, next_wan_phra,
            thai_lunar_date, year_animal_index,
        )
        today = now_local.date()
        t_month, t_day, t_doubled = thai_lunar_date(today)
        label_lang = "th" if lang == "th" else "en"
        fest_day, fest_key = next_thai_festival(today)
        calendar_block = {
            "name": cal,
            "month": t_month,
            "doubled_eighth": t_doubled,
            "day": t_day,
            "phase": "waxing" if t_day <= 15 else "waning",
            "phase_day": t_day if t_day <= 15 else t_day - 15,
            "label": thai_lunar_label(t_month, t_day, t_doubled,
                                      label_lang),
            "year_cs": cs_year(today),
            "year_be": today.year + 543,
            "year_animal": thai_year_label(year_animal_index(today),
                                           label_lang),
            "wan_phra": is_wan_phra(today),
            "next_wan_phra": next_wan_phra(today).isoformat(),
            "next_festival": {
                "name": thai_festival_name(fest_key, label_lang),
                "date": fest_day.isoformat(),
            },
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
