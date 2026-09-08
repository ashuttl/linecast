# Sky and Moon rendering evidence

Sky already has Moon-style timed motion. Its wide view rendered faster than
Moon in this study, while maximum zoom had a specific geometry bottleneck:
constellation arcs were densely sampled even when they could not reach the
viewport. Conservative culling made maximum-zoom rendering about seven times
faster in a Python-only prototype. This file records that experiment. The
validated culling fix subsequently landed on `sky` as `a7ecc9b`, with frozen
reference-raster regression tests in `tests/test_sky_arcs.py`.

## Measurements

Environment: repository `.venv/bin/python`, Python 3.13.15, Clang 22.1.3,
arm64 macOS 27.0, truecolor, English/plain icons, fullscreen, no install banner.
Location: New York, 40.7128/-74.006; night starts 2026-09-07 23:00 EDT; the
daytime case is ten hours earlier. Time advances by 1/30 second per frame.
Sky pans 0.5 degrees per frame at altitude 30 degrees; Moon advances its
cumulative drag by one column per frame. FOV 100 is representative of a wide
view; the actual default is 110. FOV 6 is maximum zoom.

Four warmups precede each 50-frame baseline. Times include complete frame
generation and ANSI serialization, excluding UTF-8 byte counting, import,
cold catalogue loads, input parsing, terminal transport, and terminal display.
CPU and wall times were nearly equal. Other agents' timing windows were
coordinated to avoid overlap. These are local measurements, not delivered FPS.

Baseline median / p95 wall time, milliseconds:

| View | 80×24 | 120×40 | 200×60 |
|---|---:|---:|---:|
| Moon drag | 11.18 / 11.52 | 24.36 / 24.73 | 46.97 / 48.23 |
| Sky night, FOV 100 drag | 8.87 / 9.26 | 15.59 / 15.93 | 32.21 / 34.53 |
| Sky night, FOV 100 hover | 8.81 / 8.96 | 15.47 / 15.69 | 32.25 / 32.95 |
| Sky day, FOV 100 drag | 5.81 / 5.96 | 8.47 / 8.69 | 15.26 / 17.57 |
| Sky night, FOV 6 drag | 51.55 / 55.02 | 78.94 / 83.29 | 133.52 / 143.70 |

Median complete-frame UTF-8 bytes before the live writer's diff:

| View | 80×24 | 120×40 | 200×60 |
|---|---:|---:|---:|
| Moon drag | 49,442 | 124,482 | 288,504 |
| Sky night, FOV 100 | 56,019 | 132,840 | 316,698 |
| Sky night, FOV 6 | 35,300 | 84,432 | 206,897 |

Maximum zoom is much slower despite emitting fewer bytes. Wide-Sky versus
Moon perceived latency needs the shared-loop and actual terminal measurements
alongside these CPU results.

## Bottleneck and prototype

