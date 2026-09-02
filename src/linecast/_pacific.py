"""Pacific lunar calendars, from the ephemeris: Hawaiʻi, American
Samoa, and the Mariana Islands.

Each is a count of named nights beginning the evening the young
crescent is first seen, not the night of the new moon itself: thirty
names to a month, the twenty-ninth dropped when a lunation runs only
twenty-nine nights, so the last name always closes the month. Hawaiʻi
groups its nights in three ten-night anahulu — hoʻonui waxing, poepoe
round, hōʻemi waning; the Samoan and CHamoru calendars print their
nights ten to a row as well but name no periods.

The reference for every mapping is the Western Pacific Regional
Fishery Management Council's annual lunar calendars: the Kaulana
Mahina for Hawaiʻi, whose night names follow Clarice Taylor's
Hawaiian Almanac (Oʻahu), and the American Samoa, Guam, and CNMI
editions. Their month starts come from HM Nautical Almanac Office
crescent-visibility data for Honolulu, Pago Pago Harbor, and Hagåtña,
which makes each first night a *visibility* date: no fixed offset
from the conjunction reproduces any of the three tables. Usually the
first night is the civil day after the conjunction's at the
calendar's meridian, but when that evening's crescent geometry is
poor the published month starts a day later still.

So the first night is computed the way the source computes it:
Yallop's q test (NAO Technical Note 69) for the evening sky at each
calendar's own place — arc of vision against crescent width at the
standard "best time", sunset plus four ninths of the moonset lag. The
cutoff is calibrated per calendar, not taken from Yallop's visibility
codes: it is the q that best separates the evenings the printed
tables accept from the ones they pass over.

- Hawaiʻi: 28 months of the 2025 and 2026 editions (Nov 2024 – Feb
  2027). Accepted evenings all score q ≥ −0.060, rejected ones
  q ≤ −0.110; the line sits midway, and every month fits.
- American Samoa: 75 months of the 2021–2026 editions (Jan 2021 – Feb
  2027). The line sits between −0.072 and −0.037, and 72 months fit.
  Three fit no cutoff at all: the printed table passes over the
  evenings of 10 Mar 2024 (q −0.005) and 20 Nov 2025 (−0.009) yet
  accepts 25 Jun 2025 (−0.139), the poorest crescent it ever took.
- Mariana Islands: 75 months of the 2021–2026 Guam and CNMI editions,
  which print the same dates. The line sits between 0.010 and 0.048,
  and 70 months fit. Five fit no cutoff: evenings passed over at
  q 0.092–0.103 (Oct 2021, Jan and Jun 2024) and accepted at 0.003
  and −0.041 (Aug 2023, Dec 2024).

Every month of the 2026 editions fits, so the calendar shown agrees
with the one on the wall now. A new edition's months belong in
tests/test_pacific.py; if one disagrees, the cutoff is what to
recalibrate, and the departures listed there are what to check first.
"""

import math
from datetime import timedelta
from functools import lru_cache
from typing import NamedTuple

from linecast._ephemeris import (
    _angular_separation,
    _gmst_deg,
    _moon_altitude_deg,
    _moon_distance_er,
    _moon_ra_dec,
    _norm_deg,
    _sun_ra_dec,
    next_moon_phase_utc,
)
from linecast._lunisolar import _civil, _day_start_utc


class _Observer(NamedTuple):
    lat: float
    lng: float
    meridian_hours: int
    q_first_visible: float          # calibrated; see the module docstring


CALENDARS = {
    # Honolulu; the published tables are Oʻahu's.
    "hawaiian": _Observer(21.31, -157.86, -10, -0.085),
    # Pago Pago Harbor.
    "samoan": _Observer(-14.28, -170.69, -11, -0.054),
    # Hagåtña. The CNMI edition gives its phases for Garapan but prints
    # the same month starts as Guam's, so both read this table.
    "chamorro": _Observer(13.475, 144.75, 10, 0.029),
}
# The CNMI edition: the CHamoru nights with their Refaluwasch names.
CALENDARS["refaluwasch"] = CALENDARS["chamorro"]
PACIFIC_CALENDARS = tuple(CALENDARS)


def _sun_alt_az_deg(dt_utc, obs):
    """Sun altitude and azimuth at the observer, by the Moon's formulas."""
    ra, dec = _sun_ra_dec(dt_utc)
    lst = _norm_deg(_gmst_deg(dt_utc) + obs.lng)
    hour_angle = math.radians((lst - ra + 540.0) % 360.0 - 180.0)
    lat, dec_r = math.radians(obs.lat), math.radians(dec)
    sin_alt = (math.sin(lat) * math.sin(dec_r)
               + math.cos(lat) * math.cos(dec_r) * math.cos(hour_angle))
    alt = math.degrees(math.asin(max(-1.0, min(1.0, sin_alt))))
    az = math.atan2(
        math.sin(hour_angle),
        math.cos(hour_angle) * math.sin(lat) - math.tan(dec_r) * math.cos(lat),
    )
    return alt, (math.degrees(az) + 180.0) % 360.0


def _setting_instant(t_lo, t_hi, alt_of, horizon):
    """Where a sinking altitude crosses *horizon*, by bisection."""
    for _ in range(24):
        mid = t_lo + (t_hi - t_lo) / 2
        if alt_of(mid) > horizon:
            t_lo = mid
        else:
            t_hi = mid
    return t_lo


