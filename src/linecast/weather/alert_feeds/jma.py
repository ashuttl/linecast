"""Alerts from the Japan Meteorological Agency."""

from linecast._http import fetch_json_cached
from linecast._paths import cache_dir
from linecast.weather.sources import _SEVERITY_RANK, _cached_feed

# Center coordinates for each JMA forecast office, used for nearest-match lookup.
# Hokkaido is subdivided into 8 offices; Okinawa into 3; all others are 1:1 with prefectures.
_JMA_OFFICES = [
    # Hokkaido
    (45.4, 141.7, "011000"), (43.8, 142.4, "012000"),
    (44.0, 144.3, "013000"), (42.9, 143.2, "014030"),
    (43.0, 145.0, "014100"), (41.8, 140.7, "015000"),
    (43.1, 141.3, "016000"), (42.6, 141.6, "017000"),
    # Tohoku
    (40.8, 140.7, "020000"), (39.7, 141.1, "030000"),
    (38.3, 140.9, "040000"), (39.7, 140.1, "050000"),
    (38.2, 140.3, "060000"), (37.7, 140.5, "070000"),
    # Kanto
    (36.3, 140.4, "080000"), (36.6, 139.9, "090000"),
    (36.4, 139.1, "100000"), (35.9, 139.6, "110000"),
    (35.6, 140.1, "120000"), (35.7, 139.7, "130000"),
    (35.4, 139.6, "140000"),
    # Chubu
    (37.9, 139.0, "150000"), (36.7, 137.2, "160000"),
    (36.6, 136.6, "170000"), (36.1, 136.2, "180000"),
    (35.7, 138.6, "190000"), (36.2, 138.2, "200000"),
    (35.4, 136.8, "210000"), (34.9, 138.4, "220000"),
    (35.2, 137.0, "230000"),
    # Kinki
    (34.7, 136.5, "240000"), (35.0, 136.1, "250000"),
    (35.0, 135.8, "260000"), (34.7, 135.5, "270000"),
    (34.9, 134.7, "280000"), (34.7, 135.8, "290000"),
    (34.0, 135.4, "300000"),
    # Chugoku
    (35.5, 134.2, "310000"), (35.5, 133.1, "320000"),
    (34.7, 133.9, "330000"), (34.4, 132.5, "340000"),
    (34.2, 131.5, "350000"),
    # Shikoku
    (34.1, 134.6, "360000"), (34.3, 134.0, "370000"),
    (33.8, 132.8, "380000"), (33.6, 133.5, "390000"),
    # Kyushu
    (33.6, 130.4, "400000"), (33.3, 130.3, "410000"),
    (32.7, 129.9, "420000"), (32.8, 130.7, "430000"),
    (33.2, 131.6, "440000"), (31.9, 131.4, "450000"),
    (31.6, 130.6, "460100"),
    # Okinawa
    (26.3, 127.8, "471000"), (24.8, 125.3, "472000"),
    (24.3, 124.2, "473000"),
]

# JMA warning code -> (English name, Japanese name, severity)
_JMA_WARNING_NAMES = {
    # Special Warnings (\u7279\u5225\u8b66\u5831)
    "32": ("Special Blizzard Warning", "暴風雪特別警報", "Extreme"),
    "33": ("Special Heavy Rain Warning", "大雨特別警報", "Extreme"),
    "35": ("Special Storm Warning", "暴風特別警報", "Extreme"),
    "36": ("Special Heavy Snow Warning", "大雪特別警報", "Extreme"),
    "37": ("Special High Wave Warning", "波浪特別警報", "Extreme"),
    "38": ("Special Storm Surge Warning", "高潮特別警報", "Extreme"),
    # Warnings (\u8b66\u5831)
    "02": ("Blizzard Warning", "暴風雪警報", "Severe"),
    "03": ("Heavy Rain Warning", "大雨警報", "Severe"),
    "04": ("Flood Warning", "洪水警報", "Severe"),
    "05": ("Storm Warning", "暴風警報", "Severe"),
    "06": ("Heavy Snow Warning", "大雪警報", "Severe"),
    "07": ("High Wave Warning", "波浪警報", "Severe"),
    "08": ("Storm Surge Warning", "高潮警報", "Severe"),
    # Watches (\u6ce8\u610f\u5831)
    "10": ("Heavy Rain Watch", "大雨注意報", "Moderate"),
    "12": ("Heavy Snow Watch", "大雪注意報", "Moderate"),
    "13": ("Wind Snow Watch", "風雪注意報", "Moderate"),
    "14": ("Thunderstorm Watch", "雷注意報", "Moderate"),
    "15": ("High Wind Watch", "強風注意報", "Moderate"),
    "16": ("High Wave Watch", "波浪注意報", "Moderate"),
    "17": ("Snowmelt Watch", "融雪注意報", "Moderate"),
    "18": ("Flood Watch", "洪水注意報", "Moderate"),
    "19": ("Storm Surge Watch", "高潮注意報", "Moderate"),
    "20": ("Dense Fog Watch", "濃霧注意報", "Moderate"),
    "21": ("Dry Air Watch", "乾燥注意報", "Minor"),
    "22": ("Avalanche Watch", "なだれ注意報", "Moderate"),
    "23": ("Low Temperature Watch", "低温注意報", "Minor"),
    "24": ("Frost Watch", "霜注意報", "Minor"),
    "25": ("Icing Watch", "着氷注意報", "Moderate"),
    "26": ("Snow Accretion Watch", "着雪注意報", "Moderate"),
    "27": ("Other Watch", "その他の注意報", "Minor"),
}

