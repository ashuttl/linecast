"""The tide machine: a tide predicted from its harmonic constants.

A tide is a sum of a few dozen cosines, each turning at the speed of an
astronomical cycle (the Moon's half day, the Sun's, the Moon's swing in
declination, and the overtides shallow water adds), with an amplitude
and a phase lag that a station's own record fixes. Kelvin built a machine
of pulleys and wire to add them up in 1872; this is the same sum.

The arguments are Schureman's, from the US Coast and Geodetic Survey's
"Manual of Harmonic Analysis and Prediction of Tides" (Special
Publication 98, 1958), with the mean longitudes of the Moon, the Sun,
the lunar perigee and node, and the solar perigee after Meeus. The
nodal corrections, which follow the Moon's 18.6-year nodal cycle, are
Schureman's formulas, taken at the middle of each year as NOAA takes
them. Phases are Greenwich phase lags
in degrees, as TICON-4 and NOAA publish them, and heights are in
whatever unit the amplitudes are.

The same sums run backwards to fit a record: `fit` finds the constants
that best explain a series of heights by least squares, so a year of a
model's hourly sea level becomes a tide that can be asked for any date.

Checked against NOAA: Portland, Maine's published constants reproduce
NOAA's own hourly predictions for 2026 to a millimetre, and Seattle's,
Pensacola's and San Francisco's to under six; the times of the highs
and lows agree to a minute or two.
"""

import math
import operator
from datetime import datetime, timedelta, timezone
from functools import lru_cache

UTC = timezone.utc
_J2000 = 2451545.0
_HOURS_PER_CENTURY = 36525 * 24

