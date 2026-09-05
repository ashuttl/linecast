"""The sky view: where things are, how the view is laid out, what it says."""

import math
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast import sky  # noqa: E402
from linecast._planets import PLANETS, planet_position  # noqa: E402
from linecast._runtime import RuntimeConfig  # noqa: E402
from linecast.sky import (  # noqa: E402
    Scene, View, alt_az_of, camera_matrix, default_view, focal_length,
    horizontal_matrix, horizontal_vector, parse_facing, project, render, unproject,
)

SNAPSHOTS = Path(__file__).parent / "snapshots"
TZ = timezone(timedelta(hours=-4))
LAT, LNG = 43.68, -70.32   # Westbrook, Maine
NIGHT = datetime(2026, 9, 5, 22, 0, tzinfo=TZ)
NOON = datetime(2026, 9, 5, 13, 0, tzinfo=TZ)


def _strip(text):
    return re.sub(r"\x1b\[[^a-zA-Z]*[a-zA-Z]", "", text)


def _runtime(**overrides):
    kwargs = dict(live=False, icons="emoji", lang="en", oneline=False)
    kwargs.update(overrides)
    return RuntimeConfig(**kwargs)


def _utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


def _hours(ra_deg):
    return ra_deg / 15.0


# ---------------------------------------------------------------------------
# The planets
# ---------------------------------------------------------------------------
class TestPlanets:
    """Against the published oppositions and elongations, to a few
    arcminutes — the precision the source promises."""

    def test_mars_at_its_2025_opposition(self):
        ra, dec, mag, _dist = planet_position("mars", _utc(2025, 1, 16))
        assert abs(_hours(ra) - 7.94) < 0.03
        assert abs(dec - 25.1) < 0.3
        assert abs(mag - (-1.4)) < 0.3

    def test_saturn_at_its_2025_opposition(self):
        ra, dec, mag, _dist = planet_position("saturn", _utc(2025, 9, 21))
        assert abs(_hours(ra) - 23.97) < 0.05
        assert abs(dec - (-3.0)) < 0.4
        assert abs(mag - 0.6) < 0.3

    def test_uranus_and_neptune_at_their_2025_oppositions(self):
        ra, dec, mag, _dist = planet_position("uranus", _utc(2025, 11, 21))
        assert abs(_hours(ra) - 3.82) < 0.05
        assert abs(dec - 19.8) < 0.3
        assert abs(mag - 5.6) < 0.2
        ra, dec, mag, _dist = planet_position("neptune", _utc(2025, 9, 23))
        assert abs(_hours(ra) - 0.08) < 0.05
        assert abs(dec - (-1.0)) < 0.3
        assert abs(mag - 7.8) < 0.2

    def test_venus_at_greatest_elongation(self):
        from linecast._ephemeris import _sun_ra_dec
        when = _utc(2025, 6, 1)
        ra, dec, mag, _dist = planet_position("venus", when)
        sun_ra, sun_dec = _sun_ra_dec(when)
        r1, d1, r2, d2 = (math.radians(v) for v in (ra, dec, sun_ra, sun_dec))
        sep = math.degrees(math.acos(
            math.sin(d1) * math.sin(d2) + math.cos(d1) * math.cos(d2) * math.cos(r1 - r2)))
        assert abs(sep - 45.9) < 0.5
        assert mag < -4.0

    def test_every_planet_answers(self):
        positions = sky.planet_positions(_utc(2026, 9, 5))
        assert set(positions) == set(PLANETS)
        for ra, dec, mag, dist in positions.values():
            assert 0.0 <= ra < 360.0 and -30.0 < dec < 30.0
            assert -5.0 < mag < 9.0 and 0.2 < dist < 32.0


