"""The weather's sunrise and sunset are the app's one sunrise, the
ephemeris's, which the sunshine view and the month views give: in the
chart, its Today row, the narrative and --json."""

import copy
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from linecast.astro.ephemeris import sunrise_sunset
from linecast.weather import forecast

FIXTURE = Path(__file__).parent / "fixtures" / "open_meteo_forecast.json"
TORONTO = (43.70, -79.40)


def _runtime():
    from linecast._runtime import WeatherRuntime
    return WeatherRuntime(live=False, icons="plain", lang="en", oneline=False,
                          celsius=False, metric=False)


def _fetched(monkeypatch, raw, lat_lng=TORONTO):
    """fetch_forecast's answer for *raw*, as Open-Meteo sent it."""
    monkeypatch.setattr(forecast, "fetch_json_cached",
                        lambda *_a, **_kw: copy.deepcopy(raw))
    return forecast.fetch_forecast(*lat_lng, _runtime())


def _toronto(monkeypatch):
    return _fetched(monkeypatch, json.loads(FIXTURE.read_text(encoding="utf-8")))


def test_the_forecast_asks_open_meteo_for_no_sunrise(monkeypatch):
    asked = []
    monkeypatch.setattr(forecast, "fetch_json_cached",
                        lambda _path, _age, url, **_kw: asked.append(url))
    forecast.fetch_forecast(*TORONTO, _runtime())
    assert "sunrise" not in asked[0] and "sunset" not in asked[0]


def test_each_day_carries_the_ephemeris_sunrise_and_sunset(monkeypatch):
    daily = _toronto(monkeypatch)["daily"]
    zone = ZoneInfo("America/Toronto")
    for i, text in enumerate(daily["time"]):
        rise, sset = sunrise_sunset(date.fromisoformat(text), *TORONTO, zone)
        assert daily["sunrise"][i] == rise.strftime("%Y-%m-%dT%H:%M")
        assert daily["sunset"][i] == sset.strftime("%Y-%m-%dT%H:%M")
    # Open-Meteo's own said 06:46; the sunshine view says 06:47.
    assert daily["sunrise"][1] == "2026-03-05T06:47"


def test_the_clock_change_is_read_on_the_wall_clock(monkeypatch):
    # The fixture is stamped in EST throughout; on 8 March the clocks
    # go forward, and the sunrise is 7:42 EDT, as the hours beside it.
    data = _toronto(monkeypatch)
    i = data["daily"]["time"].index("2026-03-08")
    assert data["daily"]["sunrise"][i] == "2026-03-08T07:42"
    assert "2026-03-08T03:00" in data["hourly"]["time"]
    assert "2026-03-08T02:00" not in data["hourly"]["time"]


def test_the_json_gives_the_apps_sunrise(monkeypatch):
    from linecast.weather.json import build_payload
    payload = build_payload(_toronto(monkeypatch), "Toronto", "CA", _runtime(),
                            now=datetime(2026, 3, 5, 14, 30))
    assert payload["today"]["sunrise"] == "2026-03-05T06:47"
    assert payload["daily"][0]["sunrise"] == "2026-03-05T06:47"


def test_the_narrative_reads_the_apps_sunrise(monkeypatch):
    # Open-Meteo put sunrise at 06:46; at 06:46:30 the Sun is not up yet.
    from linecast.weather.narrative import _is_daylight
    daily = _toronto(monkeypatch)["daily"]
    assert not _is_daylight(daily, datetime(2026, 3, 5, 6, 46, 30))
    assert _is_daylight(daily, datetime(2026, 3, 5, 6, 47, 30))


def test_polar_night_and_the_midnight_sun(monkeypatch):
    first = date(2026, 6, 20)
    days = [(first + timedelta(days=k)).isoformat() for k in range(3)]
    raw = {"timezone": "Arctic/Longyearbyen", "utc_offset_seconds": 7200,
           "daily": {"time": days}}
    daily = _fetched(monkeypatch, raw, (78.22, 15.65))["daily"]
    assert daily["sunrise"] == ["2026-06-20T00:00", "2026-06-21T00:00", "2026-06-22T00:00"]
    assert daily["sunset"] == ["2026-06-21T00:00", "2026-06-22T00:00", "2026-06-23T00:00"]
    raw["daily"]["time"] = ["2026-12-21"]
    raw["utc_offset_seconds"] = 3600
    daily = _fetched(monkeypatch, raw, (78.22, 15.65))["daily"]
    assert daily["sunrise"] == [None] and daily["sunset"] == [None]
    assert forecast.sun_of_day(daily, 0) == (None, None)


def test_a_zone_the_machine_does_not_know_is_read_on_the_stamped_offset(monkeypatch):
    raw = {"timezone": "Nowhere/Atlantis", "utc_offset_seconds": -18000,
           "daily": {"time": ["2026-03-05"]}}
    daily = _fetched(monkeypatch, raw)["daily"]
    assert daily["sunrise"] == ["2026-03-05T06:47"]