# Each constituent's argument is a sum of whole multiples of five angles
# (T, s, h, p, p1) and a fixed phase in degrees: T the hour angle of the
# mean Sun, s the Moon's mean longitude, h the Sun's, p the lunar
# perigee's, p1 the solar perigee's. Its nodal correction is a product
# of the few basic factors below, each to a power: the amplitude factors
# multiply and the angles add with the powers' signs.
#
# TICON-4 also lists 3N2, 3L2, MTM, MSQM, T3, R3, and an MKS2 at
# 28.435°/h that is not Schureman's MKS2. None could be checked against
# a published table, so they are left out: a few millimetres on an open
# coast, up to a few centimetres in some rivers.
CONSTITUENTS = {
    # long period
    "SA": ((0, 0, 1, 0, 0, 0), ()),
    "SSA": ((0, 0, 2, 0, 0, 0), ()),
    "MM": ((0, 1, 0, -1, 0, 0), (("Mm", 1),)),
    "MSF": ((0, 2, -2, 0, 0, 0), (("M2", -1),)),
    "MF": ((0, 2, 0, 0, 0, 0), (("Mf", 1),)),
    # diurnal
    "2Q1": ((1, -4, 1, 2, 0, 90), (("O1", 1),)),
    "SGM": ((1, -4, 3, 0, 0, 90), (("O1", 1),)),
    "Q1": ((1, -3, 1, 1, 0, 90), (("O1", 1),)),
    "RHO1": ((1, -3, 3, -1, 0, 90), (("O1", 1),)),
    "O1": ((1, -2, 1, 0, 0, 90), (("O1", 1),)),
    # NOAA's M1, whose nodal correction Schureman builds from two terms
    # that also turn with the perigee. K1's stands in: of the simple
    # choices it matched NOAA's predictions best, and M1 is a centimetre
    # or two at most.
    "M1": ((1, -1, 1, 1, 0, -90), (("K1", 1),)),
    "P1": ((1, 0, -1, 0, 0, 90), ()),
    "S1": ((1, 0, 0, 0, 0, 0), ()),
    "K1": ((1, 0, 1, 0, 0, -90), (("K1", 1),)),
    "J1": ((1, 1, 1, -1, 0, -90), (("J1", 1),)),
    "OO1": ((1, 2, 1, 0, 0, -90), (("OO1", 1),)),
    # semidiurnal
    "2N2": ((2, -4, 2, 2, 0, 0), (("M2", 1),)),
    "EP2": ((2, -5, 4, 1, 0, 0), (("M2", 1),)),
    "MU2": ((2, -4, 4, 0, 0, 0), (("M2", 1),)),
    "N2": ((2, -3, 2, 1, 0, 0), (("M2", 1),)),
    "NU2": ((2, -3, 4, -1, 0, 0), (("M2", 1),)),
    "M2": ((2, -2, 2, 0, 0, 0), (("M2", 1),)),
    # M2's yearly swing, which rivers and estuaries give it: a tenth of a
    # metre on the Elbe and the Loire. Neither is in the tide-raising
    # force, so the phase convention is a choice; TICON-4's is checked
    # against BSH's 2027 curve for Cuxhaven, which it fits better with
    # these two than without them, and worse with any other offset.
    "MA2": ((2, -2, 1, 0, 0, 0), (("M2", 1),)),
    "MB2": ((2, -2, 3, 0, 0, 0), (("M2", 1),)),
    "LAMBDA2": ((2, -1, 0, 1, 0, 180), (("M2", 1),)),
    "L2": ((2, -1, 2, -1, 0, 180), (("L2", 1),)),
    "T2": ((2, 0, -1, 0, 1, 0), ()),
    "S2": ((2, 0, 0, 0, 0, 0), ()),
    "R2": ((2, 0, 1, 0, -1, 180), ()),
    "K2": ((2, 0, 2, 0, 0, 0), (("K2", 1),)),
    "2SM2": ((2, 2, -2, 0, 0, 0), (("M2", -1),)),
    # the overtides and compound tides of shallow water
    "2MK3": ((3, -4, 3, 0, 0, 90), (("M2", 2), ("K1", -1))),
    "M3": ((3, -3, 3, 0, 0, 0), (("M2", 1.5),)),
    "S3": ((3, 0, 0, 0, 0, 0), ()),
    "MK3": ((3, -2, 3, 0, 0, -90), (("M2", 1), ("K1", 1))),
    "N4": ((4, -6, 4, 2, 0, 0), (("M2", 2),)),
    "MN4": ((4, -5, 4, 1, 0, 0), (("M2", 2),)),
    "M4": ((4, -4, 4, 0, 0, 0), (("M2", 2),)),
    "MS4": ((4, -2, 2, 0, 0, 0), (("M2", 1),)),
    "S4": ((4, 0, 0, 0, 0, 0), ()),
    "2MO5": ((5, -6, 5, 0, 0, 90), (("M2", 2), ("O1", 1))),
    "2MK5": ((5, -4, 5, 0, 0, -90), (("M2", 2), ("K1", 1))),
    "M6": ((6, -6, 6, 0, 0, 0), (("M2", 3),)),
    "2MS6": ((6, -4, 4, 0, 0, 0), (("M2", 2),)),
    "S6": ((6, 0, 0, 0, 0, 0), ()),
    "M8": ((8, -8, 8, 0, 0, 0), (("M2", 4),)),
}

# Other names for the same constituents, as NOAA and TICON spell them.
ALIASES = {"LAM2": "LAMBDA2", "RHO": "RHO1", "SIG1": "SGM", "SIGMA1": "SGM",
           "EPS2": "EP2"}

# Degrees an hour for each of the six angles, from Meeus's rates.
_RATES = (15.0, 481267.88123421 / _HOURS_PER_CENTURY, 36000.76983 / _HOURS_PER_CENTURY,
          4069.0137287 / _HOURS_PER_CENTURY, 1.71946 / _HOURS_PER_CENTURY)


def canonical(name):
    """The name the table above knows a constituent by, or None."""
    name = name.upper()
    name = ALIASES.get(name, name)
    return name if name in CONSTITUENTS else None


def speed(name):
    """A constituent's speed in degrees an hour."""
    coeffs = CONSTITUENTS[name][0]
    return sum(c * r for c, r in zip(coeffs, _RATES))


