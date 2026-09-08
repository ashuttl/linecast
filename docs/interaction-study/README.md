Interaction study: Maps, Sky, and Moon
====================================

Investigated 7–8 September 2026 against commit `93002fc`, on arm64 macOS
with CPython 3.13.15 and its GIL enabled. This report records the original
investigation, benchmarks, and isolated prototypes before implementation.
The Sky fix is committed on `sky` as `a7ecc9b`; subsequent Maps work is on
`codex/continuous-maps`. See [implementation and validation](implementation.md)
for the resulting behavior and remaining limits. References to "current" or
"existing" below describe the study's baseline, not the new implementation.

The recommended destination is **one continuous map camera, with immediate
visual movement and asynchronous improvement of detail**. The existing flat
and globe interaction split should be replaced. Sky's eased zoom is the
interaction reference; the user's suggestion to scale the currently rendered
map while a new rendering catches up is a practical foundation, supported by
an experiment below.

Sky needs substantially less work. Its maximum-zoom slowdown has a specific
geometric cause, and an isolated culling experiment removes most of it without
changing the checked output. Shared input scheduling and terminal encoding
also have improvements that benefit all three views.

The measurements
---------------

These are warmed **frame-generation wall times**, including construction of
the returned ANSI string, but excluding terminal write, terminal parsing,
compositing, and display. They are not measured interactive FPS or end-to-end
input latency. Moon/Sky used 50 samples per case; Maps used 40. Profiles were
collected separately and their instrumented durations are not benchmark times.
Timing batches were coordinated between investigators to avoid overlapping
benchmark runs. The machine was not otherwise laboratory-isolated.

| Existing renderer / workload | 80×24 median | 120×40 median | 200×60 median |
| --- | ---: | ---: | ---: |
| Moon, dragged disc | 11.2 ms | 24.4 ms | 47.0 ms |
| Sky, 100° night view, dragging | 8.9 ms | 15.6 ms | 32.2 ms |
| Sky, 6° night view, dragging | 51.5 ms | 78.9 ms | 133.5 ms |
| Terrain globe, diagonal dragging, 130° | 32.4 ms | 62.4 ms | 126.0 ms |
| Terrain globe, same drag with daylight | 35.9 ms | 67.6 ms | 133.8 ms |
| Street map, existing retained pan preview | 0.8 ms | 1.7 ms | 3.5 ms |
| Street map, rebuilding at successive centres | 18.8 ms | 36.1 ms | 77.3 ms |

At 120×40, p95 was 24.7 ms for Moon, 15.9 ms for wide Sky, 83.3 ms for deep
Sky, and 64.2 ms for the terrain globe. A 30 Hz interaction has only 33.3 ms
for its entire frame, including terminal presentation. The globe is over that
budget before it writes a byte. Moon itself is not universally within that
budget at a large terminal; its motion is the reference, not a guarantee of
speed at every size.

Globe measurements use the real vendored elevation canvases and geography,
with cloud cover disabled. Camera movement changes both latitude and longitude;
horizontal movement alone is cheaper because the current inverse-projection
cache can reuse latitude-dependent work. The street fixture uses copied local
z14 vector tiles around 43.6678716°N, 70.1916504°W, at a 0.01° span. All three
required tiles were present throughout the checked camera sequence. This is
one coastal street fixture, not a survey of dense cities. The metadata's
top-level `lat`/`lon` fields refer to the globe case; the street coordinates
are fixed separately in the harness. An earlier incomplete street fixture was
excluded from these results.

Map benchmarks disable network access and use a private copy of the tile
cache. They do not measure new-place download latency. Sky/Moon use bundled
data at a fixed starting date, advancing time and camera during each sequence.
The raw results retain byte counts, CPU times, medians, p95, and maxima.

Why the current interaction varies
---------------------------------

The Moon animates a bounded local scene using clock-based motion. Sky already
has the corresponding camera: a 30 Hz ticker, 0.28-second zoom easing,
retargeting, coast, flight, and keyboard easing. See
[`_sky_live.py`](../../src/linecast/_sky_live.py).

Maps' current [`on_drag()`](../../src/linecast/_maps_live.py) has two contracts.
Flat dragging shifts the old viewport-sized scene and changes the geographic
centre only on release. Exposed edges have no extra scene behind them. Release
then misses a cache keyed to the exact viewport, so the loader returns an
empty/loading scene until replacement data is prepared. A warm globe instead
changes the centre during the gesture and renders synchronously. This retains
the globe's shape but puts expensive geometry work in front of further input.

