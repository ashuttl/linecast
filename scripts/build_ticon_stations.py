"""Regenerate src/linecast/data/ticon.json.gz, the tide constants of the
world's gauges outside the United States and Canada.

The constants are TICON-4's (Hart-Davis, Dettmering and Seitz, 2025,
fitted to the GESLA-4 sea-level records; CC BY 4.0), by way of the
Slackwater station database, which normalises the names, geocodes each
gauge's region and time zone, re-fits the German and Dutch gauges whose
records were stamped in local time, and derives each gauge's datums
from its record: mean sea level, and the chart datum its country's
charts use. Slackwater also scores every station and marks duplicates
of the same gauge from other sources as superseded.

    git clone --depth 1 --branch v1.0.0-beta.20260930 \\
        https://github.com/openwatersio/slackwater-database.git /tmp/slackwater
    python3 scripts/build_ticon_stations.py /tmp/slackwater

Kept: TICON-4 stations Slackwater accepts, whose licence allows
commercial use (it marks the gauges GESLA relayed from Copernicus Marine
as non-commercial, and linecast is MIT), outside the United States and
Canada, which NOAA and CHS cover from their own tables. Of two gauges
within a kilometre the better-scored stays. Each keeps the constituents
linecast's tide machine knows, with amplitudes in millimetres and phases
in tenths of a degree, which is finer than either is known to.

Run once at authoring time, with the release tag above or a newer one;
the output records the tag. Check a few stations against a national
table after a rebuild (the TICON provider's docstring names them).
"""

import glob
import gzip
import json
import math
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
from linecast.tides import harmonic  # noqa: E402

OUT = os.path.join(HERE, "..", "src", "linecast", "data", "ticon.json.gz")
LEFT_OUT_COUNTRIES = {"United States", "Canada"}
ATTRIBUTION = (
    "Tide constants: Hart-Davis, M., Dettmering, D., Seitz, F. (2025), TICON-4: "
    "TIdal CONstants based on GESLA-4 sea-level records, SEANOE, "
    "https://doi.org/10.17882/109129, licensed CC BY 4.0, by way of the Slackwater "
    "database (https://github.com/openwatersio/slackwater-database), which "
    "normalises names, derives datums, and re-fits some gauges."
)


def km_apart(a, b):
    lat1, lng1, lat2, lng2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2)
    return 12742 * math.asin(math.sqrt(h))


def main(root):
    quality = {q["id"]: q for q in json.load(open(os.path.join(root, "quality.json")))}
    try:
        tag = subprocess.run(["git", "-C", root, "describe", "--tags"],
                             capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        tag = "unknown"

    candidates = []
    unknown = {}
    for path in sorted(glob.glob(os.path.join(root, "data", "ticon", "*.json"))):
        ident = os.path.basename(path)[:-5]
        q = quality.get(f"ticon/{ident}")
        station = json.load(open(path))
        if not q or not q.get("accepted"):
            continue
        if not station.get("license", {}).get("commercial_use"):
            continue
        if station.get("country") in LEFT_OUT_COUNTRIES:
            continue
        datums = station.get("datums") or {}
        chart = station.get("chart_datum") or "MSL"
        if "MSL" not in datums or (chart != "MSL" and chart not in datums):
            continue
        for c in station["harmonic_constituents"]:
            if harmonic.canonical(c["name"]) is None:
                unknown[c["name"]] = max(unknown.get(c["name"], 0.0), c["amplitude"])
        candidates.append((q.get("score", 0), ident, station))

    # Of two gauges a kilometre apart, the better-scored one stays.
    candidates.sort(key=lambda c: (-c[0], c[1]))
    kept = []
    for score, ident, station in candidates:
        here = (station["latitude"], station["longitude"])
        if any(km_apart(here, (s["latitude"], s["longitude"])) < 1 for _, _, s in kept):
            continue
        kept.append((score, ident, station))
    kept.sort(key=lambda c: c[1])

    names = [n for n in harmonic.CONSTITUENTS
             if any(harmonic.canonical(c["name"]) == n
                    for _, _, s in kept for c in s["harmonic_constituents"])]
    rows = []
    for _score, ident, station in kept:
        by_name = {harmonic.canonical(c["name"]): c for c in station["harmonic_constituents"]}
        amps, phases = [], []
        for n in names:
            c = by_name.get(n)
            amps.append(round(c["amplitude"] * 1000) if c else 0)
            phases.append(round((c["phase"] % 360) * 10) if c else 0)
        datums = station["datums"]
        chart = station.get("chart_datum") or "MSL"
        z0 = datums["MSL"] - (datums[chart] if chart != "MSL" else datums["MSL"])
        rows.append([
            ident, station["name"], station.get("region") or "", station["country"],
            round(station["latitude"], 4), round(station["longitude"], 4),
            station["timezone"], chart, round(z0 * 1000), amps, phases,
        ])

    payload = {
        "source": f"slackwater-database {tag}, TICON-4",
        "attribution": ATTRIBUTION,
        "constituents": names,
        "stations": rows,
    }
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    with gzip.GzipFile(OUT, "wb", mtime=0, compresslevel=9) as f:
        f.write(raw)
    countries = {}
    for r in rows:
        countries[r[3]] = countries.get(r[3], 0) + 1
    print(f"{len(rows)} stations in {len(countries)} countries, {len(names)} constituents, "
          f"{os.path.getsize(OUT):,} bytes gzipped ({len(raw):,} raw)")
    print("left out, largest amplitude anywhere (m):",
          ", ".join(f"{n} {a:.3f}" for n, a in sorted(unknown.items(), key=lambda kv: -kv[1])))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
