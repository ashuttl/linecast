"""Whose weather it is: the credit lines for the forecast, the sky and
the alerts."""

from datetime import datetime, timezone

from linecast.weather.alert_feeds import alert_source
from linecast.weather.forecast import FORECAST_SOURCE
from linecast.weather.observed import OBSERVATION_SOURCE

# The forecast, the air quality, and the geocoder are Open-Meteo's, and
# its CC BY 4.0 terms ask for a line on screen. The alerts are the
# national services', and alert_feeds.ALERT_FEEDS says whose; the phrase
# around a service's name is translated, and the name is its own.
ATTRIBUTION = "Weather data by Open-Meteo"


def forecast_attribution(lang: str = "en") -> str:
    """The forecast credit in the display language."""
    from linecast.weather.i18n import _STRINGS
    from linecast._i18n import lookup
    return lookup(_STRINGS, "credit_forecast", lang, source=FORECAST_SOURCE)


def observation_source(station: str = "") -> str:
    """The current conditions' source, with the station whose report it
    is by its ICAO code: the one name for it that reads the same in
    every language, where the station names the reports carry are
    clipped, and in English."""
    return f"{OBSERVATION_SOURCE} ({station})" if station else OBSERVATION_SOURCE


def observation_attribution(lang: str = "en", station: str = "") -> str:
    """The current conditions credit in the display language."""
    from linecast.weather.i18n import _STRINGS
    from linecast._i18n import lookup
    return lookup(_STRINGS, "credit_current", lang, source=observation_source(station))


def observed_credit(observed, lang="en", metric=False, use_24h=False, tz_name="",
                    named=True):
    """Where and when the current sky was seen: "Observed at 7:51a from
    Portland Intl Jetport, 4 mi away". The station goes by the name its
    report gives, clipped before the state and country, or by its ICAO
    code where `named` is false or there is no name. None without a
    report. The place stays in English, as the reports write it."""
    from linecast.weather.i18n import _STRINGS
    from linecast._timefmt import fmt_time_dt
    from linecast._i18n import lookup
    if not observed or not observed.get("station"):
        return None
    name = (observed.get("name") or "").split(",")[0].strip()
    km = observed.get("distance_km") or 0
    place = name if named and name else observed["station"]
    n = max(1, round(km)) if metric else max(1, round(km / 1.609344))
    far = f"{n} {lookup(_STRINGS, 'unit_km' if metric else 'unit_mi', lang)}"
    seen = datetime.fromtimestamp(observed.get("time") or 0, timezone.utc)
    try:
        from zoneinfo import ZoneInfo
        seen = seen.astimezone(ZoneInfo(tz_name)) if tz_name else seen.astimezone()
    except Exception:
        seen = seen.astimezone()
    return lookup(_STRINGS, "credit_observed", lang, time=fmt_time_dt(seen, use_24h),
                  place=place, distance=far)


def alert_attribution(country_code: str, lang: str = "en") -> str | None:
    """The alerts credit in the display language, or None where none
    are fetched."""
    from linecast.weather.i18n import _STRINGS
    from linecast._i18n import lookup
    source = alert_source(country_code, lang)
    return lookup(_STRINGS, "credit_alerts", lang, source=source) if source else None