The globe profile places most cost in inverse projection, elevation sampling,
border rasterization, lakes, terrain shading, and city placement. Composition
is relatively small. Simply hiding labels does little because the expensive
border/lake/coast work is still performed. A diagnostic at 120×40 reduced a
diagonal frame from roughly 62 ms to 18 ms by dropping supersampling, coastlines,
lakes, and borders. This changes geography and appearance; it is evidence about
cost, not an acceptable final renderer.

There is also an avoidable blocking hazard. `MapApp.render()` uses `block=True`
for a warm globe drag. That reaches `_get_clouds()`, which synchronously fetches
when no cloud canvas exists. Having elevation in memory does not establish that
all other layers are ready. The new contract must distinguish **render using
prepared data** from **permission to wait for data**.

The shared [`live_loop()`](../../src/linecast/_live.py) synchronously renders,
writes, and flushes before handling more input. Its current coalescing also
keeps consuming input until the queue empties, without a paint deadline or
persistent dirty flag. Deterministic probes of the actual loop reproduced:

- A forced stream of 1,000 drag events at simulated 1 ms intervals with no
  intermediate paint between 1 ms and 1,001 ms. This is a stress reproduction,
  not a claim that typical terminals deliver that workload.
- A changed action followed by ignored input losing its pending repaint.

Give the loop a durable dirty state, monotonic frame deadlines, and bounded
input batches. Coalesce obsolete camera positions while preserving releases,
clicks, keyboard commands, help/search, and quit. Keep the existing correct
drain-before-render wakeup ordering: draining after rendering can lose a data
completion that arrived during composition. A faster ticker alone does not fix
any expensive synchronous frame.

The proposed continuous map
---------------------------

