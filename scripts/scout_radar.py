#!/usr/bin/env python3
"""Rank candidate radar locations by how much weather is on them right now.

A radar screenshot is only worth taking where something is happening, and
that moves. This asks the radar's own source for the newest observed frame
over each candidate city, at the gallery's window, and reports the echo
coverage the header would show. Only places inside LibreWXR's real radar
regions are tried, so the winner is a radar composite, not a model.

    scripts/scout_radar.py            # a table, best first
    scripts/scout_radar.py --best     # the winning place and its language

capture_screenshots.sh calls it with --best when LINECAST_CAPTURE_RADAR_PLACE
is "auto".
"""

from __future__ import annotations

import argparse
import sys

from linecast.radar import frames as _radar_frames
from linecast.radar.render import bbox_for
from linecast.radar.sources import get_source, has_radar

# The gallery radar frame: 120x36 cells, two of them header and footer.
COLS, ROWS = 120, 36
ZOOM = 6.0

# Each candidate carries the language the radar should speak there, from
# the ones linecast has, so the frame reads as a local's would.
CANDIDATES = [
    # North America
    ("Seattle, Washington", 47.606, -122.332, "en"),
    ("Portland, Oregon", 45.505, -122.675, "en"),
    ("San Francisco, California", 37.775, -122.419, "en"),
    ("Los Angeles, California", 34.052, -118.244, "en"),
    ("Denver, Colorado", 39.739, -104.990, "en"),
    ("Dallas, Texas", 32.777, -96.797, "en"),
    ("Houston, Texas", 29.760, -95.370, "en"),
    ("Kansas City, Missouri", 39.100, -94.578, "en"),
    ("Minneapolis, Minnesota", 44.978, -93.265, "en"),
    ("Chicago, Illinois", 41.878, -87.630, "en"),
    ("St. Louis, Missouri", 38.627, -90.199, "en"),
    ("Nashville, Tennessee", 36.163, -86.781, "en"),
    ("Atlanta, Georgia", 33.749, -84.388, "en"),
    ("New Orleans, Louisiana", 29.951, -90.072, "en"),
    ("Miami, Florida", 25.762, -80.192, "en"),
    ("Charlotte, North Carolina", 35.227, -80.843, "en"),
    ("Washington, DC", 38.907, -77.037, "en"),
    ("New York, New York", 40.713, -74.006, "en"),
    ("Boston, Massachusetts", 42.360, -71.059, "en"),
    ("Portland, Maine", 43.661, -70.255, "en"),
    ("Buffalo, New York", 42.887, -78.879, "en"),
    ("Toronto, Ontario", 43.653, -79.383, "en"),
    ("Montreal, Quebec", 45.502, -73.567, "fr"),
    ("Halifax, Nova Scotia", 44.649, -63.575, "en"),
    ("Vancouver, British Columbia", 49.283, -123.121, "en"),
    ("Calgary, Alberta", 51.045, -114.072, "en"),
    ("Winnipeg, Manitoba", 49.895, -97.139, "en"),
    # Europe
    ("Reykjavík, Iceland", 64.147, -21.942, "is"),
    ("Glasgow, Scotland", 55.861, -4.250, "en"),
    ("Dublin, Ireland", 53.350, -6.260, "en"),
    ("London, England", 51.507, -0.128, "en"),
    ("Paris, France", 48.857, 2.352, "fr"),
    ("Bordeaux, France", 44.838, -0.579, "fr"),
    ("Amsterdam, Netherlands", 52.370, 4.895, "nl"),
    ("Hamburg, Germany", 53.551, 9.994, "de"),
    ("Berlin, Germany", 52.520, 13.405, "de"),
    ("Munich, Germany", 48.135, 11.582, "de"),
    ("Vienna, Austria", 48.208, 16.374, "de"),
    ("Zurich, Switzerland", 47.377, 8.541, "de"),
    ("Milan, Italy", 45.464, 9.190, "it"),
    ("Rome, Italy", 41.903, 12.496, "it"),
    ("Madrid, Spain", 40.417, -3.704, "es"),
    ("Lisbon, Portugal", 38.722, -9.139, "pt"),
    ("Barcelona, Spain", 41.385, 2.173, "es"),
    ("Oslo, Norway", 59.913, 10.752, "no"),
    ("Bergen, Norway", 60.392, 5.324, "no"),
    ("Stockholm, Sweden", 59.329, 18.069, "sv"),
    ("Copenhagen, Denmark", 55.676, 12.568, "da"),
    ("Helsinki, Finland", 60.170, 24.938, "fi"),
    ("Warsaw, Poland", 52.230, 21.012, "pl"),
    ("Prague, Czechia", 50.075, 14.438, "en"),
    ("Athens, Greece", 37.984, 23.728, "en"),
    # East and Southeast Asia
    ("Tokyo, Japan", 35.676, 139.650, "ja"),
    ("Osaka, Japan", 34.694, 135.502, "ja"),
    ("Sapporo, Japan", 43.062, 141.354, "ja"),
    ("Fukuoka, Japan", 33.590, 130.402, "ja"),
    ("Taipei, Taiwan", 25.033, 121.565, "zh"),
    ("Manila, Philippines", 14.600, 120.984, "en"),
    ("Kuala Lumpur, Malaysia", 3.139, 101.687, "en"),
    ("Singapore", 1.352, 103.820, "en"),
]


def echo_at(lat: float, lon: float) -> float | None:
    """Echo coverage, in percent, of the newest observed frame over a place."""
    source = get_source(lat, lon, 1)
    _radar_frames._source = source
    frames = [f for f in source.current_frames() if not f.future]
    if not frames:
        return None
    bbox = bbox_for(lat, lon, ZOOM, COLS, ROWS - 2)
    _, echo = _radar_frames._load_frame(bbox, COLS, ROWS - 2, frames[-1])
    return float(echo)


def score(echo: float) -> float:
    """Echo is good up to a point; past it the frame is a wall of rain."""
    return echo - max(0.0, echo - 35.0) * 2


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--best", action="store_true",
                        help="print only the winning place and language, tab-separated")
    parser.add_argument("--limit", type=int, default=0,
                        help="try only the first N candidates (for a quick look)")
    args = parser.parse_args()

    results: list[tuple[float, float, str, str]] = []
    candidates = CANDIDATES[:args.limit] if args.limit else CANDIDATES
    for name, lat, lon, lang in candidates:
        if not has_radar(lat, lon):
            continue
        try:
            echo = echo_at(lat, lon)
        except Exception as exc:  # a stalled host is not the end of the scout
            print(f"{name}: {exc}", file=sys.stderr)
            continue
        if echo is None:
            continue
        results.append((score(echo), echo, name, lang))
        if not args.best:
            print(f"{echo:5.1f}%  {name}  ({lang})", flush=True)

    if not results:
        sys.exit("scout_radar: no frames came back")
    results.sort(reverse=True)
    if args.best:
        _, _, name, lang = results[0]
        print(f"{name}\t{lang}")
    else:
        print()
        print("best first:")
        for _, echo, name, lang in results[:8]:
            print(f"{echo:5.1f}%  {name}  ({lang})")


if __name__ == "__main__":
    main()
