"""A provider's answer with a null where a list or an object belongs.

Every tide provider method is asked with every field it reads set to
null, and none may raise: a null is read as nothing there, as a missing
field is. The answers come from _http.fetch_json, with the cache out of
the way.
"""

import json
from datetime import date

import pytest

from linecast import _http
from linecast.tides import chs, common, marine, noaa, openmeteo, qld, tidecheck
from linecast.tides.providers import PROVIDERS

NULLS = {"predictions": None, "data": None, "features": None, "extremes": None,
         "hourly": None, "stations": None, "result": None, "records": None,
         "metadata": None, "station": None}
NESTED = {"result": {"results": None, "records": None}, "hourly": {"time": None},
          "stations": [{"details": None, "id": "1"}]}
IDS = {"noaa": "8418150", "chs": "5cebf1de3d0f4a073c4bbd1e", "qld": "Brisbane Bar",
       "hko": "QUB", "tidecheck": "portland-maine", "openmeteo": "om:43.6,-70.2"}
D0, D1 = date(2026, 9, 27), date(2026, 9, 29)
CALLS = (("station_metadata", lambda sid: (sid,)),
         ("tides_range", lambda sid: (sid, D0, D1, None)),
         ("hilo_range", lambda sid: (sid, D0, D1, None)),
         ("y_range", lambda sid: (sid, D0, None)),
         ("nearest", lambda sid: (43.6, -70.2)),
         ("search", lambda sid: ("portland", ["portland"])))


@pytest.fixture
def answering(monkeypatch):
    """Every fetch answers the payload the test sets, and no cache is read."""
    answer = {}

    def fetch_json(*args, **kwargs):
        return json.loads(json.dumps(answer["payload"]))

    monkeypatch.setenv("LINECAST_TIDECHECK_KEY", "k")
    monkeypatch.setenv("LINECAST_TIDECHECK_PAID", "1")
    for module in (_http, chs, noaa, qld, tidecheck, openmeteo, marine):
        if hasattr(module, "fetch_json"):
            monkeypatch.setattr(module, "fetch_json", fetch_json)
    for module in (_http, common, qld, tidecheck):
        for name in ("read_cache", "read_stale"):
            if hasattr(module, name):
                monkeypatch.setattr(module, name, lambda *a, **k: None)
    monkeypatch.setattr(_http, "write_cache", lambda *a, **k: None)
    monkeypatch.setattr(noaa, "_stations_memo", None)
    return answer


@pytest.mark.parametrize("payload", [NULLS, NESTED], ids=["nulls", "nested-nulls"])
@pytest.mark.parametrize("method, args", CALLS, ids=[c[0] for c in CALLS])
@pytest.mark.parametrize("provider", sorted(PROVIDERS))
def test_a_null_is_read_as_nothing(answering, provider, method, args, payload):
    answering["payload"] = payload
    try:
        getattr(PROVIDERS[provider], method)(*args(IDS[provider]))
    except NotImplementedError:
        pass


@pytest.mark.parametrize("payload", [NULLS, NESTED], ids=["nulls", "nested-nulls"])
def test_the_marine_line_reads_a_null_as_nothing(answering, payload):
    answering["payload"] = payload
    assert marine.parse_marine_current(marine.fetch_marine(43.6, -70.2)) is None