Start with one **orthographic camera at every zoom**. Earth occupies less or
more of the viewport; at street scale its visible patch naturally appears
flat. Its forward/inverse projection is established geometry, and the current
`_globe._radius()` already expresses a continuous centre scale. This is a
design recommendation, not an implemented all-scale renderer. [PROJ documents
the orthographic projection](https://proj.org/en/stable/operations/projections/ortho.html).

The camera should own centre/orientation, continuous scale, viewport and cell
aspect, pointer anchoring, current animation, and a revision. Every visual and
interactive layer must use that same camera snapshot. Street and terrain can
remain visual styles; neither needs a different gesture model.

Merely deleting `is_globe()` would not accomplish this. The present globe
samples whole-world elevation only up to source zoom 3 and does not render
street vectors. Its scene keys round camera coordinates to 0.01° and scale to
0.1°, which would collapse distinct street-scale views. The new design needs:

- Visible-region tile selection and local high-resolution sampling, with
  cached parent-resolution data filling gaps while children arrive. Never
  build a whole-world mosaic at street resolution.
- Reusable decoded tiles and prepared geometry, rather than only a handful of
  complete viewport images. Existing tile caches, decoders, palettes, and
  cartographic rules remain useful.
- One forward/inverse transform for raster samples, polygons, shorelines,
  roads, routes, markers, labels, and hit testing. The current separable
  flat-map vector projector needs replacement or an equivalent local fast path.
- Correct clipping and sufficient subdivision near the limb. Water fill and
  the coastline derived from it must stay registered. The current globe's
  simplified treatment of partially hidden lakes is insufficient for general
  vector mapping.
- Scale-sensitive precision or camera revisions in render-cache keys;
  bounded source caches keyed by source/version/tile; explicit invalidation
  for viewport, theme, language, style, and relevant layer data.

Perspective projection could be explored later if a more photographic camera
is wanted. It adds camera-distance and horizon behavior; it is not required
for continuity. Likewise, an internal local-coordinate fast path need not
become a user-visible mode. MapLibre is useful prior art for projecting the
same tile geometry onto a sphere and keeping subdivisions consistent. Its
documented high-zoom handoff addresses GPU float32 precision; that is not by
itself a requirement for this Python float64 renderer. Precision still needs
testing at minimum zoom and near the poles. [MapLibre globe implementation
guide](https://github.com/maplibre/maplibre-gl-js/blob/main/developer-guides/globe.md).

The zoom preview the user described
----------------------------------

Use Sky's easing and retargeting behavior to drive the displayed map camera
immediately. Retain structured scene layers, transform those layers for each
intermediate frame, and replace them with better prepared layers as soon as
they are useful.

For a centre-anchored orthographic zoom with unchanged orientation, screen
coordinates relative to the centre scale in direct proportion to globe radius.
Thus scaling the old image matches the geometric zoom exactly. Sampling detail,
available coverage, label choice, and resolution-dependent shading still differ
from a fresh render. Pointer-anchored zoom changes the camera orientation as
well; a simple scale-about-pointer is then an approximation away from the
anchor, especially near the limb. Globe rotation needs spherical reprojection
or a cheap coarse rendering, not a translation of the entire disc.

A prototype captured a real globe's RGB fill buffer and braille masks, scaled
the fills and individual braille dots, and used the existing compositor:

| Retained-layer zoom preview | Median | p95 |
| --- | ---: | ---: |
| 120×40 terminal | 4.98 ms | 5.23 ms |
| 200×60 terminal | 12.74 ms | 13.09 ms |

These 40-frame runs used scale factors from 0.85 to 1.23. They include sampling
and encoding, but exclude fresh map construction, labels, chrome, clouds,
terminal presentation, and fetching. Identity scaling matched the retained
layers and ANSI output exactly. This validates the computational approach;
it is not a finished visual-quality or interaction demonstration.

The implementation should obey these rules:

1. Keep an original retained scene plus its camera, rather than repeatedly
   resampling the last preview. Repeated resampling accumulates blur and error.
2. Preserve Sky's smoothly retargeted motion when another wheel event arrives.
   Display state, target camera, and available scene are distinct pieces of
   state. A slow renderer must not determine animation duration.
3. On completion, transform a prepared scene from *its* camera into the
   *current displayed* camera. A scene built for an earlier target must not
   snap the display back. Discard obsolete display work while retaining useful
   decoded tiles.
4. Keep real text at normal glyph size. Transform its anchors, apply a cheap
   collision policy during motion, and refine label placement afterward.
   Scale actual braille geometry, not the font glyph or an ANSI string.
5. Preserve coverage on zoom-out and pan using a margin and coarser source
   tiles. A retained viewport alone cannot invent newly exposed geography.
   Margin size must have a memory limit and should not silently change the
   final viewport's label budget.
6. Project markers and routes consistently, and tie hover IDs to the displayed
   scene/transform. A tooltip must describe the ink under the pointer, not a
   future target frame. Publish a scene and its hit index together.
7. Swap coherent geometry at the same camera. An indiscriminate crossfade can
   produce doubled roads or shorelines. Fading new labels/detail may help, but
   is optional; smooth movement does not require crossfading every feature.

Use bounded workers and latest-request priority for refinement. Camera motion
must remain local and must never require network completion. Coalesce new
network demand, but let already prepared/cached data become visible promptly;
the current universal 300 ms zoom hold should not become an artificial delay
for local results. More Python threads are not a general cure for CPU-heavy
geometry: normal CPython permits only one thread to execute Python bytecode at
a time. Chunking work, making it cheaper, or eventually a measured process/native
boundary are separate choices. [Python threading documentation](https://docs.python.org/3.13/library/threading.html).

Sky and terminal improvements
-----------------------------

Sky's `_plot_arc()` samples constellation arcs according to projected length,
then checks whether each sample is visible. Tight zoom increases the work even
for lines wholly outside the viewport. That path consumed about 82% of the
profiled 6° workload. A conservative spherical-cap and horizon reject leaves
visible arcs on the original rendering path:

| Paired culling experiment | Before median | Prototype median |
| --- | ---: | ---: |
| Sky 6°, 120×40, corrected prototype | 78.85 ms | 10.61 ms |
| Sky 6°, 200×60 | 135.11 ms | 19.53 ms |

The initial experiment matched 48 complete frames exactly. Stronger checks
found a horizon-rounding edge case, fixed by retaining the original path
within a conservative numerical margin. The corrected prototype matched 5,100
low-level arc cases and 73 additional complete frames, including randomized
views and an explicit frame for each of the 23 culture choices. The saved
sky evidence records the initial failure and correction. These are convincing
prototype checks, not a replacement for integrated regression tests.
The original 48-frame comparison also passed again after correction, for 121
complete-frame comparisons on the corrected prototype. The 120×40 timing was
rechecked after the numerical correction; the 200×60 number is the original
paired timing, retained separately in the raw evidence.

Sky also rebuilds the full view on hover; at 120×40 that costs 15.47 ms,
essentially the same as wide-view dragging. Retain the displayed body and hit
index and repaint the floating chip separately. Scene/ephemeris construction
alone was only about 1% of the wide-view profile, so memoizing that alone is
not the main opportunity.

Every live frame currently rewrites the whole body. Within each row, redundant
foreground/background commands also repeat. A separate one-frame experiment
removed only identical repeated colour commands while verifying glyphs,
effective colours/attributes, and non-SGR controls:

| 120×40 frame | Original bytes | Compacted bytes | Reduction |
| --- | ---: | ---: | ---: |
| Terrain globe | 115,066 | 64,442 | 44.0% |
| Moon | 129,807 | 91,355 | 29.6% |
| Wide Sky | 133,484 | 87,006 | 34.8% |

These savings do not establish terminal FPS. Production should emit stateful
colour runs directly, not parse completed ANSI strings with a regular
expression. Retained row/cell output can follow, taking special care to erase
old overlay footprints, reset on resize/theme changes, and preserve wide and
combining glyphs and all colour modes. Whole-screen camera movement may still
change most cells; hover and stationary UI stand to benefit most from diffing.

Delivery and acceptance
-----------------------

I would deliver this as several reviewable changes, with the all-scale map
camera as the destination rather than polishing the old split indefinitely:

| Stage | Concrete result | What it establishes |
| --- | --- | --- |
| Shared loop and Sky | Dirty state, bounded input batching, tested arc culling, then colour-run encoding | Immediate improvements with relatively contained scope |
| Maps vertical slice | One camera through globe and a known street tile set; Sky-like zoom easing; retained structured preview | Visual feel, projection correctness, preview cost, and mid-animation replacement |
| Maps data/render integration | Visible tiled sampling, reusable prepared geometry, bounded refinement, coarse coverage fallback | Continuous dragging/zooming without blank scene replacement or synchronous fetches |
| Cartography and presentation | Stable labels, route/hover registration, coherent water/coast layers, overlays and incremental output | Correctness and polish across the existing feature set |

Sky is a bounded optimization. Maps is a substantial renderer and state-model
refactor; it should not be described as a small animation patch. The preview
experiment reduces uncertainty about making motion cheap. It does not yet
resolve the cost of all-scale geometry preparation or terminal presentation.
Estimate the full integration after the vertical slice exposes those costs.

Proposed acceptance targets, to validate on named terminals rather than assume:

- At 120×40, aim for 30 Hz visible motion, with preview construction comfortably
  below 20 ms and input-to-visible-response p95 around 50 ms or better. Measure
  output separately; a fast generator cannot guarantee those display targets.
- At 200×60, adapt preview work to the measured budget. Treat 60 Hz as a later
  stretch target, not a promise supported by the current evidence.
- Under continuous input, produce intermediate frames, show the latest camera,
  and handle release/quit promptly. No backlog of obsolete render jobs.
- No network calls in an interaction frame. Missing detail preserves available
  geography; worker completion cannot move the camera backward.
- Exercise the present 45° handoff region at several latitudes, minimum scale,
  poles, antimeridian, repeated/reversed wheel events, resize during motion,
  pointer anchoring, and completion arriving both mid-animation and after retargeting.
- Verify roads, water, labels, routes, and hover agree throughout preview and
  refinement. Cover light/dark themes, 16/256/truecolor/no-colour, translated,
  wide, and combining text, help/search panels, and offline/incomplete data.
- Measure cold start, cached start, warm movement, download/refinement time,
  background CPU contention, memory/cache bounds, and idle CPU separately.
- Validate real macOS and Windows terminals and a slow-output/remote case.
  Windows's input polling, terminal write backpressure, and display latency
  were not tested in this study.

The evidence is enough to choose a direction: implement the targeted Sky fix
and shared responsiveness work, then build the continuous-camera maps slice
around the retained zoom transition. Full-detail rendering can catch up to
interaction without being responsible for its timing.

Reproduction
------------

Run Python probes from the repository root using the same interpreter where
possible. The Maps baseline harness requires a checkout of `93002fc` or
`a7ecc9b` via `--repo`; use `maps/live_pty.py` for the current implementation. Experimental scripts live in `sky/`, `shared/`, `globe/`, and
`maps/`; their local notes explain the workloads and validation. Each is
separate from the installed package. Avoid running timing probes concurrently.

The map baseline can be reproduced with:

```sh
.venv/bin/python docs/interaction-study/maps/bench.py --repo /path/to/baseline-checkout --n 40 --out /tmp/maps-globe.jsonl
.venv/bin/python docs/interaction-study/maps/bench.py --repo /path/to/baseline-checkout --flat-only --cache-source /path/to/linecast-cache --n 40 --out /tmp/maps-street.jsonl
```

The second command requires the matching cached vector tiles and asserts
coverage; it copies them into a private temporary directory and disables
network access. It never deletes or modifies the supplied source cache.
`--profile` writes separate instrumented profiles alongside the requested
output. The initial scene-building cold costs are deliberately warmed out.

Raw baseline results are in `maps/globe-baseline.jsonl` and
`maps/street-baseline.jsonl`; profiles are in `maps/profiles/`. The supplementary
experiments preserve their own results and limitations. No production patches,
commits, or changes to package dependencies were made for this investigation.
