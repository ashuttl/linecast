"""Positions of the Sun and Moon, and the rise and set times that follow.

Low-precision ephemeris after Paul Schlyter, itself a simplification of
Meeus, "Astronomical Algorithms" (2nd ed.). Good to a couple of
arcminutes for the Moon and a hundredth of a degree for the Sun, which is
finer than a terminal cell and finer than the minute the clock times are
printed to.

Source: https://stjarnhimlen.se/comp/ppcomp.html
"""

import math
from datetime import datetime, timedelta, timezone


def _julian_day(dt_utc):
    """Convert a UTC datetime into Julian Day.

    Uses the Unix epoch offset: JD 2440587.5 = 1970-01-01T00:00:00Z.
    Reference: Meeus, "Astronomical Algorithms" (2nd ed.), ch. 7.
    """
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
    else:
        dt_utc = dt_utc.astimezone(timezone.utc)
    return dt_utc.timestamp() / 86400.0 + 2440587.5


def _norm_deg(angle):
    """Normalize an angle to [0, 360) degrees."""
    return angle % 360.0


def _sun_mean_elements(d):
    """Sun's argument of perihelion and mean anomaly, in radians.

    Shared by the solar position and by the lunar perturbation terms,
    which are driven by the Sun's pull and so need its place in the sky.
    """
    w = math.radians(_norm_deg(282.9404 + 4.70935e-5 * d))
    m = math.radians(_norm_deg(356.0470 + 0.9856002585 * d))
    return w, m


def _obliquity(d):
    """Mean obliquity of the ecliptic in radians (Meeus, eq. 22.2)."""
    return math.radians(23.4393 - 3.563e-7 * d)


def _to_equatorial(lon, lat, radius, obliq):
    """Ecliptic longitude/latitude/distance to equatorial RA/dec in degrees."""
    x = radius * math.cos(lat) * math.cos(lon)
    y = radius * math.cos(lat) * math.sin(lon)
    z = radius * math.sin(lat)
    y_eq = y * math.cos(obliq) - z * math.sin(obliq)
    z_eq = y * math.sin(obliq) + z * math.cos(obliq)
    return (_norm_deg(math.degrees(math.atan2(y_eq, x))),
            math.degrees(math.atan2(z_eq, math.hypot(x, y_eq))))


def _sun_ecliptic(dt_utc):
    """Geocentric Sun ecliptic longitude (radians) and distance (AU).

    Schlyter's solar position, the companion to _moon_ecliptic. The Sun's
    orbit needs no perturbation terms at this precision: one Kepler solve
    puts it within about 0.01 degrees, which is finer than the Moon. Its
    ecliptic latitude is zero by definition.

    Source: https://stjarnhimlen.se/comp/ppcomp.html#5
    """
    d = _julian_day(dt_utc) - 2451543.5
    w, m = _sun_mean_elements(d)
    e = 0.016709 - 1.151e-9 * d

    e_anom = m + e * math.sin(m) * (1.0 + e * math.cos(m))
    x_v = math.cos(e_anom) - e
    y_v = math.sqrt(1.0 - e * e) * math.sin(e_anom)
    return math.atan2(y_v, x_v) + w, math.hypot(x_v, y_v)


def _sun_ra_dec(dt_utc):
    """Geocentric Sun right ascension/declination in degrees."""
    lon, radius = _sun_ecliptic(dt_utc)
    return _to_equatorial(lon, 0.0, radius,
                          _obliquity(_julian_day(dt_utc) - 2451543.5))


def sun_declination(dt_utc):
    """Sun's declination in degrees."""
    return _sun_ra_dec(dt_utc)[1]