_JMA_ACTIVE = {"発表", "継続"}

# Every JMA area, from the centers down to the municipalities: a name, an
# English name, and a parent. A municipality's code is its JIS code with
# two zeros after it; a big city split for warning purposes gets a part
# each (1410011 横浜市北部, 1410012 横浜市南部; Kobe and Hiroshima a ward
# each). Municipalities merge now and then, so the table is fetched and
# kept a month rather than baked.
_JMA_AREA_URL = "https://www.jma.go.jp/bosai/common/const/area.json"
_JMA_AREA_MAX_AGE = 30 * 86400


def _jma_prefecture(address):
    """The two-digit prefecture code of a Nominatim address (JP-13 is
    Tokyo), which JMA's area codes begin with, or ""."""
    region = str((address or {}).get("ISO3166-2-lvl4", ""))
    code = region[3:]
    if region.startswith("JP-") and len(code) == 2 and code.isdigit():
        return code
    return ""


def _jma_office_for_coords(lat, lng, prefecture=""):
    """Find the nearest JMA office code for given coordinates.

    With a prefecture, the nearest of that prefecture's offices: the
    nearest office overall can be the neighbour's for a reader near a
    border (Kawaguchi, in Saitama, is nearer Tokyo's office than its own).
    """
    import math
    cos_lat = math.cos(math.radians(lat))
    offices = [o for o in _JMA_OFFICES if o[2].startswith(prefecture)] or _JMA_OFFICES
    best_code = "130000"
    best_dist = float("inf")
    for olat, olng, code in offices:
        dlat = lat - olat
        dlng = (lng - olng) * cos_lat
        dist = dlat * dlat + dlng * dlng
        if dist < best_dist:
            best_dist = dist
            best_code = code
    return best_code


def _jma_area_for_address(address, office_code):
    """The JMA areas a Nominatim address falls in, or None.

    The warning file for an office lists every municipality in it with
    its own warnings, so a reader in Shinagawa need not hear about high
    waves in the Izu islands, which are Tokyo too. The reverse geocoder,
    asked in the country's own language, names the municipality as JMA
    spells it (品川区, 大島町), so an exact name is the match; a city JMA
    splits into parts (横浜市北部, 横浜市南部) or wards (神戸市中央区) is
    matched by prefix and the parts pooled. The prefecture in the address
    (JP-13) keeps a namesake in another prefecture out (府中市 is in Tokyo
    and Hiroshima); without one, the nearest office stands in for it.

    Returns {"office": code, "codes": [municipality codes], "names":
    {every name from the municipality up to the office}}, or None when
    the address names nothing, the table is unavailable, or no municipality
    matches; the caller then reads the whole office, as before.
    """
    if not address:
        return None
    names = [address.get(k) for k in ("city", "town", "village", "municipality")]
    names = [n for n in names if isinstance(n, str) and n]
    if not names:
        return None
    prefecture = _jma_prefecture(address)

    table = fetch_json_cached(
        cache_dir("weather") / "jma_areas.json", _JMA_AREA_MAX_AGE, _JMA_AREA_URL,
        timeout=10, fallback=None, provider="weather/alerts",
    )
    if not isinstance(table, dict):
        return None
    class20s = table.get("class20s") or {}
    class15s = table.get("class15s") or {}
    class10s = table.get("class10s") or {}
    offices = table.get("offices") or {}

    def chain(code):
        """(office, [(level, code, name), ...]) up from a municipality, or None."""
        c20 = class20s.get(code) or {}
        c15 = class15s.get(c20.get("parent")) or {}
        c10 = class10s.get(c15.get("parent")) or {}
        office = c10.get("parent")
        if not office:
            return None
        return office, [c20.get("name"), c15.get("name"), c10.get("name"),
                        (offices.get(office) or {}).get("name")]

    for exact in (True, False):
        codes, names_seen, office = [], set(), None
        for code, entry in class20s.items():
            name = entry.get("name") or ""
            if exact:
                hit = name in names
            else:
                hit = any(name.startswith(n) for n in names)
            if not hit:
                continue
            if prefecture and not code.startswith(prefecture):
                continue
            found = chain(code)
            if found is None:
                continue
            if not prefecture and found[0] != office_code:
                continue
            if office is None:
                office = found[0]
            elif found[0] != office:
                continue
            codes.append(code)
            names_seen.update(n for n in found[1] if n)
        if codes:
            return {"office": office, "codes": codes, "names": names_seen}
    return None


