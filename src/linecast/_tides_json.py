"""Machine-readable JSON payload for `tides --json`.

Builds a plain-dict snapshot of tide predictions for external consumers
(e.g. a desktop widget). Heights arrive in feet (the internal unit for all
providers) and are converted per TidesRuntime; times are minute-precision
local ISO strings in station time. A missing station yields a payload with
null/empty fields rather than an error.
"""

from datetime import timedelta

from linecast._sunshine_json import _iso

SCHEMA_VERSION = 1

MAX_EVENTS = 6
SERIES_PAST_HOURS = 6
SERIES_FUTURE_HOURS = 24
SERIES_STEP_MINUTES = 30


def build_payload(station_name, runtime, now_local, predictions, hilo,
                  station_id=None, source=None, tz_name=None, location=None):
    """Build the `tides --json` payload dict from preloaded data.

    predictions: [(dt, height_ft)] sorted; hilo: [(dt, height_ft, "H"|"L")].
    Either may be None/empty — the payload degrades to nulls and [].
    """
    from linecast._tides_render import interp_height

    predictions = predictions or []
    hilo = hilo or []
    convert = runtime.convert_height

    events = []
    for dt, height, typ in sorted(hilo):
        if dt >= now_local and len(events) < MAX_EVENTS:
            events.append({
                "kind": "high" if typ == "H" else "low",
                "time": _iso(dt),
                "height": round(convert(height), 2),
            })

    series = []
    if predictions:
        first, last = predictions[0][0], predictions[-1][0]
        t = now_local - timedelta(hours=SERIES_PAST_HOURS)
        end = now_local + timedelta(hours=SERIES_FUTURE_HOURS)
        step = timedelta(minutes=SERIES_STEP_MINUTES)
        while t <= end:
            if first <= t <= last:
                series.append({
                    "time": _iso(t),
                    "height": round(convert(interp_height(t, predictions)), 2),
                })
            t += step
    now_height = (round(convert(interp_height(now_local, predictions)), 2)
                  if predictions else None)

    return {
        "schema": SCHEMA_VERSION,
        "location": location or station_name or "",
        "timezone": tz_name or None,
        "fetched_at": _iso(now_local),
        "station": station_name or None,
        "units": {"height": "m" if runtime.metric else "ft"},
        "events": events,
        "series": series,
        "now_height": now_height,
        # Extras a widget would want: which provider and station served this.
        "station_id": station_id or None,
        "source": source or None,
    }