# Schlyter's perturbation terms for the Moon, in degrees. Each is an
# amplitude and the integer multiples of (Ms, Mm, D, F) making up its
# argument: the Sun's mean anomaly, the Moon's, the mean elongation, and
# the argument of latitude. The first three longitude terms are the named
# classical inequalities -- evection, variation, and the yearly equation --
# and between them they move the Moon by up to two degrees, which is four
# lunar diameters.
_MOON_LON_TERMS = (
    (-1.274, (0, 1, -2, 0)),    # evection
    (+0.658, (0, 0, 2, 0)),     # variation
    (-0.186, (1, 0, 0, 0)),     # yearly equation
    (-0.059, (0, 2, -2, 0)),
    (-0.057, (1, 1, -2, 0)),
    (+0.053, (0, 1, 2, 0)),
    (+0.046, (-1, 0, 2, 0)),
    (+0.041, (-1, 1, 0, 0)),
    (-0.035, (0, 0, 1, 0)),     # parallactic equation
    (-0.031, (1, 1, 0, 0)),
    (-0.015, (0, 0, -2, 2)),
    (+0.011, (0, 1, -4, 0)),
)
_MOON_LAT_TERMS = (
    (-0.173, (0, 0, -2, 1)),
    (-0.055, (0, 1, -2, -1)),
    (-0.046, (0, 1, -2, 1)),
    (+0.033, (0, 0, 2, 1)),
    (+0.017, (0, 2, 0, 1)),
)

def _moon_ecliptic(dt_utc):
    """Geocentric Moon ecliptic longitude and latitude, in radians.

    Paul Schlyter's lunar ephemeris, a simplification of the method in
    Meeus, "Astronomical Algorithms" (2nd ed.), ch. 47: two-body orbital
    elements, then the perturbation terms above, which are what the Sun's
    pull does to the orbit. With them the position is good to a couple of
    arcminutes; without them it strays by up to a couple of degrees, and
    the Moon's age with it.

    Source: https://stjarnhimlen.se/comp/ppcomp.html#15
    Orbital elements epoch: 2000-Jan-0.0 (JD 2451543.5).

    Element key:
      N  — longitude of the ascending node (deg)
      i  — orbital inclination (deg)
      w  — argument of perigee (deg)
      a  — semi-major axis (Earth radii)
      e  — orbital eccentricity
      M  — mean anomaly (deg)
    """
    jd = _julian_day(dt_utc)
    # Days since the orbital elements epoch (2000-Jan-0.0 = JD 2451543.5)
    d = jd - 2451543.5

    # Lunar orbital elements (Schlyter, epoch 2000-Jan-0.0)
    n = math.radians(_norm_deg(125.1228 - 0.0529538083 * d))      # ascending node
    inc = math.radians(5.1454)                                      # inclination
    w = math.radians(_norm_deg(318.0634 + 0.1643573223 * d))       # argument of perigee
    a = 60.2666                                                     # semi-major axis (Earth radii)
    e = 0.0549                                                      # eccentricity
    m = math.radians(_norm_deg(115.3654 + 13.0649929509 * d))      # mean anomaly

    e_anom = m + e * math.sin(m) * (1.0 + e * math.cos(m))
    x_v = a * (math.cos(e_anom) - e)
    y_v = a * (math.sqrt(1.0 - e * e) * math.sin(e_anom))
    true_anom = math.atan2(y_v, x_v)
    radius = math.hypot(x_v, y_v)

    x_h = radius * (
        math.cos(n) * math.cos(true_anom + w)
        - math.sin(n) * math.sin(true_anom + w) * math.cos(inc)
    )
    y_h = radius * (
        math.sin(n) * math.cos(true_anom + w)
        + math.cos(n) * math.sin(true_anom + w) * math.cos(inc)
    )
    z_h = radius * (math.sin(true_anom + w) * math.sin(inc))

    lon = math.atan2(y_h, x_h)
    lat = math.atan2(z_h, math.hypot(x_h, y_h))

    # Arguments the perturbation terms are built from.
    sun_w, sun_m = _sun_mean_elements(d)
    sun_lon = sun_w + sun_m               # Sun's mean longitude
    moon_lon = n + w + m                  # Moon's mean longitude
    elong = moon_lon - sun_lon            # mean elongation
    arg_lat = moon_lon - n                # argument of latitude
    args = (sun_m, m, elong, arg_lat)

    def total(terms):
        return sum(amp * math.sin(sum(k * v for k, v in zip(mult, args)))
                   for amp, mult in terms)

    lon += math.radians(total(_MOON_LON_TERMS))
    lat += math.radians(total(_MOON_LAT_TERMS))
    # Schlyter perturbs the distance too, but direction is what the
    # callers here want, and the two-body radius is already within a
    # percent — good enough for the parallax and crescent width the
    # Hawaiian calendar reads from it.

    return lon, lat, radius


