# Continuous Maps implementation

Implemented on `codex/continuous-maps`, branched from Sky fix `a7ecc9b`.
The [original investigation](README.md) preserves the baseline measurements
and alternatives considered. This document describes the implemented path.

## What changed

`MapCamera` owns one orthographic projection from the whole planet down to
street detail. Fills, elevation, land cover, coastlines, roads, labels, route
strokes, markers, and pointer lookups use its geometry. The old projection
switch is absent from the live map and `--print`; optional legacy arguments
remain for shared radar helpers and existing renderer callers.

The camera's inverse defines the sample centers; its conservative geographic
bounds choose source tiles, and a separate center-scale footprint chooses
detail and shading. Exact camera keys preserve movement at the deepest zoom.
Longitude coverage wraps by the world's period, never by a regional raster
patch's width. Vectors are clipped before walking offscreen raster lines.

The displayed camera is separate from the input target and from completed
detail. Zoom eases in log space over 280 ms, using the same timing as Sky.
Wheel zoom holds its geographic anchor where a north-up solution exists.
Pans follow the sphere; repeated keyboard pans accumulate, while a direction
change begins from the current displayed position. A drag is immediate and
uses one cumulative gesture at every scale. Reset actually returns home.

`PreparedMap` retains immutable color samples, actual braille dots, stroke
ink ownership, elevation, label runs, and hover data. Movement transforms the
original prepared scene, avoiding cumulative resampling damage. Text keeps
its normal glyph size, including wide and combining characters; city dots
keep their geographic anchors. Settled scenes keep exact hover ownership.
Transformed previews withhold feature hover until a coherent index is ready.
Markers and interaction panels are composed for the displayed camera.

Small local previews use separable scale-and-translation sampling only when
an analytic bound keeps the geometric error below 0.05 braille dot in both
source and target grids. Otherwise the full spherical transform runs. Detailed
scenes always use the exact camera. The [derivation and paired benchmark](maps/affine-preview.md)
document this approximation and its nearest-neighbor quantization limit.

Preparation includes up to one zoom-out step of extra coverage around a local
view, at the same pixel density. Padding shrinks near a source boundary so it
cannot reduce detail. A complete planet needs no extra empty-space padding.
Exact integer crops preserve dot geometry, whole labels, and translated
hover ownership. Expensive preview expansion is primed in the worker.

One worker prepares detail, with at most one active build and one latest
pending request. Completion cannot move the camera. A small cache chooses
retained scenes by displayed-camera coverage and resolution, preventing a
late distant result from displacing useful nearby geography. Failed stationary
views schedule a bounded retry wake. Stopping discards pending publication.

Clouds load separately from the initial map. Fresh cloud data invalidates
detail while the previous map remains usable. Theme, style, language, route,
and label options have distinct compatibility keys; source revisions trigger
refinement without discarding compatible geography.

The shared terminal loop now preserves pending repaint requests and limits
continuous input batches to 4 ms. Mouse movement and key repeats cannot
indefinitely starve paint, and an ignored event cannot erase an earlier change.

## Validation

Final full-suite result: **4,012 passed, 1 skipped, 72 deselected, and 263
subtests passed** in 38.04 seconds. Ruff and `git diff --check` passed.
The earlier Sky commit independently passed 3,771 tests and 263 subtests.

Regression coverage includes the original Sky raster, polar and dateline
camera geometry, local vector and raster registration, camera sampling of
climate, source selection, deepest-zoom cache precision, retained colors and
braille, overscan hover, wide text, marker placement, late scene selection,
clock-based retargeting, cloud refresh, failure recovery, and actual shared-loop
input scheduling. Retained render tests compare complete output across terrain
and street styles, local and world sources, lighting, and all four color modes.

The [PTY harness](maps/live_pty.py) runs the real `MapApp` and terminal loop.
It injects SGR mouse drags, anchored wheel zoom, WASD, help, search, resize,
reset, and quit; checks that animation settles and terminal state is restored;
and records frame times, detail builds, input events, and raw ANSI output.
Network is disabled, world data is bundled, and street data uses a private
copy of the same cached coastal fixture as the initial investigation.
`--delay` adds latency only inside background preparation.

Final sequential live runs on 8 September 2026 all passed, across 284 frames:

| Scenario | Terminal at start | Frames | Render median | Render p95 |
| --- | --- | ---: | ---: | ---: |
| Terrain globe | 120×40 | 62 | 19.75 ms | 56.12 ms |
| Terrain globe, 300 ms added detail delay | 120×40 | 80 | 16.22 ms | 34.40 ms |
| Cached coastal streets | 120×40 | 74 | 3.54 ms | 8.69 ms |
| Cached coastal streets | 200×60 | 68 | 7.24 ms | 15.98 ms |

Each sequence includes a resize to 10 fewer columns and 4 more rows. These are
mixed interaction sequences with background work, not uniform drag benchmarks;
they should not be divided directly into the original renderer-only results
to claim a speedup. Added worker delay can reduce foreground contention, which
explains the faster delayed case. [Raw results](maps/live-results.json) retain
maxima, byte counts, and local trace locations. This is one sequence per case,
not a survey of machines, terminal applications, or map locations.

The harness initializes the same runtime as the CLI and observes the camera
passed to the renderer without advancing animation itself. Frame timings
exclude PTY writing and native presentation. Native Terminal UI automation was
blocked in this environment, so these checks are not native display-latency
measurements. Sample ANSI frames were additionally rendered to images for
visual inspection.

Run the live checks with the repository interpreter:

```sh
.venv/bin/python docs/interaction-study/maps/live_pty.py
.venv/bin/python docs/interaction-study/maps/live_pty.py --delay .3
.venv/bin/python docs/interaction-study/maps/live_pty.py --view street --zoom .01 --cache-source /path/to/cache
.venv/bin/python docs/interaction-study/maps/live_pty.py --view street --zoom .01 --cols 200 --rows 60 --cache-source /path/to/cache
```

## Limits and next measurements

This is one camera with multiple data resolutions. World elevation and
vendored geography still yield to local raster and vector sources as detail
becomes appropriate. Fresh detail can visibly refine coastlines, labels, and
roads; the camera itself remains in place. The local vector pipeline has a
conservative footprint limit to keep buffered tile geometry on the visible
hemisphere and within Mercator coverage.

Retained viewport data cannot supply an unseen hemisphere. Large rapid turns
or motion beyond the coverage margin can briefly expose unfilled regions
until a replacement is prepared. A coarse global color fallback would be a
separate improvement if native interaction testing makes those gaps distracting.

Background threads still share CPython's GIL. Larger windows and detailed
scenes can exceed the 30 Hz frame budget while preparation is busy. The
measurements distinguish fast retained-frame arithmetic from the complete live
loop; neither alone establishes native input-to-display latency. Dense cities,
slow real networks, and additional terminal applications remain useful next
validation cases. In-flight network operations cannot be forcibly canceled;
their late results are prevented from moving or repainting a stopped app.
