"""Tests for the RainViewer XYZ-tile fetch + Web-Mercator reprojection.

No network access: _fetch_tile is monkeypatched to return synthetic,
programmatically-built PNG bytes rather than hitting the real API.
"""

import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast import _radar_rainviewer as rv
from linecast._radar_rainviewer import (
    _lonlat_to_world, _pick_zoom, _tile_url, reproject, _MAX_ZOOM, _TILE_SIZE,
)

_SIG = b"\x89PNG\r\n\x1a\n"


def _chunk(ctype, data):
    return (struct.pack(">I", len(data)) + ctype + data
            + struct.pack(">I", zlib.crc32(ctype + data) & 0xFFFFFFFF))


def _solid_png(width, height, r, g, b, a):
    """A filter-0, color-type-6 (RGBA) PNG filled with one solid color."""
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    row = bytes([0]) + bytes([r, g, b, a]) * width  # filter byte + pixels
    idat = zlib.compress(row * height)
    return b"".join([
        _SIG,
        _chunk(b"IHDR", ihdr),
        _chunk(b"IDAT", idat),
        _chunk(b"IEND", b""),
    ])


class TestLonLatToWorld:
    def test_origin(self):
        x, y = _lonlat_to_world(0.0, 0.0)
        assert x == 0.5
        assert y == 0.5

    def test_lon_180_maps_to_x_1(self):
        x, _y = _lonlat_to_world(180.0, 0.0)
        assert x == 1.0

    def test_lat_clamping_near_poles_does_not_crash(self):
        for lat in (89.9, 90.0, 95.0, -89.9, -90.0, -95.0):
            x, y = _lonlat_to_world(0.0, lat)
            assert 0.0 <= x <= 1.0
            assert -1.0 <= y <= 2.0  # not asserting exact clamp, just sane/no crash

    def test_y_decreases_as_lat_increases(self):
        _, y_low = _lonlat_to_world(0.0, 10.0)
        _, y_high = _lonlat_to_world(0.0, 50.0)
        assert y_high < y_low


class TestPickZoom:
    def test_never_exceeds_max_zoom(self):
        for bbox, w in [((-180, -80, 180, 80), 4096),
                         ((-1, -1, 1, 1), 4096),
                         ((-0.01, -0.01, 0.01, 0.01), 8192)]:
            assert _pick_zoom(bbox, w) <= _MAX_ZOOM

    def test_wider_bbox_gives_lower_zoom(self):
        w = 1024
        z_wide = _pick_zoom((-180, -80, 180, 80), w)
        z_narrow = _pick_zoom((-1, -1, 1, 1), w)
        assert z_wide < z_narrow

    def test_never_negative(self):
        assert _pick_zoom((-180, -80, 180, 80), 1) >= 0


class TestTileUrl:
    def test_exact_format(self):
        url = _tile_url("https://h", "/v2/radar/abc", 5, 3, 7)
        assert url == "https://h/v2/radar/abc/256/5/3/7/2/1_1.png"


class TestReproject:
    def _patch_fetch_tile(self, fn):
        original = rv._fetch_tile
        rv._fetch_tile = fn
        return original

    def test_solid_tile_resamples_to_known_color(self):
        color = (100, 150, 200, 255)
        png = _solid_png(_TILE_SIZE, _TILE_SIZE, *color)
        original = self._patch_fetch_tile(lambda *a, **k: png)
        try:
            bbox = (-10.0, -10.0, 10.0, 10.0)
            w, h = 4, 4
            out_w, out_h, out = reproject("https://host", "/path", bbox, w, h)
        finally:
            rv._fetch_tile = original

        assert (out_w, out_h) == (w, h)
        assert isinstance(out, bytearray)
        assert len(out) == w * h * 4

        cx, cy = w // 2, h // 2
        i = (cy * w + cx) * 4
        assert tuple(out[i:i + 4]) == color

    def test_missing_tile_yields_fully_transparent_output(self):
        original = self._patch_fetch_tile(lambda *a, **k: None)
        try:
            bbox = (-10.0, -10.0, 10.0, 10.0)
            w, h = 4, 4
            out_w, out_h, out = reproject("https://host", "/path", bbox, w, h)
        finally:
            rv._fetch_tile = original

        assert (out_w, out_h) == (w, h)
        assert len(out) == w * h * 4
        assert all(v == 0 for v in out)
