"""Map loaders reuse exact scenes synchronously inside their bounded owner."""

import sys
import threading
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast import _maps_views
from linecast._maps_camera import MapCamera
from linecast._scenes import Memo


@pytest.fixture(params=("elevation", "street", "globe"))
def loader(request, monkeypatch):
    """Real loader/memo behavior with tiny deterministic primary sources."""
    calls, fail = [], [False]

    def fetched():
        calls.append(threading.get_ident())
        if fail[0]:
            raise RuntimeError("primary source offline")

    kind = request.param
    cache = Memo(keep=2)
    cache_name = {"elevation": "_elev_cache", "street": "_street_cache",
                  "globe": "_globe_cache"}[kind]
    monkeypatch.setattr(_maps_views, cache_name, cache)
    if kind == "elevation":
        def elevation(bbox, w, h, **kwargs):
            fetched()
            return [[100.] * w for _ in range(h)]

        monkeypatch.setattr(_maps_views, "elevation_grid", elevation)
        monkeypatch.setattr(_maps_views, "_tile_water", lambda camera: (None,) * 4)
        monkeypatch.setattr(_maps_views, "_builtup_layer", lambda camera: None)
        load = _maps_views._get_elevation
    elif kind == "street":
        def tiles(keys):
            fetched()
            return {keys[0]: object()}

        monkeypatch.setattr(_maps_views._maps_streets, "view_tiles",
                            lambda *args, **kwargs: (0, 1, [(1, 0, 0)]))
        monkeypatch.setattr(_maps_views._maps_streets, "fetch_tiles", tiles)
        monkeypatch.setattr(_maps_views._maps_streets, "build_street_view",
                            lambda *args, **kwargs: (object(), object(), {}))
        load = _maps_views._get_street
    else:
        def elevation(lls, zoom, h):
            fetched()
            return [[100.] * len(row) for row in lls]

        globe = _maps_views._globe
        monkeypatch.setattr(globe, "geometry", lambda lat, lon, zoom, w, h:
                            ([[(lat, lon)] * w for _ in range(h)], None, None))
        monkeypatch.setattr(globe, "elevation", elevation)
        for name in ("atmosphere", "lake_mask", "ice_cover", "border_layer", "limb_lls"):
            monkeypatch.setattr(globe, name, lambda *args: None)
        load = _maps_views._get_globe
    return load, cache, calls, fail


def test_primary_load_runs_on_the_caller_and_exact_repaints_reuse_it(loader):
    load, cache, calls, _ = loader
    camera = MapCamera(40, -73, .01, 4, 2)
    first = load(camera)
    assert load(replace(camera)) is first
    assert calls == [threading.get_ident()]
    assert len(cache) == 1


def test_camera_changes_miss_and_old_geography_is_evicted_within_the_bound(loader):
    load, cache, calls, _ = loader
    camera = MapCamera(40, -73, .01, 4, 2)
    first = load(camera)
    moved = load(replace(camera, lon=camera.lon + 1e-8))
    resized = load(replace(camera, gw=6))
    assert moved is not first and resized is not first
    assert len(cache) == 2
    assert load(camera) is not first
    assert len(calls) == 4 and len(cache) == 2


def test_theme_change_misses_prepared_source_colours(loader, monkeypatch):
    load, _, calls, _ = loader
    camera = MapCamera(40, -73, .01, 4, 2)
    first = load(camera)
    monkeypatch.setattr(_maps_views._theme, "generation", _maps_views._theme.generation + 1)
    assert load(camera) is not first
    assert len(calls) == 2


def test_primary_failure_propagates_and_is_not_cached(loader):
    load, cache, calls, fail = loader
    camera = MapCamera(40, -73, .01, 4, 2)
    fail[0] = True
    with pytest.raises(RuntimeError, match="primary source offline"):
        load(camera)
    assert not len(cache)
    fail[0] = False
    recovered = load(camera)
    assert load(camera) is recovered
    assert len(calls) == 2


def test_missing_street_tiles_fail_without_poisoning_the_camera_cache(monkeypatch):
    cache = Memo()
    camera = MapCamera(40, -73, .01, 4, 2)
    monkeypatch.setattr(_maps_views, "_street_cache", cache)
    monkeypatch.setattr(_maps_views._maps_streets, "view_tiles",
                        lambda *args, **kwargs: (0, 1, [(1, 0, 0)]))
    monkeypatch.setattr(_maps_views._maps_streets, "fetch_tiles", lambda keys: {keys[0]: None})
    with pytest.raises(RuntimeError):
        _maps_views._get_street(camera)
    assert not len(cache)


def test_all_missing_elevation_fails_before_the_ocean_mask_can_hide_it(monkeypatch):
    camera = MapCamera(40, -73, .01, 4, 2)
    cache = Memo()
    monkeypatch.setattr(_maps_views, "_elev_cache", cache)
    monkeypatch.setattr(_maps_views, "elevation_grid", lambda bbox, w, h, **kwargs:
                        [[None] * w for _ in range(h)])
    monkeypatch.setattr(_maps_views, "_tile_water", lambda camera:
                        (None, None, None, [[1] * 8 for _ in range(8)]))
    monkeypatch.setattr(_maps_views, "_builtup_layer", lambda camera: None)
    with pytest.raises(RuntimeError):
        _maps_views._get_elevation(camera)
    assert not len(cache)


