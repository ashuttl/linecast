"""Regenerate GAUGE_COORDS in src/linecast/_tides_qld.py.

The Queensland portal's "predicted interval data" gauge packages carry
no coordinates.  Where a package has a description file (the standard
ports do), that file states the gauge's position in degrees and
minutes; the rest geocode from the gauge's name via Nominatim, which is
plenty for ranking stations by distance.  Gauges that resolve neither
way are printed at the end and simply left out of the table — they stay
reachable by name, just never offered as the nearest station.

    python3 scripts/build_qld_tide_stations.py

Prints the GAUGE_COORDS dict to stdout with a source comment per line;
paste it over the one in _tides_qld.py after eyeballing the geocoded
entries against a map.  Rerun only when the portal adds gauges.
"""

import json
import re
import time
import urllib.parse
import urllib.request

SEARCH_URL = ("https://www.data.qld.gov.au/api/3/action/package_search?"
              + urllib.parse.urlencode({"q": '"predicted interval data"',
                                        "rows": "100"}))
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
PKG_SUFFIX = "-tide-gauge-predicted-interval-data"
# tmr.qld.gov.au (which hosts the description files) rejects
# non-browser user agents.
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) linecast-dev"


def fetch(url):
    parts = urllib.parse.urlsplit(url)
    url = urllib.parse.urlunsplit(
        parts._replace(path=urllib.parse.quote(parts.path)))
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    return urllib.request.urlopen(req, timeout=30).read()


def coords_from_description(txt):
    """(lat, lng) from a description file's degrees + decimal minutes."""
    def field(label):
        m = re.search(rf"^{label},(-?\d+(?:\.\d+)?)", txt, re.M)
        return float(m.group(1)) if m else None

    lat_d, lat_m = field("Latitude Degrees"), field("Latitude Minutes")
    lng_d, lng_m = field("Longitude Degrees"), field("Longitude Minutes")
    if None in (lat_d, lat_m, lng_d, lng_m):
        return None
    lat = lat_d - lat_m / 60 if lat_d < 0 else lat_d + lat_m / 60
    return lat, lng_d + lng_m / 60


def geocode(name):
    url = NOMINATIM_URL + "?" + urllib.parse.urlencode({
        "q": f"{name}, Queensland, Australia", "format": "json", "limit": "1"})
    hits = json.loads(fetch(url))
    time.sleep(1.1)  # Nominatim asks for one request a second
    if not hits:
        return None
    return float(hits[0]["lat"]), float(hits[0]["lon"])


def main():
    packages = json.loads(fetch(SEARCH_URL))["result"]["results"]
    table = {}
    missing = []
    for pkg in sorted(packages, key=lambda p: p.get("name", "")):
        name = pkg.get("name", "")
        if not name.endswith(PKG_SUFFIX):
            continue
        display = pkg.get("title", "").split(" tide gauge")[0].strip()
        coords, source = None, None

        for res in pkg.get("resources", []):
            if (res.get("name") or "").lower().startswith("description"):
                try:
                    coords = coords_from_description(
                        fetch(res["url"]).decode("utf-8", "replace"))
                    source = "description"
                except OSError:
                    pass
                break
        if coords is None:
            coords = geocode(display)
            source = "geocoded"
        if coords is None:
            missing.append(display)
            continue
        table[name[:-len(PKG_SUFFIX)]] = (coords, source)

    print("GAUGE_COORDS = {")
    for key, ((lat, lng), source) in table.items():
        line = f'    "{key}": ({lat:.4f}, {lng:.4f}),'
        print(line if source == "description" else f"{line}  # geocoded")
    print("}")
    if missing:
        print(f"\n# no coordinates found: {', '.join(missing)}")


if __name__ == "__main__":
    main()
