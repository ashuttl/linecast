"""Tests for the radar condition layers (temperature tint, wind arrows)."""

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast import _color
from linecast._color import BG_PRIMARY, lerp
from linecast._radar_layers import (
    Field, TEMP_STOPS, build_temp_buffer, field_key, wind_color,
    wind_overlays,
)
from linecast._radar_render import compose
from linecast.radar import parse_layers

_ANSI_RE = re.compile(r"\033\[[^m]*m")


def _make_field(nx=2, ny=2, temps=None, u=None, v=None, n_times=1):
    """A tiny hand-built field over bbox (0, 0, 10, 10)."""
    lats = [10.0 - j * 10.0 / (ny - 1) for j in range(ny)]
    lons = [i * 10.0 / (nx - 1) for i in range(nx)]
    npts = nx * ny
    payload = {
        "lats": lats,
        "lons": lons,
        "times": ["2026-07-14T%02d:00" % h for h in range(n_times)],
        "temp": temps or [[20.0] * n_times] * npts,
        "u": u or [[0.0] * n_times] * npts,
        "v": v or [[0.0] * n_times] * npts,
    }
    return Field(payload)


class TestFieldSampling:
    def test_uniform_field_samples_uniform(self):
        f = _make_field()
        assert f.sample_temp(0, 5.0, 5.0) == 20.0
        assert f.sample_temp(0, 0.0, 10.0) == 20.0

    def test_bilinear_midpoint(self):
        # corners: nw=0, ne=10, sw=20, se=30 → centre = mean = 15
        f = _make_field(temps=[[0.0], [10.0], [20.0], [30.0]])
        assert abs(f.sample_temp(0, 5.0, 5.0) - 15.0) < 0.2
        # north edge midpoint: between nw and ne
        assert abs(f.sample_temp(0, 5.0, 10.0) - 5.0) < 0.2

    def test_sample_clamps_outside_bbox(self):
        f = _make_field(temps=[[0.0], [10.0], [20.0], [30.0]])
        assert f.sample_temp(0, -100.0, 100.0) == 0.0  # nw corner

    def test_wind_direction_recovered_from_vectors(self):
        # pure northward flow: u=0, v=+10 → bearing 0°, speed 10
        f = _make_field(u=[[0.0]] * 4, v=[[10.0]] * 4)
        speed, bearing = f.sample_wind(0, 5.0, 5.0)
        assert abs(speed - 10.0) < 1e-9
        assert bearing == 0.0
        # pure eastward flow: u=+10 → bearing 90°
        f = _make_field(u=[[10.0]] * 4, v=[[0.0]] * 4)
        _, bearing = f.sample_wind(0, 5.0, 5.0)
        assert abs(bearing - 90.0) < 1e-9

    def test_wind_interpolation_crosses_north_correctly(self):
        # NW wind on one side, NE wind on the other must average to N,
        # not to S (the 0°/360° wrap bug vector components avoid)
        import math
        s = 10.0 / math.sqrt(2)
        f = _make_field(u=[[-s], [s], [-s], [s]], v=[[s], [s], [s], [s]])
        _, bearing = f.sample_wind(0, 5.0, 5.0)
        assert bearing == 0.0

    def test_nearest_time_idx(self):
        import datetime
        f = _make_field(n_times=3)
        when = datetime.datetime(2026, 7, 14, 1, 20,
                                 tzinfo=datetime.timezone.utc)
        assert f.nearest_time_idx(when) == 1
        when = datetime.datetime(2026, 7, 14, 1, 40,
                                 tzinfo=datetime.timezone.utc)
        assert f.nearest_time_idx(when) == 2


class TestFieldKey:
    def test_snaps_outward(self):
        key = field_key((-71.13, 42.11, -70.87, 42.39))
        assert key == (-71.25, 42.0, -70.75, 42.5)

    def test_nearby_views_share_a_key(self):
        a = field_key((-71.13, 42.11, -70.87, 42.39))
        b = field_key((-71.14, 42.12, -70.88, 42.38))
        assert a == b


