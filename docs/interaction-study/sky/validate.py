"""Deterministic differential checks of the sibling Sky culling prototype."""

import argparse
import json
import math
import random
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import prototype
from prototype import counts, culled_arc, original_arc
from support import Results, runtime, sky
from linecast._sky_catalogue import CULTURES

rng = random.Random(20260908)
categories = {}
failures = []

def unit(v):
    d = math.sqrt(sum(x*x for x in v))
    return tuple(x/d for x in v)

def direction():
    return unit(tuple(rng.gauss(0, 1) for _ in range(3)))

def compare(a, b, cam, f, cx, cy, width, height, category):
    before, after = {}, {}
    original_arc(before, a, b, cam, f, cx, cy, width, height)
    culled_arc(after, a, b, cam, f, cx, cy, width, height)
    categories[category] = categories.get(category, 0) + 1
    if before != after:
        failures.append(dict(category=category, a=a, b=b, cam=cam, f=f,
                             width=width, height=height,
                             missing=len(before.keys()-after.keys()),
                             extra=len(after.keys()-before.keys()),
                             example_before=list(before.items())[:10],
                             example_after=list(after.items())[:10]))
        if len(failures) < 5:
            print(json.dumps({'mismatch': failures[-1]}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--strict-horizon", action="store_true",
                        help="Reproduce the initial horizon-rounding failure")
    args = parser.parse_args()
    if args.strict_horizon:
        prototype.HORIZON_EPSILON = 0.0
    results = Results(args.output_dir, "validation.jsonl")
    sizes = [(20, 6), (78, 24), (118, 40), (198, 60), (300, 8), (20, 100)]
    fovs = [6, 7, 20, 60, 110, 180, 236]
    for i in range(2500):
        width, height = rng.choice(sizes)
        fov = rng.choice(fovs)
        f, cx, cy = sky.focal_length(width, fov), width/2, height
        cam = sky.camera_matrix(rng.uniform(-720, 720), rng.uniform(-12, 98))
        a, b = direction(), direction()
        compare(a, b, cam, f, cx, cy, width, height, 'random_sphere')
        if i < 400:
            for sign, label in [(1, 'near_identical'), (-1, 'near_antipodal')]:
                scale = 10**rng.uniform(-13, -3)
                q = direction()
                b = unit(tuple(sign*x + scale*y for x,y in zip(a,q)))
                compare(a, b, cam, f, cx, cy, width, height, label)
        if i < 300:
            compare(a, a, cam, f, cx, cy, width, height, 'identical')
            compare(a, tuple(-v for v in a), cam, f, cx, cy, width, height, 'antipodal')
        if i < 600:
            # Almost tangent to the geometric horizon, for floating-point sign
            # differences between endpoint and normalized interpolated tests.
            normal = (cam[2], cam[5], cam[8])
            e1 = unit((normal[1], -normal[0], 0))
            e2 = (normal[1]*e1[2]-normal[2]*e1[1],
                  normal[2]*e1[0]-normal[0]*e1[2],
                  normal[0]*e1[1]-normal[1]*e1[0])
            pts=[]
            for _j in range(2):
                t = rng.uniform(-math.pi, math.pi)
                h = -10**rng.uniform(-17, -8)
                pts.append(unit(tuple(math.cos(t)*u + math.sin(t)*v + h*n
                                      for u,v,n in zip(e1,e2,normal))))
            compare(*pts, cam, f, cx, cy, width, height, 'tangent_horizon')
        if i < 600:
            # Screen-edge and corner arcs include the slight negative coordinates
            # that int() rounds toward zero into the first cell.
            edge_x = rng.choice([-.5, 0, width]) + rng.uniform(-1e-7, 1e-7)
            edge_y = rng.choice([-.5, 0, height*2]) + rng.uniform(-1e-7, 1e-7)
            a = sky.unproject(edge_x, edge_y, f, cx, cy)
            b = sky.unproject(edge_x+rng.uniform(-5, 5),
                              edge_y+rng.uniform(-5, 5), f, cx, cy)
            compare(a, b, cam, f, cx, cy, width, height, 'screen_edge')

    results.write({'low_level_checks': sum(categories.values()),
                      'categories': categories, 'mismatches': len(failures),
                      'counts': counts})
    (args.output_dir / 'validation_failures.json').write_text(json.dumps(failures, indent=2))

    base = datetime(2026, 9, 7, 23, tzinfo=ZoneInfo('America/New_York'))
    cultures = [None, *CULTURES]
    frame_cases = []
    for i in range(50):
        width, height = rng.choice(sizes[:4])
        size = width + 2, height
        sky.get_terminal_size = lambda size=size: size
        fov = rng.choice(fovs)
        view = sky.View(rng.uniform(0,360), rng.uniform(-12,98), fov,
                        rng.choice([0,1,2]), cultures[i % len(cultures)])
        now = base + timedelta(hours=rng.uniform(-4000,4000))
        lat, lng = rng.uniform(-85,85), rng.uniform(-180,180)
        sky._plot_arc = original_arc
        expected = sky.render(now,lat,lng,runtime,view,fullscreen=True)
        sky._plot_arc = culled_arc
        actual = sky.render(now,lat,lng,runtime,view,fullscreen=True)
        same = actual == expected
        frame_cases.append(dict(size=size, view=view, now=str(now), lat=lat, lng=lng,
                                equal=same, bytes=len(actual.encode())))
        if not same:
            results.write({'frame_mismatch':frame_cases[-1]})
    # Ensure every culture actually draws its figures at night, independent
    # of the random cases above (which may choose daylight or figures=0).
    for index, culture in enumerate(cultures):
        sky.get_terminal_size = lambda: (120, 40)
        view = sky.View(rng.uniform(0, 360), 50, [6, 20, 110, 236][index % 4], 2, culture)
        sky._plot_arc = original_arc
        expected = sky.render(base, 40.7128, -74.006, runtime, view, fullscreen=True)
        sky._plot_arc = culled_arc
        actual = sky.render(base, 40.7128, -74.006, runtime, view, fullscreen=True)
        frame_cases.append(dict(size=(120, 40), view=view, now=str(base), lat=40.7128,
                                lng=-74.006, equal=actual == expected,
                                bytes=len(actual.encode()), kind="culture_night"))
        if actual != expected:
            results.write({'frame_mismatch': frame_cases[-1]})
    results.write({'complete_frames': len(frame_cases),
                      'frame_mismatches': sum(not r['equal'] for r in frame_cases),
                      'cultures': sorted(set(str(c['view'].culture) for c in frame_cases)),
                      'counts': counts})
    (args.output_dir / 'validation_frames.json').write_text(json.dumps(frame_cases, indent=2))
    assert not failures, f'{len(failures)} arc mismatches'
    assert all(c['equal'] for c in frame_cases), 'frame mismatch'

if __name__ == "__main__":
    try:
        main()
    finally:
        sky._plot_arc = original_arc
