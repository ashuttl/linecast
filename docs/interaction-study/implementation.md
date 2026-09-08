# Continuous Maps implementation

Implemented on `codex/continuous-maps`, branched from Sky fix `a7ecc9b`.
The [original investigation](README.md) preserves the baseline measurements
and alternatives considered. This document describes the implemented path.

## What changed

`MapCamera` owns one orthographic projection from the whole planet down to
street detail. Fills, elevation, land cover, coastlines, roads, labels, route
strokes, markers, and pointer lookups use its geometry. The old projection
switch and its old policy are deleted. Shared radar projection helpers retain
their own sampling contracts.

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

A recent flick now continues into a short coast. Its speed halves every
180 ms and reaches a finite stop within 911 ms; its launch speed is bounded
relative to the shorter physical viewport dimension. One rule serves street
and world views. The existing motion controller integrates decay from the
release time and fixes the destination once, allowing the worker to prepare
that destination while the displayed camera follows the spherical path.
There is no new renderer, ticker, worker, or dependency.

Velocity comes from recent moving samples, expressed in the release camera's
basis so a pole crossing cannot reverse the coast. Paused releases, stationary
motion reports, short event bursts, and ambiguous hemisphere-sized jumps do
not launch it. Grabbing, zooming, keyboard navigation, opening Help or search,
and resizing stop at the displayed location. Interrupted drags ignore their
remaining motion and release reports. The shared loop's optional interrupt
hook distinguishes grabbing and opening Help from an ordinary release.

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

World scenes also retain a complete 720×360 geographic color texture. This
fixes the black slivers that appeared when a moving globe sampled space near
the old limb, or exposed an unseen hemisphere. The same worker prepares the
texture from bundled elevation, climate, ice, and lake data; a two-entry memo
holds terrain and street colors. One resolution serves every world zoom, so
zooming never triggers another texture bake. The packed RGB data occupies
about 760 KiB per style. No additional worker or dependency is involved.

Moving frames bilinearly sample this surface, then apply the displayed
camera's limb shading and atmosphere. Longitude wraps at the dateline and
samples converge at the poles. Daylight and cloud opacity are captured during
preparation; a single cloud texture refreshes on source publication. Painting
does no source loading or weather lookup. Coastlines, borders, and labels
retain their existing transforms until fresh detail arrives. Exact stationary
frames and static output still use their original rendering.

`prepare_map(camera, ...)` produces a `PreparedMap` directly. It never formats
terminal output. `render_map(camera, prepared, ...)` only composes that retained
map and the current UI. Live and `--print` use this same rendering path;
static output builds first and reports source failures at the CLI boundary.
The camera-free renderer, capture callback, shifted-drag paths, nested
`SceneCache` scheduling, and unused zoom hold are deleted. Synchronous bounded
memos preserve geographic data without introducing another scheduling owner.
This consolidation removes 387 production lines net from the initial Maps
implementation, retaining its camera, easing, coverage margin, and preview
geometry. It adds no dependencies.

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

Final full-suite result: **4,120 passed, 1 skipped, 72 deselected, and 263
subtests passed** in 36.01 seconds. Ruff and whitespace checks on source, tests, and documentation
passed; ANSI text snapshots deliberately retain terminal-cell padding.
The earlier Sky commit independently passed 3,771 tests and 263 subtests.

Complete-surface regressions cover the opposite hemisphere, small turns with
simultaneous scaling, camera-independent limb lighting on a uniform sphere,
bilinear seam and polar continuity, lake islands, relief scale, captured cloud
revisions, reuse across zoom and resize, and worker-only preparation. The
shared Mercator sampler now wraps by the world's pixel period rather than a
stitched canvas's padded width; asymmetric height and cloud fixtures exercise
both sides of the dateline with shifted origins and cropped source rows.

Regression coverage includes the original Sky raster, polar and dateline
camera geometry, local vector and raster registration, camera sampling of
climate, source selection, deepest-zoom cache precision, retained colors and
braille, overscan hover, wide text, marker placement, late scene selection,
clock-based retargeting, cloud refresh, failure recovery, and actual shared-loop
input scheduling. Retained render tests compare complete output against 32 frozen hashes from
the initial Maps commit `d3dfee7`, spanning terrain and street styles, local and
world sources, lighting, and all four color modes. This keeps the comparison
independent after deleting the duplicate renderer. Polar hillshade must match
the same projected relief at the equator and both poles. Only the older terrain
snapshot fixture changed: its synthetic shoreline now follows geographic sample
centers under the actual camera. The other three Maps text snapshots match.

The [PTY harness](maps/live_pty.py) runs the real `MapApp` and terminal loop.
It injects SGR mouse drags, anchored wheel zoom, WASD, help, search, resize,
reset, and quit; checks that animation settles and terminal state is restored;
and records frame times, detail builds, input events, and raw ANSI output.
Network is disabled, world data is bundled, and street data uses a private
copy of the same cached coastal fixture as the initial investigation.
`--delay` adds latency only inside background preparation.

The consolidation's sequential live runs on 8 September 2026 all passed,
across 294 frames, before the complete globe surface was added:

| Scenario | Terminal at start | Frames | Render median | Render p95 |
| --- | --- | ---: | ---: | ---: |
| Terrain globe | 120×40 | 62 | 19.64 ms | 52.23 ms |
| Terrain globe, 300 ms added detail delay | 120×40 | 80 | 16.39 ms | 33.39 ms |
| Cached coastal streets | 120×40 | 78 | 3.40 ms | 9.97 ms |
| Cached coastal streets | 200×60 | 74 | 7.05 ms | 18.99 ms |

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

