"""Alerts from the Bureau of Meteorology, Australia's weather service.

The Bureau publishes each warning as a CAP file on its anonymous FTP,
the channel it offers for machine access (its website turns away
anything that is not a browser). A file is named for its product --
IDV29000 is Victoria's Warning to Sheep Graziers -- and overwritten at
each issue. It carries no polygon: each of its infos names the
districts it covers by area code, the forecast district VIC_PW007, the
fire weather district VIC_FW007, the metropolitan area VIC_ME001.

So a point is first given the codes of the districts it is in, from
the Bureau's table of forecast locations (IDM00013), and a warning is
kept where an info names one of them. Nothing of the Bureau's is
bundled: its terms allow a copy for personal use and not supplying one
to anyone else, so the table is fetched on the user's machine and kept
for a month.
"""

import hashlib
import io
import re
import struct
import zipfile

from linecast._cache import location_cache_key, write_bytes_atomic
from linecast._geo import haversine_nm
from linecast._http import fetch_json_cached
from linecast._log import log_failure
from linecast._paths import cache_dir
from linecast.weather.alert_feeds.cap import local_tag, sweep_cap_files
from linecast.weather.alert_feeds import _cached_feed

_FTP_HOST = "ftp.bom.gov.au"
_WARNINGS_DIR = "/anon/gen/fwo/"
_LOCATIONS_PATH = "/anon/home/adfd/spatial/IDM00013.zip"
_LOCATIONS_MAX_AGE = 30 * 86400
_CAP_PREFIX = "alerts_au_cap_"

# Ceilings on what is read: a CAP file runs a few KB, and the table's
# zip about 100 KB, its dBase file inside it under a megabyte.
_CAP_BYTES = 256 * 1024
_LOCATIONS_BYTES = 4 * 1024 * 1024
_TABLE_BYTES = 8 * 1024 * 1024

# The third letter of a product code is the state that issued it, by
# the prefix of the area codes it files under. The ACT's districts are
# filed as New South Wales's.
_STATE_LETTERS = {"NSW": "N", "ACT": "N", "NT": "D", "QLD": "Q", "SA": "S",
                  "TAS": "T", "VIC": "V", "WA": "W"}

# A forecast location this much farther than the nearest still lends
# the point its districts; see _area_codes.
_NEAR_KM = 15
_KM_PER_NM = 1.852

_SEVERITIES = ("Extreme", "Severe", "Moderate", "Minor")


def fetch(lat, lng, lang="en", address=None):
    """Fetch the Bureau of Meteorology's warnings (Australia). Cached 15min.

    Only the files of the states the point's districts are in are
    listed, and a file is fetched again only when its line in the
    listing changes. Warnings are in English.
    """
    return _cached_feed(
        cache_dir("weather") / f"alerts_au_{location_cache_key(lat, lng)}.json",
        f"ftp://{_FTP_HOST}{_WARNINGS_DIR}",
        lambda found: _parse_bom(*found),
        fetch=lambda url, timeout: _fetch_bom(lat, lng, timeout), timeout=15)


def _fetch_bom(lat, lng, timeout):
    """The area codes around the point, and the CAP files of the states
    they are in, as (codes, [bytes, ...])."""
    from ftplib import FTP

    codes = _area_codes(lat, lng, timeout)
    if not codes:
        raise LookupError("no forecast locations to place the point by")
    letters = sorted({_STATE_LETTERS[code.split("_", 1)[0]] for code in codes
                      if code.split("_", 1)[0] in _STATE_LETTERS})
    caps, live = [], {letter: set() for letter in letters}
    with FTP(_FTP_HOST, timeout=timeout) as ftp:
        ftp.login()
        for letter in letters:
            listing = []
            ftp.retrlines(f"LIST {_WARNINGS_DIR}ID{letter}*.cap.xml", listing.append)
            for line in listing:
                name = line.split()[-1] if line.strip() else ""
                if not name.endswith(".cap.xml"):
                    continue
                # The line holds the size and the minute the file was
                # written, so a new issue is a new key.
                digest = hashlib.sha1(line.encode()).hexdigest()[:10]
                key = f"{name[:-len('.cap.xml')]}_{digest}"
                live[letter].add(key[len(f"ID{letter}"):])
                raw = _cap_file(ftp, name, key)
                if raw:
                    caps.append(raw)
    # each state's files only, so a place in another state keeps its own
    for letter, keys in live.items():
        sweep_cap_files(f"{_CAP_PREFIX}ID{letter}", keys, "Bureau of Meteorology")
    return codes, caps


