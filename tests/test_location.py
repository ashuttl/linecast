import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from linecast import _location


class GetLocationTests(unittest.TestCase):
    def test_stale_cache_refreshes_after_one_hour(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_file = Path(tmpdir) / "location.json"
            cache_file.write_text(json.dumps({"lat": 1.0, "lng": 2.0, "country": "US"}))
            stale_at = time.time() - _location._MAX_AGE - 1
            os.utime(cache_file, (stale_at, stale_at))

            payload = {"loc": "3.0,4.0", "country": "CA"}

            with patch.object(_location, "_CACHE_FILE", cache_file), \
                 patch.object(_location, "fetch_json", return_value=payload):
                location = _location.get_location()

        self.assertEqual(location, (3.0, 4.0, "CA"))


if __name__ == "__main__":
    unittest.main()