### Complete globe surface

The texture's first preparation measured 703 ms with bundled source canvases
already warm. It runs on the scene worker; subsequent zooms and resizes reuse
it in under 0.04 ms. At 120×40, painting complete globe fills measured 3.98 ms
for yaw and 5.41 ms when latitude changes too. These are surface-only medians
over ten measured frames after two warmups, excluding retained cartography
and terminal composition. Synthetic clouds plus daylight and city lights
raised those medians to 9.30 and 10.77 ms.

A sequential 120×40 live control at `6c9e92b` measured 23.34 ms median and
40.72 ms p95; the completed surface measured 25.25 ms median and 70.72 ms p95.
The first texture build finished before input began. The slower tail frames
overlapped ordinary zoom-detail preparation, which still competes with surface
sampling for Python execution time. Complete coverage has a rendering cost;
these results do not establish a consistent 30 Hz frame rate.

`--spin --fast-drag --delay .3` additionally exercises actual `r` spin,
alternating anchored zooms, and a turn exposing the old view's far side. The
coverage audit uses an independent disk mask to find missing samples. A color
equal to the background counts as a gap only when it disagrees with the
complete surface: shaded ocean can legitimately have the same RGB as space.
The uniform-surface regression independently checks that the sphere remains
opaque and that its limb does not move with latitude or longitude. Coverage
observer time is included in these spin runs, so they are not clean timing
benchmarks. [Results](maps/globe-surface-results.json) preserve both kinds of
measurement separately.

Final 120×40 and 200×60 spin audits passed across 302 frames and 2,038,916
visible-Earth samples, with no missing or background gaps. Both exposed a
previously hidden center, reaching turns of 135° and 145° from the retained
view. Drag, zoom, keyboard pan, overlays, resize, reset, and terminal cleanup
checks passed. Terrain and street ANSI frames were also rendered to images
and inspected at rest, during a small turn, and on the opposite hemisphere.

```sh
.venv/bin/python docs/interaction-study/maps/live_pty.py --spin --fast-drag --delay .3
.venv/bin/python docs/interaction-study/maps/live_pty.py --spin --fast-drag --delay .3 --cols 200 --rows 60
```

### Release coast

Deterministic tests cover speed decay, a fixed endpoint under different frame
cadences, exact stopping time, viewport scaling, poles and the dateline,
reversal, pauses with duplicate motion reports, input bursts, and takeover by
grabbing, zoom, keyboard pan, search, spin, Help, resize, and shutdown. Shared
loop tests verify that a press stops motion before a queued drag is processed,
and that opening Help cancels the coast a synthetic release could start.
Help describes flicking separately from keyboard panning in all 18 languages.

The PTY harness's `--coast` phase sends a flick, a paused release, and a second
flick caught by a new press. It records actual callback receipt times and
rendered cameras, checking continued movement toward a fixed target, complete
settlement, and no movement after a paused release or regrab. All three final
runs passed across 473 frames:

| Scenario | Terminal | Moving frames after first release | Added travel, fraction of shorter viewport |
| --- | --- | ---: | ---: |
| Globe, spin/coverage audit, 300 ms detail delay | 120×40 | 24 | 0.207 |
| Cached coastal streets | 120×40 | 24 | 0.170 |
| Globe, 300 ms detail delay | 200×60 | 15 | 0.195 |

The combined globe audit also checked 998,184 Earth samples with no coverage
gaps. Added travel is measured from the first rendered post-release frame;
terminal callback timing and the spherical projection affect that fraction.
These are application/PTY checks, not native display-latency measurements.
[Raw results](maps/coast-results.json) include render timings and trace paths.

```sh
.venv/bin/python docs/interaction-study/maps/live_pty.py --coast --spin --fast-drag --delay .3
.venv/bin/python docs/interaction-study/maps/live_pty.py --coast --view street --zoom .01 --cache-source /path/to/cache
.venv/bin/python docs/interaction-study/maps/live_pty.py --coast --cols 200 --rows 60 --delay .3
```

## Limits and next measurements

This is one camera with multiple data resolutions. World elevation and
vendored geography still yield to local raster and vector sources as detail
becomes appropriate. Fresh detail can visibly refine coastlines, labels, and
roads; the camera itself remains in place. The local vector pipeline has a
conservative footprint limit to keep buffered tile geometry on the visible
hemisphere and within Mercator coverage.

Complete world surfaces cover unseen hemispheres during rotation. Their
coastlines and labels can still refine afterward, as can relief when the
camera settles. Local viewport data remains limited by its coverage margin
until a replacement is prepared. The retained braille and whole-label
machinery has a measured purpose; flattening it to terminal cells would tear
wide glyphs and lose street detail. Any further simplification should
demonstrate the visual tradeoff before replacing that machinery.

Background threads still share CPython's GIL. Larger windows and detailed
scenes can exceed the 30 Hz frame budget while preparation is busy. The
measurements distinguish fast retained-frame arithmetic from the complete live
loop; neither alone establishes native input-to-display latency. Dense cities,
slow real networks, and additional terminal applications remain useful next
validation cases. In-flight network operations cannot be forcibly canceled;
their late results are prevented from moving or repainting a stopped app.
