# Globe interaction diagnostics

These experiments test where warm globe rotation spends time. They do not change
production code or propose deleting geographic detail. Their purpose is to inform
a continuous map renderer whose source resolution changes underneath one camera.

## Reproduce

From the repository root, using Python 3.10 or later:

```sh
python docs/interaction-study/globe/globe_lod_diagnostic.py
python docs/interaction-study/globe/globe_labels_toggle.py
```

Both scripts accept `--repo /path/to/linecast`, `--samples N`, and
`--output /path/to/results.txt`. Without `--repo`, they use the checkout containing
the script; without `--output`, they print to stdout. The LOD script also accepts
`--profile-frames N` (zero skips profiling). They use only the standard library and
Linecast source, block socket connections, and warm the packaged z1/z2 canvases.
Run timing experiments separately from other CPU-intensive work.

The archived raw results were collected during the September 7, 2026 local-time
investigation on macOS 27 arm64, CPython 3.13.15. The portable scripts were then
refactored from the temporary harnesses. Their profile filenames/line numbers
therefore differ from the archived capture. No timing values were regenerated
during that refactor.

## Captured results

The fixture is a 120-column, 40-row terminal (120x38 map cells), terrain mode,
zoom 125 degrees, starting near 43 N / 70 W. Color is forced to true color.
Clouds and daylight are off. Horizontal motion changes longitude by 0.37 degrees
per frame; diagonal motion also changes latitude by 0.21 degrees. Twelve timed
frames follow warmup. Times include rendering to ANSI strings, but exclude input
processing, terminal writes, and terminal presentation.

| LOD diagnostic | Horizontal median | Diagonal median |
| --- | ---: | ---: |
| Full renderer | 52.7 ms | 62.1 ms |
| Omit coast extraction, lakes, borders; keep city labels | 30.7 ms | 40.3 ms |
| Same, omit city labels | 28.0 ms | 37.5 ms |
| Single fill sample, omit coast/lakes/borders; keep city labels | 15.6 ms | 18.0 ms |
| Same, omit city labels | 13.2 ms | 15.3 ms |

The last two cases replace the four fine samples averaged into each fill subpixel
with one sample at that subpixel. They retain the source tile resolution, climate
coloring, hillshade, ice, and atmosphere. They remove inland-lake information and
linework and change anti-aliasing and terrain values. These are deliberate quality
ablations, not acceptable final-quality drop-ins. In the raw capture, `no_labels`
means geometry was also removed; it is **not** the existing label toggle.

The separate existing-toggle experiment changes only `show_labels`. Its first
timed frame repeats the warmup camera, so the following moving-frame medians
exclude sample zero:

| Existing toggle | Horizontal median | Diagonal median |
| --- | ---: | ---: |
| Labels on | 51.53 ms | 60.82 ms |
| Labels off | 48.62 ms | 57.33 ms |

The portable toggle script reports both medians explicitly. The archived JSON is
unchanged and contains the original all-sample median and all raw samples.

## What this establishes

In the four-frame diagonal profile, globe view construction consumed 0.525 of
0.664 instrumented seconds: geometry 0.195, borders 0.123, elevation sampling
0.109, and lakes 0.052. Base terrain shading consumed 0.073 seconds, city labels
0.045, and composition 0.019. These costs overlap where calls are nested.
Profiler overhead makes them unsuitable as frame-latency measurements.

Removing labels alone barely helps because the current view loader still builds
the geometry. A substantial quality reduction can approach a 16 ms render budget
at this terminal size, while the full renderer cannot. Prepared source data,
reusable geometry, and a bounded refinement pipeline deserve investigation;
switching to a continuous projection by itself does not remove these costs.

These measurements cover one warm location and size. They do not establish
production interaction latency, cold/offline loading behavior, cloud/daylight
costs, large-terminal performance, or visual acceptability of the reduced paths.

- [LOD timings and profiles](lod-results.txt)
- [Original label-toggle samples](labels-toggle-results.json)
