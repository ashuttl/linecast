"""Tests for the provider-parameterized XYZ-tile fetch + reprojection.

No network access: _fetch_tile is monkeypatched to return synthetic,
programmatically-built PNG bytes rather than hitting the real API, and the
cache-policy tests run against a temp directory with urlopen stubbed.
"""

import os
import struct
import sys
import tempfile
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast import _radar_tiles as tiles
from linecast._radar_tiles import (
    _lonlat_to_world, _pick_zoom, _tile_url, reproject, _TILE_SIZE,
    librewxr_provider, rainviewer_provider,
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


class TestProviders:
    def test_rainviewer_free_tier_constants(self):
        p = rainviewer_provider()
        assert (p.name, p.color, p.max_zoom) == ("rv", 2, 7)

    def test_librewxr_carries_colour_and_deep_zoom(self):
        p = librewxr_provider(7)
        assert (p.name, p.color, p.max_zoom) == ("lwxr", 7, 12)
        assert p.index_url == "https://api.librewxr.net/public/weather-maps.json"

    def test_librewxr_base_url_env_override(self):
        os.environ["LINECAST_LIBREWXR_URL"] = "http://selfhost:8080/"
        try:
            p = librewxr_provider(2)
        finally:
            del os.environ["LINECAST_LIBREWXR_URL"]
        assert p.index_url == "http://selfhost:8080/public/weather-maps.json"


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
            assert _pick_zoom(bbox, w, 7) <= 7

    def test_deep_zoom_ceiling_honoured(self):
        z = _pick_zoom((-0.01, -0.01, 0.01, 0.01), 8192, 12)
        assert 7 < z <= 12

    def test_wider_bbox_gives_lower_zoom(self):
        w = 1024
        z_wide = _pick_zoom((-180, -80, 180, 80), w, 7)
        z_narrow = _pick_zoom((-1, -1, 1, 1), w, 7)
        assert z_wide < z_narrow

    def test_never_negative(self):
        assert _pick_zoom((-180, -80, 180, 80), 1, 7) >= 0


class TestTileUrl:
    def test_rainviewer_exact_format(self):
        url = _tile_url(rainviewer_provider(), "https://h", "/v2/radar/abc", 5, 3, 7)
        assert url == "https://h/v2/radar/abc/256/5/3/7/2/1_1.png"

    def test_librewxr_colour_lands_in_url(self):
        url = _tile_url(librewxr_provider(9), "https://h", "/v2/radar/abc", 5, 3, 7)
        assert url == "https://h/v2/radar/abc/256/5/3/7/9/1_1.png"


class TestTileCachePolicy:
    """Disk-cache behaviour: per-colour keys, nowcast TTL, stale fallback."""

    def _run(self, mutable, age, urlopen):
        provider = librewxr_provider(2)
        original_root, original_open = tiles.CACHE_ROOT, tiles.urllib.request.urlopen
        with tempfile.TemporaryDirectory() as tmp:
            tiles.CACHE_ROOT = Path(tmp)
            cdir = tiles._cache_dir(provider)
            cdir.mkdir(parents=True)
            cpath = cdir / "v2_radar_123_3_1_1_c2_1_1.png"
            cpath.write_bytes(b"CACHED")
            stamp = os.stat(cpath).st_mtime - age
            os.utime(cpath, (stamp, stamp))
            tiles.urllib.request.urlopen = urlopen
            try:
                return tiles._fetch_tile(provider, "https://h", "/v2/radar/123",
                                         3, 1, 1, mutable=mutable)
            finally:
                tiles.CACHE_ROOT = original_root
                tiles.urllib.request.urlopen = original_open

    class _Fresh:
        _body = b"FRESH"

        def read(self, n=-1):
            body, self._body = self._body, b""
            return body

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def test_immutable_tile_served_from_cache_forever(self):
        def no_network(*a, **k):
            raise AssertionError("immutable cached tile must not refetch")
        assert self._run(False, age=100000, urlopen=no_network) == b"CACHED"

    def test_fresh_nowcast_tile_served_from_cache(self):
        def no_network(*a, **k):
            raise AssertionError("fresh nowcast tile must not refetch")
        assert self._run(True, age=60, urlopen=no_network) == b"CACHED"

    def test_stale_nowcast_tile_refetched(self):
        assert self._run(True, age=700,
                         urlopen=lambda *a, **k: self._Fresh()) == b"FRESH"

    def test_stale_nowcast_falls_back_to_cache_when_offline(self):
        def offline(*a, **k):
            raise OSError("no network")
        assert self._run(True, age=700, urlopen=offline) == b"CACHED"


class TestReproject:
    def _patch_fetch_tile(self, fn):
        original = tiles._fetch_tile
        tiles._fetch_tile = fn
        return original

    def test_solid_tile_resamples_to_known_color(self):
        color = (100, 150, 200, 255)
        png = _solid_png(_TILE_SIZE, _TILE_SIZE, *color)
        original = self._patch_fetch_tile(lambda *a, **k: png)
        try:
            bbox = (-10.0, -10.0, 10.0, 10.0)
            w, h = 4, 4
            out_w, out_h, out = reproject(rainviewer_provider(),
                                          "https://host", "/path", bbox, w, h)
        finally:
            tiles._fetch_tile = original

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
            out_w, out_h, out = reproject(rainviewer_provider(),
                                          "https://host", "/path", bbox, w, h)
        finally:
            tiles._fetch_tile = original

        assert (out_w, out_h) == (w, h)
        assert len(out) == w * h * 4
        assert all(v == 0 for v in out)


class TestSmoothGray:
    """Bilinear resample for raw reflectivity tiles."""

    def _canvas(self, pixels, w, h):
        buf = bytearray(w * h * 4)
        for (x, y), (gray, a) in pixels.items():
            i = (y * w + x) * 4
            buf[i] = buf[i + 1] = buf[i + 2] = gray
            buf[i + 3] = a
        return buf

    def _run(self, canvas, w, h, out_w, out_h):
        # world = canvas size so 1 canvas px == 1/world of the world; bbox
        # covering exactly the canvas in lon (lat is mercator, keep it tiny
        # and symmetric so rows map ~linearly)
        from linecast._radar_tiles import _smooth_gray
        return _smooth_gray(canvas, w, h, 0, 0, w, (-180, -0.5, 180, 0.5),
                            out_w, out_h)

    def test_edge_fades_and_keeps_intensity(self):
        # left half covered at 60 gray, right half transparent; 2 canvas
        # px wide, sample 4 output px across: centre samples straddle
        canvas = self._canvas({(0, 0): (60, 255)}, 2, 1)
        _w, _h, out = self._run(canvas, 2, 1, 4, 1)
        alphas = [out[i * 4 + 3] for i in range(4)]
        grays = [out[i * 4] for i in range(4) if out[i * 4 + 3]]
        assert alphas[0] == 255 and alphas[-1] == 0
        assert 0 < alphas[2] < 255  # the fade
        assert all(g == 60 for g in grays)  # never darkened by the gap

    def test_snow_bit_by_majority(self):
        canvas = self._canvas({(0, 0): (128 + 50, 255), (1, 0): (50, 255)},
                              2, 1)
        _w, _h, out = self._run(canvas, 2, 1, 4, 1)
        assert out[0] >= 128 and out[12] < 128
        assert all((out[i * 4] & 127) == 50 for i in range(4))
