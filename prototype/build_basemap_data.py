"""Build the vendored US basemap data file from Natural Earth GeoJSON.

Clips to a generous CONUS region, simplifies with Douglas-Peucker, rounds
coordinates, and writes a compact JSON consumed at runtime by
linecast._radar_basemap.  Run once at authoring time:

    NE_DIR=/path/to/geojson python3 prototype/build_basemap_data.py

Output: src/linecast/data/basemap_us.json
"""

import json
import math
import os

NE_DIR = os.environ.get("NE_DIR", ".")
OUT = os.path.join(os.path.dirname(__file__), "..", "src", "linecast",
                   "data", "basemap_us.json")

# generous continental-US region (lon_min, lat_min, lon_max, lat_max)
REGION = (-130.0, 20.0, -60.0, 55.0)


def _load(name):
    with open(os.path.join(NE_DIR, name)) as fh:
        return json.load(fh)["features"]


def _bbox_hit(coords):
    """Does any vertex of a (possibly nested) coord list fall in REGION+margin?"""
    minlon, minlat, maxlon, maxlat = REGION
    stack = [coords]
    while stack:
        c = stack.pop()
        if c and isinstance(c[0], (int, float)):
            lon, lat = c[0], c[1]
            if minlon <= lon <= maxlon and minlat <= lat <= maxlat:
                return True
        else:
            stack.extend(c)
    return False


def _dp(points, eps):
    """Douglas-Peucker simplify a list of [lon, lat]."""
    if len(points) < 3:
        return points
    # find point farthest from the line (first, last)
    x0, y0 = points[0]
    x1, y1 = points[-1]
    dx, dy = x1 - x0, y1 - y0
    denom = math.hypot(dx, dy) or 1e-12
    dmax, idx = 0.0, 0
    for i in range(1, len(points) - 1):
        px, py = points[i]
        # perpendicular distance to the segment
        d = abs(dy * px - dx * py + x1 * y0 - y1 * x0) / denom
        if d > dmax:
            dmax, idx = d, i
    if dmax > eps:
        left = _dp(points[:idx + 1], eps)
        right = _dp(points[idx + 1:], eps)
        return left[:-1] + right
    return [points[0], points[-1]]


def _simplify(points, eps):
    """Simplify a polyline OR closed ring.

    Plain Douglas-Peucker degenerates on a closed ring (first == last makes a
    zero-length baseline that collapses everything), so for rings we split at
    the vertex farthest from the start and simplify each half independently.
    """
    if len(points) >= 4 and points[0] == points[-1]:
        p0 = points[0]
        far = max(range(1, len(points) - 1),
                  key=lambda i: (points[i][0] - p0[0]) ** 2 + (points[i][1] - p0[1]) ** 2)
        head = _dp(points[:far + 1], eps)
        tail = _dp(points[far:], eps)
        return head[:-1] + tail
    return _dp(points, eps)


def _round(points, nd=3):
    return [[round(x, nd), round(y, nd)] for x, y in points]


def _lines(features, eps):
    out = []
    for ft in features:
        g = ft["geometry"]
        parts = ([g["coordinates"]] if g["type"] == "LineString"
                 else g["coordinates"] if g["type"] == "MultiLineString" else [])
        for coords in parts:
            if len(coords) < 2 or not _bbox_hit(coords):
                continue
            out.append(_round(_simplify([list(c) for c in coords], eps)))
    return out


def _polys(features, eps, min_ring=6):
    out = []
    for ft in features:
        g = ft["geometry"]
        polys = ([g["coordinates"]] if g["type"] == "Polygon"
                 else g["coordinates"] if g["type"] == "MultiPolygon" else [])
        for poly in polys:
            if not _bbox_hit(poly):
                continue
            rings = []
            for ring in poly:
                simp = _round(_simplify([list(c) for c in ring], eps))
                if len(simp) >= min_ring:
                    rings.append(simp)
            if rings:
                out.append(rings)
    return out


def main():
    minlon, minlat, maxlon, maxlat = REGION
    land = _polys(_load("ne_50m_land.geojson"), eps=0.02)
    coast = _lines(_load("ne_50m_coastline.geojson"), eps=0.012)
    borders = (_lines(_load("ne_50m_admin_1_states_provinces_lines.geojson"), eps=0.012)
               + _lines(_load("ne_50m_admin_0_boundary_lines_land.geojson"), eps=0.012))

    cities = []
    for ft in _load("ne_50m_populated_places_simple.geojson"):
        lon, lat = ft["geometry"]["coordinates"]
        if not (minlon <= lon <= maxlon and minlat <= lat <= maxlat):
            continue
        pr = ft["properties"]
        cities.append([round(lon, 3), round(lat, 3),
                       int(pr.get("pop_max", 0)), pr.get("name", "?")])
    cities.sort(key=lambda c: -c[2])

    data = {"region": list(REGION), "land": land, "coast": coast,
            "borders": borders, "cities": cities}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(data, fh, separators=(",", ":"))
    size = os.path.getsize(OUT)
    print(f"wrote {OUT} ({size // 1024} KB): "
          f"{len(land)} land polys, {len(coast)} coast lines, "
          f"{len(borders)} border lines, {len(cities)} cities")


if __name__ == "__main__":
    main()
