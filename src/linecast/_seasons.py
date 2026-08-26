"""Equinoxes, solstices, and traditional full moon names.

The equinox and solstice instants come from the series in Meeus,
*Astronomical Algorithms*, chapter 27 — valid 1000–3000 CE and good to
a minute or so.  The result is nominally Terrestrial Time; the ~minute
of offset from UTC is ignored, consistent with the moon command's
mean-synodic phase math.

Full moon names follow the Old Farmer's Almanac: one traditional name
per month, except that the full moon nearest the September equinox is
the Harvest Moon, the one after it is the Hunter's Moon, and a second
full moon in a calendar month is a Blue Moon.  The names are a North
American tradition and are applied worldwide, as the almanac does.
"""

import math
from datetime import datetime, timedelta, timezone

MARCH_EQUINOX, JUNE_SOLSTICE, SEPTEMBER_EQUINOX, DECEMBER_SOLSTICE = range(4)

# Mean event JDE as a polynomial in Y = (year - 2000) / 1000, one row
# per event in the order above (Meeus table 27.B).
_MEAN_JDE = (
    (2451623.80984, 365242.37404, 0.05169, -0.00411, -0.00057),
    (2451716.56767, 365241.62603, 0.00325, 0.00888, -0.00030),
    (2451810.21715, 365242.01767, -0.11575, 0.00337, 0.00078),
    (2451900.05952, 365242.74049, -0.06223, -0.00823, 0.00032),
)

# Periodic terms (A, B, C): the correction is 0.00001 · Σ A·cos(B + C·T)
# days, angles in degrees (Meeus table 27.C).
_PERIODIC = (
    (485, 324.96, 1934.136), (203, 337.23, 32964.467),
    (199, 342.08, 20.186), (182, 27.85, 445267.112),
    (156, 73.14, 45036.886), (136, 171.52, 22518.443),
    (77, 222.54, 65928.934), (74, 296.72, 3034.906),
    (70, 243.58, 9037.513), (58, 119.81, 33718.147),
    (52, 297.17, 150.678), (50, 21.02, 2281.226),
    (45, 247.54, 29929.562), (44, 325.15, 31555.956),
    (29, 60.93, 4443.417), (18, 155.12, 67555.328),
    (17, 288.79, 4562.452), (16, 198.04, 62894.029),
    (14, 199.76, 31436.921), (12, 95.39, 14577.848),
    (12, 287.11, 31931.756), (12, 320.81, 34777.259),
    (9, 227.73, 1222.114), (8, 15.45, 16859.074),
)

_UNIX_EPOCH_JD = 2440587.5


def season_event_utc(year, event):
    """The UTC instant of an equinox or solstice in the given year."""
    a, b, c, d, e = _MEAN_JDE[event]
    y = (year - 2000) / 1000.0
    jde0 = a + b * y + c * y * y + d * y ** 3 + e * y ** 4
    t = (jde0 - 2451545.0) / 36525.0
    w = math.radians(35999.373 * t - 2.47)
    dlam = 1.0 + 0.0334 * math.cos(w) + 0.0007 * math.cos(2.0 * w)
    s = sum(pa * math.cos(math.radians(pb + pc * t)) for pa, pb, pc in _PERIODIC)
    jde = jde0 + 0.00001 * s / dlam
    return (datetime(1970, 1, 1, tzinfo=timezone.utc)
            + timedelta(days=jde - _UNIX_EPOCH_JD))


def next_season_event(dt):
    """The first equinox or solstice after *dt* (aware datetime).

    Returns (event, instant): the event constant and its UTC datetime.
    """
    utc = dt.astimezone(timezone.utc)
    for year in (utc.year, utc.year + 1):
        for event in range(4):
            when = season_event_utc(year, event)
            if when > utc:
                return event, when
    raise ValueError(f"no season event after {dt}")  # unreachable


# Traditional names, January..December; September and October are the
# usual homes of the Harvest and Hunter's Moons, resolved dynamically.
FULL_MOON_NAMES = (
    "Wolf", "Snow", "Worm", "Pink", "Flower", "Strawberry",
    "Buck", "Sturgeon", "Corn", "Hunter's", "Beaver", "Cold",
)


def full_moon_name(full_local, synodic_days):
    """Traditional name for the full moon at *full_local* (aware datetime).

    *synodic_days* is the caller's synodic month length, so the nearest-
    full-moon windows stay consistent with its phase math.
    """
    full_utc = full_local.astimezone(timezone.utc)
    eq = season_event_utc(full_utc.year, SEPTEMBER_EQUINOX)
    delta = (full_utc - eq).total_seconds() / 86400.0
    half = synodic_days / 2.0
    if abs(delta) <= half:
        return "Harvest"          # the full moon nearest the equinox
    if half < delta <= 3.0 * half:
        return "Hunter's"         # the one after the Harvest Moon
    prev = full_local - timedelta(days=synodic_days)
    if (prev.year, prev.month) == (full_local.year, full_local.month):
        return "Blue"             # second full moon this calendar month
    return FULL_MOON_NAMES[full_local.month - 1]
