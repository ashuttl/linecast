"""Alerts from the China Meteorological Administration."""

from linecast._i18n import base_language
from linecast._paths import cache_dir
from linecast.weather.alert_feeds import _cached_feed

# Warning type names parsed from titles: Chinese -> English
_CMA_WARNING_NAMES = {
    "台风": "Typhoon",
    "暴雨": "Rainstorm",
    "暴雪": "Blizzard",
    "寒潮": "Cold Wave",
    "大风": "Strong Wind",
    "沙尘暴": "Sandstorm",
    "高温": "Heat Wave",
    "干旱": "Drought",
    "雷电": "Thunderstorm",
    "冰隹": "Hail",
    "霜冻": "Frost",
    "大雾": "Dense Fog",
    "霾": "Haze",
    "道路结冰": "Road Icing",
    "森林火险": "Forest Fire Risk",
    "雷雨大风": "Thunderstorm Gale",
    "强对流": "Severe Convection",
}

# CMA color -> severity
_CMA_COLORS = {
    "红": "Extreme",   # red
    "橙": "Severe",    # orange
    "黄": "Moderate",  # yellow
    "蓝": "Minor",     # blue
}

# CMA color -> English name
_CMA_COLOR_EN = {
    "红": "Red",
    "橙": "Orange",
    "黄": "Yellow",
    "蓝": "Blue",
}

# Pic URL level code -> severity
_CMA_PIC_LEVELS = {
    "001": "Extreme",
    "002": "Severe",
    "003": "Moderate",
    "004": "Minor",
}

# Center coordinates for each Chinese province, used for nearest-match lookup.
# Maps (lat, lng) -> 2-digit GB/T 2260 province code prefix.
_CMA_PROVINCES = [
    (39.9, 116.4, "11"),    # Beijing
    (39.1, 117.2, "12"),    # Tianjin
    (38.0, 114.5, "13"),    # Hebei
    (37.9, 112.5, "14"),    # Shanxi
    (40.8, 111.7, "15"),    # Inner Mongolia
    (41.8, 123.4, "21"),    # Liaoning
    (43.9, 125.3, "22"),    # Jilin
    (45.8, 126.5, "23"),    # Heilongjiang
    (31.2, 121.5, "31"),    # Shanghai
    (32.1, 118.8, "32"),    # Jiangsu
    (30.3, 120.2, "33"),    # Zhejiang
    (31.8, 117.3, "34"),    # Anhui
    (26.1, 119.3, "35"),    # Fujian
    (28.7, 115.9, "36"),    # Jiangxi
    (36.7, 117.0, "37"),    # Shandong
    (34.8, 113.7, "41"),    # Henan
    (30.6, 114.3, "42"),    # Hubei
    (28.2, 112.9, "43"),    # Hunan
    (23.1, 113.3, "44"),    # Guangdong
    (22.8, 108.3, "45"),    # Guangxi
    (20.0, 110.3, "46"),    # Hainan
    (29.6, 106.5, "50"),    # Chongqing
    (30.6, 104.1, "51"),    # Sichuan
    (26.6, 106.7, "52"),    # Guizhou
    (25.0, 102.7, "53"),    # Yunnan
    (29.6, 91.1, "54"),     # Tibet
    (34.3, 108.9, "61"),    # Shaanxi
    (36.1, 103.8, "62"),    # Gansu
    (36.6, 101.8, "63"),    # Qinghai
    (38.5, 106.3, "64"),    # Ningxia
    (43.8, 87.6, "65"),     # Xinjiang
]


def _cma_provinces_for_coords(lat, lng, n=3):
    """Return the *n* nearest CMA province codes for given coordinates.

    Using multiple candidates handles border cities that are closer to a
    neighbouring province's centre than their own.
    """
    import math
    cos_lat = math.cos(math.radians(lat))
    dists = []
    for plat, plng, code in _CMA_PROVINCES:
        dlat = lat - plat
        dlng = (lng - plng) * cos_lat
        dists.append((dlat * dlat + dlng * dlng, code))
    dists.sort()
    return [code for _, code in dists[:n]]