def _crescent_q(evening, obs):
    """Yallop's q for the young crescent on *evening*, or None if set.

    Topocentric arc of vision (geocentric altitudes less the Moon's
    parallax) against topocentric crescent width, evaluated at best
    time. The Moon within a couple of days of new is what this is
    for; the polynomial is Yallop's own.
    """
    dusk = _day_start_utc(evening, obs.meridian_hours) + timedelta(hours=16)
    sunset = _setting_instant(dusk, dusk + timedelta(hours=5),
                              lambda t: _sun_alt_az_deg(t, obs)[0], -0.833)

    def moon_alt(t):
        return _moon_altitude_deg(t, obs.lat, obs.lng)

    # The same effective horizon moonrise/set uses elsewhere in the app.
    if moon_alt(sunset) <= 0.125:
        return None                      # sets before the sun: no crescent
    moonset = _setting_instant(sunset, sunset + timedelta(hours=6),
                               moon_alt, 0.125)
    best = sunset + (moonset - sunset) * 4 / 9

    parallax = math.degrees(math.asin(1.0 / _moon_distance_er(best)))
    alt = moon_alt(best)
    arcv = (alt - parallax * math.cos(math.radians(alt))
            - _sun_alt_az_deg(best, obs)[0])
    moon_ra, moon_dec = _moon_ra_dec(best)
    arcl = _angular_separation(moon_ra, moon_dec, *_sun_ra_dec(best))
    width = 60.0 * 0.27245 * parallax * (1.0 - math.cos(math.radians(arcl)))
    return (arcv - (11.8371 - 6.3226 * width + 0.7319 * width ** 2
                    - 0.1018 * width ** 3)) / 10.0


def _first_night(conj_utc, obs):
    """The civil date of the first night of the month begun at *conj_utc*."""
    day = _civil(conj_utc, obs.meridian_hours) + timedelta(days=1)
    for _ in range(2):
        q = _crescent_q(day, obs)
        if q is not None and q > obs.q_first_visible:
            return day
        day += timedelta(days=1)
    return day       # two evenings on the crescent is beyond doubt


@lru_cache(maxsize=512)
def pacific_night(cal, local_date):
    """(night, nights in the month) for a Gregorian date, both 1-based.

    The mapping is fixed by the calendar's own meridian: a user
    anywhere looks their own civil date up in it, which is what the
    printed calendar's readers do.
    """
    obs = CALENDARS[cal]
    conj = next_moon_phase_utc(_day_start_utc(local_date, obs.meridian_hours),
                               0.0, backwards=True)
    start = _first_night(conj, obs)
    if start > local_date:
        # The tail of the old month: its last night, or the extra dark
        # night before a late first crescent.
        nxt = conj
        conj = next_moon_phase_utc(conj - timedelta(days=2), 0.0,
                                   backwards=True)
        start = _first_night(conj, obs)
    else:
        nxt = next_moon_phase_utc(conj + timedelta(days=1), 0.0)
    return (local_date - start).days + 1, (_first_night(nxt, obs) - start).days


def hawaiian_night(local_date):
    """(night, nights in the month) by the Kaulana Mahina."""
    return pacific_night("hawaiian", local_date)


# ---------------------------------------------------------------------------
# The practice layer, shown with the calendar: fishing counsel quoted
# from the Council's educational display "Hawaiian Moon Phases and
# Traditional Natural Resource Management" (WPRFMC, NOAA-funded) —
# the same source the UH Climate Data Portal cites for its guidance.
# The Council's own words, lightly compressed, never paraphrased into
# new claims. Permission to carry this layer is asked but not yet
# answered (issue #46, scope B); it ships nowhere until it is.
# ---------------------------------------------------------------------------

COUNSEL_ATTRIBUTION = "Western Pacific Regional Fishery Management Council"
# The on-screen attribution names the domain: the live view owns the
# mouse for scrubbing, so no terminal can offer link hover or click
# there — the text carries the address on its own. The URL itself
# goes out only in the JSON, as data.
COUNSEL_SOURCE_LINE = "Source: wpcouncil.org"
COUNSEL_URL = "https://www.wpcouncil.org/educational-resources/lunar-calendars/"

# Per-anahulu fishing counsel, keyed by the anahulu names in
# _moon_i18n. Each line leads with the anahulu it speaks for, so it
# reads as the tradition's counsel and not as a weather forecast.
ANAHULU_COUNSEL = {
    "hoʻonui": ("Hoʻonui nights — good lamalama (torching) and net "
                "fishing in the first half; poor fishing the rest"),
    "poepoe": ("Poepoe nights — fair to good fishing, near shore "
               "and deep sea"),
    "hōʻemi": ("Hōʻemi nights — poor fishing in the first half; the "
               "second half good at night and in the deep sea"),
}

# Nights the display marks specially: the four monthly kapu (sacred)
# periods, drawn there over these exact nights, and the unproductive
# ʻOle runs — both runs, so the repeated names collapse to one entry.
_KU = "Kapu Kū — spent at temple; no planting or fishing"
_OLE = "ʻOle night — low fishing productivity"
_HUA = "Kapu Hua — a sacred period"
_KALOA = "Kapu Kāloa — certain crops planted, certain kinds of fishing"
_NIGHT_NOTES = {
    "Hilo": _KU, "Hoaka": _KU, "Kūkahi": _KU, "Kūlua": _KU,
    "ʻOlekūkahi": _OLE, "ʻOlekūlua": _OLE,
    "ʻOlekūkolu": _OLE, "ʻOlepau": _OLE,
    "Mōhalu": _HUA, "Hua": _HUA,
    "Kāloakūkahi": _KALOA, "Kāloakūlua": _KALOA,
    "Kāne": "Kapu Kāne — fishing and planting restricted",
    "Lono": "Kapu Kāne — prayers and offerings to Lono",
}


def night_note(po_name):
    """The display's kapu or ʻole note for a named night, or None."""
    return _NIGHT_NOTES.get(po_name)
