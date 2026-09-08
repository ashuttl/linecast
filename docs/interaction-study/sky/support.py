"""Shared setup for the read-only Sky/Moon rendering experiments."""

import json
import os
import statistics
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = next((p for p in (Path.cwd(), *Path(__file__).resolve().parents)
             if (p / "src/linecast/sky.py").is_file()), None)
if REPO is None:
    raise SystemExit("Run from the Linecast repository or keep these scripts inside it")
sys.path.insert(0, str(REPO / "src"))
os.environ["LINECAST_COLOR"] = "truecolor"

from linecast import _color, moon, sky  # noqa: E402
from linecast._runtime import RuntimeConfig  # noqa: E402

_color._COLOR_MODE = "truecolor"
moon.install_banner = sky.install_banner = lambda: ""
runtime = RuntimeConfig(live=True, icons="plain", lang="en", oneline=False)
BASE = datetime(2026, 9, 7, 23, 0, tzinfo=ZoneInfo("America/New_York"))
LAT, LNG = 40.7128, -74.006


def summary(values):
    return {
        "median": round(statistics.median(values), 3),
        "p95": round(sorted(values)[int(.95 * (len(values) - 1))], 3),
        "max": round(max(values), 3),
    }


class Results:
    """Write JSONL to a chosen directory and display the same records."""

    def __init__(self, directory, name):
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / name
        self.path.write_text("")

    def write(self, record):
        line = json.dumps(record)
        print(line, flush=True)
        with self.path.open("a") as stream:
            stream.write(line + "\n")


def fn_for(which, mode, size, day=False, fov=100):
    """Original benchmark workload, with warmed process-local catalogues."""
    moon.get_terminal_size = sky.get_terminal_size = lambda: size
    dt0 = BASE - timedelta(hours=10) if day else BASE
    turn = moon.Turn()

    def frame(index):
        now = dt0 + timedelta(seconds=index / 30)
        if which == "moon":
            turn.drag(index % 50 - 25, 3)
            return moon.render(now, LAT, LNG, runtime, fullscreen=True,
                               calendar_name="almanac", turn=turn)
        az = 180 + (index % 50 - 25) * .5 if mode == "drag" else 180
        return sky.render(
            now, LAT, LNG, runtime, sky.View(az, 30, fov, 2), fullscreen=True,
            mouse_pos=((index % 50) + 10, 15) if mode == "hover" else None,
        )

    return frame