def _moon_ra_dec(dt_utc):
    """Geocentric Moon right ascension/declination in degrees."""
    lon, lat, _dist = _moon_ecliptic(dt_utc)
    return _to_equatorial(lon, lat, 1.0,
                          _obliquity(_julian_day(dt_utc) - 2451543.5))


def _moon_distance_er(dt_utc):
    """Moon distance in Earth radii (two-body, unperturbed: ~1%)."""
    return _moon_ecliptic(dt_utc)[2]


def _gmst_deg(dt_utc):
    """Greenwich mean sidereal time in degrees.

    Uses the IAU 1982 expression for GMST as a function of Julian Date.
    Reference: Meeus, "Astronomical Algorithms" (2nd ed.), eq. 12.4.
    J2000.0 epoch = JD 2451545.0; Julian century = 36525 days.
    """
    jd = _julian_day(dt_utc)
    t = (jd - 2451545.0) / 36525.0
    gmst = (
        280.46061837
        + 360.98564736629 * (jd - 2451545.0)
        + 0.000387933 * t * t
        - (t * t * t) / 38710000.0
    )
    return _norm_deg(gmst)


def _moon_altitude_deg(dt_utc, lat_deg, lng_deg):
    """Approximate Moon altitude for a UTC datetime and observer lat/lng.

    Standard altitude formula (Meeus, ch. 13):
      sin(alt) = sin(lat)*sin(dec) + cos(lat)*cos(dec)*cos(ha)
    Geocentric: parallax and refraction are not corrected here, and the
    threshold_deg parameter in _moon_events_for_local_date stands in for
    the pair of them.
    """
    ra_deg, dec_deg = _moon_ra_dec(dt_utc)
    lst_deg = _norm_deg(_gmst_deg(dt_utc) + lng_deg)
    hour_angle = math.radians((lst_deg - ra_deg + 540.0) % 360.0 - 180.0)

    lat = math.radians(lat_deg)
    dec = math.radians(dec_deg)
    sin_alt = (
        math.sin(lat) * math.sin(dec)
        + math.cos(lat) * math.cos(dec) * math.cos(hour_angle)
    )
    sin_alt = max(-1.0, min(1.0, sin_alt))
    return math.degrees(math.asin(sin_alt))


def _moon_azimuth_deg(dt_utc, lat_deg, lng_deg):
    """Approximate Moon azimuth, degrees east of north.

    The companion to _moon_altitude_deg: same RA/dec and hour angle
    (Meeus, ch. 13), so knowing which way to look costs only the second
    trig call.  Meeus measures azimuth westward from south; the +180
    turns that into the compass bearing the rest of the app speaks.
    """
    ra_deg, dec_deg = _moon_ra_dec(dt_utc)
    lst_deg = _norm_deg(_gmst_deg(dt_utc) + lng_deg)
    hour_angle = math.radians((lst_deg - ra_deg + 540.0) % 360.0 - 180.0)

    lat = math.radians(lat_deg)
    dec = math.radians(dec_deg)
    azimuth = math.atan2(
        math.sin(hour_angle),
        math.cos(hour_angle) * math.sin(lat) - math.tan(dec) * math.cos(lat),
    )
    return (math.degrees(azimuth) + 180.0) % 360.0