def _cap_file(ftp, name, key):
    """A CAP file's bytes, from the cache under `key` or fetched, or
    None when it does not parse: a file caught mid-write is not kept,
    and is asked for again next time."""
    from xml.etree import ElementTree

    path = cache_dir("weather") / f"{_CAP_PREFIX}{key}.xml"
    try:
        return path.read_bytes()
    except OSError:
        pass
    raw = _retrieve(ftp, _WARNINGS_DIR + name, _CAP_BYTES)
    try:
        ElementTree.fromstring(raw)
    except ElementTree.ParseError as exc:
        log_failure("weather/alerts", f"CAP parse of {name}", exc, fallback="skipped")
        return None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_bytes_atomic(path, raw)
    except OSError as exc:
        log_failure("cache", f"write of {path.name}", exc, fallback="not cached")
    return raw


def _retrieve(ftp, path, limit):
    """A file's bytes over an open FTP session, refused past `limit`."""
    chunks, size = [], 0

    def take(block):
        nonlocal size
        size += len(block)
        if size > limit:
            raise ValueError(f"{path} exceeds cap of {limit} bytes")
        chunks.append(block)

    ftp.retrbinary(f"RETR {path}", take)
    return b"".join(chunks)


def _area_codes(lat, lng, timeout):
    """The area codes of the districts around a point: those of the
    nearest of the Bureau's forecast locations, and of any other within
    _NEAR_KM farther. Empty when the table could not be had.

    The district boundaries are published too, but at 4.6 MB, and 14
    for the fire districts, they are more than a client should fetch
    for this. The nearest location names the district of 96.5% of
    points within 20 km of a town; taking those nearly as near as well,
    98.5%, for a tenth of a district extra on average. A point near a
    line is more likely shown its neighbor's warning than not shown its
    own.
    """
    locations = _locations(timeout)
    if not locations:
        return set()
    distances = [(haversine_nm(lat, lng, la, ln) * _KM_PER_NM, codes)
                 for la, ln, codes in locations]
    nearest = min(km for km, _codes in distances)
    return {code for km, codes in distances if km <= nearest + _NEAR_KM
            for code in codes.split()}


def _locations(timeout):
    """The forecast locations as [[lat, lng, "CODE CODE ..."], ...], or
    None. Fetched once a month; an older copy stands in when the FTP
    does not answer."""
    return fetch_json_cached(
        cache_dir("weather") / "bom_locations.json", _LOCATIONS_MAX_AGE,
        f"ftp://{_FTP_HOST}{_LOCATIONS_PATH}",
        fetch=lambda url, timeout: _ftp_get(_LOCATIONS_PATH, _LOCATIONS_BYTES, timeout),
        transform=_parse_locations, timeout=timeout, provider="weather/alerts")


def _ftp_get(path, limit, timeout):
    """One file from the Bureau's FTP, in a session of its own."""
    from ftplib import FTP
    with FTP(_FTP_HOST, timeout=timeout) as ftp:
        ftp.login()
        return _retrieve(ftp, path, limit)


def _parse_locations(blob):
    """The forecast locations from the IDM00013 zip, each with the codes
    of its forecast district, fire weather district, and metropolitan
    areas (a location can be in several). The virtual buoys at sea are
    in no district and are left out."""
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        info = archive.getinfo("IDM00013.dbf")
        if info.file_size > _TABLE_BYTES:
            raise ValueError(f"IDM00013.dbf exceeds cap of {_TABLE_BYTES} bytes")
        rows = _dbf_rows(archive.read(info), ("LAT", "LON", "AAC_PW", "AAC_FW", "AAC_ME"))
    locations = []
    for lat, lng, *codes in rows:
        if not codes[0]:
            continue
        locations.append([round(float(lat), 5), round(float(lng), 5),
                          " ".join(code for code in codes if code)])
    if not locations:
        raise ValueError("no forecast locations in IDM00013")
    return locations


