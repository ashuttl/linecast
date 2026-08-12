"""Moon phase, illumination, and rise/set times.

Usage: moon [--print] [--oneline] [--emoji] [--lang CODE]

Shows the current phase and illuminated fraction, whether the Moon is up
right now, the next moonrise and moonset, and the dates of the next full
and new moons. Rise/set times use the same low-precision ephemeris as the
tides chart's moon labels (accurate to within a few minutes); phase and
illumination come from the mean synodic cycle, which is what printed
almanacs round to as well.
"""

import math
import sys
from datetime import datetime, timedelta, timezone

from linecast._framebuffer import fmt_time_dt
from linecast._graphics import fg, RESET, live_loop
from linecast._location import get_location
from linecast._runtime import RuntimeConfig, moon_parser
from linecast._tides_i18n import _moon_name
from linecast._tides_render import _moon_altitude_deg, _moon_events_for_local_date
from linecast.sunshine import (
    INFO_AMBER_RGB,
    INFO_DIM_RGB,
    INFO_PURPLE_RGB,
    INFO_TEXT_RGB,
    SYNODIC_MONTH,
    moon_cycle_frac,
    moon_phase,
)

# Matches the rise/set threshold in _moon_events_for_local_date: net effect
# of refraction and lunar parallax puts the geometric event at +0.125°.
HORIZON_THRESHOLD_DEG = 0.125


def moon_illumination(dt):
    """Illuminated fraction of the lunar disc, in [0, 1].

    For a uniformly lit sphere the fraction is (1 − cos elongation) / 2;
    the mean synodic cycle position stands in for elongation, consistent
    with the accuracy of moon_phase().
    """
    return (1.0 - math.cos(2.0 * math.pi * moon_cycle_frac(dt))) / 2.0


def upcoming_moon_events(now_local, lat, lng):
    """Next (moonrise, moonset) datetimes strictly after *now_local*.

    Scans up to three local calendar days. At high latitudes the Moon can
    stay up (or down) for days, so either value may still be None.
    """
    tzinfo = now_local.tzinfo
    next_rise = None
    next_set = None
    for offset in range(3):
        day = now_local.date() + timedelta(days=offset)
        rise, sset = _moon_events_for_local_date(day, lat, lng, tzinfo)
        if next_rise is None and rise is not None and rise > now_local:
            next_rise = rise
        if next_set is None and sset is not None and sset > now_local:
            next_set = sset
        if next_rise is not None and next_set is not None:
            break
    return next_rise, next_set


def _fmt_event(dt, now_local, use_24h):
    """Format an event time, marking events that fall on a later day."""
    if dt is None:
        return "—"
    time_str = fmt_time_dt(dt, use_24h=use_24h)
    days_ahead = (dt.date() - now_local.date()).days
    if days_ahead == 1:
        return f"{time_str} ({dt.strftime('%a')})"
    if days_ahead > 1:
        return f"{time_str} ({dt.strftime('%a')}, +{days_ahead}d)"
    return time_str


def render(now_local, lat, lng, runtime):
    """Build the multi-line moon summary."""
    idx, _name, icon = moon_phase(now_local, runtime)
    name = _moon_name(idx, runtime)
    frac = moon_cycle_frac(now_local)
    illum = moon_illumination(now_local)
    age = frac * SYNODIC_MONTH
    alt = _moon_altitude_deg(now_local.astimezone(timezone.utc), lat, lng)
    rise, sset = upcoming_moon_events(now_local, lat, lng)

    amber = fg(*INFO_AMBER_RGB)
    purple = fg(*INFO_PURPLE_RGB)
    text = fg(*INFO_TEXT_RGB)
    dim = fg(*INFO_DIM_RGB)
    use_24h = runtime.use_24h

    days_to_full = ((0.5 - frac) % 1.0) * SYNODIC_MONTH
    days_to_new = ((1.0 - frac) % 1.0) * SYNODIC_MONTH
    full_dt = now_local + timedelta(days=days_to_full)
    new_dt = now_local + timedelta(days=days_to_new)

    lines = [
        f"{text}{icon} {name}  "
        f"{dim}{illum * 100:.0f}% illuminated · "
        f"day {age:.1f} of {SYNODIC_MONTH:.1f}{RESET}"
    ]

    if alt > HORIZON_THRESHOLD_DEG:
        lines.append(f"{amber}Up now{text} · {alt:.0f}° above the horizon{RESET}")
    else:
        lines.append(f"{dim}Below the horizon{RESET}")

    lines.append(
        f"{amber}↑{text}Moonrise {_fmt_event(rise, now_local, use_24h)}  "
        f"{purple}↓{text}Moonset {_fmt_event(sset, now_local, use_24h)}{RESET}"
    )
    lines.append(
        f"{dim}Full Moon {full_dt.strftime('%b')} {full_dt.day} "
        f"(in {days_to_full:.1f}d) · "
        f"New Moon {new_dt.strftime('%b')} {new_dt.day} "
        f"(in {days_to_new:.1f}d){RESET}"
    )

    return "\n".join(lines)


def main():
    args = moon_parser().parse_args()
    runtime = RuntimeConfig.from_sources(namespace=args)

    lat, lng, _country = get_location()
    if lat is None:
        print("Could not determine location.", file=sys.stderr)
        sys.exit(1)

    if runtime.oneline:
        from linecast._oneline import moon_oneline
        print(moon_oneline(datetime.now().astimezone(), lat, lng, runtime))
        return

    def _render(offset_minutes=0, mouse_pos=None, active_alert=None, modal_scroll=0):
        # Extra args are ignored; accepted so moon can use shared live_loop
        # mouse-wheel scrubbing support.
        moment = datetime.now().astimezone()
        if offset_minutes:
            moment += timedelta(minutes=offset_minutes)
        return render(moment, lat, lng, runtime)

    if runtime.live:
        live_loop(_render, mouse=True)
    else:
        print(_render())


if __name__ == "__main__":
    main()