# ---------------------------------------------------------------------------
# The geometry
# ---------------------------------------------------------------------------
class TestGeometry:
    def test_the_pole_stands_at_the_latitude(self):
        m = horizontal_matrix(123.0, 43.7)
        e, n, u = sky._mat_apply(m, (0.0, 0.0, 1.0))
        alt, az = alt_az_of((e, n, u))
        assert abs(alt - 43.7) < 1e-6 and abs(az) < 1e-6

    def test_the_meridian_point_is_due_south(self):
        lst = 80.0
        m = horizontal_matrix(lst, 43.7)
        v = (math.cos(math.radians(lst)), math.sin(math.radians(lst)), 0.0)
        alt, az = alt_az_of(sky._mat_apply(m, v))
        assert abs(az - 180.0) < 1e-6
        assert abs(alt - (90.0 - 43.7)) < 1e-6

    def test_the_camera_is_orthonormal_and_right_is_along_the_horizon(self):
        for az, alt in ((0.0, 0.0), (180.0, 30.0), (250.0, 89.0), (90.0, 90.0)):
            c = camera_matrix(az, alt)
            rows = [c[0:3], c[3:6], c[6:9]]
            for i in range(3):
                for j in range(3):
                    dot = sum(rows[i][k] * rows[j][k] for k in range(3))
                    assert abs(dot - (1.0 if i == j else 0.0)) < 1e-9
            assert abs(rows[0][2]) < 1e-9      # right has no up-component
            forward = horizontal_vector(az, alt)
            assert all(abs(a - b) < 1e-9 for a, b in zip(rows[2], forward))

    def test_looking_south_the_east_is_left(self):
        c = camera_matrix(180.0, 20.0)
        x, _y, _z = sky._mat_apply(c, horizontal_vector(120.0, 20.0))
        assert x < 0.0

    def test_project_and_unproject_agree(self):
        f = focal_length(78.0, 110.0)
        for v in ((0.0, 0.0, 1.0), (0.3, -0.2, 0.93), (-0.6, 0.5, 0.62)):
            n = math.sqrt(sum(a * a for a in v))
            v = tuple(a / n for a in v)
            px, py = project(v, f, 39.0, 23.0)
            back = unproject(px, py, f, 39.0, 23.0)
            assert all(abs(a - b) < 1e-9 for a, b in zip(v, back))

    def test_the_field_spans_the_width(self):
        f = focal_length(78.0, 110.0)
        edge = math.radians(55.0)
        px, _py = project((math.sin(edge), 0.0, math.cos(edge)), f, 39.0, 23.0)
        assert abs(px - 78.0) < 1e-6

    def test_behind_the_viewer_is_not_placed(self):
        assert project((0.0, 0.0, -1.0), 40.0, 39.0, 23.0) is None

    def test_parse_facing(self):
        assert parse_facing("N") == 0.0
        assert parse_facing("sw") == 225.0
        assert parse_facing("270") == 270.0
        assert parse_facing(" 400 ") == 40.0
        assert parse_facing(None) is None
        with pytest.raises(ValueError):
            parse_facing("up")


