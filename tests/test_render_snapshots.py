"""Snapshot tests for rendering output.

These tests render with fixed data, fixed terminal size, and a pinned clock,
then compare the ANSI-stripped text output against a stored reference.  If the
reference file doesn't exist yet, the first run creates it (test passes).

To regenerate snapshots after an intentional rendering change:
    rm tests/snapshots/*.txt && pytest tests/test_render_snapshots.py
"""

import json
import math
import re
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

FIXTURES = Path(__file__).parent / "fixtures"
SNAPSHOTS = Path(__file__).parent / "snapshots"

# Fixed "now" for deterministic rendering
FIXED_NOW = datetime(2026, 3, 5, 14, 30)


def _strip_ansi(text):
    """Remove all ANSI escape sequences for stable comparison."""
    text = re.sub(r"\x1b\][^\x1b]*\x1b\\", "", text)  # OSC
    text = re.sub(r"\x1b\[[^a-zA-Z]*[a-zA-Z]", "", text)  # CSI
    text = re.sub(r"\x1b[()][0-9A-Za-z]", "", text)  # charset
    return text


def _load_fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _read_snapshot(name):
    path = SNAPSHOTS / name
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None


def _write_snapshot(name, content):
    SNAPSHOTS.mkdir(exist_ok=True)
    (SNAPSHOTS / name).write_text(content, encoding="utf-8")


def _sphere(lat_deg, lon_deg):
    """A unit-sphere point in the Moon's frame from selenographic coordinates."""
    lat, lon = math.radians(lat_deg), math.radians(lon_deg)
    return (math.cos(lat) * math.sin(lon), -math.sin(lat),
            math.cos(lat) * math.cos(lon))


def _max_channel_gap(a, b):
    return max(abs(pa[i] - pb[i])
               for ra, rb in zip(a, b) for pa, pb in zip(ra, rb) for i in range(3))


def _compare_or_create(snapshot_name, actual):
    """Compare against stored snapshot, or create it on first run."""
    stored = _read_snapshot(snapshot_name)
    if stored is None:
        _write_snapshot(snapshot_name, actual)
        return  # first run -- snapshot created
    assert actual == stored, (
        f"Snapshot mismatch for {snapshot_name}. "
        f"Delete tests/snapshots/{snapshot_name} and re-run to update."
    )


def _weather_render(cols, rows, runtime, fixture="open_meteo_forecast.json",
                     location_name="Toronto, Ontario"):
    """Render weather dashboard with mocked terminal size and clock."""
    from linecast.weather import render_from_data

    data = _load_fixture(fixture)

    with patch("linecast.weather.get_terminal_size", return_value=(cols, rows)), \
         patch("linecast.weather._local_now_for_data", return_value=FIXED_NOW), \
         patch("linecast._weather_hourly._local_now_for_data", return_value=FIXED_NOW):
        output, _ = render_from_data(
            data, alerts=[], runtime=runtime,
            location_name=location_name,
        )
    return _strip_ansi(output)


# -----------------------------------------------------------------------
# Weather rendering snapshots
# -----------------------------------------------------------------------
class TestWeatherSnapshot:
    """Render the weather dashboard with fixture data and compare output."""

    def _make_runtime(self, **overrides):
        from linecast._runtime import WeatherRuntime
        defaults = dict(
            live=False, icons="emoji", lang="en", oneline=False,
            celsius=False, metric=False, shading=False,
        )
        defaults.update(overrides)
        return WeatherRuntime(**defaults)

    def test_weather_80x24(self):
        output = _weather_render(80, 24, self._make_runtime())
        _compare_or_create("weather_80x24.txt", output)

    def test_weather_120x40(self):
        output = _weather_render(120, 40, self._make_runtime())
        _compare_or_create("weather_120x40.txt", output)

    def test_weather_metric_french(self):
        runtime = self._make_runtime(lang="fr", celsius=True, metric=True)
        output = _weather_render(80, 24, runtime)
        _compare_or_create("weather_metric_fr_80x24.txt", output)


