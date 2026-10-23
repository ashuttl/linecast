"""Where the sun is, and when it rises and sets, in the decimal hours
the sunshine views plot a day by.

Both come from the ephemeris: the sunrise and sunset are
astro.ephemeris.sunrise_sunset, the one the tides' and the weather's
month views and the traditional hours read too, and the height is the
same ephemeris's. The tides chart, the globe and the one-line summaries
borrow from here as well.
"""

import math
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache

from linecast.astro.ephemeris import sun_declination, sun_transit_utc, sunrise_sunset


def day_offset(day, tzinfo=None):
    """The UTC offset, in hours, a day's rise and set are read on: the
    one its noon keeps, in *tzinfo* or the machine's zone.

    That is the day's own clock. The hours after midnight on the night
    the clocks change still keep the old offset, and a view that read
    the day on the offset of the moment would put its sunrise and sunset
    an hour off until two in the morning.
    """
    noon = datetime.combine(day, time(12), tzinfo=tzinfo)
    return (noon if tzinfo else noon.astimezone()).utcoffset().total_seconds() / 3600


def _day_of(doy):
    """The date of day *doy* of the user's year, which 0 and 367 leave
    for the neighboring years, as callers' yesterday and tomorrow do.
    The year is read through _local_today so a test can pin it."""
    return date(_local_today().year, 1, 1) + timedelta(days=doy - 1)


def _offset(doy, tz_offset_h):
    """*tz_offset_h*, or without one the machine's offset on day *doy*."""
    return day_offset(_day_of(doy)) if tz_offset_h is None else tz_offset_h


def _clock(day, offset_h):
    """The fixed zone a day's decimal hours are read in, and its midnight."""
    tz = timezone(timedelta(hours=offset_h))
    return tz, datetime(day.year, day.month, day.day, tzinfo=tz)


def _hours_since(midnight, moment):
    return (moment - midnight).total_seconds() / 3600


@lru_cache(maxsize=1024)
def _declination_on(year, doy):
    """Solar declination in degrees at UTC noon on a day of *year*."""
    noon = datetime(year, 1, 1, 12, tzinfo=timezone.utc) + timedelta(days=doy - 1)
    return sun_declination(noon)


def _declination(doy):
    """Solar declination in degrees at UTC noon on day *doy* of the
    user's year (_day_of), from the ephemeris."""
    return _declination_on(_local_today().year, doy)


def solar_times(lat, lng, doy, tz_offset_h=None):
    """Sunrise and sunset on day *doy*, as local decimal hours.

    They are astro.ephemeris.sunrise_sunset's: the upper limb on the
    horizon, refracted, to the second. A rise or set the other side of
    midnight is real, and lands below 0 or past 24. On a day the Sun
    does not rise both are its transit, and on a day it does not set
    they are the transit less and plus twelve hours, so the length of
    the day says which (polar_state).

    tz_offset_h is the UTC offset the "local" hours are expressed in,
    day_offset's for the day in the place's zone; it defaults to the
    machine's on that day, which is only right when the machine is at
    the location.
    """
    day = _day_of(doy)
    tz, midnight = _clock(day, _offset(doy, tz_offset_h))
    rise, sset = sunrise_sunset(day, lat, lng, tz)
    if rise is not None and sset - rise < timedelta(days=1):
        return _hours_since(midnight, rise), _hours_since(midnight, sset)
    noon = _hours_since(midnight, sun_transit_utc(day, lng, tz))
    if rise is None:
        return noon, noon
    return noon - 12, noon + 12


# A day length this close to 0h or 24h is one solar_times() gave for a
# day the sun does not cross the horizon: noon twice, or noon less and
# plus twelve hours, rather than a rise and a set.
POLAR_EPSILON_HOURS = 0.01


def polar_state(day_len_h):
    """"night", "day", or None — whether the sun crosses the horizon."""
    if day_len_h <= POLAR_EPSILON_HOURS:
        return "night"
    if day_len_h >= 24 - POLAR_EPSILON_HOURS:
        return "day"
    return None


