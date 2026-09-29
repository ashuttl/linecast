"""The weather alerts: fetch_alerts, ALERT_FEEDS, which routes a country
to the service that issues its alerts, and what every service's alerts
pass through on the way out -- the expiry, the order, the cut, and the
note of how the answer came. Each service is a module of its own here,
imported when its country is first asked for; cap.py holds what the
services that send CAP files share."""

from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, NamedTuple

from linecast._cache import is_fresh
from linecast._http import fetch_json_cached
from linecast._i18n import base_language
from linecast._plaintext import plain_text
from linecast._timefmt import from_iso

# Alerts past this many are cut, gravest first. Enough for a bad day on
# one point -- a hurricane's watch, warning, surge, and flood advisories
# fit -- and few enough that a feed gone wrong stays a band, not a wall.
MAX_ALERTS = 8

_SEVERITY_RANK = {"Extreme": 0, "Severe": 1, "Moderate": 2, "Minor": 3}

# How long a feed's alerts are kept before the provider is asked again.
_ALERT_MAX_AGE = 900

# How a fetch_alerts answer came to be (issue #122). An empty list is
# either a service saying nothing is in force or a service that could
# not be asked, and the reader must be able to tell the two apart.
ALERTS_OK = "ok"                    # the provider answered, now or within its cache time
ALERTS_STALE = "stale"              # it did not; an older copy stands in
ALERTS_UNAVAILABLE = "unavailable"  # it did not, and there is no copy
ALERTS_UNSUPPORTED = "unsupported"  # linecast has no feed for the country


class AlertList(list):
    """The alerts, a list like any other, carrying how they were got.

    `status` is one of the ALERTS_* values; `fetched_at` is when the
    provider last answered, ISO 8601 in UTC, or None when that is not
    known. A caller that only wants the alerts can ignore both.
    """

    def __init__(self, alerts=(), status=ALERTS_OK, fetched_at=None):
        super().__init__(alerts)
        self.status = status
        self.fetched_at = fetched_at


def alerts_status(alerts) -> dict[str, Any]:
    """The status of a fetch_alerts answer, as `--json` gives it. A
    plain list, from before there was a status, reads as a good one."""
    return {
        "status": getattr(alerts, "status", ALERTS_OK),
        "fetched_at": getattr(alerts, "fetched_at", None),
    }


# The record the provider in hand leaves for fetch_alerts, by thread:
# the dashboard fetches the alerts on a worker of its own.
_ALERT_CHECK: "ContextVar[dict[str, Any] | None]" = ContextVar(
    "linecast_alert_check", default=None)


def _utc_iso(timestamp):
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat(timespec="seconds")


def _note_alert_cache(cache_file, max_age, answered):
    """Record how a provider's feed came, for fetch_alerts to report.

    Called just after the feed's cached fetch. The cache file's age says
    it: a fetch that succeeds writes the file, so a file within
    `max_age` is an answer from the provider, now or lately; an older
    one is the stale copy the fetch stood in with; no file is a failure
    with nothing to stand in, unless the provider `answered` and only
    the cache could not be written.
    """
    check = _ALERT_CHECK.get()
    if check is None:
        return
    try:
        mtime = cache_file.stat().st_mtime
    except OSError:
        mtime = None
    if mtime is None:
        if not answered:
            check.update(status=ALERTS_UNAVAILABLE, fetched_at=None)
        else:
            check.update(status=ALERTS_OK,
                         fetched_at=_utc_iso(datetime.now(timezone.utc).timestamp()))
    elif is_fresh(mtime, max_age):
        check.update(status=ALERTS_OK, fetched_at=_utc_iso(mtime))
    else:
        check.update(status=ALERTS_STALE, fetched_at=_utc_iso(mtime))


