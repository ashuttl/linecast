"""Plumbing regression tests: terminal-size env overrides, atomic writes."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from linecast._cache import write_bytes_atomic, write_cache
from linecast._framebuffer import get_terminal_size


class AtomicWriteTests(unittest.TestCase):
    def test_write_bytes_atomic_publishes_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "tile.png"
            write_bytes_atomic(path, b"pixels")
            self.assertEqual(path.read_bytes(), b"pixels")
            self.assertEqual(os.listdir(tmpdir), ["tile.png"])  # no .tmp litter

    def test_write_bytes_atomic_replaces_existing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "tile.png"
            path.write_bytes(b"old")
            write_bytes_atomic(path, b"new")
            self.assertEqual(path.read_bytes(), b"new")

    def test_write_cache_round_trips_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sub" / "cache.json"
            write_cache(path, {"a": 1})
            self.assertEqual(json.loads(path.read_text()), {"a": 1})
            self.assertEqual(os.listdir(path.parent), ["cache.json"])


class RadarPruneTests(unittest.TestCase):
    def test_prunes_only_old_tiles(self):
        from linecast import _radar_tiles
        with tempfile.TemporaryDirectory() as tmpdir:
            pdir = Path(tmpdir) / "radar" / "lwxr"
            pdir.mkdir(parents=True)
            old = pdir / "v2_radar_1000_5_1_2_c2.png"
            fresh = pdir / "v2_radar_2000_5_1_2_c2.png"
            index = pdir / "weather-maps.json"
            for f in (old, fresh, index):
                f.write_bytes(b"x")
            stale_at = 0  # epoch: comfortably past any cutoff
            os.utime(old, (stale_at, stale_at))
            with patch.object(_radar_tiles, "CACHE_ROOT", Path(tmpdir)):
                _radar_tiles.prune_tile_cache()
            self.assertFalse(old.exists())
            self.assertTrue(fresh.exists())
            self.assertTrue(index.exists())  # index is TTL-managed, not swept

    def test_missing_cache_dir_is_fine(self):
        from linecast import _radar_tiles
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(_radar_tiles, "CACHE_ROOT", Path(tmpdir) / "nope"):
                _radar_tiles.prune_tile_cache()  # must not raise


class TerminalSizeTests(unittest.TestCase):
    def test_columns_lines_env_overrides_are_honoured(self):
        # Status bars and tmux panes size captures via COLUMNS/LINES;
        # os.get_terminal_size ignores them, shutil's consults them first.
        with patch.dict(os.environ, {"COLUMNS": "120", "LINES": "40"}):
            self.assertEqual(tuple(get_terminal_size()), (120, 40))

    def test_fallback_without_env_or_tty(self):
        env = {k: v for k, v in os.environ.items()
               if k not in ("COLUMNS", "LINES")}
        with patch.dict(os.environ, env, clear=True):
            cols, rows = get_terminal_size()
        self.assertGreaterEqual(cols, 1)
        self.assertGreaterEqual(rows, 1)


if __name__ == "__main__":
    unittest.main()
