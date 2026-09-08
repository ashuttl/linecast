"""Offline retained map-layer scaling proof; labels excluded, no tty timing."""
import argparse
import json
import math
import os
import socket
import statistics
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[3])
args = parser.parse_args()

os.environ['LINECAST_CACHE_DIR'] = tempfile.mkdtemp(prefix='linecast-zoom-')
os.environ['LINECAST_CONFIG_DIR'] = tempfile.mkdtemp(prefix='linecast-zoom-config-')
os.environ['LINECAST_COLOR'] = 'truecolor'
os.environ['LINECAST_THEME'] = 'off'
os.environ.pop('NO_COLOR', None)
sys.path.insert(0, str(args.repo / 'src'))

def offline(*args, **kwargs):
    raise OSError('network disabled for retained zoom probe')

socket.socket.connect = socket.create_connection = offline
from linecast import maps, _color, _maps_paint  # noqa: E402
from linecast._runtime import RuntimeConfig  # noqa: E402

_color._COLOR_MODE = 'truecolor'
runtime = RuntimeConfig(live=True, icons='plain', lang='en', oneline=False)
BITS = ((0,0,1), (0,1,2), (0,2,4), (0,3,64),
        (1,0,8), (1,1,16), (1,2,32), (1,3,128))

def expand_masks(masks, width, height):
    dots = [bytearray(width * 2) for _ in range(height * 4)]
    for cy, row in enumerate(masks):
        for cx, mask in enumerate(row):
            for dx, dy, bit in BITS:
                if mask & bit:
                    dots[cy*4+dy][cx*2+dx] = 1
    return dots

def indexes(n, scale):
    return [math.floor(n/2 + (i+.5-n/2)/scale) for i in range(n)]

def sample_grid(grid, xs, ys, empty):
    h, w = len(grid), len(grid[0])
    blank = [empty] * len(xs)
    rows = []
    for y in ys:
        rows.append([grid[y][x] if 0 <= x < w else empty for x in xs]
                    if 0 <= y < h else blank[:])
    return rows

def scaled_masks(dots, xs, ys, w, h):
    sampled = sample_grid(dots, xs, ys, 0)
    rows = []
    for cy in range(h):
        yy = cy * 4
        r0, r1, r2, r3 = sampled[yy:yy+4]
        row = []
        for cx in range(w):
            x = cx * 2
            row.append(r0[x] | (r1[x]<<1) | (r2[x]<<2) | (r3[x]<<6) |
                       (r0[x+1]<<3) | (r1[x+1]<<4) | (r2[x+1]<<5) | (r3[x+1]<<7))
        rows.append(row)
    return rows

def stats(xs):
    return dict(median=round(statistics.median(xs), 3),
                p95=round(sorted(xs)[int(.95*(len(xs)-1))], 3),
                max=round(max(xs), 3))

original = maps.compose_terrain
captured = {}
def capture(basemap, terrain, overlays, w, h, **kwargs):
    captured.update(terrain=terrain, overlays=overlays, w=w, h=h, kwargs=kwargs)
    return original(basemap, terrain, overlays, w, h, **kwargs)
maps.compose_terrain = capture

for size in ((120,40), (200,60)):
    maps.get_terminal_size = lambda size=size: size
    maps.render_map(43.66, -70.2, 'Preview', 130, marker=(43.66,-70.2),
                    runtime=runtime, block=True, view='terrain')
    w, h = captured['w'], captured['h']
    fills = captured['terrain']
    coast = captured['kwargs']['coast']
    border = captured['kwargs']['strokes'][0]
    coast_dots = expand_masks(coast, w, h)
    border_dots = expand_masks(border.dots, w, h)
    # These are structured colors and geometry, never ANSI glyph images.
    # Every retained border dot has BORDER's ink; resampling its geometry
    # does not require resampling labels or inventing stroke colors.
    border_colors = [[_maps_paint.BORDER_STROKE] * w for _ in range(h)]

    def preview(scale, w=w, h=h, fills=fills, coast_dots=coast_dots,
                border_dots=border_dots, border_colors=border_colors):
        tx, ty = indexes(w,scale), indexes(h*2,scale)
        dx, dy = indexes(w*2,scale), indexes(h*4,scale)
        scaled_fills = sample_grid(fills, tx, ty, _color.BG_PRIMARY)
        scaled_coast = scaled_masks(coast_dots, dx, dy, w, h)
        scaled_border = scaled_masks(border_dots, dx, dy, w, h)
        layer = SimpleNamespace(dots=scaled_border, color=border_colors)
        return scaled_fills, scaled_coast, layer

    def compose(data, w=w, h=h):
        f, c, b = data
        return original(None, f, {}, w, h, coast=c, strokes=[b])

    # Identity must preserve the original geometry, fill, and glyph encoding.
    identity = preview(1)
    assert identity[0] == fills
    assert identity[1] == coast
    assert identity[2].dots == border.dots
    assert compose(identity) == original(None, fills, {}, w, h,
                                         coast=coast, strokes=[border])
    for i in range(5):
        compose(preview(1+i/50))
    sampling, encoding, total, bytes_ = [], [], [], []
    for i in range(40):
        scale = .85 + (i % 20)/50
        t0 = time.perf_counter()
        data = preview(scale)
        t1 = time.perf_counter()
        out = '\n'.join(compose(data))
        t2 = time.perf_counter()
        sampling.append((t1-t0)*1000)
        encoding.append((t2-t1)*1000)
        total.append((t2-t0)*1000)
        bytes_.append(len(out.encode()))
    print(json.dumps(dict(size=size, map_cells=[w,h], n=40,
                          source_zoom=130, factors=[.85,1.23],
                          sampling_ms=stats(sampling), encoding_ms=stats(encoding),
                          total_ms=stats(total), bytes=stats(bytes_),
                          identity_exact=True,
                          labels='excluded and retained separately',
                          excludes=('tty writes, labels, fresh geometry, shading, '
                                    'requests, frame chrome'))),
          flush=True)
