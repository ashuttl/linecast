"""The eye a flat view is projected about (globe.Camera.eye): a window
panning over a plane hung where the pan began, so every frame of the
pan and the view it rests on are one picture at different offsets.
"""

import math

import pytest

from linecast._xyz import bbox_for
from linecast.maps import globe as g
from linecast.maps import loaders
from linecast.maps import overscan as o
from linecast.maps import view as maps
from linecast.maps.live import ARC_MAX, LEAN_MAX, Camera as LiveCamera

GW, HC = 160, 43
EYE = (47.26, 11.39)


def _over(dcol, drow, zoom, eye=EYE):
    """The centre `dcol, drow` cells over from the eye on its plane."""
    cam = g.Camera(eye[0], eye[1], zoom, GW, HC)
    rx, r = g._grid_plane(cam, GW, HC)
    lat, dlon = g._unproject(dcol / rx, -drow / r,
                             math.sin(math.radians(eye[0])),
                             math.cos(math.radians(eye[0])))
    return lat, eye[1] + dlon


class TestTheCamerasEye:
    def test_no_eye_and_an_eye_at_the_centre_are_the_same_camera(self):
        plain = g.Camera(*EYE, 1.0, GW, HC)
        same = g.Camera(*EYE, 1.0, GW, HC, eye=EYE)
        assert same.eye is None and same.offset == (0.0, 0.0)
        assert same.plane(GW * 2, HC * 4) == plain.plane(GW * 2, HC * 4)
        assert same.affine == plain.affine

    def test_a_window_off_its_eye_is_the_centred_one_slid_over(self):
        centred = g.Camera(*EYE, 1.0, GW, HC)
        lat, lon = _over(30, 6, 1.0)
        over = g.Camera(lat, lon, 1.0, GW, HC, eye=EYE)
        assert over.eye == EYE and over.lat0 == EYE[0]
        for plon, plat in ((11.5, 47.3), (11.0, 47.0), (12.0, 47.6)):
            x0, y0 = centred.cell(plon, plat)
            x1, y1 = over.cell(plon, plat)
            assert (x0 - x1, y0 - y1) == pytest.approx((30, 6), abs=1e-8)
        l0 = centred.geometry(GW, HC * 2)[0]
        l1 = over.geometry(GW, HC * 2)[0]
        for y in range(12, HC * 2, 7):
            for x in range(0, GW - 30, 11):
                assert l0[y][x + 30] == pytest.approx(l1[y - 12][x], abs=1e-9)

    def test_ground_and_screen_cell_agree_off_the_eye(self):
        lat, lon = _over(-25, 9, 0.3)
        cam = g.Camera(lat, lon, 0.3, GW, HC, eye=EYE)
        for col, row in ((0, 0), (80, 21), (159, 42)):
            at = cam.ground(col, row)
            assert cam.screen_cell(at[1], at[0]) == (col, row)
        assert cam.screen_cell(lon, lat) == (GW // 2, HC // 2)

    def test_an_eye_over_the_horizon_is_refused(self):
        cam = g.Camera(47.0, 11.0, 1.0, GW, HC, eye=(-47.0, -169.0))
        assert cam.eye is None

    def test_a_window_off_its_eye_is_never_the_box(self):
        lat, lon = _over(3, 0, 0.01)
        assert g.Camera(*EYE, 0.01, GW, HC).affine
        assert not g.Camera(lat, lon, 0.01, GW, HC, eye=EYE).affine

    def test_the_crop_index_between_two_crops_of_one_plane_translates(self):
        a = g.Camera(*_over(4, 2, 1.0), 1.0, GW, HC, eye=EYE)
        b = g.Camera(*_over(10, -3, 1.0), 1.0, GW, HC, eye=EYE)
        idx = g.crop_index(a, b, GW, HC, GW, HC)
        # b sits six columns east of a and five rows up it, so b's cell
        # (x, y) is a's cell (x + 6, y - 5), and b's top five rows are
        # ground a never held
        for y in range(5, HC, 9):
            for x in range(0, GW - 6, 13):
                assert idx[y * GW + x] == (y - 5) * GW + (x + 6)
        assert idx[0] == -1

    def test_lean_is_the_meridians_convergence(self):
        lean, arc = g.lean(*EYE, EYE[0], EYE[1] + 6.0)
        assert lean == pytest.approx(6.0 * math.sin(math.radians(EYE[0])),
                                     abs=0.15)
        assert arc == pytest.approx(6.0 * math.cos(math.radians(EYE[0])),
                                    abs=0.05)
        assert g.lean(*EYE, *EYE) == (0.0, 0.0)


class TestTheFramesEye:
    def test_a_frame_without_an_eye_looks_down_at_its_centre(self):
        bbox = bbox_for(*EYE, 1.0, GW, HC)
        frame = o.window_frame(bbox, GW, HC)
        assert frame.eye is None
        assert frame.eye_point == pytest.approx(EYE)
        assert o.window_frame(bbox, GW, HC, EYE).eye == EYE

    def test_a_window_on_the_plane_is_a_whole_cell_crop_of_a_frame_on_it(self):
        bbox = bbox_for(*EYE, 1.0, GW, HC)
        frame, at = o.plan(bbox, GW, HC, eye=EYE)
        assert frame.eye == EYE
        assert o.locate(frame, bbox, GW, HC, cap=g.cap(1.0, GW, HC),
                        eye=EYE) == at
        # a drag's worth over, on the plane: still a crop, exactly
        over = bbox_for(*_over(7, -3, 1.0), 1.0, GW, HC)
        assert o.locate(frame, over, GW, HC, cap=g.cap(1.0, GW, HC),
                        eye=EYE) == (at[0] + 7, at[1] - 3)

    def test_a_margin_ahead_is_planned_on_the_plane(self):
        bbox = bbox_for(*EYE, 1.0, GW, HC)
        frame, at = o.plan(bbox, GW, HC, ahead=(1, -1), eye=EYE)
        pw, ph = o.padding(GW, HC)
        assert at == (0, 2 * ph)           # all the margin east and north
        assert o.locate(frame, bbox, GW, HC, cap=g.cap(1.0, GW, HC),
                        eye=EYE) == at
        for dcol in range(1, 2 * pw + 1, 5):
            over = bbox_for(*_over(dcol, 0, 1.0), 1.0, GW, HC)
            assert o.locate(frame, over, GW, HC, eye=EYE) == (dcol, 2 * ph)

    def test_a_frame_about_another_eye_is_no_exact_crop(self):
        bbox = bbox_for(*EYE, 1.0, GW, HC)
        frame, _at = o.plan(bbox, GW, HC, eye=EYE)
        other = (EYE[0] + 0.5, EYE[1] - 0.5)
        cap = g.cap(1.0, GW, HC)
        assert o.locate(frame, bbox, GW, HC, cap=cap, eye=other) is None
        # a window looking down at its own centre is about that centre:
        # at the eye it is a crop of the frame, a few cells over it is
        # a window about another point
        assert o.locate(frame, bbox, GW, HC, cap=cap) is not None
        over = bbox_for(*_over(3, 0, 1.0), 1.0, GW, HC)
        assert o.locate(frame, over, GW, HC, cap=cap) is None
        # and a frame looking down at its centre is a frame about that eye
        down, at = o.plan(bbox, GW, HC)
        assert o.locate(down, bbox, GW, HC, cap=cap, eye=EYE) == at

    def test_another_zoom_on_the_same_plane_is_another_view(self):
        bbox = bbox_for(*EYE, 1.0, GW, HC)
        frame, _at = o.plan(bbox, GW, HC, eye=EYE)
        closer = bbox_for(*EYE, 0.5, GW, HC)
        assert o.locate(frame, closer, GW, HC, eye=EYE) is None


class TestTheKeysAndTheViewInHand:
    def test_the_eye_is_part_of_a_views_key(self):
        bbox = bbox_for(*EYE, 1.0, GW, HC)
        plain = loaders._view_key(bbox, GW, HC)
        assert loaders._view_key(bbox, GW, HC, None) == plain
        eyed = loaders._view_key(bbox, GW, HC, EYE)
        assert eyed != plain and eyed[:len(plain)] == plain

    def test_the_view_in_hand_remembers_its_eye(self):
        assert maps._eye_of("street", ("bbox", 8, 4, "fills", "layer")) is None
        assert maps._eye_of("street", ("bbox", 8, 4, "f", "l", {}, EYE)) == EYE
        terrain = ("bbox", 8, 4) + (None,) * 8 + (EYE,)
        assert maps._eye_of("terrain", terrain) == EYE
        assert maps._eye_of("terrain", terrain[:11]) is None


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def _camera(lat=EYE[0], lon=EYE[1], zoom=1.0):
    cam = LiveCamera(lat, lon, zoom, clock=_Clock())
    cam.gw, cam.hc = GW, HC
    return cam


class TestTheLiveCamera:
    def test_a_press_hangs_the_plane_where_the_window_is(self):
        cam = _camera()
        assert cam.eye is None
        cam.press()
        assert cam.eye == EYE
        cam.drag(12, -4)
        assert cam.eye == EYE
        assert (cam.lat, cam.lon) == pytest.approx(_over(-12, 4, 1.0), abs=1e-9)
        cam.release()
        assert cam.eye == EYE                 # kept for the next drag

    def test_a_second_press_keeps_the_plane(self):
        cam = _camera()
        cam.press()
        cam.drag(5, 0)
        cam.release()
        cam.press()
        assert cam.eye == EYE

    def test_the_planet_takes_no_eye(self):
        cam = _camera(zoom=60.0)
        cam.press()
        assert cam.eye is None

    def test_a_keyed_pan_hangs_the_plane_too(self):
        cam = _camera()
        cam.pan_by(10, 0)
        assert cam.eye == EYE
        cam.clock.advance(5.0)
        cam.view()
        assert (cam.lat, cam.lon) == pytest.approx(_over(-10, 0, 1.0), abs=1e-9)

    def test_a_flight_and_a_jump_put_the_plane_down(self):
        cam = _camera()
        cam.press()
        cam.release()
        cam.fly_to(48.0, 12.0, 0.5)
        assert cam.eye is None
        cam.press()
        cam.release()
        assert cam.eye is not None
        cam.jump_to(46.0, 10.0, 1.0)
        assert cam.eye is None

    def test_a_zoom_keeps_the_plane(self):
        cam = _camera()
        cam.press()
        cam.release()
        cam.zoom_to(0.5)
        assert cam.eye == EYE

    def test_a_flick_rests_on_a_whole_cell_of_the_plane(self):
        cam = _camera()
        cam.press()
        cam.drag(0, 0)
        cam.clock.advance(0.05)
        cam.drag(-20, 3)
        cam.release()
        assert cam._coast is not None
        lat, lon = cam.coast_destination()
        ux, uy, _c = g.forward(lat, lon, *EYE)
        rx, r = cam._cells_per_unit()
        assert ux * rx == pytest.approx(round(ux * rx), abs=1e-6)
        assert uy * r == pytest.approx(round(uy * r), abs=1e-6)
        cam.clock.advance(5.0)
        cam.view()
        assert not cam.moving()
        assert (cam.lat, cam.lon) == pytest.approx((lat, lon), abs=1e-9)

    def test_the_plane_is_overdrawn_past_the_lean_or_the_arc(self):
        cam = _camera()
        cam.press()
        assert not cam.eye_overdrawn()
        cam.lat, cam.lon = EYE[0], EYE[1] + 1.0
        assert not cam.eye_overdrawn()
        cam.lat, cam.lon = EYE[0], EYE[1] + (LEAN_MAX + 1.0) / math.sin(
            math.radians(EYE[0]))
        assert cam.eye_overdrawn()
        cam.lat, cam.lon = EYE[0] + ARC_MAX + 1.0, EYE[1]   # due north: no lean
        assert cam.eye_overdrawn()
