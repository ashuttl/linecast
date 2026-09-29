"""weather --oneline: the conditions now in one line, for a status bar or
a prompt."""

from linecast._i18n import fmt_percent
from linecast.terminal.color import RESET
from linecast.weather.i18n import fmt_wind


def weather_oneline(data, location_name, runtime):
    """Return a compact weather summary line.

    Example: ``Portland 58°F Partly cloudy Wind 8mph 💧32%``
    """
    from linecast.weather.cover import sky_condition
    from linecast.weather.i18n import _wmo_icons, wmo_label
    from linecast.weather.style import _colored_temp, TEXT, MUTED, WIND_COLOR

    if not data:
        return "No weather data"

    # A key present and null is a reading the model has no value for;
    # the line leaves it out rather than print it as 0
    current = data.get("current") or {}
    temp = current.get("temperature_2m")
    wmo = sky_condition(current.get("weather_code") or 0, current.get("cloud_cover"))
    wind = current.get("wind_speed_10m") or 0
    humidity = current.get("relative_humidity_2m")

    icons = _wmo_icons(runtime)
    icon = icons.get(wmo, icons[0])
    desc = wmo_label(wmo, runtime.lang)

    deg = runtime.temp_unit
    parts = []

    if location_name:
        # Use short location: first component only (e.g. "Portland" from "Portland, ME")
        short_name = location_name.split(",")[0].strip()
        parts.append(f"{TEXT}{short_name}")

    if temp is not None:
        parts.append(f"{_colored_temp(temp, runtime, deg)}")
    parts.append(f"{TEXT}{icon} {desc}")

    # A breath of wind that rounds to nothing is calm, and left off as
    # calm is, not given as "Wind 0mph"
    if round(wind) > 0:
        from linecast.weather.i18n import _s
        parts.append(f"{WIND_COLOR}{_s('wind', runtime)} {fmt_wind(wind, runtime)}")

    if humidity is not None:
        parts.append(f"{MUTED}\U0001f4a7{fmt_percent(humidity, runtime)}")

    return " ".join(parts) + RESET