# ---------------------------------------------------------------------------
# The scene
# ---------------------------------------------------------------------------
class TestScene:
    def test_sun_and_moon_agree_with_the_ephemeris(self):
        from linecast._ephemeris import (
            _moon_altitude_deg, _moon_azimuth_deg, sun_alt_az_deg,
        )
        moment = NIGHT.astimezone(timezone.utc)
        scene = Scene(moment, LAT, LNG)
        alt, az = sun_alt_az_deg(moment, LAT, LNG)
        assert abs(scene.sun_alt - alt) < 1e-9 and abs(scene.sun_az - az) < 1e-9
        # The Moon sits below its geocentric place by its parallax.
        geocentric = _moon_altitude_deg(moment, LAT, LNG)
        assert 0.3 < geocentric - scene.moon_alt < 1.1
        assert abs(scene.moon_az - _moon_azimuth_deg(moment, LAT, LNG)) < 1e-9

    def test_night_is_dark_and_noon_is_not(self):
        night = Scene(NIGHT.astimezone(timezone.utc), LAT, LNG)
        noon = Scene(NOON.astimezone(timezone.utc), LAT, LNG)
        assert night.darkness == 1.0 and night.eye_limit == 6.5
        assert noon.darkness == 0.0 and noon.eye_limit < -3.0

    def test_planets_are_sorted_brightest_first(self):
        scene = Scene(NIGHT.astimezone(timezone.utc), LAT, LNG)
        mags = [p[4] for p in scene.planets]
        assert mags == sorted(mags)

    def test_default_view_faces_the_moon_when_it_is_up(self):
        # 04:30: a waning crescent high in the east.
        moment = datetime(2026, 9, 5, 4, 30, tzinfo=TZ).astimezone(timezone.utc)
        scene = Scene(moment, LAT, LNG)
        assert scene.moon_alt > 5.0
        view = default_view(scene, 100, 30)
        assert abs(view.az - scene.moon_az) < 1e-6

    def test_default_view_faces_south_with_nothing_up(self):
        scene = Scene(NOON.astimezone(timezone.utc), LAT, LNG)
        if scene.moon_alt > 5.0:
            pytest.skip("the Moon is up at this moment")
        assert default_view(scene, 100, 30).az == 180.0

    def test_facing_flag_wins(self):
        scene = Scene(NIGHT.astimezone(timezone.utc), LAT, LNG)
        view = default_view(scene, 100, 30, facing=45.0, fov=60.0)
        assert view.az == 45.0 and view.fov == 60.0


# ---------------------------------------------------------------------------
# The frame
# ---------------------------------------------------------------------------
def _frame(now, cols, rows, lang="en", **kwargs):
    runtime = _runtime(lang=lang)
    scene = Scene(now.astimezone(timezone.utc), LAT, LNG)
    view = kwargs.pop("view", None) or default_view(scene, cols, rows, 103.0, 110.0)
    with patch("linecast.sky.get_terminal_size", return_value=(cols, rows)):
        out = render(now, LAT, LNG, runtime, view, location_label="Westbrook",
                     today=now.date(), **kwargs)
    return out


