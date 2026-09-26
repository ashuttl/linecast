"""Where the planets are: positions and brightness, for the sky view.

Low-precision ephemeris after Paul Schlyter, the companion to the Sun
and Moon in `_ephemeris.py`: Keplerian elements for each planet at a
2000 epoch and their rates, one Kepler solve, and the few perturbation
terms that matter at arcminute precision — Jupiter and Saturn on each
other, both on Uranus. Positions come out within a couple of arcminutes
for the inner planets and Jupiter, a few for Saturn and beyond, which is
well inside a terminal cell at any zoom the view offers.

Magnitudes follow the same source: a distance term and a phase term per
planet, and for Saturn the tilt of the rings, which swings it by more
than a magnitude over its year.

Source: https://stjarnhimlen.se/comp/ppcomp.html
"""

import math

from linecast._ephemeris import _julian_day, _obliquity, _sun_ecliptic

PLANETS = ("mercury", "venus", "mars", "jupiter", "saturn", "uranus", "neptune")

# Orbital elements at d = 0 (2000 Jan 0.0) and their daily rates:
# N  longitude of the ascending node (deg)
# i  inclination to the ecliptic (deg)
# w  argument of perihelion (deg)
# a  semi-major axis (AU)
# e  eccentricity
# M  mean anomaly (deg)
_ELEMENTS = {
    "mercury": ((48.3313, 3.24587e-5), (7.0047, 5.00e-8), (29.1241, 1.01444e-5),
                (0.387098, 0.0), (0.205635, 5.59e-10), (168.6562, 4.0923344368)),
    "venus": ((76.6799, 2.46590e-5), (3.3946, 2.75e-8), (54.8910, 1.38374e-5),
              (0.723330, 0.0), (0.006773, -1.302e-9), (48.0052, 1.6021302244)),
    "mars": ((49.5574, 2.11081e-5), (1.8497, -1.78e-8), (286.5016, 2.92961e-5),
             (1.523688, 0.0), (0.093405, 2.516e-9), (18.6021, 0.5240207766)),
    "jupiter": ((100.4542, 2.76854e-5), (1.3030, -1.557e-7), (273.8777, 1.64505e-5),
                (5.20256, 0.0), (0.048498, 4.469e-9), (19.8950, 0.0830853001)),
    "saturn": ((113.6634, 2.38980e-5), (2.4886, -1.081e-7), (339.3939, 2.97661e-5),
               (9.55475, 0.0), (0.055546, -9.499e-9), (316.9670, 0.0334442282)),
    "uranus": ((74.0005, 1.3978e-5), (0.7733, 1.9e-8), (96.6612, 3.0565e-5),
               (19.18171, -1.55e-8), (0.047318, 7.45e-9), (142.5905, 0.011725806)),
    "neptune": ((131.7806, 3.0173e-5), (1.7700, -2.55e-7), (272.8461, -6.027e-6),
                (30.05826, 3.313e-8), (0.008606, 2.15e-9), (260.2471, 0.005995147)),
}

# Absolute magnitude and the phase-angle coefficients: mag = abs + 5 log10(r R)
# + c1·FV + c2·FV^n, FV the phase angle in degrees.
_MAGNITUDE = {
    "mercury": (-0.36, 0.027, 2.2e-13, 6),
    "venus": (-4.34, 0.013, 4.2e-7, 3),
    "mars": (-1.51, 0.016, 0.0, 1),
    "jupiter": (-9.25, 0.014, 0.0, 1),
    "saturn": (-9.0, 0.044, 0.0, 1),
    "uranus": (-7.15, 0.001, 0.0, 1),
    "neptune": (-6.90, 0.001, 0.0, 1),
}


def _elements(name, d):
    return tuple(v0 + rate * d for v0, rate in _ELEMENTS[name])


def _mean_anomaly(name, d):
    return math.radians((_ELEMENTS[name][5][0] + _ELEMENTS[name][5][1] * d) % 360.0)


