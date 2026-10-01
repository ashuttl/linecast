"""Regenerate _TABLE and GAUGES in src/linecast/tides/jma.py.

JMA's list of tide-table stations is an HTML page in Japanese: each row
gives a two-character code, the station's name, and its position in
degrees and minutes north and east.  The romanized names are not on the
list but on each station's own table page, in capitals after the
Japanese one: 潮位表 田子（TAGO）.  They are set in title case here, and
a parenthesis gets a space before it.  GAUGES is the codes in JMA's list
of the stations it observes at itself.

    python3 scripts/build_jma_tide_stations.py

Prints the two tables to stdout; paste them over the ones in
tides/jma.py.  That is one request per station, half a second apart, so
a run takes a few minutes.  A station whose page gives no romanized name
is printed at the end with its Japanese name standing in: romanize it by
hand and mark the line.  JMA republishes the list each year; rerun when
a station comes or goes.
"""

import html
import re
import time
import urllib.request

BASE = "https://www.data.jma.go.jp/kaiyou/db/tide"
STATIONS_URL = f"{BASE}/suisan/station.php"
GAUGES_URL = f"{BASE}/genbo/station.php"
PAGE_URL = f"{BASE}/suisan/suisan.php?stn={{code}}"


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "linecast-dev"})
    return urllib.request.urlopen(req, timeout=30).read().decode("utf-8")


def rows(page):
    """Each station row's cells as plain text."""
    out = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", page, flags=re.S):
        cells = [html.unescape(re.sub(r"<[^>]+>", "", c)).strip()
                 for c in re.findall(r"<td[^>]*>(.*?)</td>", row, flags=re.S)]
        # A station's row opens with its number in the list, then its code
        if len(cells) > 4 and cells[0].isdigit():
            out.append(cells)
    return out


def degrees(text):
    """Decimal degrees from JMA's 45゜24' form."""
    m = re.match(r"(\d+)゜(\d+)'", text)
    return int(m.group(1)) + int(m.group(2)) / 60 if m else None


def romanized(code):
    """The name in the station page's heading, "潮位表 三宅島（坪田）
    （MIYAKEJIMA(TSUBOTA)）", as "Miyakejima (Tsubota)"; None if absent.
    The romanized part is the last full-width parenthesis; the ASCII
    ones inside it are part of the name."""
    m = re.search(r"<h1>(.*?)</h1>", fetch(PAGE_URL.format(code=code)), flags=re.S)
    if not m:
        return None
    heading = html.unescape(m.group(1)).strip()
    start, end = heading.rfind("（"), heading.rfind("）")
    name = heading[start + 1:end] if 0 <= start < end else ""
    if not re.search(r"[A-Za-z]", name):
        return None
    name = re.sub(r"[A-Za-z']+", lambda w: w.group(0).capitalize(), name)
    return re.sub(r"\s*\(\s*", " (", name).strip()


def main():
    gauges = sorted({cells[1] for cells in rows(fetch(GAUGES_URL))})
    table, unnamed = [], []
    for cells in rows(fetch(STATIONS_URL)):
        code, name_ja = cells[1], cells[2]
        lat, lng = degrees(cells[3]), degrees(cells[4])
        if lat is None or lng is None:
            unnamed.append(f"{code} {name_ja} (no position; left out)")
            continue
        time.sleep(0.5)
        name = romanized(code)
        if name is None:
            unnamed.append(f"{code} {name_ja}")
            name = name_ja
        table.append((code, name_ja, name, lat, lng))

    print("_TABLE = (")
    for code, name_ja, name, lat, lng in table:
        print(f'    ("{code}", "{name_ja}", "{name}", {lat:.4f}, {lng:.4f}),')
    print(")")
    print()
    print("GAUGES = frozenset((")
    for i in range(0, len(gauges), 12):
        print("    " + " ".join(f'"{g}",' for g in gauges[i:i + 12]))
    print("))")
    if unnamed:
        print(f"\n# no romanized name: {', '.join(unnamed)}")


if __name__ == "__main__":
    main()
