"""Compare retained local previews with exact rotation and bounded affine sampling.

Synthetic immutable street layers isolate transformation cost without network,
source preparation, terminal writes, or a concurrent detail worker. The exact
variant disables only the new affine gate, preserving all other optimizations.
"""

import argparse
from dataclasses import replace
import json
from pathlib import Path
import platform
import statistics
import sys
import time
from types import SimpleNamespace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument('--samples', type=int, default=40)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    if args.samples < 1:
        parser.error('--samples must be positive')
    sys.path.insert(0, str(args.repo / 'src'))
    from linecast import _maps_preview
    from linecast._maps_camera import MapCamera

    affine_warp = _maps_preview._Warp

    class ExactWarp(affine_warp):
        def __init__(self, source, target):
            super().__init__(source, target)
            self.affine = None

    rows = []
    for gw, hc in ((120, 38), (200, 58)):
        base = MapCamera(43.66787, -70.19165, .01, gw, hc)
        camera = replace(base, gw=gw + 2 * (gw // 4), hc=hc + 2 * (hc // 4),
                         zoom=base.zoom * (hc + 2 * (hc // 4)) / hc)
        w, h = camera.gw, camera.hc
        fills = [[(30 + x % 4, 45 + y % 4, 40) for x in range(w)] for y in range(h * 2)]
        dots = [[(x * 7 + y * 13) % 256 if x % 7 == 0 or y % 11 == 0 else 0
                 for x in range(w)] for y in range(h)]
        coast = [[255 if x == w // 4 else 0 for x in range(w)] for y in range(h)]
        layer = SimpleNamespace(dots=dots, color=[[(60, 70, 90)] * w for _ in range(h)],
                                ribbon=set())
        prepared = _maps_preview.PreparedMap(camera, fills, layer=layer, coast=coast,
                                             street=True).prime()
        targets = [base.pan(6 + .45 * i, 2 + .16 * i) for i in range(args.samples)]
        assert all(affine_warp(camera, target).affine is not None for target in targets)
        timings = {name: [] for name in ('exact', 'affine')}
        # Alternate the execution order rather than timing one long phase first.
        for i, target in enumerate(targets):
            order = (('exact', ExactWarp), ('affine', affine_warp))
            for name, warp in order[::(-1 if i % 2 else 1)]:
                _maps_preview._Warp = warp
                start = time.perf_counter()
                result = prepared.transformed(target)
                timings[name].append((time.perf_counter() - start) * 1000)
                assert len(result.fills) == hc * 2
        for name, samples in timings.items():
            rows.append(dict(size=[gw, hc + 2], path=name, samples=args.samples,
                             median_ms=statistics.median(samples),
                             p95_ms=sorted(samples)[int(.95 * (len(samples) - 1))],
                             max_ms=max(samples)))
    _maps_preview._Warp = affine_warp
    report = dict(python=sys.version, platform=platform.platform(),
                  note='Isolated synthetic retained layers; no GIL contention or terminal write',
                  results=rows)
    rendered = json.dumps(report, indent=2)
    print(rendered)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered + '\n')


if __name__ == '__main__':
    main()