def day_length_change(lat, lng, doy, tz_offset_h=None, yesterday_offset_h=None):
    """(day length in hours, its change since yesterday in seconds).

    Both come unrounded, and each caller rounds them its own way: the
    day view and the one-line summary truncate, the JSON rounds.
    Yesterday's rise and set are read on *yesterday_offset_h*, the UTC
    offset that day kept, or on today's, *tz_offset_h*, without one.
    """
    rise, sset = solar_times(lat, lng, doy, tz_offset_h)
    y_rise, y_set = solar_times(
        lat, lng, doy - 1,
        tz_offset_h if yesterday_offset_h is None else yesterday_offset_h)
    day_len = sset - rise
    return day_len, (day_len - (y_set - y_rise)) * 3600


@lru_cache(maxsize=1024)
def _transits(year, doy, lng, offset_h):
    """The Sun's transits before, on and after day *doy*, as decimal
    hours from its midnight, each with the declination then."""
    day = date(year, 1, 1) + timedelta(days=doy - 1)
    tz, midnight = _clock(day, offset_h)
    track = []
    for k in (-1, 0, 1):
        t = sun_transit_utc(day + timedelta(days=k), lng, tz)
        track.append((_hours_since(midnight, t), math.radians(sun_declination(t))))
    return tuple(track)


def sun_elevation(lat, lng, local_hour, doy, tz_offset_h=None):
    """The Sun's elevation in degrees at a local decimal hour of day
    *doy*: geometric, the centre against the true horizon.

    The hour angle turns once from one transit to the next, and the
    declination moves less than half a degree a day, so between the two
    transits either side of the hour both are a straight line. That is
    the ephemeris's own place to within an arcsecond or two, at the cost
    of a little trigonometry, which a frame that asks thousands of times
    needs.
    """
    track = _transits(_local_today().year, doy, lng, _offset(doy, tz_offset_h))
    (t0, d0), (t1, d1) = track[:2] if local_hour < track[1][0] else track[1:]
    frac = (local_hour - t0) / (t1 - t0)
    hour_angle = 2 * math.pi * frac
    dec = d0 + (d1 - d0) * frac
    lat_r = math.radians(lat)
    sin_e = (math.sin(lat_r) * math.sin(dec) +
             math.cos(lat_r) * math.cos(dec) * math.cos(hour_angle))
    return math.degrees(math.asin(max(-1.0, min(1.0, sin_e))))


def daylight_factor(local_hour, doy, lat, lng, tz_offset_h):
    """Compute a smooth day/night brightness factor for a local clock hour.

    Uses a slightly different declination formula (cosine form, with
    23.44° tilt and day offset +10 for the winter solstice epoch) for
    the day/night shading of the tides chart background.
    """
    decl = -23.44 * math.cos(math.radians(360 / 365 * (doy + 10)))
    lat_rad = math.radians(lat)
    decl_rad = math.radians(decl)

    cos_ha = -math.tan(lat_rad) * math.tan(decl_rad)
    if cos_ha <= -1:
        return 1.0  # midnight sun
    if cos_ha >= 1:
        return 0.0  # polar night

    ha = math.degrees(math.acos(cos_ha))

    solar_noon = 12.0
    if lng is not None:
        tz_meridian = tz_offset_h * 15
        solar_noon += (tz_meridian - lng) / 15

    sunrise = solar_noon - ha / 15
    sunset = solar_noon + ha / 15
    transition = 40 / 60  # 40 minutes

    if local_hour < sunrise - transition or local_hour > sunset + transition:
        return 0.0
    if sunrise + transition <= local_hour <= sunset - transition:
        return 1.0
    if local_hour < sunrise + transition:
        return (local_hour - sunrise + transition) / (2 * transition)
    return (sunset + transition - local_hour) / (2 * transition)


def _local_today():
    """The user's own date, on the machine's clock."""
    return datetime.now().date()