def _heliocentric(name, d):
    """Heliocentric ecliptic longitude and latitude (radians) and distance
    (AU), perturbations included."""
    n_deg, i_deg, w_deg, a, e, m_deg = _elements(name, d)
    node, incl, peri = math.radians(n_deg), math.radians(i_deg), math.radians(w_deg)
    m = math.radians(m_deg % 360.0)
    # Kepler's equation, Newton's way; the first guess is already close.
    ecc = m + e * math.sin(m) * (1.0 + e * math.cos(m))
    for _ in range(10):
        step = (ecc - e * math.sin(ecc) - m) / (1.0 - e * math.cos(ecc))
        ecc -= step
        if abs(step) < 1e-7:
            break
    xv = a * (math.cos(ecc) - e)
    yv = a * math.sqrt(1.0 - e * e) * math.sin(ecc)
    v = math.atan2(yv, xv)
    r = math.hypot(xv, yv)
    u = v + peri
    xh = r * (math.cos(node) * math.cos(u) - math.sin(node) * math.sin(u) * math.cos(incl))
    yh = r * (math.sin(node) * math.cos(u) + math.cos(node) * math.sin(u) * math.cos(incl))
    zh = r * math.sin(u) * math.sin(incl)
    lon = math.atan2(yh, xh)
    lat = math.atan2(zh, math.hypot(xh, yh))

    if name in ("jupiter", "saturn", "uranus"):
        mj, ms, mu = (_mean_anomaly(p, d) for p in ("jupiter", "saturn", "uranus"))
        rad, sin, cos = math.radians, math.sin, math.cos
        dlon = dlat = 0.0
        if name == "jupiter":
            dlon = (-0.332 * sin(2 * mj - 5 * ms - rad(67.6))
                    - 0.056 * sin(2 * mj - 2 * ms + rad(21))
                    + 0.042 * sin(3 * mj - 5 * ms + rad(21))
                    - 0.036 * sin(mj - 2 * ms)
                    + 0.022 * cos(mj - ms)
                    + 0.023 * sin(2 * mj - 3 * ms + rad(52))
                    - 0.016 * sin(mj - 5 * ms - rad(69)))
        elif name == "saturn":
            dlon = (+0.812 * sin(2 * mj - 5 * ms - rad(67.6))
                    - 0.229 * cos(2 * mj - 4 * ms - rad(2))
                    + 0.119 * sin(mj - 2 * ms - rad(3))
                    + 0.046 * sin(2 * mj - 6 * ms - rad(69))
                    + 0.014 * sin(mj - 3 * ms + rad(32)))
            dlat = (-0.020 * cos(2 * mj - 4 * ms - rad(2))
                    + 0.018 * sin(2 * mj - 6 * ms - rad(49)))
        else:
            dlon = (+0.040 * sin(ms - 2 * mu + rad(6))
                    + 0.035 * sin(ms - 3 * mu + rad(33))
                    - 0.015 * sin(mj - mu + rad(20)))
        lon += rad(dlon)
        lat += rad(dlat)
    return lon, lat, r


def planet_position(name, dt_utc):
    """Geocentric right ascension and declination in degrees, the visual
    magnitude, and the distance from Earth in AU."""
    d = _julian_day(dt_utc) - 2451543.5
    lon, lat, r = _heliocentric(name, d)
    sun_lon, rs = _sun_ecliptic(dt_utc)

    xh = r * math.cos(lat) * math.cos(lon)
    yh = r * math.cos(lat) * math.sin(lon)
    zh = r * math.sin(lat)
    xg = xh + rs * math.cos(sun_lon)
    yg = yh + rs * math.sin(sun_lon)
    zg = zh
    dist = math.sqrt(xg * xg + yg * yg + zg * zg)

    obliq = _obliquity(d)
    xe = xg
    ye = yg * math.cos(obliq) - zg * math.sin(obliq)
    ze = yg * math.sin(obliq) + zg * math.cos(obliq)
    ra = math.degrees(math.atan2(ye, xe)) % 360.0
    dec = math.degrees(math.atan2(ze, math.hypot(xe, ye)))

    # Phase angle at the planet, Sun–planet–Earth.
    cos_fv = (r * r + dist * dist - rs * rs) / (2.0 * r * dist)
    fv = math.degrees(math.acos(max(-1.0, min(1.0, cos_fv))))
    absolute, c1, c2, power = _MAGNITUDE[name]
    mag = absolute + 5.0 * math.log10(r * dist) + c1 * fv + c2 * fv ** power
    if name == "saturn":
        # The rings: their tilt toward Earth, from the geocentric ecliptic
        # position and the ring plane's pole.
        glon = math.atan2(yg, xg)
        glat = math.atan2(zg, math.hypot(xg, yg))
        ir = math.radians(28.06)
        nr = math.radians(169.51 + 3.82e-5 * d)
        sin_b = (math.sin(glat) * math.cos(ir)
                 - math.cos(glat) * math.sin(ir) * math.sin(glon - nr))
        b = math.asin(max(-1.0, min(1.0, sin_b)))
        mag += -2.6 * math.sin(abs(b)) + 1.2 * math.sin(b) ** 2
    return ra, dec, mag, dist


def planet_positions(dt_utc):
    """{name: (ra_deg, dec_deg, mag, dist_au)} for every planet."""
    return {name: planet_position(name, dt_utc) for name in PLANETS}
