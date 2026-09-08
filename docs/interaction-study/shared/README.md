# Shared interaction probes

These are research artifacts, not changes to Linecast's live renderer. Results were
collected locally on macOS with the repository's Python 3.13 virtual environment.
The input experiment uses a deterministic simulated clock; its milliseconds are
scenario inputs, not measured execution time. Only the zoom experiment measures
CPU-side wall time. None measures terminal display latency.

Run from the repository root with its installed dependencies:

```sh
.venv/bin/python docs/interaction-study/shared/live_input_probe.py
.venv/bin/python docs/interaction-study/shared/ansi_run_probe.py
.venv/bin/python docs/interaction-study/shared/zoom_preview_probe.py
```

Each script infers the repository from its own location and accepts `--repo PATH`.
Results go to stdout. The rendering scripts disable network connections and use
fresh temporary cache and config directories. They do not delete those directories
or change the user's cache/config. Saved result files preserve the original runs;
the checked-in scripts add portable repository discovery and lint-only adjustments.

## Input scheduling

`live_input_probe.py` drives the actual shared loop with a fake terminal and clock.
It demonstrates two separate issues:

- A changed key followed by an ignored byte loses its requested repaint.
- Continuous input readiness can defer all intermediate drag paints. In the forced
  1,000-event scenario, the screen paints at simulated 1 ms and 1,001 ms.

This does not claim real terminals ordinarily deliver 1,000 events per second.
It isolates the missing persistent dirty state and missing bounded paint deadline.
The existing drain-before-render ordering must survive any scheduler change: a
worker completing during composition needs its wakeup preserved for another frame.

## ANSI color runs

`ansi_run_probe.py` removes only identical repeated color commands while tracking
resets and treating unfamiliar escapes as conservative barriers. It verifies the
same glyph order, effective colors/attributes, and non-SGR controls. One actual
120 by 40 globe terrain frame shrinks from 115,066 to 64,442 UTF-8 bytes (44%).
Moon and sky shrink approximately 30% and 35% in their example frames.

This proves avoidable output volume, not a corresponding FPS improvement. A
production implementation should encode color runs from structured cells instead
of reparsing completed ANSI strings. Terminal display and output backpressure still
need measurement.

## Retained zoom preview

`zoom_preview_probe.py` captures a real 130-degree globe's inputs to
`compose_terrain`: RGB fill samples, coastline masks, and border masks. It retains
the fills at one sample per column and two per cell row; it expands braille masks
to their actual two by four dot geometry, scales those dots, and repacks braille.
It never treats ANSI strings or printed glyphs as raster pixels.

Forty preview frames sample factors 0.85 through 1.23 and use the current terrain
compositor to encode the result. Identity scaling is checked against the source
fills, masks, and label-free ANSI output. Median resample plus encode is 4.982 ms
at 120 by 40 and 12.739 ms at 200 by 60. P95 is 5.228 ms and 13.088 ms.

These timings exclude labels, markers, UI chrome, terminal writes, fresh projection,
new terrain shading, loading, and job dispatch. They are not full application FPS.
The experiment uses nearest-neighbor sampling; it makes no visual-quality assertion
about aliasing, thin strokes, or the eventual detailed-frame replacement.

### Why an eased preview is viable

For an unchanged orthographic view center, projection-plane coordinates are fixed
and globe radius is proportional to `1 / zoom`. Thus geometry at a new zoom is an
exact centered scale of the old projection: `scale = source_zoom / display_zoom`.
Nearest-neighbor resampling of an already rasterized image is still an approximation;
resolution-dependent hillshade, stroke thickness, labels, and atmospheric samples
can differ in a newly computed frame.

The user-visible camera and detailed-render jobs should have separate state. Wheel
input changes a target zoom; a monotonic eased animation advances the displayed
zoom. Each detailed frame carries its source camera, dimensions, style/theme/data
versions, and request generation. When a new frame arrives mid-animation, render it
through the transform from its source camera to the current displayed camera. Do
not snap the displayed camera to that frame's requested zoom.

A subsequent wheel step starts from the current displayed camera and updates the
target. Keep at most one useful running build and one latest pending request;
obsolete work may finish into a cache but must not reset the displayed view. A frame
for an earlier zoom is usable as a retained source when its metadata and coverage
remain compatible; generation mismatch alone need not discard useful cached detail.
Terminal resize and theme changes require explicit invalidation.

Labels must remain a separate text layer. Move each label's anchor and render the
glyphs at normal terminal size; never scale individual characters as pixels. Existing
flattened per-cell label overlays are insufficient to preserve whole label anchors,
text width, collisions, and priorities across arbitrary fractional zoom. Proper
retention should preserve label identity, geographic anchor, string, and style.
Markers and crosshair also need their semantic positioning maintained.

Zooming out exposes world area absent from a screen-sized retained frame. A guard
band, lower-detail wider source, or cheap geometric fallback prevents empty edges.
Once a globe is fully visible, space beyond its limb is legitimately background;
that does not solve coverage at city scale. Reprojecting a changed center or crossing
the current flat/globe boundary is not generally a simple scale. The planned
continuous orthographic camera makes centered zoom particularly straightforward;
pointer-anchored zoom can also change center and needs the appropriate transform.

### Practical scope

An initial centered zoom preview is a bounded first slice: retain compositor layers,
add eased zoom state and a ticker, show the retained preview while one final-detail
request runs, and adopt the result at the current display scale. Making this robust
still requires coverage and cancellation rules, source-camera metadata, label
retention, and the shared scheduler repair. It can validate the desired interaction
before the larger continuous-camera and source-detail redesign is complete.