[`sky._plot_arc`](../../../src/linecast/sky.py#L421) derives a sample count from
projected endpoint distance, normalizes every interpolated sample, and rejects
offscreen samples only at the end. All constellation arcs reach that routine.
At maximum zoom, distant arcs can become very long in projected space.

At 120×40 and FOV 6, `_plot_arc` accounted for 81.6% of profiled render time:
740 calls per frame, with about 361,000 `sqrt` calls per frame overall. At
FOV 100, background painting accounted for 50.7%, arc plotting 19.0%, and
framebuffer encoding 13.3%. Scene construction was about 1.1%. Profiler overhead
distorts absolute timings; these proportions identify targets, not frame budgets.

The prototype rejects arcs whose spherical caps cannot intersect a cone
enclosing the viewport, and arcs wholly below the horizon. Every retained arc
uses the original routine unchanged. No detail or visual feature is disabled.

Initial paired 30-frame median / p95 times:

| Case | Original | Initial culling prototype |
|---|---:|---:|
| 80×24, FOV 6 | 51.89 / 52.49 | 7.62 / 17.22 |
| 120×40, FOV 6 | 78.43 / 78.85 | 10.79 / 10.97 |
| 200×60, FOV 6 | 135.11 / 136.87 | 19.53 / 19.88 |
| 80×24, FOV 100 | 8.90 / 9.24 | 7.48 / 7.72 |
| 120×40, FOV 100 | 15.50 / 15.89 | 13.01 / 13.53 |
| 200×60, FOV 100 | 32.24 / 33.30 | 27.45 / 28.57 |

Stronger validation found one rounding issue in the initial horizon rejection.
Adding a conservative numerical margin fixed it. A focused timing rerun of the
corrected implementation at 120×40/FOV 6 measured **78.85 / 80.66 ms before,
10.61 / 10.72 ms after**, retaining the improvement. The other paired numbers
above are explicitly the initial run; they were not rerun after that correction.

## Why the rejection is conservative

For non-antipodal unit endpoints `a` and `b`, the original normalized linear
interpolation traverses their shorter great-circle arc. Every point lies
inside the cap centered on `normalize(a+b)` with radius `angle(a,b)/2`.
The implementation keeps near-antipodal pairs on the original path.

Under stereographic projection, a point at angular separation `theta` from
camera forward lies at plane distance `2*f*tan(theta/2)`. A cone with angular
radius `2*atan(hypot(cx+1, cy+1)/(2*f))` encloses the viewport. The one-subpixel
margin also encloses the slight negative coordinates that Python's `int()`
rounds into the first cell. If the cap center is farther from camera forward
than the two radii combined, the arc cannot affect a displayed cell. An
additional angular tolerance protects the floating-point comparison.

The horizon is a linear functional of each vector. If negative at both
endpoints, it remains negative along their positive-weight interpolation;
normalization preserves the sign. In floating-point arithmetic, however,
endpoint and interpolated dot products can round to different signs near
zero. The original prototype rejected on `< 0`, and a deliberately tangent
arc exposed a missing single braille cell. The corrected prototype rejects
only if both endpoints are below `-1e-12`, retaining the original path near
the boundary. Initial failure inputs and logs are preserved in `results/`.

## Differential validation

The corrected implementation passes 5,100 deterministic low-level comparisons,
checking equality of the complete braille-dot dictionaries:

- 2,500 random sphere pairs.
- 400 near-identical and 400 near-antipodal pairs.
- 300 identical and 300 antipodal pairs.
- 600 deliberately near-tangent horizon pairs.
- 600 screen-edge/corner pairs, including integer-rounding boundaries.

Cases span six viewport shapes, including 300×8 and 20×100, seven FOVs from
6 to 236 degrees, arbitrary camera azimuths, and altitudes from -12 to 98.

Complete-frame comparisons also pass: 48 representative frames covering
FOV 6/20/100/236, horizon, zenith, azimuth wrap, and IAU/Chinese figures;
50 deterministic random frames spanning location, time, viewport, figures,
and all 23 culture choices; and 23 additional night frames with figures enabled,
one per culture choice. These compare complete ANSI strings byte-for-byte.
The random seed is 20260908. Cross-platform numeric behavior and visual quality
still need production validation; this experiment is not a formal floating-point
proof or a test of actual input-to-display latency.

## Implications for implementation

1. Land conservative geometry culling with the differential cases, retaining
   original sampling and the numerical margins. Native dependencies or a GPU
   path are unnecessary for the measured improvement.
2. Retain the last displayed body, scene, viewport, and hit map. Hover can then
   update only the floating chip, avoiding the current complete 15.47 ms render
   at 120×40. Invalidate for camera, time, palette, size, culture, and figure
   changes; hit testing must use the same revision as the displayed image.
3. Apply shared input scheduling and output improvements. A 30 Hz ticker only
   requests frames. Even the improved 200×60 wide view consumed 27.45 ms before
   terminal I/O, leaving little room in a 33 ms frame budget.
4. Re-profile broad-view background painting afterward. Bounded fixed-FOV
   camera-ray reuse or color-table reuse may help. Scene construction was only
   about 1% of the broad-view profile. Deep stars already use a bounded 96-zone
   cache and were not the measured zoom bottleneck.

Moon's trackball and 0.7-second settle provide the interaction reference. Sky
already has monotonic-clock drag/coast, eased zoom, flights, and WASD panning
in `_sky_live.Camera`. Sky's velocity estimate uses processing timestamps;
queued input after a slow render may affect coast estimation. The shared-loop
study covers this separately. Moon also recomputes its whole display on drag
and exceeded 33 ms at 200×60 here.

## Reproduction and evidence

Run from the repository with an available Python 3.10+ installation. The
scripts use only the standard library and production modules. They discover
the repository from the current directory or script ancestors, import sibling
helpers normally, and write to `--output-dir` (default: the script directory).
Each command runs only its requested experiment; importing a helper does not
launch a hidden benchmark. Keep fresh outputs separate from recorded evidence.

```sh
.venv/bin/python docs/interaction-study/sky/benchmark.py --output-dir /tmp/sky-baseline
.venv/bin/python docs/interaction-study/sky/prototype.py --output-dir /tmp/sky-prototype
.venv/bin/python docs/interaction-study/sky/prototype.py --validate-only --output-dir /tmp/sky-frames
.venv/bin/python docs/interaction-study/sky/prototype.py --quick-timing --output-dir /tmp/sky-quick
.venv/bin/python docs/interaction-study/sky/validate.py --output-dir /tmp/sky-validation
ruff check docs/interaction-study/sky/*.py
```

`validate.py --strict-horizon` deliberately restores the original zero-margin
condition and is expected to fail on the preserved tangent-horizon case.

Recorded files in `results/`: `baseline.jsonl`, three `*_profile.txt` reports,
`prototype_initial.jsonl` and its unedited `initial_probe_log.txt`, corrected
`prototype_quick.jsonl`, representative `prototype.jsonl`, randomized
`validation.jsonl`/`validation_frames.json`/`validation_failures.json`, and
`validation_initial.jsonl`/`validation_initial_failures.json` for the discovered
edge case. Baseline and initial timing scripts were subsequently reorganized
into the readable sibling modules here without changing their frame workload.