def test_partial_elevation_remains_usable_and_recovers_at_the_same_camera(monkeypatch):
    camera = MapCamera(40, -73, .01, 4, 2)
    cache, calls = Memo(), []
    monkeypatch.setattr(_maps_views, "_elev_cache", cache)

    def elevation(bbox, w, h, **kwargs):
        calls.append(True)
        fine = [[100.] * w for _ in range(h)]
        if len(calls) == 1:
            for row in fine[:2]:
                row[:2] = [None, None]
        return fine

    monkeypatch.setattr(_maps_views, "elevation_grid", elevation)
    monkeypatch.setattr(_maps_views, "_tile_water", lambda camera: (None,) * 4)
    monkeypatch.setattr(_maps_views, "_builtup_layer", lambda camera: None)
    partial = _maps_views._get_elevation(camera)
    assert not partial.complete and partial.elev[0] == [None, 100., 100., 100.]
    assert not len(cache)
    recovered = _maps_views._get_elevation(camera)
    assert recovered.complete and recovered.elev[0] == [100.] * 4
    assert _maps_views._get_elevation(camera) is recovered
    assert len(calls) == 2 and len(cache) == 1


def test_partial_street_tiles_remain_usable_and_recover_at_the_same_camera(monkeypatch):
    camera = MapCamera(40, -73, .01, 4, 2)
    keys = [(1, 0, 0), (1, 1, 0)]
    cache, calls, painted = Memo(), [], []
    monkeypatch.setattr(_maps_views, "_street_cache", cache)
    monkeypatch.setattr(_maps_views._maps_streets, "view_tiles",
                        lambda *a, **kw: (0, 1, keys))

    def fetch(keys):
        calls.append(True)
        return {keys[0]: b"land", keys[1]: None if len(calls) == 1 else b""}

    def build(bbox, w, h, tiles, *args, **kwargs):
        painted.append(tiles.copy())
        return "usable fills", "usable streets", {}

    monkeypatch.setattr(_maps_views._maps_streets, "fetch_tiles", fetch)
    monkeypatch.setattr(_maps_views._maps_streets, "build_street_view", build)
    partial = _maps_views._get_street(camera)
    assert not partial.complete and partial.fills == "usable fills"
    assert painted == [{keys[0]: b"land", keys[1]: None}] and not len(cache)
    recovered = _maps_views._get_street(camera)
    assert recovered.complete  # a fetched empty tile is complete, unlike a failed fetch
    assert _maps_views._get_street(camera) is recovered
    assert len(calls) == 2 and len(cache) == 1


def test_incomplete_terrain_colours_cannot_poison_a_recovered_camera(monkeypatch):
    camera = MapCamera(40, -73, .01, 4, 2)
    cache, colours = Memo(), []
    monkeypatch.setattr(_maps_views, "_terrain_cache", cache)
    monkeypatch.setattr(_maps_views._climate, "grid_for_lls", lambda *a: None)

    def paint(elev, *args, **kwargs):
        colours.append(elev)
        return object()

    monkeypatch.setattr(_maps_views, "build_terrain_buffer", paint)
    partial = _maps_views._terrain_buffer([[None, 100.]], camera, complete=False)
    assert not len(cache)
    recovered = _maps_views._terrain_buffer([[100., 100.]], camera)
    assert recovered is not partial
    assert _maps_views._terrain_buffer([[100., 100.]], camera) is recovered
    assert colours == [[[None, 100.]], [[100., 100.]]]


def test_optional_source_failure_keeps_elevation_available(monkeypatch):
    camera = MapCamera(40, -73, .01, 4, 2)
    monkeypatch.setattr(_maps_views, "_elev_cache", Memo())
    monkeypatch.setattr(_maps_views, "elevation_grid", lambda bbox, w, h, **kwargs:
                        [[100.] * w for _ in range(h)])

    def fail(*args, **kwargs):
        raise RuntimeError("optional source offline")

    monkeypatch.setattr(_maps_views._maps_streets, "fetch_view", fail)
    monkeypatch.setattr(_maps_views._builtup, "enabled", lambda: True)
    monkeypatch.setattr(_maps_views._builtup, "builtup_grid", fail)
    view = _maps_views._get_elevation(camera)
    assert view.elev == [[100.] * 4 for _ in range(4)]
    assert view.water is None and view.rivers is None and view.cover is None


def test_street_label_cache_accounts_for_language_and_reserved_cells(monkeypatch):
    camera = MapCamera(40, -73, .01, 4, 2)
    monkeypatch.setattr(_maps_views, "_street_cache", Memo())
    monkeypatch.setattr(_maps_views._maps_streets, "view_tiles",
                        lambda *args, **kwargs: (0, 1, [(1, 0, 0)]))
    monkeypatch.setattr(_maps_views._maps_streets, "fetch_tiles", lambda keys: {keys[0]: object()})
    monkeypatch.setattr(_maps_views._maps_streets, "build_street_view",
                        lambda *args, **kwargs: (object(), object(), {}))
    first = _maps_views._get_street(camera, "en", ((0, 0), (1, 1)))
    assert _maps_views._get_street(camera, "en", ((1, 1), (0, 0))) is first
    assert _maps_views._get_street(camera, "ja", ((0, 0), (1, 1))) is not first
    assert _maps_views._get_street(camera, "en", ((0, 0),)) is not first