def _astro(t):
    """(T, s, h, p, N, p1) in degrees at the UTC instant *t*."""
    jd = t.timestamp() / 86400.0 + 2440587.5
    c = (jd - _J2000) / 36525.0
    s = 218.3164477 + 481267.88123421 * c - 0.0015786 * c * c
    h = 280.46646 + 36000.76983 * c + 0.0003032 * c * c
    p = 83.3532465 + 4069.0137287 * c - 0.0103200 * c * c
    n = 125.04452 - 1934.136261 * c + 0.0020708 * c * c
    p1 = 282.93735 + 1.71946 * c + 0.00046 * c * c
    ut_hours = ((jd + 0.5) % 1.0) * 24.0
    return 180.0 + 15.0 * ut_hours, s, h, p, n, p1


def _nodal(n_deg, p_deg):
    """The basic nodal factors as {name: (f, u in degrees)}.

    Schureman's formulas: I is the inclination of the Moon's orbit to
    the equator, which the node swings between 18.3° and 28.6°, and ν, ξ,
    ν′ and 2ν″ are the angles it drags the constituents' arguments by.
    """
    n = math.radians(n_deg)
    i = math.acos(0.913694997 - 0.035692561 * math.cos(n))
    nu = math.asin(0.08968 * math.sin(n) / math.sin(i))
    xi = n - 2 * math.atan(0.64412 * math.tan(n / 2)) - nu
    sin_i, sin_2i = math.sin(i), math.sin(2 * i)
    nu1 = math.atan(sin_2i * math.sin(nu) / (sin_2i * math.cos(nu) + 0.3347))
    nu2 = math.atan(sin_i ** 2 * math.sin(2 * nu)
                    / (sin_i ** 2 * math.cos(2 * nu) + 0.0727)) / 2
    cos_half = math.cos(i / 2)
    f_m2 = cos_half ** 4 / 0.9154
    u_m2 = 2 * xi - 2 * nu
    # L2 also turns with the perigee (Schureman 213-215).
    big_p = math.radians(p_deg) - xi
    tan2 = math.tan(i / 2) ** 2
    inv_ra = math.sqrt(1 - 12 * tan2 * math.cos(2 * big_p) + 36 * tan2 * tan2)
    r = math.atan(math.sin(2 * big_p) / (1 / (6 * tan2) - math.cos(2 * big_p)))
    d = math.degrees
    return {
        "M2": (f_m2, d(u_m2)),
        "O1": (sin_i * cos_half ** 2 / 0.3800, d(2 * xi - nu)),
        "K1": (math.sqrt(0.8965 * sin_2i ** 2 + 0.6001 * sin_2i * math.cos(nu) + 0.1006),
               d(-nu1)),
        "K2": (math.sqrt(19.0444 * sin_i ** 4 + 2.7702 * sin_i ** 2 * math.cos(2 * nu)
                         + 0.0981), d(-2 * nu2)),
        "J1": (sin_2i / 0.7214, d(-nu)),
        "OO1": (sin_i * math.sin(i / 2) ** 2 / 0.01640, d(-2 * xi - nu)),
        "Mm": ((2 / 3 - sin_i ** 2) / 0.5021, 0.0),
        "Mf": (sin_i ** 2 / 0.1578, d(-2 * xi)),
        "L2": (f_m2 * inv_ra, d(u_m2 - r)),
    }


@lru_cache(maxsize=64)
def _year_nodal(year):
    """The basic nodal factors for *year*, taken at its middle.

    They drift over the 18.6-year cycle by a few percent a year at most,
    so one set serves the year; NOAA's tables are computed the same way.
    """
    _t, _s, _h, p, n, _p1 = _astro(datetime(year, 7, 2, tzinfo=UTC))
    return _nodal(n % 360, p % 360)


def _day_arguments(day_start, names):
    """[(f, V + u in degrees)] for *names* at the UTC instant *day_start*."""
    t, s, h, p, _n, p1 = _astro(day_start)
    basic = _year_nodal(day_start.year)
    out = []
    for name in names:
        (a, b, c, e, g, k), recipe = CONSTITUENTS[name]
        v = a * t + b * s + c * h + e * p + g * p1 + k
        f, u = 1.0, 0.0
        for factor, power in recipe:
            ff, uu = basic[factor]
            f *= ff ** abs(power)
            u += power * uu
        out.append((f, v + u))
    return out


def _utc(t):
    return t.replace(tzinfo=UTC) if t.tzinfo is None else t.astimezone(UTC)


