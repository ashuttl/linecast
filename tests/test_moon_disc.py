"""The Moon's disc: the terminator and the maria, the turn and the drag,
the earthshine, and the stars about it.  They lived beside the moon
snapshots; they test the drawing, not a frame."""

import math
from datetime import datetime
from unittest.mock import patch


def _sphere(lat_deg, lon_deg):
    """A unit-sphere point in the Moon's frame from selenographic coordinates."""
    lat, lon = math.radians(lat_deg), math.radians(lon_deg)
    return (math.cos(lat) * math.sin(lon), -math.sin(lat),
            math.cos(lat) * math.cos(lon))


def _max_channel_gap(a, b):
    return max(abs(pa[i] - pb[i])
               for ra, rb in zip(a, b) for pa, pb in zip(ra, rb) for i in range(3))


class TestMoonDisc:
    def test_terminator_squares_up_to_the_bright_limb(self):
        """The lit half sits where the bright limb points."""
        from linecast.terminal.framebuffer import Framebuffer
        from linecast.moon.disc import _draw_moon_disc

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
        from linecast.terminal.framebuffer import Framebuffer
        from linecast.moon.disc import _draw_moon_disc

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
        from linecast.terminal.framebuffer import Framebuffer
        from linecast.moon.disc import _draw_moon_disc

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
        from linecast.astro.ephemeris import _moon_parallactic_deg

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
        from linecast.astro.ephemeris import (
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
        from linecast.moon.disc import _load_albedo, _surface_shade

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
        from linecast.terminal.framebuffer import Framebuffer
        from linecast.moon.disc import _IDENTITY, _draw_moon_disc

        plain = Framebuffer(40, 20)
        _draw_moon_disc(plain, 20, 20, 15, 0.7, 110.0, 25.0)
        turned = Framebuffer(40, 20)
        _draw_moon_disc(turned, 20, 20, 15, 0.7, 110.0, 25.0, _IDENTITY)
        assert turned.fb == plain.fb

    def test_a_turn_carries_the_light_round_with_the_surface(self):
        """Dragging turns the whole Moon: the lit half goes with it."""
        from linecast.terminal.framebuffer import Framebuffer
        from linecast.moon.disc import _draw_moon_disc, _rotation

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
        from linecast.terminal.framebuffer import Framebuffer
        from linecast.moon.palette import MOON_SHADOW_RGB
        from linecast.moon.disc import _draw_moon_disc, _rotation

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
        from linecast.terminal.framebuffer import Framebuffer
        from linecast.moon.palette import MOON_NIGHT_RGB, MOON_SHADOW_RGB, SKY_RGB
        from linecast.moon.disc import _draw_moon_disc, _rotation

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
        from linecast.terminal.framebuffer import Framebuffer
        from linecast.moon.stars import _STAR_DENSITY, star_overlays

        fb = Framebuffer(120, 40)
        cx, cy, radius = 60, 40, 30
        taken = {(x, row) for x in range(90, 120) for row in range(10, 30)}
        sky = (60.0, 20.0, 0.0)   # the Moon in Taurus, pole up
        stars = star_overlays(fb, cx, cy, radius, sky, taken=taken)
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
        from linecast.terminal.framebuffer import Framebuffer
        from linecast.moon.stars import _load_stars, star_overlays

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
        field = star_overlays(fb, cx, cy, radius, sky)
        brightest = [cell for cell, (glyph, _c, _b) in field.items() if glyph == "✱"]
        expect = (cx, int((cy + 1.5 * radius * math.radians(60.0)) // 2))
        assert expect in brightest, (expect, brightest)
        # Later in the night the sky has turned: with celestial north
        # ninety degrees round to the right, Sirius lies to the left.
        field = star_overlays(fb, cx, cy, radius, (101.29, 43.28, 90.0))
        brightest = [cell for cell, (glyph, _c, _b) in field.items() if glyph == "✱"]
        expect = (cx - int(round(1.5 * radius * math.radians(60.0))), cy // 2)
        assert expect in brightest, (expect, brightest)

    def test_turning_the_disc_sweeps_the_stars_the_other_way(self):
        """Roll the surface right and the sky behind it goes left, as the
        background does when you walk round a statue."""
        from linecast.moon.stars import _load_stars, _project_star, _star_direction
        from linecast.moon.disc import _rotation

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
        from linecast.astro.ephemeris import mat_transpose
        from linecast.moon.disc import Turn, _axis_angle

        def centre_after(dcol, drow):
            turn = Turn()
            turn.radius = 40.0
            turn.drag(dcol, drow)
            m = mat_transpose(turn.matrix())   # screen point → surface point
            return (m[2], m[5], m[8]), _axis_angle(turn.matrix())[1]

        (x, _y, _z), angle = centre_after(40, 0)
        assert x < -0.8 and abs(angle - 1.0) < 1e-9
        (_x, y, _z), angle = centre_after(0, 20)   # a cell is two sub-pixels tall
        assert y < -0.8 and abs(angle - 1.0) < 1e-9

    def test_release_settles_back_to_rest(self):
        """Let go and the turn eases to nothing, on the clock."""
        from linecast.moon.disc import Turn, _axis_angle

        turn = Turn()
        turn.radius = 40.0
        assert turn.matrix() is None
        assert turn.release() is False             # nothing was dragged
        turn.drag(30, 5)
        held = _axis_angle(turn.matrix())[1]
        assert turn.release() is True
        with patch("linecast.moon.disc.time.monotonic",
                   return_value=turn._settle[2] + Turn.SETTLE * 0.5):
            assert 0.0 < _axis_angle(turn.matrix())[1] < held
        with patch("linecast.moon.disc.time.monotonic",
                   return_value=turn._settle[2] + Turn.SETTLE * 1.01):
            assert turn.matrix() is None
        turn._ticker.thread.join(timeout=2.0)
        assert not turn._ticker.thread.is_alive()

    def test_a_drag_mid_settle_picks_the_disc_up_where_it_is(self):
        from linecast.moon.disc import Turn, _axis_angle

        turn = Turn()
        turn.radius = 40.0
        turn.drag(40, 0)
        turn.release()
        with patch("linecast.moon.disc.time.monotonic",
                   return_value=turn._settle[2] + Turn.SETTLE * 0.5):
            partway = _axis_angle(turn.matrix())[1]
            turn.drag(0, 0)
        assert abs(_axis_angle(turn.matrix())[1] - partway) < 1e-9
        assert turn._settle is None