def _jma_headline_for(headline, names):
    """The sentences of a JMA headline that speak to the reader's area.

    The office writes one headline for the prefecture, a sentence per
    concern, each opening with the areas it is for: "伊豆諸島南部では、
    強風や高波に注意してください。伊豆諸島北部、伊豆諸島南部では、…".
    A sentence that opens with areas keeps only if one of them is the
    reader's; one that opens with none is for everyone. "Xを除くYでは"
    (Y except X) counts the reader out when they are in X.
    """
    kept = []
    for sentence in (headline or "").split("。"):
        if not sentence:
            continue
        areas, spoke, _rest = sentence.partition("では")
        if spoke:
            excluded, minus, remainder = areas.partition("を除く")
            if minus:
                if any(n in excluded for n in names):
                    continue
                areas = remainder
            if not any(n in areas for n in names):
                continue
        kept.append(sentence + "。")
    return "".join(kept)


def fetch(lat, lng, lang="en", address=None):
    """Fetch active JMA weather warnings (Japan). Cached 15min.

    The office is the nearest in the address's prefecture, or the
    nearest outright without one. The warnings are the reader's
    municipality's when the address names one the office's file lists;
    otherwise every area's in the office's prefecture, pooled, or every
    area's in the file when none of its codes carry the prefecture.
    """
    office_code = _jma_office_for_coords(lat, lng, _jma_prefecture(address))
    area = _jma_area_for_address(address, office_code)
    if area:
        office_code = area["office"]
        key = "-".join(area["codes"])
    else:
        key = office_code
    return _cached_feed(
        cache_dir("weather") / f"alerts_jp_{key}_{lang}.json",
        f"https://www.jma.go.jp/bosai/warning/data/warning/{office_code}.json",
        lambda data: _parse_jma(data, office_code, area, lang), timeout=10)


def _parse_jma(data, office_code, area, lang):
    """An office's warning file as normalized alerts for the area."""
    # both are null, not absent, when the office has nothing to say
    headline = data.get("headlineText") or ""
    report_dt = data.get("reportDatetime") or ""
    use_ja = lang == "ja"

    rows = [a for t in data.get("areaTypes") or [] for a in t.get("areas") or []]
    mine = []
    if area:
        mine = [r for r in rows if r.get("code") in area["codes"]]
        if mine:
            headline = _jma_headline_for(headline, area["names"])
    if not mine:
        # an area code's first two digits are its prefecture
        mine = [r for r in rows if str(r.get("code", "")).startswith(office_code[:2])]
    rows = mine or rows

    active_codes = set()
    for row in rows:
        for w in row.get("warnings") or []:
            if w.get("status", "") in _JMA_ACTIVE and w.get("code") in _JMA_WARNING_NAMES:
                active_codes.add(w["code"])

    alerts = []
    seen = set()
    # The codes are a set; within a severity, JMA's own numbering orders
    # them, so the same warnings come out the same way every run.
    for code in sorted(active_codes,
                       key=lambda c: (_SEVERITY_RANK[_JMA_WARNING_NAMES[c][2]], c)):
        en_name, ja_name, severity = _JMA_WARNING_NAMES[code]
        event = ja_name if use_ja else en_name
        dedup_key = (event, severity)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        alerts.append({
            "event": event,
            "headline": headline if use_ja else event,
            "description": headline,
            "effective": report_dt,
            "expires": "",
            "severity": severity,
            "url": "https://www.jma.go.jp/bosai/warning/",
        })
    return alerts