def _moon_parallactic_deg(dt_utc, lat_deg, lng_deg):
    """Approximate parallactic angle of the Moon, in degrees.

    The angle at the Moon between the direction to the celestial pole and
    the direction to the observer's zenith (Meeus, ch. 14):
      tan(q) = sin(ha) / (tan(lat)*cos(dec) - sin(dec)*cos(ha))
    This is how far the Moon appears rotated from pole-up, and it turns
    with the hour angle as the Moon crosses the sky as well as with
    latitude. Positive east of the meridian; zero for a Moon due south of
    a northern observer.
    """
    ra_deg, dec_deg = _moon_ra_dec(dt_utc)
    lst_deg = _norm_deg(_gmst_deg(dt_utc) + lng_deg)
    hour_angle = math.radians((lst_deg - ra_deg + 540.0) % 360.0 - 180.0)

    lat = math.radians(lat_deg)
    dec = math.radians(dec_deg)
    return math.degrees(math.atan2(
        math.sin(hour_angle),
        math.tan(lat) * math.cos(dec) - math.sin(dec) * math.cos(hour_angle),
    ))


def _refine_moon_crossing_utc(t0_utc, t1_utc, lat_deg, lng_deg, threshold_deg):
    """Refine a moonrise/moonset crossing between two UTC datetimes.

    Uses bisection (16 iterations → ~30 second precision) to locate the
    zero-crossing of (altitude - threshold) between the bracketing times.
    """
    f0 = _moon_altitude_deg(t0_utc, lat_deg, lng_deg) - threshold_deg
    f1 = _moon_altitude_deg(t1_utc, lat_deg, lng_deg) - threshold_deg
    if f0 == 0:
        return t0_utc
    if f1 == 0:
        return t1_utc

    lo, hi = t0_utc, t1_utc
    vlo = f0
    for _ in range(16):
        mid = lo + timedelta(seconds=(hi - lo).total_seconds() / 2.0)
        vmid = _moon_altitude_deg(mid, lat_deg, lng_deg) - threshold_deg
        if vlo == 0:
            return lo
        if vlo * vmid <= 0:
            hi = mid
        else:
            lo, vlo = mid, vmid
        if abs((hi - lo).total_seconds()) < 30:
            break
    return lo + timedelta(seconds=(hi - lo).total_seconds() / 2.0)


def _moon_events_for_local_date(local_date, lat_deg, lng_deg, tzinfo, threshold_deg=0.125):
    """Return (moonrise_local, moonset_local) for one local calendar date.

    The threshold_deg of 0.125° approximates the combined effect of
    atmospheric refraction (~0.57° at horizon) and lunar horizontal
    parallax (~0.95°), which partially cancel. The net geometric rise
    happens when the Moon's center is about 0.125° above the true
    horizon. (See Meeus, ch. 15, for the full derivation.)

    Events are found by stepping in 10-minute increments, detecting sign
    changes in (altitude - threshold), then refining via bisection.
    """
    start_local = datetime(local_date.year, local_date.month, local_date.day, tzinfo=tzinfo)
    end_local = start_local + timedelta(days=1)
    start_utc = start_local.astimezone(timezone.utc)
    end_utc = end_local.astimezone(timezone.utc)

    rise = None
    sset = None
    step = timedelta(minutes=10)
    t_prev = start_utc
    v_prev = _moon_altitude_deg(t_prev, lat_deg, lng_deg) - threshold_deg
    t_cur = t_prev + step

    while t_cur <= end_utc and (rise is None or sset is None):
        v_cur = _moon_altitude_deg(t_cur, lat_deg, lng_deg) - threshold_deg
        crossing = (
            v_prev == 0
            or v_cur == 0
            or (v_prev < 0 <= v_cur)
            or (v_prev > 0 >= v_cur)
        )
        if crossing:
            cross_utc = _refine_moon_crossing_utc(
                t_prev, t_cur, lat_deg, lng_deg, threshold_deg
            )
            before = _moon_altitude_deg(
                cross_utc - timedelta(minutes=1), lat_deg, lng_deg
            ) - threshold_deg
            after = _moon_altitude_deg(
                cross_utc + timedelta(minutes=1), lat_deg, lng_deg
            ) - threshold_deg
            is_rise = after > before
            cross_local = cross_utc.astimezone(tzinfo)
            if start_local <= cross_local < end_local:
                if is_rise and rise is None:
                    rise = cross_local
                elif not is_rise and sset is None:
                    sset = cross_local

        t_prev, v_prev = t_cur, v_cur
        t_cur += step

    return rise, sset


