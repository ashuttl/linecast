"""Galaxies, nebulae and clusters: catalogue positions, extended sky glows.

The glows are schematic, scaled by angular size; they are not photographs
or a calibrated model of visual detectability. Integrated magnitude alone
cannot describe the visibility of an extended object. A modest penalty
for diffuse light keeps these behind the stars, fading out in twilight.
"""

import gzip
import json
import math
from functools import lru_cache

from linecast._runtime import log_failure
from linecast._sky_catalogue import _DATA, equatorial_vector


@lru_cache(maxsize=1)
def objects():
    try:
        records = json.loads(gzip.decompress((_DATA / 'sky-objects.json.gz').read_bytes()))
        for r in records:
            r['at'] = equatorial_vector(math.radians(r['ra']), math.radians(r['dec']))
        return sorted(records, key=lambda r: (r['mag'], r['id']))
    except Exception as exc:
        log_failure('sky', 'deep-sky object load', exc, fallback='no deep-sky objects')
        return []


def object_name(record, lang):
    return record['names'].get(lang) or record['name']


def paint(fb, scene, cam, frame, f, cx, cy, eye_limit, color):
    """Paint under stars and bodies; return label anchors and hover targets."""
    from linecast.sky import _extinction, _mat_apply, alt_az_of, project, unproject
    labels, hits = [], []
    if scene.darkness <= 0:
        return labels, hits
    for record in objects():
        vec = record['at']
        alt, az = alt_az_of(_mat_apply(scene.horizontal, vec))
        if alt <= 0:
            continue
        visibility = min(1.0, max(0.0, (eye_limit - record['mag']
                                        - _extinction(alt) - 0.7) / 2.0))
        strength = scene.darkness * visibility * min(1.0, alt / 12.0)
        if strength <= 0:
            continue
        at = _mat_apply(frame, vec)
        if at[2] <= 0:
            continue
        centre = project(at, f, cx, cy)
        sx, sy = centre
        scale = 2.0 * f / (1.0 + at[2])
        major, minor = (math.radians(size / 120.0) * scale for size in record['size'])
        ux, uy = 1.0, 0.0
        if 'pa' in record:
            ra, dec, pa = (math.radians(record[k]) for k in ('ra', 'dec', 'pa'))
            north = (-math.sin(dec) * math.cos(ra), -math.sin(dec) * math.sin(ra),
                     math.cos(dec))
            east = (-math.sin(ra), math.cos(ra), 0.0)
            axis = tuple(n * math.cos(pa) + e * math.sin(pa) for n, e in zip(north, east))
            offset = tuple(v * math.cos(0.001) + a * math.sin(0.001)
                           for v, a in zip(vec, axis))
            tip = project(_mat_apply(frame, offset), f, cx, cy)
            ux, uy = tip[0] - sx, tip[1] - sy
            length = math.hypot(ux, uy)
            ux, uy = ux / length, uy / length
        else:
            major = minor = math.sqrt(major * minor)
        major, minor = max(1.2, major), max(0.8, minor)
        radius = max(major, minor)
        if sx + radius < 0 or sx - radius >= fb.graph_w:
            continue
        if sy + radius < 0 or sy - radius >= fb.total_spy:
            continue
        cells = set()
        for y in range(max(0, int(sy - radius)), min(fb.total_spy, int(sy + radius) + 1)):
            for x in range(max(0, int(sx - radius)), min(fb.graph_w, int(sx + radius) + 1)):
                dx, dy = x + 0.5 - sx, y + 0.5 - sy
                r2 = ((dx * ux + dy * uy) / major) ** 2
                r2 += ((-dx * uy + dy * ux) / minor) ** 2
                if r2 > 1:
                    continue
                # Clip every part of an extended object at the horizon.
                camera = unproject(x + 0.5, y + 0.5, f, cx, cy)
                if cam[2] * camera[0] + cam[5] * camera[1] + cam[8] * camera[2] <= 0:
                    continue
                # Open clusters are their real constituent stars, with a
                # name and hover footprint; do not turn them into nebulosity.
                if record['type'] != 'oc':
                    glow = 0.28 * math.exp(-3.5 * r2) + 0.22 * math.exp(-24 * r2)
                    fb.set_pixel(x, y, color, strength * glow)
                cells.add((x, y // 2))
        payload = (record, alt, az)
        hits.extend((x, row * 2, 'deep_sky', payload) for x, row in sorted(cells))
        if 0 <= sx < fb.graph_w and 0 <= sy < fb.total_spy:
            labels.append((record, int(sx), int(sy) // 2, strength))
    return labels, hits
