"""Profile Sky and compare conservative arc culling, without production edits."""

import argparse
import cProfile
import io
import math
import pstats
import time
from datetime import timedelta
from pathlib import Path

from support import BASE, LAT, LNG, Results, fn_for, runtime, sky, summary

original_arc = sky._plot_arc
counts = {"calls": 0, "culled": 0, "steps_before": 0, "steps_after": 0}
HORIZON_EPSILON = 1e-12


def culled_arc(dots, a, b, cam, f, cx, cy, graph_w, graph_h):
    """Keep original sampling, rejecting only arcs that cannot affect a cell.

    Non-antipodal unit endpoints bound their normalized linear interpolation
    by the spherical cap centered on normalized(a+b), radius angle(a,b)/2.
    The viewport is enclosed by a cone around camera +z. Its plane-space
    radius is expanded one subpixel because int() rounds slightly negative
    screen coordinates into the first cell. Disjoint caps cannot share any
    visible sample. Near-antipodal pairs fall back to original sampling.

    A linear horizon functional stays negative if negative at both endpoints.
    A numerical margin retains arcs close enough to the horizon for float
    rounding to affect the original renderer's sign check.

    Diagnostic counters and repeated endpoint projections intentionally remain
    in this research prototype; a production implementation can simplify them.
    """
    counts["calls"] += 1
    pa, pb = sky.project(a, f, cx, cy), sky.project(b, f, cx, cy)
    nsteps = 0
    if pa is not None and pb is not None:
        length = math.hypot(pb[0] - pa[0], pb[1] - pa[1])
        if length <= 6 * f:
            nsteps = max(1, int(length * 2)) + 1
    counts["steps_before"] += nsteps
    dot = max(-1, min(1, sum(x * y for x, y in zip(a, b))))
    half = math.acos(dot) * .5
    size = math.sqrt(sum((x + y) ** 2 for x, y in zip(a, b)))
    reject = False
    if size > 1e-8:
        cos_to_forward = max(-1, min(1, (a[2] + b[2]) / size))
        radius = 2 * math.atan(math.hypot(cx + 1, cy + 1) / (2 * f))
        reject = math.acos(cos_to_forward) > radius + half + 1e-8
    u0, u1, u2 = cam[2], cam[5], cam[8]
    reject = reject or (
        u0 * a[0] + u1 * a[1] + u2 * a[2] < -HORIZON_EPSILON
        and u0 * b[0] + u1 * b[1] + u2 * b[2] < -HORIZON_EPSILON
    )
    if reject:
        counts["culled"] += 1
        return
    counts["steps_after"] += nsteps
    return original_arc(dots, a, b, cam, f, cx, cy, graph_w, graph_h)


def profile(output_dir):
    for which, fov in [("moon", 100), ("sky", 100), ("sky", 6)]:
        render_frame = fn_for(which, "drag", (120, 40), fov=fov)
        for index in range(3):
            render_frame(index)
        profiler = cProfile.Profile()
        profiler.enable()
        for index in range(10):
            render_frame(index)
        profiler.disable()
        output = io.StringIO()
        pstats.Stats(profiler, stream=output).strip_dirs().sort_stats("cumulative").print_stats(30)
        (output_dir / f"{which}_{fov}_profile.txt").write_text(output.getvalue())


def compare_frames(results):
    compared = 0
    for fov in (6, 20, 100, 236):
        for az, alt, culture in [(180, 30, None), (0, 0, None), (359, 90, None),
                                 (80, 45, "chinese")]:
            sky.get_terminal_size = lambda: (120, 40)
            for index in range(3):
                now = BASE + timedelta(seconds=index / 30)
                view = sky.View(az + index * .5, alt, fov, 2, culture)
                sky._plot_arc = original_arc
                expected = sky.render(now, LAT, LNG, runtime, view, fullscreen=True)
                sky._plot_arc = culled_arc
                actual = sky.render(now, LAT, LNG, runtime, view, fullscreen=True)
                assert expected == actual, (fov, az, alt, culture, index)
                compared += 1
    results.write({"exact_frames_matched": compared, "counts": counts.copy()})


def paired_timings(results, sizes=((80, 24), (120, 40), (200, 60)), fovs=(6, 100)):
    for size in sizes:
        for fov in fovs:
            for mode in ("before", "culled"):
                render_frame = fn_for("sky", "drag", size, fov=fov)
                sky._plot_arc = original_arc if mode == "before" else culled_arc
                for index in range(3):
                    render_frame(index)
                times = []
                for index in range(30):
                    started = time.perf_counter()
                    render_frame(index)
                    times.append((time.perf_counter() - started) * 1000)
                results.write({"size": size, "fov": fov, "mode": mode,
                               "wall_ms": summary(times)})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--validate-only", action="store_true",
                        help="Compare the 48 representative frames without timing or profiling")
    parser.add_argument("--quick-timing", action="store_true",
                        help="Only pair 30 frames at 120x40, FOV6 after the numerical guard")
    parser.add_argument("--strict-horizon", action="store_true",
                        help="Reproduce the original prototype without its numerical margin")
    args = parser.parse_args()
    global HORIZON_EPSILON
    if args.strict_horizon:
        HORIZON_EPSILON = 0.0
    filename = "prototype_quick.jsonl" if args.quick_timing else "prototype.jsonl"
    results = Results(args.output_dir, filename)
    try:
        if args.quick_timing:
            paired_timings(results, sizes=((120, 40),), fovs=(6,))
            return
        if not args.validate_only:
            profile(args.output_dir)
        compare_frames(results)
        if not args.validate_only:
            paired_timings(results)
    finally:
        sky._plot_arc = original_arc


if __name__ == "__main__":
    main()
