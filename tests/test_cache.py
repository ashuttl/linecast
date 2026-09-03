"""read_cache: a file's age decides, and a file from the future has none."""

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from linecast._cache import is_fresh, read_cache, write_cache


def _aged(path, seconds_ago):
    stamp = time.time() - seconds_ago
    os.utime(path, (stamp, stamp))


class TestIsFresh:
    def test_a_young_file_is_fresh(self):
        assert is_fresh(time.time() - 10, 60)

    def test_an_old_file_is_not(self):
        assert not is_fresh(time.time() - 120, 60)

    def test_a_file_from_the_future_is_not(self):
        # Written while the clock ran two days ahead: its age is
        # meaningless, and by the plain subtraction it would never expire.
        assert not is_fresh(time.time() + 2 * 86400, 3600)

    def test_a_moment_ahead_is_a_coarse_clock(self):
        assert is_fresh(time.time() + 5, 60)


class TestReadCache:
    def test_serves_a_fresh_file(self, tmp_path):
        path = tmp_path / "c.json"
        write_cache(path, {"k": 1})
        assert read_cache(path, 60) == {"k": 1}

    def test_expires_an_old_file(self, tmp_path):
        path = tmp_path / "c.json"
        write_cache(path, {"k": 1})
        _aged(path, 120)
        assert read_cache(path, 60) is None

    def test_expires_a_file_from_the_future(self, tmp_path):
        path = tmp_path / "c.json"
        write_cache(path, {"k": 1})
        _aged(path, -2 * 86400)
        assert read_cache(path, 3600) is None

    def test_a_missing_file_is_none(self, tmp_path):
        assert read_cache(tmp_path / "none.json", 60) is None