def _cached_feed(cache_file, url, parse, max_age=_ALERT_MAX_AGE, **kwargs):
    """A feed's alerts, fetched, parsed and cached, with how they came
    noted for fetch_alerts.

    `parse` turns the feed's answer into normalized alerts, and only
    they are cached, so a copy read back, fresh or stale, is alerts. A
    parse that raises is a failed fetch: the stale copy stands in, or
    nothing. The other arguments go to fetch_json_cached.
    """
    answered = False

    def transform(data):
        nonlocal answered
        alerts = parse(data)
        answered = True
        return alerts

    alerts = fetch_json_cached(cache_file, max_age, url, fallback=[],
                               transform=transform, provider="weather/alerts", **kwargs)
    _note_alert_cache(cache_file, max_age, answered)
    # A file from before the feeds were parsed on the way in can hold a
    # feed's own payload, left behind where parsing it failed.
    return alerts if isinstance(alerts, list) else []


def fetch_alerts(lat: float, lng: float, country_code: str = "", lang: str = "en",
                 address: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Fetch active weather alerts from the appropriate provider.

    Routes to the best available source for each country, then keeps
    the board readable: the gravest alerts first, and no more than
    MAX_ALERTS of them. A feed that files one warning per county can
    land hundreds on a single point (issue #57); past a handful, the
    pills stop informing and start papering the screen.

    An alert past its own expiry is dropped here, whatever its source.
    Each provider caches its list for fifteen minutes, and a stale copy
    stands in for as long as the provider is unreachable, so without
    this a wind advisory fetched on Tuesday could still be listed on
    Thursday (issue #70).

    The answer is an AlertList, which says besides whether the provider
    answered, a stale copy stood in, or neither (issue #122): an empty
    list alone cannot tell "no warnings" from "could not check".
    """
    feed = ALERT_FEEDS.get((country_code or "").upper())
    if feed is None:
        return AlertList(status=ALERTS_UNSUPPORTED)
    check = {"status": ALERTS_OK, "fetched_at": None}
    token = _ALERT_CHECK.set(check)
    try:
        alerts = feed.fetch(lat, lng, lang, address)
    finally:
        _ALERT_CHECK.reset(token)
    return AlertList(_trim_alerts(_drop_expired(alerts)), **check)


def _alert_expiry(alert):
    """When a normalized alert lapses, as an aware UTC datetime, or None
    when it does not say.

    Providers write the expiry as ISO 8601 with an offset, or with a
    trailing Z, which fromisoformat reads only from Python 3.11. A time
    with no offset is taken as UTC: an hour or two out is a far smaller
    error than never expiring.
    """
    expires = alert.get("expires") if isinstance(alert, dict) else None
    if not isinstance(expires, str) or not expires:
        return None
    try:
        dt = from_iso(expires)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _expired(alert, now):
    """Whether an alert has lapsed by `now` (UTC)."""
    expiry = _alert_expiry(alert)
    return expiry is not None and expiry < now


def _drop_expired(alerts, now=None):
    """The alerts still in force at `now` (UTC), or that carry no expiry."""
    if now is None:
        now = datetime.now(timezone.utc)
    return [alert for alert in alerts if not _expired(alert, now)]


def _by_severity(alerts):
    """The gravest first. The sort is stable, so a provider's own order
    holds within a severity; an unknown severity sorts last."""
    return sorted(alerts, key=lambda a: _SEVERITY_RANK.get(a.get("severity"), 9))


def _trim_alerts(alerts):
    """The gravest alerts first, at most MAX_ALERTS of them."""
    return [_plain_alert(alert) for alert in _by_severity(alerts)[:MAX_ALERTS]]


def _plain_alert(alert):
    """An alert with a feed's terminal controls taken out of its text.

    Done here, where every provider's list passes on its way out, so a
    list read back from a provider's cache is cleaned too.  The
    description keeps its line breaks, which mark its paragraphs.
    """
    return {key: plain_text(value, lines=key == "description")
            for key, value in alert.items()}


class AlertFeed(NamedTuple):
    """A country's alert service: its name, the root of the host its
    feed comes from, and the module of alert_feeds that fetches it.

    The name is a proper name, given as the service writes its own:
    `names` has it for the display languages the service has one in, and
    `name` stands for the rest. `slug` names the country's feed at
    MeteoAlarm, which serves 35 countries from one module.
    """

    name: str
    url: str
    module: str
    names: "dict[str, str] | None" = None
    slug: str = ""

    def source(self, lang: str = "en") -> str:
        """The service's name for a reader in `lang`."""
        return (self.names or {}).get(base_language(lang), self.name)

    def fetch(self, lat: float, lng: float, lang: str,
              address: "dict[str, Any] | None") -> list[dict[str, Any]]:
        """The service's alerts for the place. Its module is imported
        here, when first asked: a run asks one service and loads no
        other."""
        from importlib import import_module
        feed = import_module(f"linecast.weather.alert_feeds.{self.module}")
        if self.slug:
            return feed.fetch(lat, lng, lang, address, slug=self.slug)
        return feed.fetch(lat, lng, lang, address)


# ISO 3166-1 alpha-2 -> MeteoAlarm feed slug, for the European countries
# without a service of their own here (DE, NO and IE have one).
_METEOALARM_SLUGS = {
    "AT": "austria", "BE": "belgium", "BA": "bosnia-herzegovina",
    "BG": "bulgaria", "HR": "croatia",
    "CY": "cyprus", "CZ": "czechia", "DK": "denmark", "EE": "estonia",
    "FI": "finland", "FR": "france", "GR": "greece",
    "HU": "hungary", "IS": "iceland", "IL": "israel", "IT": "italy",
    "LV": "latvia", "LT": "lithuania", "LU": "luxembourg", "MT": "malta",
    "MD": "moldova", "ME": "montenegro",
    "NL": "netherlands", "MK": "republic-of-north-macedonia",
    "PL": "poland", "PT": "portugal",
    "RO": "romania", "RS": "serbia", "SK": "slovakia", "SI": "slovenia",
    "ES": "spain", "SE": "sweden", "CH": "switzerland",
    "UA": "ukraine", "GB": "united-kingdom",
}

# Every country linecast has alerts for, with the service that issues
# them: routing, the credit line, and doctor all read it here.
ALERT_FEEDS = {
    "US": AlertFeed("US National Weather Service", "https://api.weather.gov/", "nws"),
    "CA": AlertFeed("Environment Canada", "https://api.weather.gc.ca/", "eccc",
                    {"fr": "Environnement Canada"}),
    "DE": AlertFeed("DWD", "https://api.brightsky.dev/", "dwd",
                    {"de": "Deutscher Wetterdienst"}),
    "NO": AlertFeed("MET Norway", "https://api.met.no/", "metno",
                    {"no": "Meteorologisk institutt"}),
    "IE": AlertFeed("Met Éireann", "https://prodapi.metweb.ie/", "meteireann"),
    "JP": AlertFeed("Japan Meteorological Agency", "https://www.jma.go.jp/", "jma",
                    {"ja": "気象庁"}),
    "HK": AlertFeed("Hong Kong Observatory", "https://data.weather.gov.hk/", "hko",
                    {"zh": "香港天文台", "zh-Hant": "香港天文台"}),
    "CN": AlertFeed("China Meteorological Administration", "http://www.nmc.cn/", "cma",
                    {"zh": "中国气象局", "zh-Hant": "中國氣象局"}),
    "IN": AlertFeed("SACHET", "https://sachet.ndma.gov.in/", "sachet"),
    "NZ": AlertFeed("MetService", "https://alerts.metservice.com/", "metservice"),
    **{code: AlertFeed("MeteoAlarm", "https://feeds.meteoalarm.org/", "meteoalarm", slug=slug)
       for code, slug in _METEOALARM_SLUGS.items()},
}


def alert_source(country_code: str, lang: str = "en") -> str | None:
    """Who issues the alerts shown for a country: its national service,
    MeteoAlarm across the rest of Europe, None where linecast has no feed."""
    feed = ALERT_FEEDS.get((country_code or "").upper())
    return feed.source(lang) if feed else None
