"""Machine-readable JSON payload for `sky --json`.

A snapshot of the sky over the location at the moment: the Sun and the
Moon, every planet, and the brightest stars up, each with its altitude
and azimuth. Times are minute-precision local ISO strings.
"""

from datetime import timezone

from linecast._sunshine_json import _iso, _local_timezone_name, _location_label

SCHEMA_VERSION = 1


def build_payload(now_local, lat, lng, runtime, location=None, facing=None,
                  fov=None):
    from linecast._sky_catalogue import star_names, stars
    from linecast._ephemeris import _alt_az_deg
    from linecast._sunshine_i18n import sky_phase
    from linecast.sky import (
        FOV_DEFAULT, Scene, compass_point, default_view, easily_seen,
    )
    from linecast.sunshine import moon_phase
    import math

    scene = Scene(now_local.astimezone(timezone.utc), lat, lng)
    view = default_view(scene, 80, 24, facing, fov or FOV_DEFAULT)
    idx, _name, _icon = moon_phase(scene.moment_utc, runtime)
    from linecast._tides_i18n import _moon_name

    def place(alt, az):
        return {"altitude": round(alt, 1), "azimuth": round(az, 1),
                "compass": compass_point(az, runtime), "up": alt > 0.0}

    planets = []
    for key, _vec, alt, az, mag in scene.planets:
        planets.append({"name": key, **place(alt, az), "magnitude": round(mag, 1),
                        "visible": alt > 0.0 and easily_seen(mag, alt, scene)})

    bright = []
    names = star_names()
    for i, (ra, dec, mag, _bv) in enumerate(stars()):
        if mag > 1.6 or len(bright) >= 12:
            break
        alt, az = _alt_az_deg(math.degrees(ra), math.degrees(dec), scene.moment_utc,
                              lat, lng)
        if alt > 0.0:
            proper, desig = names.get(i, ("", ""))
            bright.append({"name": proper or None, "designation": desig or None,
                           "magnitude": round(mag, 1), **place(alt, az)})

    tz = now_local.tzinfo
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _iso(now_local),
        "timezone": (getattr(tz, "key", None) or _local_timezone_name()),
        "location": {"lat": lat, "lng": lng,
                     "name": location if location is not None else _location_label(lat, lng)},
        "view": {"azimuth": round(view.az, 1), "altitude": round(view.alt, 1),
                 "field_of_view": round(view.fov, 1)},
        "sun": {**place(scene.sun_alt, scene.sun_az),
                "sky": sky_phase(scene.sun_alt, runtime, morning=scene.morning())},
        "moon": {**place(scene.moon_alt, scene.moon_az),
                 "illumination": round(scene.moon_illum * 100.0, 1),
                 "phase": _moon_name(idx, runtime), "phase_index": idx},
        "planets": planets,
        "bright_stars": bright,
        "limiting_magnitude": round(scene.eye_limit, 1),
    }