class TestTempBuffer:
    def test_shape_and_tint(self):
        f = _make_field()
        buf = build_temp_buffer(f, 0, (0, 0, 10, 10), 8, 4)
        assert len(buf) == 8 and len(buf[0]) == 8
        # uniform 20°C field → every sub-pixel is the same tinted color,
        # blended halfway toward the terminal background
        from linecast._color import interp_stops
        expected = lerp(BG_PRIMARY, interp_stops(TEMP_STOPS, 20.0), 0.5)
        assert buf[0][0] == expected
        assert buf[7][7] == expected


class TestWindOverlays:
    def test_arrow_points_where_wind_blows(self):
        f = _make_field(u=[[0.0]] * 4, v=[[10.0]] * 4)  # northward
        ov = wind_overlays(f, 0, (0, 0, 10, 10), 40, 12)
        assert ov, "expected arrows on the lattice"
        chars = {ch for ch, _color in ov.values()}
        assert chars == {"↑"}

    def test_calm_draws_nothing(self):
        f = _make_field()  # zero wind everywhere
        ov = wind_overlays(f, 0, (0, 0, 10, 10), 40, 12)
        assert ov == {}

    def test_speed_sets_contrast_not_hue(self):
        from linecast._theme import contrast_ratio, theme_bg
        assert wind_color(0.0) is None
        assert wind_color(4.0) is None  # lightest breeze stays invisible
        breeze, gale = wind_color(12.0), wind_color(70.0)
        # neutral: on the bg→fg axis, both are grays (channels near-equal
        # when fg/bg are), and faster wind stands out more from the bg
        assert contrast_ratio(gale, theme_bg) > contrast_ratio(breeze,
                                                               theme_bg)
        ov = wind_overlays(_make_field(u=[[60.0]] * 4, v=[[0.0]] * 4),
                           0, (0, 0, 10, 10), 40, 12)
        assert {color for _ch, color in ov.values()} == {wind_color(60.0)}


class TestParseLayers:
    def test_aliases(self):
        assert parse_layers("temp,wind") == frozenset({"temp", "wind"})
        assert parse_layers("Temperature; W") == frozenset({"temp", "wind"})
        assert parse_layers("") == frozenset()

    def test_unknown_layer_is_an_error(self):
        assert parse_layers("temp,plasma") is None


class TestComposeUnder:
    # color mode resolves to "none" under pytest (no tty); force truecolor
    # so the tint's escape codes are observable.  Patch the module imported
    # at the top of this file — the same generation compose() reads even
    # after test_oneline purges sys.modules
    @pytest.fixture(autouse=True)
    def _truecolor(self, monkeypatch):
        monkeypatch.setattr(_color, "_COLOR_MODE", "truecolor")

    def test_under_fills_empty_cells_and_backs_braille(self):
        gw, hc = 2, 1
        radar = [[None] * gw for _ in range(hc * 2)]
        tint = (60, 40, 40)
        under = [[tint] * gw for _ in range(hc * 2)]

        class FakeBasemap:
            dots = [[0, 0x01]]
            color = [[None, (120, 150, 178)]]

        lines = compose(FakeBasemap(), radar, {}, gw, hc, under=under)
        # empty cell renders the tint as a half-block pair, braille cell
        # renders the geography glyph over a tinted background
        assert "⠁" in lines[0]
        assert f"48;2;{tint[0]};{tint[1]};{tint[2]}" in lines[0]

    def test_radar_echo_beats_under(self):
        gw, hc = 1, 1
        echo = (200, 30, 30)
        radar = [[echo], [None]]
        under = [[(60, 40, 40)], [(60, 40, 40)]]

        class FakeBasemap:
            dots = [[0]]
            color = [[None]]

        lines = compose(FakeBasemap(), radar, {}, gw, hc, under=under)
        # halfblock: top sub-pixel is the bg code, bottom (▄) the fg code —
        # echo owns the top, the tint backfills the bottom
        assert f"48;2;{echo[0]};{echo[1]};{echo[2]}" in lines[0]
        assert "38;2;60;40;40" in lines[0]

    def test_no_under_matches_previous_behavior(self):
        gw, hc = 1, 1
        radar = [[None], [None]]

        class FakeBasemap:
            dots = [[0]]
            color = [[None]]

        lines = compose(FakeBasemap(), radar, {}, gw, hc)
        assert _ANSI_RE.sub("", lines[0]) == " "
