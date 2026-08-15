"""Tests for the vector-tile transport layer.

No network: TileJSON discovery is patched at the module and tile
fetches stub urllib's urlopen. The disk cache is redirected to a
temporary directory per test.
"""

import gzip
import io
import sys
import urllib.request
from pathlib import Path

import pytest

# Ensure the worktree src is preferred over any installed version.
# (No sys.modules purge here: this file is collected after other test
# modules that hold references into already-imported linecast modules.)
_src = str(Path(__file__).resolve().parent.parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from linecast import _vtiles as vt

TEMPLATE = "https://tiles.example/planet/20260802_080001_pt/{z}/{x}/{y}.pbf"
TILEJSON = {"tiles": [TEMPLATE], "maxzoom": 14}


class _Resp:
    def __init__(self, body):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(vt, "CACHE_ROOT", tmp_path)
    return tmp_path


@pytest.fixture
def canned_tilejson(monkeypatch):
    monkeypatch.setattr(vt, "tilejson", lambda: dict(TILEJSON))


class TestTileInfo:
    def test_version_segment_parsed_from_template(self, canned_tilejson):
        template, version, maxzoom = vt.tile_info()
        assert template == TEMPLATE
        assert version == "20260802_080001_pt"
        assert maxzoom == 14

    def test_unversioned_template_gets_default_namespace(self, monkeypatch):
        monkeypatch.setattr(vt, "tilejson", lambda: {
            "tiles": ["https://host/osm/{z}/{x}/{y}"], "maxzoom": 14})
        assert vt.tile_info()[1] == "default"

    def test_missing_tilejson_yields_none(self, monkeypatch):
        monkeypatch.setattr(vt, "tilejson", lambda: None)
        assert vt.tile_info() is None

    def test_tilejson_disk_cache_wiring(self, cache, monkeypatch):
        seen = {}

        def fake_cached(cache_file, max_age, url, headers=None, **kw):
            seen.update(cache_file=cache_file, max_age=max_age, url=url,
                        headers=headers)
            return dict(TILEJSON)

        monkeypatch.setattr(vt, "fetch_json_cached", fake_cached)
        assert vt.tilejson() == TILEJSON
        assert seen["cache_file"] == cache / "maps" / "tilejson.json"
        assert seen["max_age"] == 86400
        assert "linecast/" in seen["headers"]["User-Agent"]

    def test_refresh_drops_the_cache_file(self, cache):
        path = cache / "maps" / "tilejson.json"
        path.parent.mkdir(parents=True)
        path.write_text("{}")
        vt.refresh_tilejson()
        assert not path.exists()
        vt.refresh_tilejson()  # idempotent when already gone


class TestSourceZoom:
    def test_matches_view_width(self):
        # lon span 0.0879° -> z_eff = log2(360/0.0879) ≈ 12.0 -> ceil 12
        assert vt.source_zoom((-70.3, 43.6, -70.2121, 43.7)) == 12

    def test_clamps_to_maxzoom(self):
        # a street-level span (0.005°) wants z ≈ 16.1 -> clamped
        assert vt.source_zoom((-70.255, 43.65, -70.250, 43.66)) == 14

    def test_world_view_clamps_to_zero(self):
        assert vt.source_zoom((-180.0, -60.0, 180.0, 60.0)) == 0


class TestTilesForBbox:
    def test_covers_portland_view(self):
        # z12: Portland ME (-70.3..-70.2) -> world x ≈ 0.6047..0.6050
        # -> tile x 1248; lat 43.6..43.7 -> tile y 1494 only
        keys = vt.tiles_for_bbox((-70.3, 43.6, -70.2, 43.7), 12)
        assert (12, 1248, 1494) in keys
        assert 1 <= len(keys) <= 4
        assert all(z == 12 for z, _x, _y in keys)

    def test_antimeridian_wraps_x(self):
        # a view past 180°E must wrap into low tile-x numbers
        keys = vt.tiles_for_bbox((179.9, -10.0, 180.4, -9.5), 8)
        xs = {x for _z, x, _y in keys}
        assert 255 in xs and 0 in xs

    def test_polar_view_clamps_y(self):
        keys = vt.tiles_for_bbox((-10.0, 84.0, 10.0, 89.9), 4)
        assert all(0 <= y < 16 for _z, _x, y in keys)


class TestFetchTile:
    def _stub(self, monkeypatch, body, calls):
        def fake_urlopen(req, timeout=0):
            calls.append(req.full_url)
            return _Resp(body)

        monkeypatch.setattr(vt.urllib.request, "urlopen", fake_urlopen)

    def test_gzip_body_decompressed_and_cached_raw(
            self, cache, canned_tilejson, monkeypatch):
        calls = []
        self._stub(monkeypatch, gzip.compress(b"tilebytes"), calls)
        assert vt.fetch_tile(14, 4994, 5978) == b"tilebytes"
        assert calls == [TEMPLATE.replace("{z}", "14")
                         .replace("{x}", "4994").replace("{y}", "5978")]
        cached = cache / "maps" / "vt" / "20260802_080001_pt" / \
            "14_4994_5978.pbf"
        assert cached.read_bytes() == b"tilebytes"  # stored decompressed

    def test_cache_hit_skips_network(self, cache, canned_tilejson,
                                     monkeypatch):
        calls = []
        self._stub(monkeypatch, gzip.compress(b"tilebytes"), calls)
        vt.fetch_tile(14, 4994, 5978)
        assert vt.fetch_tile(14, 4994, 5978) == b"tilebytes"
        assert len(calls) == 1

    def test_empty_tile_cached_and_not_refetched(
            self, cache, canned_tilejson, monkeypatch):
        # OpenFreeMap answers HTTP 200 with 0 bytes for ocean/empty
        calls = []
        self._stub(monkeypatch, b"", calls)
        assert vt.fetch_tile(14, 0, 0) == b""
        assert vt.fetch_tile(14, 0, 0) == b""
        assert len(calls) == 1

    def test_network_failure_returns_none(self, cache, canned_tilejson,
                                          monkeypatch):
        def boom(req, timeout=0):
            raise OSError("no route to host")

        monkeypatch.setattr(vt.urllib.request, "urlopen", boom)
        assert vt.fetch_tile(14, 1, 1) is None
        # a later success is not blocked by the earlier failure
        calls = []
        self._stub(monkeypatch, b"ok", calls)
        assert vt.fetch_tile(14, 1, 1) == b"ok"

    def test_no_tilejson_returns_none(self, cache, monkeypatch):
        monkeypatch.setattr(vt, "tilejson", lambda: None)
        assert vt.fetch_tile(14, 1, 1) is None

    def test_fetch_tiles_batch(self, cache, canned_tilejson, monkeypatch):
        self._stub(monkeypatch, b"x", [])
        keys = [(14, 1, 1), (14, 2, 1)]
        assert vt.fetch_tiles(keys) == {k: b"x" for k in keys}
        assert vt.fetch_tiles([]) == {}


class TestPruneVersions:
    def test_removes_only_superseded_dirs(self, cache):
        root = cache / "maps" / "vt"
        for name in ("old_version", "20260802_080001_pt"):
            (root / name).mkdir(parents=True)
            (root / name / "1_2_3.pbf").write_bytes(b"d")
        vt.prune_versions("20260802_080001_pt")
        assert not (root / "old_version").exists()
        assert (root / "20260802_080001_pt" / "1_2_3.pbf").exists()

    def test_missing_root_is_fine(self, cache):
        vt.prune_versions("anything")  # must not raise