def _midnight(t):
    return t.replace(hour=0, minute=0, second=0, microsecond=0)


class Tide:
    """A station's tide: its constants and the mean level they swing about.

    *constants* is [(name, amplitude, phase)], names as in CONSTITUENTS
    (or an alias), phases Greenwich lags in degrees; a name the table
    does not know is left out. *z0* is the mean level above whatever
    datum the heights should read from: for a chart, the mean sea level's
    height above chart datum.
    """

    def __init__(self, constants, z0=0.0):
        self.z0 = z0
        self.names, self.amps, self.phases = [], [], []
        for name, amp, phase in constants:
            key = canonical(name)
            if key is not None and amp:
                self.names.append(key)
                self.amps.append(amp)
                self.phases.append(phase)
        self.speeds = [math.radians(speed(n)) for n in self.names]
        self._days = {}

    def constants(self):
        """[(name, amplitude, phase)], as the constructor takes them."""
        return list(zip(self.names, self.amps, self.phases))

    def _terms(self, day_start):
        """[(amplitude, phase at midnight in radians, speed in radians an
        hour)] for the UTC day opening at *day_start*, kept by the day."""
        key = day_start.toordinal()
        terms = self._days.get(key)
        if terms is None:
            args = _day_arguments(day_start, self.names)
            terms = [(f * amp, math.radians(vu - g), w)
                     for (f, vu), amp, g, w in zip(args, self.amps, self.phases, self.speeds)]
            if len(self._days) > 800:
                self._days.clear()
            self._days[key] = terms
        return terms

    def height(self, t):
        """The height at the instant *t* (naive is taken as UTC)."""
        t = _utc(t)
        day = _midnight(t)
        hours = (t - day).total_seconds() / 3600.0
        cos = math.cos
        return self.z0 + sum(a * cos(ph + w * hours) for a, ph, w in self._terms(day))

    def _slopes(self, day, hours):
        """(first, second) derivative in height an hour at *hours* into *day*."""
        d1 = d2 = 0.0
        for a, ph, w in self._terms(day):
            x = ph + w * hours
            d1 -= a * w * math.sin(x)
            d2 -= a * w * w * math.cos(x)
        return d1, d2

    def series(self, start, end, step_minutes=6):
        """[(UTC datetime, height)] from *start* through *end* every
        *step_minutes*, on the step's own grid (00:00, 00:06, …)."""
        start, end = _utc(start), _utc(end)
        step = timedelta(minutes=step_minutes)
        t = _midnight(start)
        t += step * math.ceil((start - t) / step)
        out = []
        cos = math.cos
        while t <= end:
            day = _midnight(t)
            terms = self._terms(day)
            day_end = min(end, day + timedelta(days=1) - timedelta(microseconds=1))
            while t <= day_end:
                hours = (t - day).total_seconds() / 3600.0
                out.append((t, self.z0 + sum(a * cos(ph + w * hours) for a, ph, w in terms)))
                t += step
        return out

    def extremes(self, start, end, stand=0.002):
        """[(UTC datetime, height, "H" or "L")] of the turns between *start*
        and *end*: found on a 20-minute scan, then settled by Newton's
        method on the slope, which the sums give exactly.

        Where a small tide all but stops, it can turn and turn back within
        a millimetre or two; a high and a low closer than *stand* (in the
        amplitudes' unit: 2 mm for metres) are one stand of the water, not
        two tides, and are left out. NOAA's tables keep pairs 3 mm apart
        and drop most closer than that, and at 2 mm Pensacola's 2026 turns
        match theirs one for one.
        """
        start, end = _utc(start), _utc(end)
        points = self.series(start - timedelta(minutes=20), end + timedelta(minutes=20), 20)
        out = []
        for (_t0, a), (t1, b), (_t2, c) in zip(points, points[1:], points[2:]):
            if b > a and b >= c:
                kind = "H"
            elif b < a and b <= c:
                kind = "L"
            else:
                continue
            denom = a - 2 * b + c
            t = t1 + timedelta(minutes=20) * (0.5 * (a - c) / denom if denom else 0.0)
            for _ in range(4):
                day = _midnight(t)
                hours = (t - day).total_seconds() / 3600.0
                d1, d2 = self._slopes(day, hours)
                if not d2:
                    break
                shift = -d1 / d2
                if abs(shift) > 0.5:
                    break  # a flat stand; the scan's own estimate will do
                t += timedelta(hours=shift)
                if abs(shift) < 1e-4:
                    break
            if abs((t - t1).total_seconds()) > 1200:
                t = t1
            if start <= t <= end:
                out.append((t, self.height(t), kind))
        return _without_stands(out, stand)


