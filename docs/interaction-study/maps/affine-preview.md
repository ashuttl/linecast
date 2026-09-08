# Bounded local preview transform

Retained detail frames can use a separable scale and translation when the
omitted spherical terms stay below **0.05 braille dot** across the entire
viewport. This changes only temporary resampling while the next detail frame
is prepared. Camera motion, markers, text anchors, and settled source rendering
keep the exact orthographic projection.

The inverse rotation has source coordinates
`su = m00*u + m01*v + m02*sqrt(1-u²-v²)` and the analogous expression for `sv`.
The fast path retains `m00*u + m02` and `m11*v + m12`. For viewport limits
`|u| ≤ U`, `|v| ≤ V`, the x omission is bounded by
`|m01|*V + |m02|*(1-sqrt(1-U²-V²))`; the y bound swaps axes. The code converts
both bounds into source and target braille dots and requires the Euclidean
bound to be less than 0.05 in both grids. It also requires two local camera
footprints and proves that the entire target remains on the source's front
hemisphere. These are bounds over the full rectangle, including its edges,
rather than acceptance based only on sampled points.

Accepted previews reuse the existing `itemgetter` row sampling path, avoiding
a Python spherical transform and index lookup for every dot. Wide globe views,
unsupported polar footprints, large rotations, and any other failed bound
keep exact matrix resampling. Nearest-neighbor quantization can still choose
an adjacent source sample near a pixel boundary, even for a subpixel change;
the bound describes geometric registration, not bit-identical raster output.

The isolated benchmark uses primed synthetic street fills, sparse road dots,
and a coast mask, with 40 alternating exact/affine transformations per size.
It disables only the affine gate for the exact comparison. It does not include
source preparation, compositor work, concurrent worker/GIL contention, terminal
writes, or native terminal painting.

| Terminal | Exact median / p95 | Affine median / p95 |
| --- | --- | --- |
| 120 × 40 | 17.42 / 17.75 ms | 2.57 / 2.67 ms |
| 200 × 60 | 45.53 / 46.32 ms | 6.68 / 6.95 ms |

Measured on macOS 27, arm64, Python 3.13.15. Full raw values are in
`affine-preview-results.json`; run `affine_preview.py --samples 40 --out PATH`
to repeat. The script infers the repository from its location or accepts
`--repo PATH`.

The new regression coverage compares accepted transforms with independent
camera roundtrips across corners, edges, and interior points at both terminal
sizes, multiple zoom ratios, the dateline, and deep views at ±80° latitude.
It verifies exact fallback for globe, polar, wide, and excessive-rotation
cases, plus the absence of per-pixel matrix construction on the accepted path.
Existing exact spherical reference, crop, hover, Unicode text, and priming
regressions still pass.
