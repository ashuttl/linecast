"""Canada's humidex and wind chill.

Environment Canada gives these in place of a feels-like temperature, and
Canadians read them as the felt temperature: "Humidex 34", "Wind chill
minus 25".  Both are arithmetic on readings the forecast already has, by
the formulas and reporting rules of the climate glossary
(climate.weather.gc.ca/glossary_e.html):

- The humidex is reported when the air is 20 °C or warmer and the
  humidex is at least a degree above it.
- The wind chill is reported when the air is 0 °C or colder and there
  is wind; below 5 km/h the glossary's light-wind formula applies.  It
  is reported here, as the humidex is, when it is at least a degree
  below the air.

Both are indices on the Celsius scale, so they are attached only for a
reader on Celsius; one on Fahrenheit keeps the forecast's feels-like.
"""

import math

_HUMIDEX_FROM_C = 20
_WIND_CHILL_FROM_C = 0


def humidex(temp_c, dew_point_c):
    """The humidex, or None where Environment Canada would not report one."""
    if temp_c is None or dew_point_c is None or temp_c < _HUMIDEX_FROM_C:
        return None
    vapour = 6.11 * math.exp(5417.7530 * (1 / 273.16 - 1 / (273.15 + dew_point_c)))
    value = temp_c + 0.5555 * (vapour - 10.0)
    return value if value >= temp_c + 1 else None


def wind_chill(temp_c, wind_kmh):
    """The wind chill, or None where Environment Canada would not report one."""
    if temp_c is None or wind_kmh is None or temp_c > _WIND_CHILL_FROM_C or wind_kmh <= 0:
        return None
    if wind_kmh >= 5:
        speed = wind_kmh ** 0.16
        value = 13.12 + 0.6215 * temp_c - 11.37 * speed + 0.3965 * temp_c * speed
    else:
        value = temp_c + (-1.59 + 0.1345 * temp_c) / 5 * wind_kmh
    return value if value <= temp_c - 1 else None


def apply_canadian_indices(data, country_code, runtime):
    """The forecast with "humidex" and "wind_chill" beside the current
    and hourly readings, for a place in Canada read in Celsius.  An
    index that would not be reported is None.  The keys' presence is
    what tells the views to show the indices in place of feels-like."""
    if not data or country_code != "CA" or not runtime.celsius:
        return data
    current = data.get("current")
    if isinstance(current, dict):
        current["humidex"], current["wind_chill"] = _indices(
            current.get("temperature_2m"), current.get("dew_point_2m"),
            current.get("wind_speed_10m"), runtime)
    hourly = data.get("hourly")
    if isinstance(hourly, dict):
        temps = hourly.get("temperature_2m") or []
        dews = hourly.get("dew_point_2m") or []
        winds = hourly.get("wind_speed_10m") or []
        pairs = [_indices(t, dews[i] if i < len(dews) else None,
                          winds[i] if i < len(winds) else None, runtime)
                 for i, t in enumerate(temps)]
        hourly["humidex"] = [h for h, _w in pairs]
        hourly["wind_chill"] = [w for _h, w in pairs]
    return data


def _indices(temp, dew_point, wind, runtime):
    wind_kmh = runtime.wind_kmh(wind) if wind is not None else None
    return humidex(temp, dew_point), wind_chill(temp, wind_kmh)
