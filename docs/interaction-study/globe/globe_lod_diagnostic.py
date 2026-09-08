"""Offline globe quality ablations; render timing excludes terminal presentation.

Run directly with Python 3.10+, optionally passing --repo and --output.
The default repository is the checkout containing this script.
"""

import argparse
import cProfile
import contextlib
import io
import json
import os
from pathlib import Path
import pstats
import socket
import statistics
import sys
import time
from unittest.mock import patch


KINDS = ("full", "no_coast_lakes_borders", "no_labels", "coarse", "coarse_no_labels")


def blocked(*args, **kwargs):
    raise RuntimeError("Offline diagnostic attempted network")


def parser(description):
    result = argparse.ArgumentParser(description=description)
    result.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[3])
    result.add_argument("--output", type=Path, help="Write results here instead of stdout")
    result.add_argument("--samples", type=int, default=12)
    return result


def write_output(value, output):
    if output is None:
        print(value)
    else:
        output.write_text(value + "\n", encoding="utf-8")


class Diagnostic:
    """A warm, offline 120x40 terrain globe; temporary patches stay scoped."""

    zoom = 125.0

    def __init__(self, repo):
        os.environ["LINECAST_COLOR"] = "truecolor"
        sys.path.insert(0, str(repo.resolve() / "src"))
        from linecast import _globe, _maps_views, maps

        self.globe = _globe
        self.views = _maps_views
        self.maps = maps

    @contextlib.contextmanager
    def offline(self):
        with patch.object(socket.socket, "connect", blocked), \
                patch.object(self.maps, "get_terminal_size", lambda: (120, 40)):
            for z in (1, 2):
                canvas = self.globe._canvas_load(z)
                if canvas is None:
                    raise RuntimeError(f"Missing vendored globe canvas z{z}")
                self.globe._canvas_cache.put(z, canvas)
            yield

    def coarse_view(self, lat0, lon0, zoom, gw, hc, block):
        """Single fill sample; deliberately omits coast/lakes/border geometry."""
        globe = self.globe
        lls, zs, rhos = globe.geometry(lat0, lon0, zoom, gw, hc * 2)
        # Keep source resolution identical to the full renderer's selection.
        grid = globe.elevation(lls, zoom, hc * 4)
        atmo = globe.atmosphere(rhos, zoom, hc * 2)
        return globe.GlobeView(
            grid, None, zs, atmo, globe.ice_cover(lls, grid, 7), None, lls,
            globe.limb_lls(lat0, lon0, zoom, gw, hc * 2, atmo), None)

    def frame(self, i, kind, diagonal=False):
        lat = 43.0 + (i * 0.21 if diagonal else 0)
        lon = -70.0 + i * 0.37
        return self.maps.render_map(
            lat, lon, "Diagnostic", self.zoom, block=True, marker=(43.0, -70.0),
            show_labels=kind not in ("no_labels", "coarse_no_labels"),
            sun=False, clouds=False)

    def setup(self, kind):
        stack = contextlib.ExitStack()
        if kind in ("no_coast_lakes_borders", "no_labels"):
            stack.enter_context(patch.object(self.globe, "lake_mask", lambda *a: None))
            stack.enter_context(patch.object(self.globe, "border_layer", lambda *a: None))
            stack.enter_context(patch.object(self.views, "_coast_dots", lambda *a: None))
        if kind.startswith("coarse"):
            stack.enter_context(patch.object(self.maps, "_get_globe", self.coarse_view))
        return stack

    def reset(self):
        self.views._globe_cache.clear()
        self.views._terrain_cache.clear()
        self.globe._geometry_cache.clear()
        self.globe._overlay_cache.clear()


def run(diagnostic, samples=12, profile_frames=4):
    diagnostic.frame(0, "full")  # Warm immutable data and imports before timing.
    results = []
    for diagonal in (False, True):
        for kind in KINDS:
            diagnostic.reset()
            with diagnostic.setup(kind):
                diagnostic.frame(100, kind, diagonal)
                durations = []
                for i in range(samples):
                    start = time.perf_counter()
                    diagnostic.frame(i, kind, diagonal)
                    durations.append((time.perf_counter() - start) * 1000)
            results.append(dict(
                kind=kind, motion="diagonal" if diagonal else "horizontal",
                median_ms=statistics.median(durations), min_ms=min(durations),
                max_ms=max(durations), samples_ms=durations))
    parts = [json.dumps(results, indent=2)]
    # Profiles include profiler overhead; their times are not frame benchmarks.
    if profile_frames:
        for kind in ("full", "coarse_no_labels"):
            diagnostic.reset()
            with diagnostic.setup(kind):
                diagnostic.frame(100, kind, True)
                profiler = cProfile.Profile()
                profiler.enable()
                for i in range(profile_frames):
                    diagnostic.frame(i, kind, True)
                profiler.disable()
            stats = io.StringIO()
            pstats.Stats(profiler, stream=stats).strip_dirs().sort_stats(
                "cumulative").print_stats(32)
            parts.append(f"PROFILE {kind}\n{stats.getvalue()}")
    return "\n\n".join(parts)


def main():
    cli = parser(__doc__)
    cli.add_argument("--profile-frames", type=int, default=4)
    args = cli.parse_args()
    if args.samples < 1 or args.profile_frames < 0:
        cli.error("--samples must be positive and --profile-frames nonnegative")
    diagnostic = Diagnostic(args.repo)
    with diagnostic.offline():
        result = run(diagnostic, args.samples, args.profile_frames)
    write_output(result, args.output)


if __name__ == "__main__":
    main()