def _without_stands(turns, stand):
    """*turns* less each neighbouring high and low closer than *stand*,
    the closest pair first, so the highs and lows still alternate."""
    turns = list(turns)
    while len(turns) > 1:
        gaps = [(abs(a[1] - b[1]), i) for i, (a, b) in enumerate(zip(turns, turns[1:]))]
        gap, i = min(gaps)
        if gap >= stand:
            break
        # A pair in the middle goes whole; at either end only the pair's
        # outer turn, since its partner beyond the window is unseen.
        if 0 < i < len(turns) - 2:
            del turns[i:i + 2]
        elif i == 0:
            del turns[0]
        else:
            del turns[-1]
    return turns


def fit(samples, names, z0=None):
    """The Tide whose constants best explain *samples* by least squares.

    *samples* is [(datetime, height)], naive times taken as UTC; *names*
    the constituents to solve for. A year of hourly heights separates
    every pair here but S2 from T2 and R2, and K1 from S1, so leave those
    out of a fit that short. The mean level is solved for too, unless
    *z0* fixes it.

    The normal equations are built a column at a time, so the long sums
    run as products of whole lists rather than one sample at a time: a
    year of hours and thirty constituents takes about a second.
    """
    names = [canonical(n) for n in names if canonical(n)]
    speeds = [math.radians(speed(n)) for n in names]
    columns = [[] for _ in range(2 * len(names))]
    heights = []
    days = {}
    cos, sin = math.cos, math.sin
    for t, y in samples:
        t = _utc(t)
        day = _midnight(t)
        args = days.get(day)
        if args is None:
            args = days[day] = [(f, math.radians(vu)) for f, vu in _day_arguments(day, names)]
        hours = (t - day).total_seconds() / 3600.0
        for k, ((f, vu), w) in enumerate(zip(args, speeds)):
            x = vu + w * hours
            columns[2 * k].append(f * cos(x))
            columns[2 * k + 1].append(f * sin(x))
        heights.append(y if z0 is None else y - z0)
    if z0 is None:
        columns.insert(0, [1.0] * len(heights))
    dot = getattr(math, "sumprod", None) or (lambda a, b: sum(map(operator.mul, a, b)))
    width = len(columns)
    normal = [[0.0] * width for _ in range(width)]
    for i in range(width):
        for j in range(i, width):
            normal[i][j] = normal[j][i] = dot(columns[i], columns[j])
    x = _solve(normal, [dot(c, heights) for c in columns])
    if x is None:
        return None
    mean = z0 if z0 is not None else x[0]
    coeffs = x if z0 is not None else x[1:]
    constants = []
    for k, name in enumerate(names):
        a, b = coeffs[2 * k], coeffs[2 * k + 1]
        constants.append((name, math.hypot(a, b), math.degrees(math.atan2(b, a)) % 360))
    return Tide(constants, z0=mean)


def _solve(matrix, rhs):
    """x for matrix·x = rhs by Gaussian elimination with partial pivoting,
    or None when the system is singular."""
    n = len(rhs)
    m = [row[:] + [rhs[i]] for i, row in enumerate(matrix)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[pivot][col]) < 1e-12:
            return None
        m[col], m[pivot] = m[pivot], m[col]
        top = m[col]
        for r in range(col + 1, n):
            k = m[r][col] / top[col]
            if k:
                row = m[r]
                for j in range(col, n + 1):
                    row[j] -= k * top[j]
    x = [0.0] * n
    for i in reversed(range(n)):
        x[i] = (m[i][n] - sum(m[i][j] * x[j] for j in range(i + 1, n))) / m[i][i]
    return x