# -----------------------------------------------------------------------
# Sunshine rendering snapshot
# -----------------------------------------------------------------------
class TestSunshineSnapshot:
    def test_sunshine_80x24(self):
        from linecast.sunshine import render
        from linecast._runtime import RuntimeConfig

        runtime = RuntimeConfig(live=False, icons="emoji", lang="en", oneline=False)
        # Pin the UTC offset so the snapshot is hermetic. solar_times() reads
        # the host's live offset via _tz_offset_hours(), which otherwise makes
        # this test depend on both the machine's timezone and the current DST
        # state. doy=64 (March 5) is in standard time for US Eastern, so -5.
        with patch("linecast.sunshine.get_terminal_size", return_value=(80, 24)), \
             patch("linecast.sunshine._tz_offset_hours", return_value=-5):
            output = render(
                lat=43.7, lng=-79.4, doy=64,
                now_hour=14.5, fullscreen=False,
                runtime=runtime,
            )
        stripped = _strip_ansi(output)
        _compare_or_create("sunshine_80x24.txt", stripped)

    def test_sunshine_year_80x24(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from linecast._sunshine_year import render_year
        from linecast._runtime import RuntimeConfig

        runtime = RuntimeConfig(live=False, icons="emoji", lang="en", oneline=False)
        # A named zone rather than the host's: the year's per-day offsets
        # and the sun's placement then depend on nothing but the arguments.
        tz = ZoneInfo("America/Toronto")
        now = datetime(2026, 3, 5, 14, 30, tzinfo=tz)
        # The corner clock names the weekday only on a day that is not
        # the user's; pin the user's day to the rendered one.
        with patch("linecast._sunshine_year.get_terminal_size",
                   return_value=(80, 24)), \
             patch("linecast.sunshine._local_today", return_value=now.date()):
            output = render_year(43.7, -79.4, now, runtime, tz=tz,
                                 location_label="Toronto")
        _compare_or_create("sunshine_year_80x24.txt", _strip_ansi(output))

    def test_sunshine_year_polar_80x24(self):
        """Longyearbyen in March: both polar seasons in one field."""
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from linecast._sunshine_year import render_year
        from linecast._runtime import RuntimeConfig

        runtime = RuntimeConfig(live=False, icons="emoji", lang="en", oneline=False)
        tz = ZoneInfo("Europe/Oslo")
        now = datetime(2026, 3, 5, 14, 30, tzinfo=tz)
        with patch("linecast._sunshine_year.get_terminal_size",
                   return_value=(80, 24)), \
             patch("linecast.sunshine._local_today", return_value=now.date()):
            output = render_year(78.22, 15.65, now, runtime, tz=tz,
                                 location_label="Longyearbyen")
        _compare_or_create("sunshine_year_polar_80x24.txt", _strip_ansi(output))


# -----------------------------------------------------------------------
# Moon rendering snapshot
# -----------------------------------------------------------------------
class TestMoonSnapshot:
    # A fixed-offset zone keeps the rise/set times hermetic regardless of
    # the host machine's timezone. 2026-03-05 is a waning full-ish moon.
    def _now(self):
        from datetime import timedelta, timezone
        return datetime(2026, 3, 5, 14, 30,
                        tzinfo=timezone(timedelta(hours=-5)))

    def _render(self, lang):
        from linecast.moon import render
        from linecast._runtime import RuntimeConfig

        runtime = RuntimeConfig(live=False, icons="emoji", lang=lang, oneline=False)
        with patch("linecast.moon.get_terminal_size", return_value=(80, 24)):
            output = render(self._now(), 43.7, -79.4, runtime)
        return _strip_ansi(output)

    def test_moon_80x24(self):
        _compare_or_create("moon_80x24.txt", self._render("en"))

    def test_moon_80x24_french(self):
        _compare_or_create("moon_fr_80x24.txt", self._render("fr"))

    def test_moon_scrubbed_shows_simulated_time(self):
        """Scrubbing must label the simulated moment and the way back."""
        from linecast.moon import render
        from linecast._runtime import RuntimeConfig

        runtime = RuntimeConfig(live=False, icons="emoji", lang="en", oneline=False)
        with patch("linecast.moon.get_terminal_size", return_value=(80, 24)):
            output = _strip_ansi(
                render(self._now(), 43.7, -79.4, runtime, offset_minutes=2880)
            )
        assert "Thu Mar 5" in output
        assert "space to return to now" in output
        assert "Up now" not in output

    def test_terminator_squares_up_to_the_bright_limb(self):
        """The lit half sits where the bright limb points."""
        from linecast._framebuffer import Framebuffer
        from linecast.moon import _draw_moon_disc

        def sides(limb_deg, axis_deg=0.0, illum=0.5):
            fb = Framebuffer(40, 20)
            _draw_moon_disc(fb, 20, 20, 15, illum, limb_deg, axis_deg)
            left = sum(sum(fb.fb[20][x]) for x in range(6, 18))
            right = sum(sum(fb.fb[20][x]) for x in range(23, 35))
            return left, right

        lit_right = sides(90.0)
        lit_left = sides(-90.0)
        assert lit_right[1] > lit_right[0]
        assert lit_left[0] > lit_left[1]

    def test_maria_turn_without_moving_the_terminator(self):
        """The two angles are independent: the Sun lights one side of the
        Moon whichever way the Moon's own pole happens to be leaning."""
        from linecast._framebuffer import Framebuffer
        from linecast.moon import _draw_moon_disc

        def render(axis_deg):
            fb = Framebuffer(40, 20)
            _draw_moon_disc(fb, 20, 20, 15, 0.5, 90.0, axis_deg)
            left = sum(sum(fb.fb[20][x]) for x in range(6, 18))
            right = sum(sum(fb.fb[20][x]) for x in range(23, 35))
            return fb, (left, right)

        upright, upright_sides = render(0.0)
        tilted, tilted_sides = render(40.0)
        assert tilted_sides[1] > tilted_sides[0]      # still lit on the right
        assert tilted.fb != upright.fb                # but the maria moved

    def test_lit_fraction_drives_the_terminator(self):
        """Full fills the disc, new empties it."""
        from linecast._framebuffer import Framebuffer
        from linecast.moon import _draw_moon_disc

        def brightness(illum):
            fb = Framebuffer(40, 20)
            _draw_moon_disc(fb, 20, 20, 15, illum, 90.0, 0.0)
            return sum(sum(fb.fb[20][x]) for x in range(6, 35))

        assert brightness(1.0) > brightness(0.5) > brightness(0.02)

    def test_orientation_holds_steady_across_the_equator(self):
        """Walking over the equator must not turn the Moon upside down.

        Half a degree either side of the line, at one instant, the tilt
        should differ by about a degree -- not by the half turn the old
        hemisphere test drew.
        """
        from datetime import timezone
        from linecast._ephemeris import _moon_parallactic_deg

        moment = datetime(2026, 3, 5, 4, 0, tzinfo=timezone.utc)
        north = _moon_parallactic_deg(moment, 0.5, 36.8)
        south = _moon_parallactic_deg(moment, -0.5, 36.8)
        assert abs(north - south) < 2.0

    def test_familiar_hemisphere_view_falls_out_of_the_angle(self):
        """The old rule of thumb should survive where it was true.

        A moon on the meridian sits near pole-up for a northern observer
        and near a half turn for a southern one; between rising and
        setting the tilt sweeps most of the way in between.
        """
        from datetime import timedelta, timezone
        from linecast._ephemeris import (
            _moon_altitude_deg, _moon_parallactic_deg,
        )

        day = datetime(2026, 3, 5, tzinfo=timezone.utc)
        assert abs(_moon_parallactic_deg(
            day + timedelta(hours=6, minutes=50), 43.7, -79.4)) < 5.0
        assert abs(abs(_moon_parallactic_deg(
            day + timedelta(hours=14, minutes=5), -41.3, 174.8)) - 180.0) < 5.0

        tilts = [_moon_parallactic_deg(day + timedelta(hours=h), 43.7, -79.4)
                 for h in range(24)
                 if _moon_altitude_deg(day + timedelta(hours=h), 43.7, -79.4) > 0]
        assert max(tilts) - min(tilts) > 60.0

    def test_map_covers_the_whole_moon(self):
        """The albedo map runs the full 360°, near side in the middle."""
        from linecast.moon import _load_albedo, _surface_shade

        w, h, _px = _load_albedo()
        assert (w, h) == (512, 256)
        # The far side is highland almost throughout; Mare Moscoviense is
        # the exception, at about 27°N 148°E. Sample both from the far side.
        far_highland = _surface_shade(*_sphere(-20.0, -140.0), _load_albedo())
        moscoviense = _surface_shade(*_sphere(27.0, 148.0), _load_albedo())
        assert moscoviense > far_highland + 0.1
        # The seam at ±180° is continuous: the two sides of it agree.
        east = _surface_shade(*_sphere(10.0, 179.9), _load_albedo())
        west = _surface_shade(*_sphere(10.0, -179.9), _load_albedo())
        assert abs(east - west) < 0.05

    def test_no_turn_is_the_identity(self):
        """A disc drawn through an identity turn is the disc drawn without."""
        from linecast._framebuffer import Framebuffer
        from linecast.moon import _IDENTITY, _draw_moon_disc

        plain = Framebuffer(40, 20)
        _draw_moon_disc(plain, 20, 20, 15, 0.7, 110.0, 25.0)
        turned = Framebuffer(40, 20)
        _draw_moon_disc(turned, 20, 20, 15, 0.7, 110.0, 25.0, _IDENTITY)
        assert turned.fb == plain.fb

    def test_a_turn_carries_the_light_round_with_the_surface(self):
        """Dragging turns the whole Moon: the lit half goes with it."""
        from linecast._framebuffer import Framebuffer
        from linecast.moon import _draw_moon_disc, _rotation

        def render(turn, illum=0.5):
            fb = Framebuffer(40, 20)
            _draw_moon_disc(fb, 20, 20, 15, illum, 90.0, 0.0, turn)
            row = fb.fb[20]
            left = sum(sum(row[x]) for x in range(6, 18))
            right = sum(sum(row[x]) for x in range(23, 35))
            return fb, left, right

        upright, left0, right0 = render(None)
        assert right0 > left0
        # A half turn about the vertical shows the far side, lit on the
        # other side now, over different ground.
        far, left1, right1 = render(_rotation((0.0, 1.0, 0.0), math.pi))
        assert left1 > right1
        assert far.fb != upright.fb
        # A full Moon turned round shows its night: the far side is dark.
        full, _l, _r = render(None, illum=1.0)
        night, _l, _r = render(_rotation((0.0, 1.0, 0.0), math.pi), illum=1.0)
        disc = range(6, 35)
        assert (sum(sum(night.fb[20][x]) for x in disc)
                < 0.8 * sum(sum(full.fb[20][x]) for x in disc))
        # A full turn brings everything back, to rounding.
        back, _l, _r = render(_rotation((0.0, 1.0, 0.0), 2.0 * math.pi))
        assert _max_channel_gap(back.fb, upright.fb) <= 2

    def test_earthshine_shows_the_maria_on_the_near_side_only(self):
        """A thin crescent's night carries a ghost of the surface; the far
        side's night, turned toward us, is flat shadow."""
        from linecast._framebuffer import Framebuffer
        from linecast.moon import MOON_SHADOW_RGB, _draw_moon_disc, _rotation

        def night_row(illum, turn=None):
            fb = Framebuffer(60, 30)
            _draw_moon_disc(fb, 30, 30, 24, illum, 90.0, 0.0, turn)
            return [fb.fb[30][x] for x in range(10, 26)]   # left, in shadow

        crescent = night_row(0.05)
        assert len(set(crescent)) > 3                    # the maria show
        assert all(px != MOON_SHADOW_RGB for px in crescent)
        far_night = night_row(1.0, _rotation((0.0, 1.0, 0.0), math.pi))
        assert set(far_night) == {MOON_SHADOW_RGB}      # no Earth to shine
        near_full = night_row(0.98)
        assert near_full[8] != crescent[8]               # fainter by the phase

    def test_the_disc_view_night_is_darker_than_the_sky(self):
        from linecast._framebuffer import Framebuffer
        from linecast.moon import (
            MOON_NIGHT_RGB, MOON_SHADOW_RGB, SKY_RGB, _draw_moon_disc, _rotation,
        )

        assert sum(MOON_NIGHT_RGB) < sum(SKY_RGB)
        fb = Framebuffer(60, 30)
        _draw_moon_disc(fb, 30, 30, 24, 1.0, 90.0, 0.0,
                        _rotation((0.0, 1.0, 0.0), math.pi), night=MOON_NIGHT_RGB)
        assert fb.fb[30][20] == MOON_NIGHT_RGB
        fb = Framebuffer(60, 30)
        _draw_moon_disc(fb, 30, 30, 24, 1.0, 90.0, 0.0,
                        _rotation((0.0, 1.0, 0.0), math.pi))
        assert fb.fb[30][20] == MOON_SHADOW_RGB     # the calendar's default

    def test_stars_are_sown_evenly_and_keep_off_the_moon(self):
        from linecast._framebuffer import Framebuffer
        from linecast.moon import _STAR_DENSITY, _star_overlays

        fb = Framebuffer(120, 40)
        cx, cy, radius = 60, 40, 30
        taken = {(x, row) for x in range(90, 120) for row in range(10, 30)}
        sky = (60.0, 20.0, 0.0)   # the Moon in Taurus, pole up
        stars = _star_overlays(fb, cx, cy, radius, sky, taken=taken)
        free = sum(1 for x in range(120) for row in range(40)
                   if (x, row) not in taken
                   and (x - cx) ** 2 + (row * 2 + 0.5 - cy) ** 2 >= (radius + 3) ** 2)
        wanted = _STAR_DENSITY / 1000 * free
        assert 0.5 * wanted < len(stars) < 1.6 * wanted
        assert not (set(stars) & taken)
        for x, row in stars:
            assert (x - cx) ** 2 + (row * 2 + 0.5 - cy) ** 2 >= (radius + 3) ** 2
        # The sky's corners are not bare: each quarter holds stars.
        quarters = {(x < cx, row * 2 < cy) for x, row in stars}
        assert len(quarters) == 4

    def test_the_sky_is_the_real_one(self):
        """Sirius sits where it should about the Moon, and turns with the
        parallactic angle as the night goes on."""
        from linecast._framebuffer import Framebuffer
        from linecast.moon import _load_stars, _star_overlays

        stars = _load_stars()
        assert len(stars) > 2000
        ra, dec = stars[0]                        # Sirius, the brightest
        assert abs(math.degrees(ra) - 101.29) < 0.02
        assert abs(math.degrees(dec) + 16.72) < 0.02

        fb = Framebuffer(160, 60)
        cx, cy, radius = 80, 60, 20
        # The Moon sixty degrees due north of Sirius, celestial north
        # straight up: Sirius hangs below the disc, focal length times
        # the angle down.
        sky = (101.29, 43.28, 0.0)
        field = _star_overlays(fb, cx, cy, radius, sky)
        brightest = [cell for cell, (glyph, _c, _b) in field.items() if glyph == "✱"]
        expect = (cx, int((cy + 1.5 * radius * math.radians(60.0)) // 2))
        assert expect in brightest, (expect, brightest)
        # Later in the night the sky has turned: with celestial north
        # ninety degrees round to the right, Sirius lies to the left.
        field = _star_overlays(fb, cx, cy, radius, (101.29, 43.28, 90.0))
        brightest = [cell for cell, (glyph, _c, _b) in field.items() if glyph == "✱"]
        expect = (cx - int(round(1.5 * radius * math.radians(60.0))), cy // 2)
        assert expect in brightest, (expect, brightest)

    def test_turning_the_disc_sweeps_the_stars_the_other_way(self):
        """Roll the surface right and the sky behind it goes left, as the
        background does when you walk round a statue."""
        from linecast.moon import (
            _load_stars, _project_star, _rotation, _star_direction,
        )

        cx, cy, radius = 60, 40, 30
        turn = _rotation((0.0, 1.0, 0.0), 0.6)   # a drag to the right
        moved = []
        for ra, dec in _load_stars()[:300]:
            d = _star_direction(ra, dec, (60.0, 20.0, 0.0))
            rest = _project_star(d, None, cx, cy, radius)
            turned = _project_star(d, turn, cx, cy, radius)
            if rest is None or turned is None:
                continue
            if 0 <= rest[0] < 120 and abs(rest[1] * 2 - cy) < 10:
                moved.append(turned[0] - rest[0])
        assert moved and all(dx < 0 for dx in moved)

    def test_drag_rolls_the_surface_with_the_pointer(self):
        """Dragging right brings the left limb toward the centre, dragging
        down brings the top; a drag the length of the radius is a radian."""
        from linecast.moon import Turn, _axis_angle, _mat_transpose

        def centre_after(dcol, drow):
            turn = Turn()
            turn.radius = 40.0
            turn.drag(dcol, drow)
            m = _mat_transpose(turn.matrix())   # screen point → surface point
            return (m[2], m[5], m[8]), _axis_angle(turn.matrix())[1]

        (x, _y, _z), angle = centre_after(40, 0)
        assert x < -0.8 and abs(angle - 1.0) < 1e-9
        (_x, y, _z), angle = centre_after(0, 20)   # a cell is two sub-pixels tall
        assert y < -0.8 and abs(angle - 1.0) < 1e-9

    def test_release_settles_back_to_rest(self):
        """Let go and the turn eases to nothing, on the clock."""
        from linecast.moon import Turn, _axis_angle

        turn = Turn()
        turn.radius = 40.0
        assert turn.matrix() is None
        assert turn.release() is False             # nothing was dragged
        turn.drag(30, 5)
        held = _axis_angle(turn.matrix())[1]
        assert turn.release() is True
        with patch("linecast.moon.time.monotonic",
                   return_value=turn._settle[2] + Turn.SETTLE * 0.5):
            assert 0.0 < _axis_angle(turn.matrix())[1] < held
        with patch("linecast.moon.time.monotonic",
                   return_value=turn._settle[2] + Turn.SETTLE * 1.01):
            assert turn.matrix() is None
        turn._ticker.join(timeout=2.0)
        assert not turn._ticker.is_alive()

    def test_a_drag_mid_settle_picks_the_disc_up_where_it_is(self):
        from linecast.moon import Turn, _axis_angle

        turn = Turn()
        turn.radius = 40.0
        turn.drag(40, 0)
        turn.release()
        with patch("linecast.moon.time.monotonic",
                   return_value=turn._settle[2] + Turn.SETTLE * 0.5):
            partway = _axis_angle(turn.matrix())[1]
            turn.drag(0, 0)
        assert abs(_axis_angle(turn.matrix())[1] - partway) < 1e-9
        assert turn._settle is None



# -----------------------------------------------------------------------
# Ephemeris accuracy
# -----------------------------------------------------------------------
class TestEphemerisAccuracy:
    """The Moon, checked against published times and positions.

    Reference values are the ones the almanacs print, to the minute. The
    tolerances say what this low-precision ephemeris is for: naming the
    right phase on the right evening, not navigating by it.
    """

    # Principal phases of early 2026, UTC.
    PHASES = [
        (0.0, "2026-01-18 19:51"), (0.0, "2026-02-17 12:01"),
        (0.0, "2026-03-19 01:23"), (0.0, "2026-04-17 11:51"),
        (0.5, "2026-01-03 10:02"), (0.5, "2026-02-01 22:09"),
        (0.5, "2026-03-03 11:37"), (0.5, "2026-04-02 02:11"),
    ]

    def test_principal_phases_land_within_a_quarter_hour(self):
        from datetime import timedelta, timezone
        from linecast._ephemeris import next_moon_phase_utc

        for target, stamp in self.PHASES:
            want = datetime.strptime(stamp, "%Y-%m-%d %H:%M").replace(
                tzinfo=timezone.utc)
            got = next_moon_phase_utc(want - timedelta(days=5), target)
            assert got is not None, stamp
            off = abs((got - want).total_seconds()) / 60.0
            assert off < 15.0, f"{stamp}: off by {off:.0f} min"

    def test_disc_is_full_when_the_almanac_says_full(self):
        from datetime import timezone
        from linecast._ephemeris import moon_illuminated_fraction

        full = datetime(2026, 3, 3, 11, 37, tzinfo=timezone.utc)
        new = datetime(2026, 3, 19, 1, 23, tzinfo=timezone.utc)
        assert moon_illuminated_fraction(full) > 0.999
        assert moon_illuminated_fraction(new) < 0.001

    def test_moon_position_within_a_tenth_of_a_degree(self):
        """Geocentric RA/dec against pyephem, which uses ELP2000."""
        from datetime import timezone
        from linecast._ephemeris import _moon_ra_dec

        # (UTC, RA deg, dec deg)
        known = [
            ("2026-01-15 00:00", 249.8438, -27.3160),
            ("2026-03-05 19:30", 190.8829, -7.9009),
            ("2026-06-21 12:00", 174.8110, 0.0488),
            ("2026-11-08 06:00", 209.9764, -17.1436),
        ]
        for stamp, ra, dec in known:
            when = datetime.strptime(stamp, "%Y-%m-%d %H:%M").replace(
                tzinfo=timezone.utc)
            got_ra, got_dec = _moon_ra_dec(when)
            d_ra = abs((got_ra - ra + 540.0) % 360.0 - 180.0) * math.cos(
                math.radians(dec))
            assert math.hypot(d_ra, got_dec - dec) < 0.1, stamp

    def test_bright_limb_points_at_the_sun(self):
        """The lit edge must face the Sun, wherever both happen to be."""
        from datetime import timezone
        from linecast._ephemeris import (
            _moon_altitude_deg, _moon_parallactic_deg, moon_bright_limb_deg,
        )

        # Bearing from Moon to Sun in the alt/az frame, 0 = up, +90 = right,
        # taken from pyephem at four moments over a year at four sites.
        cases = [
            ("2026-01-24 18:00", 51.5, -0.1, 131.3),
            ("2026-04-22 06:00", -33.9, 151.2, -84.3),
            ("2026-08-02 21:00", 1.3, 36.8, -154.7),
            ("2026-10-30 00:00", 64.1, -21.9, -116.2),
        ]
        for stamp, lat, lng, want in cases:
            when = datetime.strptime(stamp, "%Y-%m-%d %H:%M").replace(
                tzinfo=timezone.utc)
            assert _moon_altitude_deg(when, lat, lng) > 0, stamp
            drawn = (_moon_parallactic_deg(when, lat, lng)
                     - moon_bright_limb_deg(when))
            off = abs((drawn - want + 540.0) % 360.0 - 180.0)
            assert off < 3.0, f"{stamp}: off by {off:.1f} deg"

# -----------------------------------------------------------------------
# Maps rendering snapshots
# -----------------------------------------------------------------------
class TestMapsSnapshot:
    """Both map modes over synthetic data.

    No network: the elevation and street-tile fetchers are replaced by
    hand-built data, so what is pinned is everything downstream of the
    fetch — the composer, the marks, the labels, the header and the
    footer.

    These snapshots keep their escape sequences (written `\\e`) rather
    than stripping them. On a map the colour *is* the output: strip it
    and a water fill and a park fill are both a space.
    """

    LAT, LON = 43.66, -70.26
    COLS, ROWS = 80, 24

    def _runtime(self):
        from linecast._runtime import RuntimeConfig
        return RuntimeConfig(live=False, icons="emoji", lang="en",
                             oneline=False)

    def _render(self, view, fetch_patch, zoom=0.02):
        from linecast import _color, _maps_style, _theme, maps
        stack = [
            patch("linecast.maps.get_terminal_size",
                  return_value=(self.COLS, self.ROWS)),
            patch.object(_color, "_COLOR_MODE", "truecolor"),
            patch.object(_maps_style, "color_mode", lambda: "truecolor"),
            patch.object(_theme, "theme_bg", (14, 15, 18)),
            patch.dict(maps.compose_map.__globals__,
                       {"color_mode": lambda: "truecolor"}),
            fetch_patch,
        ]
        for ctx in stack:
            ctx.__enter__()
        try:
            out = maps.render_map(
                self.LAT, self.LON, "Portland, Maine", zoom,
                runtime=self._runtime(), view=view)
        finally:
            for ctx in reversed(stack):
                ctx.__exit__(None, None, None)
        return out.replace("\033", "\\e")

    def test_maps_terrain_80x24(self):
        # A synthetic shoreline: elevation rises west to east and the
        # western third is below sea level, so the snapshot carries the
        # bathy ramp, the hypso ramp and a derived coastline.
        from linecast import maps

        def elevation(bbox, gw, hc, block):
            fine = [[(x - gw * 1.4) * 2.0 for x in range(gw * 2)]
                    for _ in range(hc * 4)]
            grid = [[(x - gw * 0.7) * 4.0 for x in range(gw)]
                    for _ in range(hc * 2)]
            # no tile water: the snapshot is the elevation-only map
            return maps.TerrainView(grid, maps._coast_dots(fine, gw, hc),
                                    None, None, None)

        output = self._render(
            "terrain", patch.object(maps, "_get_elevation", elevation))
        _compare_or_create("maps_terrain_80x24.txt", output)

    def test_maps_globe_80x24(self):
        # Planet-scale zoom hands terrain to the orthographic globe.  A
        # synthetic hemisphere — dry land east of the centre meridian,
        # deep sea west — pins the disk, the limb falloff, the
        # atmosphere rim and the space around the planet, while the
        # vendored city data pins the projected labels.
        from linecast import _globe, maps

        def synth(lls):
            return [[None if ll is None
                     else (1200.0 if ll[1] > self.LON else -3200.0)
                     for ll in row] for row in lls]

        def get_globe(lat0, lon0, zoom, gw, hc, block):
            lls, zs, rhos = _globe.geometry(lat0, lon0, zoom, gw, hc * 2)
            flls, _fz, _fr = _globe.geometry(lat0, lon0, zoom,
                                             gw * 2, hc * 4)
            return _globe.GlobeView(
                synth(lls), maps._coast_dots(synth(flls), gw, hc), zs,
                _globe.atmosphere(rhos, zoom, hc * 2), None,
                _globe.border_layer(lat0, lon0, zoom, gw, hc,
                                    maps.BORDER_STROKE))

        output = self._render(
            "terrain", patch.object(maps, "_get_globe", get_globe),
            zoom=125.0)
        _compare_or_create("maps_globe_80x24.txt", output)

        # the street register rides the same sphere in the flat street
        # map's own fills and coast ink, with no borders — pinned
        # separately
        output = self._render(
            "street", patch.object(maps, "_get_globe", get_globe),
            zoom=125.0)
        _compare_or_create("maps_globe_street_80x24.txt", output)

    @staticmethod
    def _tile_xy(lon, lat, z, tx, ty, extent=4096):
        """(lon, lat) -> tile-local coordinates: the projector, inverted,
        so the synthetic geometry actually lands in the view."""
        n = 1 << z
        wx = (lon + 180.0) / 360.0
        sin_lat = math.sin(math.radians(lat))
        wy = 0.5 - math.log((1 + sin_lat) / (1 - sin_lat)) / (4 * math.pi)
        return (round((wx * n - tx) * extent), round((wy * n - ty) * extent))

    def test_maps_street_80x24(self):
        # Hand-encoded tiles placed against the actual view: water over
        # its western half (so the coastline runs down the middle) and a
        # primary road straight across it.
        from linecast import maps
        from test_maps_streets import (
            classed, polyline, rect, tagged_line, tile,
        )

        def street(bbox, gw, hc, block, lang="en", reserved=()):
            from linecast import _maps_streets as st
            band = st.style.band_for(st.style.z_eff(bbox, hc))
            minlon, minlat, maxlon, maxlat = bbox
            midlon = (minlon + maxlon) / 2
            midlat = (minlat + maxlat) / 2
            pad = (maxlon - minlon)
            tiles = {}
            for key in st.tiles_for_bbox(bbox, 12):
                z, tx, ty = key
                def xy(lon, lat, z=z, tx=tx, ty=ty):
                    return self._tile_xy(lon, lat, z, tx, ty)
                west = xy(minlon - pad, maxlat + pad)
                east = xy(midlon, minlat - pad)
                road_w = xy(minlon - pad, midlat)
                road_e = xy(maxlon + pad, midlat)
                tiles[key] = tile(
                    classed("water", rect(west[0], west[1], east[0], east[1]),
                            "lake"),
                    tagged_line("transportation",
                                polyline(road_w, road_e),
                                {"class": "primary"}),
                )
            return st.build_street_view(bbox, gw, hc, tiles, band, lang,
                                        reserved)

        output = self._render(
            "street", patch.object(maps, "_get_street", street))
        _compare_or_create("maps_street_80x24.txt", output)
