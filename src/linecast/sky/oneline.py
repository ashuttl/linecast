"""sky --oneline: the Moon and the planets that are up, in one line."""

from linecast._i18n import fmt_percent
from linecast.terminal.color import RESET, fg


def sky_oneline(now_local, lat, lng, runtime, culture=None):
    """Return a compact sky summary line.

    Example: ``🌖 84% W 31° · Jupiter SE 42° · Saturn S 20°``

    The Moon if it is up, then the planets up and bright enough for the
    sky as it is, brightest first, each with the way to look and how
    high; the sky's name when nothing is. *culture* is the --culture
    flag, resolved here as the view resolves it: the flag, else the
    `linecast culture` setting, else the language's own.
    """
    from datetime import timezone
    from linecast.sky.scene import Scene, compass_point, easily_seen
    from linecast.sky.palette import TEXT_RGB, DIM_RGB
    from linecast._i18n import lang_of
    from linecast.sky.catalogue import resolve_culture
    from linecast.sky.i18n import _sk, body_name
    from linecast.sunshine.i18n import sky_phase
    from linecast.moon.phase import moon_phase

    scene = Scene(now_local.astimezone(timezone.utc), lat, lng)
    culture, _source = resolve_culture(culture, lang_of(runtime))
    text, dim = fg(*TEXT_RGB), fg(*DIM_RGB)
    parts = []
    if scene.moon_alt > 0.0:
        _idx, _name, icon = moon_phase(scene.moment_utc, runtime)
        parts.append(f"{text}{icon} {fmt_percent(scene.moon_illum * 100, runtime)} "
                     f"{compass_point(scene.moon_az, runtime, culture)} {scene.moon_alt:.0f}°")
    for key, _vec, alt, az, mag in scene.planets:
        if alt > 0.0 and easily_seen(mag, alt, scene):
            parts.append(f"{text}{body_name(key, runtime)} "
                         f"{compass_point(az, runtime, culture)} {alt:.0f}°")
    if not parts:
        parts.append(f"{dim}{sky_phase(scene.sun_alt, runtime, morning=scene.morning())}"
                     f" · {_sk('planets_none', runtime)}")
    return f"{dim} · ".join(parts) + RESET
