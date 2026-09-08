"""Offline map frame benchmark, using vendored globe and optional copied tile cache."""

import argparse
import cProfile
import io
import json
import os
import platform
import shutil
import socket
import statistics
import sys
import tempfile
import time
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[3])
parser.add_argument("--cache-source", type=Path)
parser.add_argument("--n", type=int, default=40)
parser.add_argument("--profile", action="store_true")
parser.add_argument("--flat-only", action="store_true")
parser.add_argument(
    "--out", type=Path, default=Path(tempfile.gettempdir()) / "linecast_maps_bench.jsonl"
)
args = parser.parse_args()
if args.n < 1:
    parser.error("--n must be positive")
if args.flat_only and not args.cache_source:
    parser.error("--flat-only requires --cache-source")
args.out.parent.mkdir(parents=True, exist_ok=True)
work = Path(tempfile.mkdtemp(prefix="linecast-map-bench-"))
os.environ["LINECAST_CACHE_DIR"] = str(work / "cache")
os.environ["LINECAST_CONFIG_DIR"] = str(work / "config")
os.environ["LINECAST_COLOR"] = "truecolor"
os.environ.pop("NO_COLOR", None)
if args.cache_source:
    shutil.copytree(args.cache_source / "maps", work / "cache" / "maps")
sys.path.insert(0, str(args.repo / "src"))


def blocked(*args, **kwargs):
    raise OSError("offline benchmark: network disabled")


socket.socket.connect = blocked
socket.create_connection = blocked
from linecast import maps, _maps_streets, _vtiles, _color  # noqa: E402
from linecast._runtime import RuntimeConfig  # noqa: E402
from linecast._radar_render import bbox_for  # noqa: E402

_color._COLOR_MODE = "truecolor"
runtime = RuntimeConfig(live=True, icons="plain", lang="en", oneline=False)
if args.cache_source:
    tj = json.loads((work / "cache" / "maps" / "tilejson.json").read_text())
    _vtiles.tilejson = lambda: tj
lat, lon = 43.66, -70.2


def stats(xs):
    return dict(
        median=round(statistics.median(xs), 3),
        p95=round(sorted(xs)[int(0.95 * (len(xs) - 1))], 3),
        max=round(max(xs), 3),
    )


def frame_fn(size, kind, mode, sun=False, zoom=None):
    maps.get_terminal_size = lambda: size
    globe = kind.startswith("globe")
    view = "street" if "street" in kind else "terrain"
    zoom = zoom or (130 if globe else 0.01)
    base_lat, base_lon = (lat, lon) if globe else (43.66787161011749, -70.191650390625)

    def frame(i):
        dlon = i * 0.43 if globe and mode == "drag" else 0
        dlat = i * 0.17 if globe and mode == "drag" else 0
        if mode == "rebuild":
            dlon = i * zoom / (size[1] * 2)
        return maps.render_map(
            base_lat + dlat,
            base_lon + dlon,
            "Benchmark",
            zoom,
            marker=(base_lat, base_lon),
            runtime=runtime,
            block=True,
            view=view,
            sun=sun,
            pan_offset=(i % 8, i % 3) if mode == "preview" else (0, 0),
            mouse_pos=(10 + i % 50, 15) if mode == "hover" else None,
        )

    return frame


out = args.out.open("w")


def emit(row):
    line = json.dumps(row)
    print(line, flush=True)
    out.write(line + "\n")
    out.flush()


emit(
    dict(
        python=sys.version,
        platform=platform.platform(),
        work=str(work),
        n=args.n,
        color=_color.color_mode(),
        lat=lat,
        lon=lon,
        note="No terminal write; network disabled; copied local tiles if supplied",
    )
)
for size in ((80, 24), (120, 40), (200, 60)):
    cases = [
        ("globe_terrain", "drag", False),
        ("globe_street", "drag", False),
        ("globe_terrain", "drag", True),
        ("globe_terrain", "hover", False),
    ]
    if args.cache_source:
        cases += [
            ("flat_street", "preview", False),
            ("flat_street", "hover", False),
            ("flat_street", "rebuild", False),
        ]
    if args.flat_only:
        cases = [case for case in cases if case[0] == "flat_street"]
    for kind, mode, sun in cases:
        fn = frame_fn(size, kind, mode, sun)
        if kind == "flat_street":
            gw, hc = maps.map_cells(size)
            keys = set()
            for i in range(-4, args.n + 6):
                bbox = bbox_for(
                    43.66787161011749, -70.191650390625 + i * 0.01 / (size[1] * 2), 0.01, gw, hc
                )
                band, z, ks = _maps_streets.view_tiles(bbox, hc)
                keys.update(ks)
            tiles = _maps_streets.fetch_tiles(list(keys))
            assert all(v is not None for v in tiles.values()), "Incomplete vector tile fixture"
            emit(
                dict(
                    coverage_for=[kind, mode, size],
                    band=band,
                    source_zoom=z,
                    tiles=len(keys),
                    present=sum(v is not None for v in tiles.values()),
                )
            )
        for i in range(-4, 0):
            fn(i)
        wall, cpu, lengths = [], [], []
        for i in range(args.n):
            t, c = time.perf_counter(), time.process_time()
            frame = fn(i)
            wall.append((time.perf_counter() - t) * 1000)
            cpu.append((time.process_time() - c) * 1000)
            lengths.append(len(frame.encode()))
        emit(
            dict(
                view=kind,
                mode=mode,
                size=size,
                sun=sun,
                wall_ms=stats(wall),
                cpu_ms=stats(cpu),
                bytes=stats(lengths),
            )
        )
        if args.profile and size == (120, 40):
            pr = cProfile.Profile()
            pr.enable()
            for i in range(args.n + 1, args.n + 6):
                fn(i)
            pr.disable()
            report = io.StringIO()
            import pstats

            pstats.Stats(pr, stream=report).strip_dirs().sort_stats("cumulative").print_stats(40)
            (args.out.parent / f"{kind}_{mode}_{sun}_profile.txt").write_text(report.getvalue())
out.close()