def _moon_transits_for_local_date(local_date, lng_deg, tzinfo):
    """Local instants the Moon crosses the meridian on one local date.

    Returns (upper, lower): the meridian transit and anti-transit as
    aware local datetimes, either None on a date without one — the
    lunar day runs about 24h50m, so a date can miss one of the pair.
    Latitude plays no part: a transit is the hour angle reaching 0°
    (upper) or 180° (lower). Solunar tables put their major activity
    periods at these two moments, their minors at moonrise and moonset.
    """
    start_local = datetime(local_date.year, local_date.month,
                           local_date.day, tzinfo=tzinfo)
    end_local = start_local + timedelta(days=1)
    start_utc = start_local.astimezone(timezone.utc)
    end_utc = end_local.astimezone(timezone.utc)

    def offset(dt_utc, kind):
        ra_deg, _dec = _moon_ra_dec(dt_utc)
        h = _norm_deg(_gmst_deg(dt_utc) + lng_deg - ra_deg)
        return (h + 180.0) % 360.0 - 180.0 if kind == "upper" else h - 180.0

    found = {"upper": None, "lower": None}
    step = timedelta(minutes=30)
    for kind in found:
        t_prev, v_prev = start_utc, offset(start_utc, kind)
        t_cur = t_prev + step
        while t_cur <= end_utc and found[kind] is None:
            v_cur = offset(t_cur, kind)
            # The hour angle gains ~14.5° an hour; a small ascending
            # zero crossing is a transit, a big jump is the wrap.
            if v_prev < 0 <= v_cur and v_cur - v_prev < 180.0:
                lo, hi = t_prev, t_cur
                for _ in range(20):
                    mid = lo + (hi - lo) / 2
                    if offset(mid, kind) < 0:
                        lo = mid
                    else:
                        hi = mid
                cross_local = (lo + (hi - lo) / 2).astimezone(tzinfo)
                if start_local <= cross_local < end_local:
                    found[kind] = cross_local
            t_prev, v_prev = t_cur, v_cur
            t_cur += step
    return found["upper"], found["lower"]


def _angular_separation(ra1, dec1, ra2, dec2):
    """Angle between two equatorial directions, in degrees."""
    ra1, dec1, ra2, dec2 = (math.radians(v) for v in (ra1, dec1, ra2, dec2))
    cos_sep = (math.sin(dec1) * math.sin(dec2)
               + math.cos(dec1) * math.cos(dec2) * math.cos(ra1 - ra2))
    return math.degrees(math.acos(max(-1.0, min(1.0, cos_sep))))


def moon_phase_frac(dt_utc):
    """Where the Moon stands in its cycle, in [0, 1).

    0 is new, 0.25 first quarter, 0.5 full, 0.75 last quarter. This is
    the difference in ecliptic longitude between Moon and Sun, which is
    how the almanacs define the principal phases: new moon is the moment
    the two longitudes agree. The angle between them in the sky will not
    serve, because the Moon rides up to five degrees off the ecliptic and
    so never quite reaches 0° or 180° from the Sun.

    Measuring the real angle rather than counting mean synodic months
    also keeps an eccentric orbit from naming the wrong phase: the Moon
    runs ahead of and behind the mean by the better part of a day.
    """
    moon_lon, _lat, _dist = _moon_ecliptic(dt_utc)
    sun_lon, _r = _sun_ecliptic(dt_utc)
    return ((math.degrees(moon_lon - sun_lon)) % 360.0) / 360.0


def moon_illuminated_fraction(dt_utc):
    """Lit fraction of the Moon's disc, in [0, 1].

    For a sphere lit from one side the fraction is (1 − cos elongation)/2.
    Here the elongation is the true angle between Moon and Sun in the
    sky, ecliptic latitude and all -- unlike the phase fraction, which
    wants longitude only. It is why a total eclipse is rare: at most new
    moons the Moon passes a few degrees clear of the Sun, and a sliver
    stays lit.
    """
    moon_ra, moon_dec = _moon_ra_dec(dt_utc)
    sun_ra, sun_dec = _sun_ra_dec(dt_utc)
    elong = math.radians(
        _angular_separation(moon_ra, moon_dec, sun_ra, sun_dec))
    return (1.0 - math.cos(elong)) / 2.0