def _dbf_rows(data, names):
    """The named fields of each live record of a dBase III table, as
    text. A field the table lacks raises KeyError."""
    count, header_len, record_len = struct.unpack_from("<IHH", data, 4)
    if header_len + count * record_len > len(data):
        raise ValueError("dBase table shorter than its header says")
    fields, pos, offset = {}, 32, 1  # a record opens with its deletion flag
    while data[pos] != 0x0D:
        name = data[pos:pos + 11].split(b"\0", 1)[0].decode("ascii")
        fields[name] = (offset, data[pos + 16])
        offset += data[pos + 16]
        pos += 32
    spans = [fields[name] for name in names]
    rows = []
    for i in range(count):
        start = header_len + i * record_len
        if data[start:start + 1] == b"*":
            continue
        rows.append([data[start + at:start + at + n].decode("latin-1").strip()
                     for at, n in spans])
    return rows


def _parse_bom(codes, caps):
    """The warnings in the CAP files that name one of the point's area
    codes, normalized."""
    codes = set(codes)
    alerts, seen = [], set()
    for raw in caps:
        for alert in _cap_alerts(raw, codes):
            key = (alert["event"], alert["headline"])
            if key not in seen:
                seen.add(key)
                alerts.append(alert)
    return alerts


def _cap_alerts(raw, codes):
    """One CAP file's warnings for the area codes, none for a test or a
    cancellation. A file can hold several infos -- a fire weather
    warning puts its Catastrophic districts in one and its Extreme ones
    in another -- and each is placed by its own areas."""
    from xml.etree import ElementTree
    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError as exc:
        log_failure("weather/alerts", "Bureau of Meteorology CAP parse", exc,
                    fallback="skipped")
        return []
    head = {local_tag(child.tag): (child.text or "").strip() for child in root}
    if head.get("status") != "Actual" or head.get("msgType") == "Cancel":
        return []
    alerts = []
    for info in root:
        if local_tag(info.tag) == "info":
            alert = _info_alert(info, codes)
            if alert is not None:
                alerts.append(alert)
    return alerts


def _info_alert(info, codes):
    """One CAP info as a normalized alert, or None when it names none of
    the area codes or calls a warning off ("Cancellation of Wind
    Warning for ...", beside the warnings still in force)."""
    text, areas = {}, set()
    for child in info:
        tag = local_tag(child.tag)
        if tag == "area":
            for geocode in child:
                if local_tag(geocode.tag) != "geocode":
                    continue
                pair = {local_tag(c.tag): (c.text or "").strip() for c in geocode}
                if pair.get("valueName") == "AMOC-AreaCode":
                    areas.add(pair.get("value", ""))
        else:
            text[tag] = (child.text or "").strip()
    headline = " ".join(text.get("headline", "").split())
    if headline.lower().startswith("cancellation") or not areas & codes:
        return None
    name = _warning_name(headline, text.get("event", ""))
    if not name:
        return None
    return {
        "event": name,
        "headline": headline or name,
        "description": _paragraphs(text.get("description", "")),
        "effective": text.get("onset") or text.get("effective", ""),
        "expires": text.get("expires", ""),
        "severity": _severity(text.get("severity", ""), name),
        "url": text.get("web", ""),
    }


def _warning_name(headline, event):
    """The warning's own name, from its headline: "Warning to Sheep
    Graziers for North Central, ... forecast districts" is a Warning to
    Sheep Graziers. The CAP event is a category ("Weather" for a Severe
    Weather Warning), and stands in only for a headline that is missing."""
    name = headline.split(" for ", 1)[0].strip() or " ".join(event.split())
    return name[:1].upper() + name[1:]


def _severity(severity, name):
    """The CAP severity, where the Bureau gives one. Its severe
    thunderstorm and severe weather warnings say Unknown; a warning
    named Severe is taken at its word, and the rest as Moderate."""
    if severity in _SEVERITIES:
        return severity
    return "Severe" if name.lower().startswith("severe") else "Moderate"


def _paragraphs(text):
    """A description with its paragraphs kept and each one's lines and
    indentation run together."""
    paragraphs = re.split(r"\n\s*\n", text.strip())
    return "\n\n".join(" ".join(p.split()) for p in paragraphs if p.strip())