class TestFrame:
    def test_snapshot_80x24(self):
        out = _strip(_frame(NIGHT, 80, 24))
        path = SNAPSHOTS / "sky_80x24.txt"
        if not path.exists():
            path.write_text(out, encoding="utf-8")
        assert out == path.read_text(encoding="utf-8"), (
            "Snapshot mismatch. Delete tests/snapshots/sky_80x24.txt and re-run to update.")

    def test_night_frame_names_what_is_there(self):
        out = _strip(_frame(NIGHT, 100, 30))
        assert "Saturn" in out and "●" in out
        assert "PISCES" in out          # a figure with room is named
        assert " E " in out or "E\n" in out   # the compass under the horizon
        assert "facing E" in out and "110° wide" in out
        assert "Westbrook · 22:00" in out
        assert "night" in out
        assert out.count("·") > 40      # the faint stars

    def test_fills_the_terminal(self):
        out = _strip(_frame(NIGHT, 80, 24, fullscreen=True))
        lines = out.split("\n")
        assert len(lines) == 24
        assert all(len(line) <= 80 for line in lines)

    def test_daylight_holds_no_stars(self):
        out = _strip(_frame(NOON, 100, 30))
        body = "\n".join(out.split("\n")[:-1])
        assert "✦" not in body and "✱" not in body and "+" not in body
        assert "daylight" in out

    def test_figures_can_be_switched_off(self):
        scene = Scene(NIGHT.astimezone(timezone.utc), LAT, LNG)
        view = default_view(scene, 100, 30, 103.0, 110.0)
        with_figures = _strip(_frame(NIGHT, 100, 30, view=view))
        without = _strip(_frame(NIGHT, 100, 30, view=view._replace(figures=0)))
        braille = re.compile(r"[⠀-⣿]")
        assert braille.search(with_figures)
        assert not braille.search(without)
        assert "PISCES" not in without

    def test_zoomed_in_names_more_stars(self):
        scene = Scene(NIGHT.astimezone(timezone.utc), LAT, LNG)
        wide = _strip(_frame(NIGHT, 100, 30, view=View(103.0, 30.0, 110.0, 2)))
        close = _strip(_frame(NIGHT, 100, 30, view=View(103.0, 30.0, 30.0, 2)))
        names = sky.star_names()
        proper = {n for n, _d in names.values() if n}
        assert sum(1 for n in proper if n in close) >= sum(1 for n in proper if n in wide)
        assert scene.eye_limit == 6.5

    def test_the_dome_puts_north_at_the_top(self):
        out = _strip(_frame(NIGHT, 100, 30, view=View(180.0, 90.0, 236.0, 2)))
        lines = out.split("\n")
        top = next(i for i, line in enumerate(lines) if re.search(r"\bN\b", line))
        bottom = next(i for i, line in enumerate(lines) if re.search(r"\bS\b", line))
        assert top < bottom
        assert "overhead" in out

    def test_scrubbed_shows_the_way_back(self):
        out = _strip(_frame(NIGHT, 100, 30, offset_minutes=120))
        assert "space to return to now" in out

    def test_playing_shows_the_rate(self):
        out = _strip(_frame(NIGHT, 100, 30, speed=86400.0))
        assert "▶ 1d/s" in out

    def test_pointer_on_a_planet_names_it(self):
        plain = _strip(_frame(NIGHT, 100, 30).split("\x00")[0])
        row, col = next((r, line.index("●") + 1)
                        for r, line in enumerate(plain.split("\n")) if "●" in line)
        out = _frame(NIGHT, 100, 30, mouse_pos=(col, row + 1))
        body, floating = out.split("\x00")
        chip = re.sub(r"\x1b\[[0-9;]*m", "", floating)
        assert "Saturn" in chip and "mag" in chip and "° · " in chip

    def test_pointer_on_nothing_shows_nothing(self):
        out = _frame(NIGHT, 100, 30, mouse_pos=(50, 2))
        # Either no chip, or a chip for whatever star happens to be there.
        assert "\x00" not in out or "mag" in out

    def test_french(self):
        out = _strip(_frame(NIGHT, 100, 30, lang="fr"))
        assert "Saturne" in out and "vers E" in out and "POISSONS" in out