def _position_angle(ra, dec, ra_to, dec_to):
    """Position angle of one sky point seen from another, in degrees.

    Measured at (ra, dec) from the direction of the celestial north pole,
    round through east (Meeus, eq. 48.5). Used for both the bright limb
    and the Moon's own axis; only the target differs.
    """
    d_ra = math.radians(ra_to - ra)
    dec = math.radians(dec)
    dec_to = math.radians(dec_to)
    return math.degrees(math.atan2(
        math.cos(dec_to) * math.sin(d_ra),
        math.sin(dec_to) * math.cos(dec)
        - math.cos(dec_to) * math.sin(dec) * math.cos(d_ra),
    ))


def moon_bright_limb_deg(dt_utc):
    """Position angle of the Moon's bright limb, in degrees.

    The lit edge points at the Sun, and the Sun is rarely square to the
    Moon's poles, so this is what keeps the terminator from being drawn
    at the wrong slant.
    """
    moon_ra, moon_dec = _moon_ra_dec(dt_utc)
    sun_ra, sun_dec = _sun_ra_dec(dt_utc)
    return _position_angle(moon_ra, moon_dec, sun_ra, sun_dec)


def moon_axis_deg(dt_utc):
    """Position angle of the Moon's north pole, in degrees.

    The Moon's axis leans only 1.5° from the pole of the ecliptic, so the
    ecliptic pole stands in for it. That is worth doing rather than
    assuming the celestial pole, which is a further 23.4° away and would
    hang the maria at a visible tilt. The remaining degree and a half is
    libration, which belongs to a longer calculation than this one.
    """
    obliq = math.degrees(_obliquity(_julian_day(dt_utc) - 2451543.5))
    moon_ra, moon_dec = _moon_ra_dec(dt_utc)
    return _position_angle(moon_ra, moon_dec, 270.0, 90.0 - obliq)


def _phase_offset(dt_utc, target_frac):
    """Signed distance from *target_frac* in the cycle, in (-0.5, 0.5]."""
    return (moon_phase_frac(dt_utc) - target_frac + 0.5) % 1.0 - 0.5


def next_moon_phase_utc(after_utc, target_frac, backwards=False):
    """When the Moon next reaches *target_frac* of its cycle.

    0 is new and 0.5 full. Steps through the cycle looking for the moment
    the phase crosses the target, then bisects it — the same shape as the
    moonrise search, and for the same reason: the Moon does not move at
    an even rate, so the crossing has to be found rather than
    extrapolated from a mean month. Returns a UTC datetime, or None if no
    crossing turns up within a cycle, which should not happen.
    """
    step = timedelta(hours=6) * (-1 if backwards else 1)
    t_prev = after_utc
    g_prev = _phase_offset(t_prev, target_frac)
    for _ in range(int(31 * 24 / 6) + 1):
        t_cur = t_prev + step
        g_cur = _phase_offset(t_cur, target_frac)
        # A crossing is a small step over zero; the half-cycle jump
        # between +0.5 and -0.5 is the wrap, not the target.
        crossed = (g_prev < 0.0 <= g_cur) if not backwards else (g_cur < 0.0 <= g_prev)
        if crossed and abs(g_cur - g_prev) < 0.25:
            lo, hi = (t_prev, t_cur) if not backwards else (t_cur, t_prev)
            for _ in range(32):
                mid = lo + (hi - lo) / 2
                if _phase_offset(mid, target_frac) < 0.0:
                    lo = mid
                else:
                    hi = mid
            return lo + (hi - lo) / 2
        t_prev, g_prev = t_cur, g_cur
    return None


def moon_age_days(dt_utc):
    """Days since the last new moon."""
    last_new = next_moon_phase_utc(dt_utc, 0.0, backwards=True)
    if last_new is None:
        return moon_phase_frac(dt_utc) * 29.53058867
    return (dt_utc - last_new).total_seconds() / 86400.0
