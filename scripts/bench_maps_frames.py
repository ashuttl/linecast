#!/usr/bin/env python3
"""Time the map's frames in the cases a reader hits, without a terminal.

Usage: bench_maps_frames.py <scenario> [cols rows] [--profile [--which CASE]]

Scenarios: street (Portland, Maine, at the default street zoom),
terrain (New Zealand at 4 degrees), terrain-close (0.2 degrees),
globe (the terrain planet with daylight and clouds: the --view now
frame), globe-plain (the planet alone).  Each scenario builds its view
once, blocking, then times the frames the live loop draws from it: at
rest, panning inside the margin, the resample a pan comes to rest on,
the stand-ins a zoom tap shows while the next view builds, and a frame
with the pointer over the map.  Each frame goes through the painter the
live loop writes with, so the time includes the terminal text.

Tiles come from the network the first time and from the cache after,
so run a scenario twice before reading its numbers, and read them as
noisy: a build landing in the background takes the interpreter for a
moment.  --profile prints cProfile for one case (--which rest, pan,
pan_rest, zoom or zoomout; default pan).

Alongside scripts/bench_maps_live.py, which drives the whole live loop
in a pty and times what it writes: this one measures a frame's
arithmetic, that one the loop around it.
"""
import cProfile
import io
import os
import pstats
import sys
import time

os.environ.setdefault("LINECAST_THEME", "dark")
os.environ.setdefault("LINECAST_THEME_POLL", "0")
os.environ.setdefault("LINECAST_CELL_ASPECT", "0.5")
os.environ.setdefault("LINECAST_COLOR", "truecolor")
os.environ.setdefault("COLORTERM", "truecolor")
os.environ.setdefault("TERM", "xterm-256color")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

HOME = (43.66, -70.26)   # the marker, and street's centre
SCENARIOS = {
    # lat, lon, zoom (degrees of latitude, or "max"), register, sky
    "street": (43.66, -70.26, 0.05, "street", False),
    "terrain": (-41.0, 172.0, 4.0, "terrain", False),
    "terrain-close": (-41.0, 172.0, 0.2, "terrain", False),
    "globe": (-41.0, 172.0, "max", "terrain", True),
    "globe-plain": (-41.0, 172.0, "max", "terrain", False),
}


def main(argv):
    flags = [a for a in argv if a.startswith("--")]
    args = [a for a in argv if not a.startswith("--")]
    if not args or args[0] not in SCENARIOS:
        sys.exit(__doc__)
    cols, rows = (int(args[1]), int(args[2])) if len(args) >= 3 else (160, 45)
    os.environ["COLUMNS"], os.environ["LINES"] = str(cols), str(rows)
    which = argv[argv.index("--which") + 1] if "--which" in argv else "pan"

    from linecast._parsers import maps_parser
    from linecast._runtime import RuntimeConfig, set_current
    from linecast.maps import loaders as L
    from linecast.maps import view as V
    from linecast.maps.motion import lon_span
    from linecast.terminal.live import FramePainter

    rt = RuntimeConfig.from_sources(
        maps_parser().parse_args(["--location", f"{HOME[0]},{HOME[1]}"]))
    set_current(rt)
    gw, hc = V.map_cells((cols, rows), show_text=True)
    lat, lon, zoom, view, sky = SCENARIOS[args[0]]
    if zoom == "max":
        zoom = V.max_zoom(gw, hc)
    print(f"{args[0]} at {cols}x{rows} (map {gw}x{hc}), zoom {zoom:.3g}")
    painter = FramePainter()

    def frame(lat, lon, zoom, block=False, **kw):
        out = V.render_map(lat, lon, "Portland", zoom, marker=HOME, runtime=rt,
                           block=block, view=view, sun=sky, clouds=sky, **kw)
        if block:
            return out
        body, _, floating = out.partition("\x00")
        painter.forget()   # every frame whole, as a moving view's are
        return painter.paint(body, floating)

    t0 = time.perf_counter()
    frame(lat, lon, zoom, block=True)
    print(f"blocking first build: {(time.perf_counter() - t0) * 1000:.0f} ms")
    if not V.wide_source(lat, zoom, gw, hc):
        # the live loop draws from an overscan, so build one and wait
        V.prefetch_view(lat, lon, zoom, view, gw, hc, "en", marker=HOME)
        take = L.take_street if view == "street" else L.take_terrain
        for _ in range(600):
            time.sleep(0.05)
            landed = take()
            if landed is not None:
                if view == "street":
                    L._street_landed[0] = landed
                else:
                    L._terrain_landed[0] = landed
                break
    frame(lat, lon, zoom)
    frame(lat, lon, zoom)

    dlon = lon_span(lat, zoom, gw, hc) / gw * 6
    cases = {
        "rest": ("resting frame (crop, no motion)",
                 lambda: frame(lat, lon, zoom)),
        "pan": ("pan frame, 6 cells inside the margin, moving",
                lambda: frame(lat, lon + dlon, zoom, moving=True, motion=(1, 0))),
        "pan_rest": ("pan frame, 6 cells, at rest (resample)",
                     lambda: frame(lat, lon + dlon, zoom)),
        "zoom": ("zoom-in stand-in frame (1.2x, moving)",
                 lambda: frame(lat, lon, zoom / 1.2, moving=True)),
        "zoomout": ("zoom-out stand-in frame (1.2x, moving)",
                    lambda: frame(lat, lon, zoom * 1.2, moving=True)),
        "mouse": ("resting frame with the pointer over the map",
                  lambda: frame(lat, lon, zoom, mouse_pos=(gw // 3, hc // 2))),
    }
    for label, fn in cases.values():
        fn()
        t0 = time.perf_counter()
        for _ in range(10):
            out = fn()
        dt = (time.perf_counter() - t0) / 10
        print(f"{label:52s} {dt * 1000:6.1f} ms  {len(out) / 1024:5.0f} KB")

    if "--profile" in flags:
        fn = cases[which][1]
        pr = cProfile.Profile()
        pr.enable()
        for _ in range(10):
            fn()
        pr.disable()
        for order in ("cumulative", "tottime"):
            s = io.StringIO()
            pstats.Stats(pr, stream=s).sort_stats(order).print_stats(30)
            print(s.getvalue())


if __name__ == "__main__":
    main(sys.argv[1:])