def fetch(lat, lng, lang="en", address=None):
    """Fetch active CMA weather warnings (China). Cached 15min.

    Uses nmc.cn/rest/findAlarm which has county-level alerts nationwide,
    filtered by the nearest province codes from the alertid prefix.
    """
    provinces = _cma_provinces_for_coords(lat, lng)
    return _cached_feed(
        cache_dir("weather") / f"alerts_cn_{provinces[0]}_{lang}.json",
        "http://www.nmc.cn/rest/findAlarm?pageNo=1&pageSize=500",
        lambda data: _parse_cma_data(data, provinces, lang), timeout=10)


def _parse_cma_data(data, provinces, lang="en"):
    """Parse CMA findAlarm response into normalized alerts.

    *provinces* is a list of 2-digit province code strings; alerts whose
    alertid starts with any of them are included.
    """
    import re

    if not isinstance(data, dict):
        return []

    prefixes = tuple(provinces) if isinstance(provinces, list) else (provinces,)

    body = data.get("data") or {}
    page = body.get("page") or {}
    entries = page.get("list") or []
    province_alarms = body.get("provinceAlarms") or []

    # The titles are in the simplified script; a traditional-script
    # reader gets them rather than the English.
    use_zh = base_language(lang) in ("zh", "zh-Hant")
    alerts = []
    seen = set()

    # Province-level alarms first (most important), then county-level
    for entry in province_alarms + entries:
        alertid = entry.get("alertid") or ""
        if alertid[:2] not in prefixes:
            continue

        title = entry.get("title") or ""
        pic = entry.get("pic") or ""
        issuetime = entry.get("issuetime") or ""
        detail_url = entry.get("url") or ""

        # Extract warning type and color from title
        tm = re.search(r'\u53d1\u5e03(.+?)(\u7ea2|\u6a59|\u9ec4|\u84dd)\u8272\u9884\u8b66', title)
        if tm:
            zh_type = tm.group(1)
            color = tm.group(2)
            severity = _CMA_COLORS.get(color, "Moderate")
        else:
            zh_type = ""
            severity = _cma_severity_from_pic(pic)
            color = ""

        # Build event name — deduplicate by warning type + severity
        if use_zh:
            event = title.split("发布")[-1] if "发布" in title else title
        else:
            en_name = _CMA_WARNING_NAMES.get(zh_type, "") if zh_type else ""
            if en_name:
                color_en = _CMA_COLOR_EN.get(color, "")
                event = f"{color_en} {en_name} Warning".strip()
            else:
                event = title

        dedup_key = (zh_type or title, severity)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        effective = _parse_cma_issuetime(issuetime)
        url = f"http://www.nmc.cn{detail_url}" if detail_url else ""

        alerts.append({
            "event": event,
            "headline": title if use_zh else event,
            "description": title,
            "effective": effective,
            "expires": "",
            "severity": severity,
            "url": url,
        })
    return alerts


def _cma_severity_from_pic(pic_url):
    """Extract severity from CMA pic URL like .../p0007003.png."""
    if not pic_url:
        return "Moderate"
    base = pic_url.rsplit(".", 1)[0]  # strip .png
    code = base[-3:] if len(base) >= 3 else ""
    return _CMA_PIC_LEVELS.get(code, "Moderate")


def _parse_cma_issuetime(s):
    """Parse CMA issuetime '2026/03/07 22:39' -> '2026-03-07T22:39:00'."""
    if not s:
        return ""
    s = s.strip()
    # Format: "2026/03/07 22:39"
    if len(s) >= 16 and s[4] == "/" and s[7] == "/" and s[10] == " ":
        return f"{s[0:4]}-{s[5:7]}-{s[8:10]}T{s[11:16]}:00"
    return ""
