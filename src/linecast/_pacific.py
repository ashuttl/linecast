"""The Hawaiian lunar calendar (Kaulana Mahina), from the ephemeris.

The month is a count of nights beginning at Hilo, the night the young
crescent is first seen, not the night of the new moon itself: thirty
named nights (pō mahina) in three ten-night anahulu — hoʻonui waxing,
poepoe round, hōʻemi waning — with Mauli dropped when a lunation runs
only twenty-nine nights, so Muku always closes the month.

The reference for the mapping is the Western Pacific Regional Fishery
Management Council's annual Kaulana Mahina, whose night names follow
Clarice Taylor's Hawaiian Almanac (Oʻahu) and whose month starts come
from HM Nautical Almanac Office crescent-visibility data. That makes
Hilo a *visibility* date, and no fixed offset from the conjunction
reproduces it: usually Hilo is the civil day after the conjunction's
(at UTC−10), but when that evening's crescent geometry is poor the
published month starts a day later still.

So Hilo is computed the way the source computes it: Yallop's q test
(NAO Technical Note 69) for the evening sky at Honolulu — arc of
vision against crescent width at the standard "best time", sunset
plus four ninths of the moonset lag. The cutoff is calibrated, not
taken from Yallop's visibility codes: against every month of the 2025
and 2026 editions — 28 month starts, Nov 2024 through Feb 2027 — the
evenings the published table accepts all score q ≥ −0.060 by this
implementation and the ones it passes over all score q ≤ −0.110, so
the line sits midway, and moving Hilo by a day would take a q error
of 0.025 on the nearest month. A new edition's months belong in
tests/test_pacific.py; if one disagrees, the cutoff is what to
recalibrate.
"""

import math
from datetime import timedelta
from functools import lru_cache

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

MERIDIAN_HOURS = -10
_LAT, _LNG = 21.31, -157.86      # Honolulu; the published tables are Oʻahu's
_Q_FIRST_VISIBLE = -0.085        # calibrated; see the module docstring


def _sun_alt_az_deg(dt_utc):
    """Sun altitude and azimuth at Honolulu, by the Moon's formulas."""
    ra, dec = _sun_ra_dec(dt_utc)
    lst = _norm_deg(_gmst_deg(dt_utc) + _LNG)
    hour_angle = math.radians((lst - ra + 540.0) % 360.0 - 180.0)
    lat, dec_r = math.radians(_LAT), math.radians(dec)
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


def _crescent_q(evening):
    """Yallop's q for the young crescent on *evening*, or None if set.

    Topocentric arc of vision (geocentric altitudes less the Moon's
    parallax) against topocentric crescent width, evaluated at best
    time. The Moon within a couple of days of new is what this is
    for; the polynomial is Yallop's own.
    """
    dusk = _day_start_utc(evening, MERIDIAN_HOURS) + timedelta(hours=16)
    sunset = _setting_instant(dusk, dusk + timedelta(hours=5),
                              lambda t: _sun_alt_az_deg(t)[0], -0.833)

    def moon_alt(t):
        return _moon_altitude_deg(t, _LAT, _LNG)

    # The same effective horizon moonrise/set uses elsewhere in the app.
    if moon_alt(sunset) <= 0.125:
        return None                      # sets before the sun: no crescent
    moonset = _setting_instant(sunset, sunset + timedelta(hours=6),
                               moon_alt, 0.125)
    best = sunset + (moonset - sunset) * 4 / 9

    parallax = math.degrees(math.asin(1.0 / _moon_distance_er(best)))
    alt = moon_alt(best)
    arcv = (alt - parallax * math.cos(math.radians(alt))
            - _sun_alt_az_deg(best)[0])
    moon_ra, moon_dec = _moon_ra_dec(best)
    arcl = _angular_separation(moon_ra, moon_dec, *_sun_ra_dec(best))
    width = 60.0 * 0.27245 * parallax * (1.0 - math.cos(math.radians(arcl)))
    return (arcv - (11.8371 - 6.3226 * width + 0.7319 * width ** 2
                    - 0.1018 * width ** 3)) / 10.0


def _hilo_date(conj_utc):
    """The civil date of Hilo for the month begun at *conj_utc*."""
    day = _civil(conj_utc, MERIDIAN_HOURS) + timedelta(days=1)
    for _ in range(2):
        q = _crescent_q(day)
        if q is not None and q > _Q_FIRST_VISIBLE:
            return day
        day += timedelta(days=1)
    return day       # two evenings on the crescent is beyond doubt


@lru_cache(maxsize=128)
def hawaiian_night(local_date):
    """(night, nights in the month) for a Gregorian date, both 1-based.

    The mapping is fixed by the Hawaiian meridian: a user anywhere
    looks their own civil date up in it, which is what the printed
    calendar's readers do.
    """
    conj = next_moon_phase_utc(_day_start_utc(local_date, MERIDIAN_HOURS),
                               0.0, backwards=True)
    start = _hilo_date(conj)
    if start > local_date:
        # The tail of the old month: its Muku, or the extra dark night
        # before a late Hilo.
        nxt = conj
        conj = next_moon_phase_utc(conj - timedelta(days=2), 0.0,
                                   backwards=True)
        start = _hilo_date(conj)
    else:
        nxt = next_moon_phase_utc(conj + timedelta(days=1), 0.0)
    return (local_date - start).days + 1, (_hilo_date(nxt) - start).days


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
# The on-screen attribution, linking to the lunar calendars
# themselves.
COUNSEL_LINK = ("Source: WPRFMC",
                "https://www.wpcouncil.org/educational-resources/lunar-calendars/")

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
