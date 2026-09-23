"""Where the sun is, and when it rises and sets.

The sunshine view is drawn from this, and the tides chart, the globe
and the one-line summaries borrow it.
"""

import math
import time as _time
from datetime import datetime, timedelta, timezone
from functools import lru_cache

from linecast._ephemeris import sun_declination


# ---------------------------------------------------------------------------
# Solar math
#
# Based on the simplified NOAA Solar Calculator equations, which are
# themselves derived from Meeus, "Astronomical Algorithms" (2nd ed.).
# See: https://gml.noaa.gov/grad/solcalc/solareqns.PDF
#
# Accuracy: ~1 minute for sunrise/sunset, ~0.3° for elevation.
# ---------------------------------------------------------------------------

def _tz_offset_hours():
    return _time.localtime().tm_gmtoff / 3600

def _equation_of_time(doy):
    """Equation of time in minutes (Spencer, 1971 / NOAA simplified form).

    B is the fractional year angle offset from the vernal equinox.
    """
    B = math.radians(360 / 365 * (doy - 81))
    return 9.87 * math.sin(2*B) - 7.53 * math.cos(B) - 1.5 * math.sin(B)

@lru_cache(maxsize=1024)
def _declination_on(year, doy):
    """Solar declination in degrees at UTC noon on a day of *year*."""
    noon = datetime(year, 1, 1, 12, tzinfo=timezone.utc) + timedelta(days=doy - 1)
    return sun_declination(noon)


def _declination(doy):
    """Solar declination in degrees, from the ephemeris.

    doy is a day of the user's current year; 0 and 367 reach into the
    neighboring years, as callers' yesterday and tomorrow do. The year
    is read through _local_today so a test can pin it.
    """
    return _declination_on(_local_today().year, doy)

def solar_times(lat, lng, doy, tz_offset_h=None):
    """Sunrise/sunset as local decimal hours.

    Uses the standard hour angle formula with a zenith of 90.833° to
    account for atmospheric refraction (~0.833° at the horizon).
    Reference: NOAA Solar Calculator, https://gml.noaa.gov/grad/solcalc/

    tz_offset_h is the UTC offset the "local" hours are expressed in;
    it defaults to the machine's, which is only right when the machine
    is at the location.
    """
    decl = _declination(doy)
    lat_r, dec_r = math.radians(lat), math.radians(decl)
    cos_ha = ((math.cos(math.radians(90.833)) -
               math.sin(lat_r) * math.sin(dec_r)) /
              (math.cos(lat_r) * math.cos(dec_r)))
    cos_ha = max(-1.0, min(1.0, cos_ha))
    ha = math.degrees(math.acos(cos_ha))
    eot = _equation_of_time(doy)
    noon_utc = 12 - lng / 15 - eot / 60
    tz = _tz_offset_hours() if tz_offset_h is None else tz_offset_h
    # A zone more than twelve hours from its own solar meridian — the
    # UTC+13 and +14 zones that sit east of the date line, Samoa, Tonga,
    # Kiritimati — puts noon_utc + tz outside the day it belongs to.
    # Solar noon is in the local date by definition, so bring it back.
    # A rise or set that falls the other side of midnight is real, and
    # is left where it lands.
    noon_local = (noon_utc + tz) % 24
    return noon_local - ha/15, noon_local + ha/15


# A day length this close to 0h or 24h means the hour angle above was
# clamped: the sun does not cross the horizon at this latitude today, and
# solar_times() returned noon twice rather than a rise and a set.
POLAR_EPSILON_HOURS = 0.01


def polar_state(day_len_h):
    """"night", "day", or None — whether the sun crosses the horizon."""
    if day_len_h <= POLAR_EPSILON_HOURS:
        return "night"
    if day_len_h >= 24 - POLAR_EPSILON_HOURS:
        return "day"
    return None


def sun_elevation(lat, lng, local_hour, doy, tz_offset_h=None):
    """Sun elevation angle in degrees at a given local hour."""
    decl = _declination(doy)
    eot = _equation_of_time(doy)
    noon_utc = 12 - lng / 15 - eot / 60
    tz = _tz_offset_hours() if tz_offset_h is None else tz_offset_h
    ha = 15 * (local_hour - tz - noon_utc)
    lat_r = math.radians(lat)
    dec_r = math.radians(decl)
    ha_r  = math.radians(ha)
    sin_e = (math.sin(lat_r) * math.sin(dec_r) +
             math.cos(lat_r) * math.cos(dec_r) * math.cos(ha_r))
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
