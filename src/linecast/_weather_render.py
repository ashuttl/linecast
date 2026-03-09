"""Compatibility façade for weather rendering helpers.

This module keeps historical imports stable while implementation lives in
smaller focused modules.
"""

from linecast._graphics import RESET
from linecast._weather_alerts import (
    _parse_alert_time,
    _render_single_alert,
    _severity_color,
    _severity_rgb,
    build_alert_modal,
    render_alerts,
)
from linecast._weather_daily import render_daily
from linecast._weather_hourly import (
    _build_braille_curve,
    _build_precip_blocks,
    _compute_daylight_columns,
    _compute_sun_labels,
    _compute_time_markers,
    _daylight_factor,
    _find_temperature_extrema,
    _fmt_hour,
    _fmt_time,
    _interpolate_columns,
    _parse_sun_events,
    _prepare_hourly_window,
    _render_braille_rows,
    _render_extrema_line,
    _render_precip_rows,
    _render_tick_labels,
    _render_today_line,
    _render_wind_row,
    render_hourly,
)
from linecast._weather_sections import (
    _PRECIP_CODES,
    _PRECIP_DESCS,
    _comparative_line,
    _past_precip_line,
    _precipitation_line,
    render_header,
)
from linecast._weather_style import (
    ALERT_AMBER,
    ALERT_RED,
    ALERT_YELLOW,
    DIM,
    MUTED,
    PRECIP,
    PRECIP_MIX,
    PRECIP_RAIN,
    PRECIP_SNOW,
    PRECIP_STORM,
    SEP,
    SPARKLINE,
    TEMP_COLORS,
    TEXT,
    TOOLTIP_BG_RGB,
    TOOLTIP_TEXT_RGB,
    WIND_ARROWS,
    WIND_COLOR,
    _colored_temp,
    _precip_color,
    _precip_type,
    _temp_color,
)