# ---------------------------------------------------------------------------
# The catalogue
# ---------------------------------------------------------------------------
class TestCatalogue:
    def test_stars_are_brightest_first(self):
        mags = [s[2] for s in sky.stars()]
        assert mags == sorted(mags)
        assert mags[0] < -1.0 and mags[-1] <= 6.5 and len(mags) > 8000

    def test_the_famous_names_are_there(self):
        proper = {n for n, _d in sky.star_names().values()}
        for name in ("Sirius", "Vega", "Polaris", "Betelgeuse", "Antares", "Canopus"):
            assert name in proper
        assert sky.star_names()[0] == ("Sirius", "α CMa")

    def test_the_constellations(self):
        records = sky.constellations()
        assert len(records) == 89   # Serpens in two parts
        orion = next(r for r in records if r["id"] == "Ori")
        assert orion["gen"] == "Orionis" and orion["lines"]
        assert sky.constellation_name(orion, "ja") == "オリオン座"
        assert sky.constellation_name(orion, "no") == "Orion"

    def test_the_milky_way_raster(self):
        raster = sky.milky_way()
        assert len(raster) == sky.MILKY_WAY_W * sky.MILKY_WAY_H
        # Bright toward the galactic centre, dark at the poles.
        w, h = sky.MILKY_WAY_W, sky.MILKY_WAY_H
        centre = max(raster[row * w + x]
                     for row in range(h // 2 - 10, h // 2 + 10)
                     for x in range(w // 2 - 20, w // 2 + 20))
        assert centre > 150 and raster[w // 2] == 0

    def test_the_moon_view_shares_the_stars(self):
        from linecast.moon import _load_stars
        assert _load_stars()[0] == sky.stars()[0][:2]


# ---------------------------------------------------------------------------
# The words
# ---------------------------------------------------------------------------
class TestStrings:
    def test_every_language_has_every_key(self):
        from linecast._i18n import LANGUAGE_CODES
        from linecast._sky_i18n import _SKY_STRINGS
        keys = set(_SKY_STRINGS["en"])
        for code in LANGUAGE_CODES:
            assert set(_SKY_STRINGS[code]) == keys, code

    def test_oneline(self):
        from linecast._oneline import sky_oneline
        line = _strip(sky_oneline(NIGHT, LAT, LNG, _runtime()))
        assert "Saturn E" in line
        noon = _strip(sky_oneline(NOON, LAT, LNG, _runtime()))
        assert noon   # the sky's name, or Venus

    def test_json(self):
        import json
        from linecast._sky_json import build_payload
        payload = build_payload(NIGHT, LAT, LNG, _runtime(), location="Westbrook")
        json.dumps(payload)
        assert set(payload) == {
            "schema_version", "generated_at", "timezone", "location", "view", "sun",
            "moon", "planets", "bright_stars", "limiting_magnitude",
        }
        assert payload["location"]["name"] == "Westbrook"
        assert {p["name"] for p in payload["planets"]} == set(PLANETS)
        saturn = next(p for p in payload["planets"] if p["name"] == "saturn")
        assert saturn["up"] and saturn["visible"] and saturn["compass"] == "E"
        assert payload["sun"]["sky"] == "night"
        assert all(s["up"] for s in payload["bright_stars"])


# ---------------------------------------------------------------------------
# The camera
# ---------------------------------------------------------------------------
class TestCamera:
    def _camera(self):
        from linecast._sky_live import Camera
        cam = Camera(180.0, 30.0, 110.0)
        cam.focal = focal_length(98.0, 110.0)
        return cam

    def test_a_drag_turns_the_view_under_the_pointer(self):
        cam = self._camera()
        cam.drag(10, 0)
        assert cam.az < 180.0          # the sky went right, the view turned left
        cam.drag(10, -4)
        assert cam.alt < 30.0          # the sky went up, the view looked down

    def test_dragging_past_the_horizon_settles_back(self):
        import time
        cam = self._camera()
        cam.drag(0, -40)               # the sky dragged up: far below the horizon
        assert cam.alt < 0.0
        cam.release()
        assert cam.moving()
        time.sleep(0.8)
        assert cam.view().alt == 0.0 and not cam.moving()

    def test_zoom_eases_and_clamps(self):
        import time
        cam = self._camera()
        assert cam.zoom(0.5)
        assert cam.moving()
        time.sleep(0.35)
        assert abs(cam.view().fov - 55.0) < 1e-6
        for _ in range(30):
            cam.zoom(0.5)
        time.sleep(0.35)
        assert cam.view().fov == sky.FOV_MIN
        for _ in range(60):
            cam.zoom(2.0)
        time.sleep(0.35)
        assert cam.view().fov == sky.FOV_MAX

    def test_zooming_all_the_way_out_lies_back(self):
        import time
        cam = self._camera()
        for _ in range(60):
            cam.zoom(2.0)
        time.sleep(0.7)
        assert cam.view().alt == 90.0

    def test_play_cycles_the_speeds(self):
        from linecast._sky_live import SPEEDS, SkyApp
        app = SkyApp(lambda: NIGHT, LAT, LNG, _runtime(live=True))
        seen = []
        for _ in range(len(SPEEDS) + 1):
            app.on_action("p")
            seen.append(app.speed)
        assert seen == [*SPEEDS, None]
        app.on_action("p")
        app.intercept("reset")
        assert app.speed is None and app.minutes == 0 and app.played == 0.0
        app.stop()

    def test_the_wheel_scrubs_time(self):
        from linecast._sky_live import SkyApp
        app = SkyApp(lambda: NIGHT, LAT, LNG, _runtime(live=True))
        app.on_wheel(1, 10, 10)
        app.on_wheel(1, 10, 10)
        app.intercept("back")
        assert app.minutes == 15
        assert app.moment() == NIGHT + timedelta(minutes=15)
