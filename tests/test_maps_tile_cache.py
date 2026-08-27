"""The map tile cache is swept by size, and by which vector version is live."""

import os

import pytest

from linecast import _maps_tile_cache
from linecast._maps_tile_cache import (DEFAULT_CACHE_MB, cache_limit_bytes,
                                  prune_maps_cache)

MB = 1_000_000  # decimal, as _maps_cache and doctor both count it


@pytest.fixture
def cache(tmp_path, monkeypatch):
    """A maps cache tree at a throwaway root."""
    monkeypatch.setenv("LINECAST_CACHE_DIR", str(tmp_path))
    maps = tmp_path / "maps"
    maps.mkdir(parents=True)
    return maps


def write(path, size, age_days=0):
    """A file of *size* bytes, last written *age_days* ago."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\0" * size)
    if age_days:
        when = os.stat(path).st_mtime - age_days * 86400
        os.utime(path, (when, when))
    return path


def version_is(monkeypatch, version):
    monkeypatch.setattr(_maps_tile_cache, "_current_vector_version",
                        lambda: version)


class TestStaleVectorVersions:
    def test_drops_versions_the_tilejson_no_longer_names(self, cache, monkeypatch):
        version_is(monkeypatch, "20260823_080002_pt")
        old = write(cache / "vt" / "20260816_080001_pt" / "8_128_85.pbf", 4 * MB)
        live = write(cache / "vt" / "20260823_080002_pt" / "8_128_85.pbf", 4 * MB)

        freed = prune_maps_cache()

        assert not old.parent.exists()
        assert live.exists()
        assert freed == 4 * MB

    def test_stands_down_when_the_live_version_is_unknown(self, cache, monkeypatch):
        # Offline with a cold tilejson: every version on disk may still be
        # the one being drawn from, so none of them go.
        version_is(monkeypatch, "")
        a = write(cache / "vt" / "20260816_080001_pt" / "8_128_85.pbf", 4 * MB)
        b = write(cache / "vt" / "20260823_080002_pt" / "8_128_85.pbf", 4 * MB)

        assert prune_maps_cache() == 0
        assert a.exists() and b.exists()


class TestSizeCap:
    def test_leaves_a_cache_under_the_cap_alone(self, cache, monkeypatch):
        version_is(monkeypatch, "")
        tile = write(cache / "terrarium_10_541_359.png", 2 * MB)

        assert prune_maps_cache(limit=10 * MB) == 0
        assert tile.exists()

    def test_evicts_oldest_fetched_first(self, cache, monkeypatch):
        version_is(monkeypatch, "")
        stale = write(cache / "terrarium_10_1_1.png", 4 * MB, age_days=200)
        older = write(cache / "terrarium_10_2_2.png", 4 * MB, age_days=30)
        fresh = write(cache / "terrarium_10_3_3.png", 4 * MB, age_days=1)

        freed = prune_maps_cache(limit=8 * MB)

        assert not stale.exists()
        assert older.exists() and fresh.exists()
        assert freed == 4 * MB

    def test_sweeps_vector_tiles_under_the_live_version_too(self, cache, monkeypatch):
        version_is(monkeypatch, "live")
        old = write(cache / "vt" / "live" / "8_1_1.pbf", 4 * MB, age_days=90)
        new = write(cache / "vt" / "live" / "8_2_2.pbf", 4 * MB, age_days=1)

        prune_maps_cache(limit=4 * MB)

        assert not old.exists()
        assert new.exists()

    def test_spares_the_small_artifacts_beside_the_tiles(self, cache, monkeypatch):
        # A few megabytes between them, and real work to rebuild: the cap
        # is about the tile pyramids, which are what grow.
        version_is(monkeypatch, "")
        write(cache / "terrarium_10_1_1.png", 8 * MB, age_days=200)
        keepers = [
            write(cache / "tilejson.json", 32 * 1024, age_days=300),
            write(cache / "polar_clouds.json", 32 * 1024, age_days=300),
            write(cache / "globe_canvas_v1_3.bin", 6 * MB, age_days=300),
            write(cache / "search" / "abc123.json", 4 * 1024, age_days=300),
        ]

        prune_maps_cache(limit=1 * MB)

        for path in keepers:
            assert path.exists(), path.name

    def test_a_missing_cache_is_not_an_error(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LINECAST_CACHE_DIR", str(tmp_path / "nothing here"))
        assert prune_maps_cache() == 0


class TestCacheLimit:
    def test_defaults_when_unset(self, monkeypatch):
        monkeypatch.delenv("LINECAST_MAPS_CACHE_MB", raising=False)
        assert cache_limit_bytes() == DEFAULT_CACHE_MB * MB

    def test_reads_the_environment(self, monkeypatch):
        monkeypatch.setenv("LINECAST_MAPS_CACHE_MB", "64")
        assert cache_limit_bytes() == 64 * MB

    def test_zero_means_keep_nothing(self, cache, monkeypatch):
        version_is(monkeypatch, "")
        monkeypatch.setenv("LINECAST_MAPS_CACHE_MB", "0")
        tile = write(cache / "terrarium_10_1_1.png", 1 * MB)

        prune_maps_cache()

        assert not tile.exists()

    @pytest.mark.parametrize("value", ["", "  ", "lots", "-1"])
    def test_falls_back_on_anything_unreadable(self, monkeypatch, value):
        monkeypatch.setenv("LINECAST_MAPS_CACHE_MB", value)
        assert cache_limit_bytes() == DEFAULT_CACHE_MB * MB
