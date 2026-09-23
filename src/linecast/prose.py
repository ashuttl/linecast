"""linecast prose -- read the weather prose over a frozen set of forecasts.

An undocumented command for working on the sentences under the weather
graph.  `linecast prose fetch` pulls real forecasts for sixty-odd places
around the world and freezes them as a named set; `linecast prose` prints
what the weather view would say for each, in the languages asked for,
so a change to the prose can be read across every climate at once and
against the same data as before.

    linecast prose fetch                 freeze today's forecasts as a set
    linecast prose                       the latest set, in English
    linecast prose --lang en,ja --data   with the hours and days underneath
    linecast prose --trace               every candidate sentence, chosen or not
    linecast prose --save before.json    keep the paragraphs; change the code;
    linecast prose --diff before.json    then read only what changed
"""

import argparse
import copy
import json
import re
import sys
import time
from datetime import datetime, timedelta

from linecast._i18n import LANGUAGE_CODES, VARIANTS, canonical_language
from linecast._paths import cache_dir
from linecast._commands import formatter_class
from linecast._runtime import VersionAction, WeatherRuntime, resolve_lang
from linecast._textwidth import wrap_display_width

# (name, latitude, longitude, units): a spread of climates and hemispheres,
# with a few imperial places so the Fahrenheit paths get read too.
PLACES = (
    ("Reykjavík", 64.15, -21.94, "m"), ("Tromsø", 69.65, 18.96, "m"),
    ("Nuuk", 64.18, -51.72, "m"), ("Anchorage", 61.22, -149.90, "i"),
    ("Vancouver", 49.28, -123.12, "m"), ("Seattle", 47.61, -122.33, "i"),
    ("San Francisco", 37.77, -122.42, "i"), ("Denver", 39.74, -104.99, "i"),
    ("Phoenix", 33.45, -112.07, "i"), ("Chicago", 41.88, -87.63, "i"),
    ("New Orleans", 29.95, -90.07, "i"), ("Halifax", 44.65, -63.57, "m"),
    ("Mexico City", 19.43, -99.13, "m"), ("Havana", 23.11, -82.37, "m"),
    ("Bogotá", 4.71, -74.07, "m"), ("Lima", -12.05, -77.04, "m"),
    ("La Paz", -16.50, -68.15, "m"), ("Santiago", -33.45, -70.67, "m"),
    ("Buenos Aires", -34.60, -58.38, "m"), ("São Paulo", -23.55, -46.63, "m"),
    ("Manaus", -3.12, -60.02, "m"), ("Ushuaia", -54.80, -68.30, "m"),
    ("London", 51.51, -0.13, "m"), ("Dublin", 53.35, -6.26, "m"),
    ("Paris", 48.86, 2.35, "m"), ("Lisbon", 38.72, -9.14, "m"),
    ("Rome", 41.90, 12.50, "m"), ("Athens", 37.98, 23.73, "m"),
    ("Berlin", 52.52, 13.41, "m"), ("Helsinki", 60.17, 24.94, "m"),
    ("Kyiv", 50.45, 30.52, "m"), ("Istanbul", 41.01, 28.98, "m"),
    ("Cairo", 30.04, 31.24, "m"), ("Nairobi", -1.29, 36.82, "m"),
    ("Cape Town", -33.93, 18.42, "m"), ("Lagos", 6.52, 3.38, "m"),
    ("Dubai", 25.20, 55.27, "m"), ("Mumbai", 19.08, 72.88, "m"),
    ("Delhi", 28.61, 77.21, "m"), ("Kathmandu", 27.72, 85.32, "m"),
    ("Bangkok", 13.76, 100.50, "m"), ("Singapore", 1.35, 103.82, "m"),
    ("Hong Kong", 22.32, 114.17, "m"), ("Tokyo", 35.68, 139.69, "m"),
    ("Sapporo", 43.06, 141.35, "m"), ("Seoul", 37.57, 126.98, "m"),
    ("Ulaanbaatar", 47.92, 106.92, "m"), ("Sydney", -33.87, 151.21, "m"),
    ("Perth", -31.95, 115.86, "m"), ("Auckland", -36.85, 174.76, "m"),
    ("Honolulu", 21.31, -157.86, "i"), ("Longyearbyen", 78.22, 15.63, "m"),
    ("Manila", 14.60, 120.98, "m"), ("Taipei", 25.03, 121.57, "m"),
    ("Jakarta", -6.21, 106.85, "m"), ("Johannesburg", -26.20, 28.05, "m"),
    ("Moscow", 55.76, 37.62, "m"), ("Riyadh", 24.71, 46.68, "m"),
    ("Miami", 25.76, -80.19, "i"), ("Minneapolis", 44.98, -93.27, "i"),
    ("Edinburgh", 55.95, -3.19, "m"), ("Zürich", 47.38, 8.54, "m"),
)

# What the hourly and daily tables call each WMO code, short enough to
# sit in a column.  l/h light/heavy, f freezing.
SHORT = {
    0: "clr", 1: "mclr", 2: "pcld", 3: "ovc", 45: "fog", 48: "fog",
    51: "ldz", 53: "dz", 55: "hdz", 56: "fdz", 57: "fdz",
    61: "lrn", 63: "rn", 65: "hrn", 66: "frn", 67: "frn",
    71: "lsn", 73: "sn", 75: "hsn", 77: "sg",
    80: "lsh", 81: "sh", 82: "hsh", 85: "ssh", 86: "hssh",
    95: "ts", 96: "ts", 99: "ts",
}

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


# ---------------------------------------------------------------------------
# Sets on disk
# ---------------------------------------------------------------------------

def sets_root():
    return cache_dir("prose")


def slug_of(name):
    return re.sub(r"[^a-z]+", "-", name.lower()).strip("-")


def list_sets():
    """Set names, oldest first."""
    root = sets_root()
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if (p / "index.json").is_file())


def load_set(name):
    """The frozen places of a set, in fetch order."""
    root = sets_root() / name
    index = json.loads((root / "index.json").read_text())
    return [json.loads((root / f"{slug}.json").read_text()) for slug in index]


def runtime_for(lang, metric):
    return WeatherRuntime(live=False, icons="plain", lang=lang, oneline=False,
                          celsius=metric, metric=metric, shading=False)


def fetch_set(name, places=PLACES, out=None):
    """Fetch every place in km/h and freeze it under `name`."""
    from linecast.weather import sources
    root = sets_root() / name
    root.mkdir(parents=True, exist_ok=True)
    out = out or sys.stdout
    index = []
    for place, lat, lng, units in places:
        metric = units == "m"
        data = sources.fetch_forecast(lat, lng, runtime_for("en", metric))
        if not data:
            print(f"failed  {place}", file=out)
            continue
        now = sources._local_now_for_data(data)
        slug = slug_of(place)
        record = {"name": place, "lat": lat, "lng": lng, "metric": metric,
                  "now": now.isoformat(), "data": data}
        (root / f"{slug}.json").write_text(json.dumps(record))
        index.append(slug)
        print(f"{now.strftime('%a %H:%M')}  {place}", file=out)
        time.sleep(0.3)
    (root / "index.json").write_text(json.dumps(index))
    return len(index)


# ---------------------------------------------------------------------------
# Reading a set
# ---------------------------------------------------------------------------

def wind_for(data, runtime):
    """The frozen data is km/h; the view fetches wind in the language's
    unit, so give a m/s language what Open-Meteo would have given it."""
    if runtime.wind_unit != "m/s":
        return data
    data = copy.deepcopy(data)
    for block, keys in (("hourly", ("wind_speed_10m", "wind_gusts_10m")),
                        ("daily", ("wind_speed_10m_max", "wind_gusts_10m_max")),
                        ("current", ("wind_speed_10m", "wind_gusts_10m"))):
        for key in keys:
            value = data.get(block, {}).get(key)
            if isinstance(value, list):
                data[block][key] = [None if v is None else v / 3.6 for v in value]
            elif value is not None:
                data[block][key] = value / 3.6
    return data


def paragraph(record, lang, trace=None):
    """The prose for one place in one language, as one string."""
    from linecast.weather.sections import narrative_lines
    runtime = runtime_for(lang, record["metric"])
    now = datetime.fromisoformat(record["now"])
    rows = narrative_lines(wind_for(record["data"], runtime), now, 10_000, runtime, trace=trace)
    return " ".join(_ANSI.sub("", row) for row in rows)


def _every_language():
    """Every language and regional variant, each variant after its base."""
    codes = []
    for code in LANGUAGE_CODES:
        codes.append(code)
        codes.extend(v for v, base in VARIANTS.items() if base == code)
    return codes


def languages(spec):
    """The languages a --lang value names, in the order given.  "all" is
    every language with its regional variants; a code may be written as a
    locale is ("pt_pt", "es-es")."""
    known = _every_language()
    if spec == "all":
        return known
    if spec:
        given = [c.strip() for c in spec.split(",") if c.strip()]
        codes = [canonical_language(c) for c in given]
        unknown = [g for g, c in zip(given, codes) if c not in known]
        if unknown:
            raise SystemExit(f"linecast prose: unknown language {', '.join(unknown)}; "
                             f"one of {', '.join(known)}")
        return codes
    configured, _source = resolve_lang()
    return ["en"] if configured == "en" else ["en", configured]


def heading(record):
    """"Reykjavík   Tue 02:26   Light Drizzle 10°C, feels 6°C"."""
    from linecast.weather.i18n import wmo_label
    current = record["data"].get("current", {})
    now = datetime.fromisoformat(record["now"])
    unit = "°C" if record["metric"] else "°F"
    parts = [wmo_label(current.get("weather_code"), "en")]
    temp, feels = current.get("temperature_2m"), current.get("apparent_temperature")
    if temp is not None:
        parts.append(f"{temp:.0f}{unit}")
    if feels is not None:
        parts[-1] += f", feels {feels:.0f}{unit}"
    return f"{record['name']}   {now.strftime('%a %H:%M')}   {' '.join(p for p in parts if p)}"


def hours_table(record):
    """The next 24 hours, one line each."""
    data, metric = record["data"], record["metric"]
    now = datetime.fromisoformat(record["now"])
    h = data["hourly"]
    first = now.replace(minute=0, second=0, microsecond=0)
    amount = "mm" if metric else "in"
    lines = [f"{'':>5}  {'':>4} {'%':>3} {amount:>5} {'gust':>4} {'temp':>4} {'feel':>4} "
             f"{'cloud':>5}"]
    cloud = h.get("cloud_cover") or []
    for i, ts in enumerate(h.get("time") or []):
        dt = datetime.fromisoformat(ts)
        if dt < first or dt > first + timedelta(hours=24):
            continue
        code = h["weather_code"][i] or 0
        p = h["precipitation_probability"][i] or 0
        a = h["precipitation"][i] or 0
        g = h["wind_gusts_10m"][i] or 0
        t = h["temperature_2m"][i]
        f = h["apparent_temperature"][i]
        c = cloud[i] if i < len(cloud) and cloud[i] is not None else 0
        day = "" if dt.date() == now.date() else "+"
        lines.append(f"{dt.strftime('%H:%M'):>5}{day:1} {SHORT.get(code, str(code)):>4} {p:3.0f} "
                     f"{a:5.1f} {g:4.0f} {t:4.0f} {f:4.0f} {c:5.0f}")
    return lines


def days_table(record):
    """Yesterday to the end of the week, one line each."""
    data, metric = record["data"], record["metric"]
    now = datetime.fromisoformat(record["now"])
    d = data["daily"]
    lines = []
    for k, ts in enumerate(d["time"]):
        day = datetime.fromisoformat(ts).date()
        off = (day - now.date()).days
        label = {-1: "yest", 0: "today", 1: "tmrw"}.get(off, day.strftime("%a"))
        hi, lo = d["temperature_2m_max"][k], d["temperature_2m_min"][k]
        p = d["precipitation_probability_max"][k] or 0
        a = d["precipitation_sum"][k] or 0
        code = d["weather_code"][k] or 0
        lines.append(f"{label:>5}  {SHORT.get(code, str(code)):>4} {lo:4.0f}–{hi:<4.0f} {p:3.0f}% "
                     f"{a:5.1f}{'mm' if metric else 'in'}")
    return lines


def trace_lines(trace):
    """Each candidate sentence, marked if it made the paragraph."""
    lines = []
    for entry in trace:
        at = entry["at"]
        when = "  week" if at == float("inf") else f"{at:+5.1f}h"
        mark = "*" if entry["chosen"] else " "
        lines.append(f"{mark} {entry['salience']}  {when}  {entry['text']}")
    return lines


def show(records, langs, width, data=False, trace=False, out=None):
    """Print the set, and return {slug: {lang: paragraph}} for --save."""
    out = out or sys.stdout
    tty = out.isatty()
    label = max(len(code) for code in langs)
    indent = " " * (label + 6)
    said = {}
    for n, record in enumerate(records, 1):
        head = heading(record)
        bold, plain = ("\x1b[1m", "\x1b[0m") if tty else ("", "")
        print(f"{n:>2}  {bold}{head}{plain}", file=out)
        said[slug_of(record["name"])] = {}
        traces = {}
        for lang in langs:
            entries = [] if trace else None
            text = paragraph(record, lang, trace=entries)
            said[slug_of(record["name"])][lang] = text
            traces[lang] = entries
            rows = wrap_display_width(text or "(nothing to say)", max(20, width - len(indent)))
            for i, row in enumerate(rows):
                print(f"    {lang:<{label}}  {row}" if i == 0 else f"{indent}{row}", file=out)
        if trace:
            for lang in langs:
                print(f"{indent}[{lang}]", file=out)
                for line in trace_lines(traces[lang]):
                    print(f"{indent}{line}", file=out)
        if data:
            for line in hours_table(record) + [""] + days_table(record):
                print(f"{indent}{line}", file=out)
        print(file=out)
    return said


def diff_lines(before, after):
    """Places and languages whose paragraph changed, old then new."""
    lines = []
    for slug, langs in after.items():
        for lang, text in langs.items():
            old = before.get(slug, {}).get(lang)
            if old is None or old == text:
                continue
            lines.append(f"{slug} [{lang}]")
            lines.append(f"  - {old or '(nothing to say)'}")
            lines.append(f"  + {text or '(nothing to say)'}")
    return lines


# ---------------------------------------------------------------------------
# The command
# ---------------------------------------------------------------------------

def prose_parser():
    p = argparse.ArgumentParser(
        prog="linecast prose", formatter_class=formatter_class(),
        description="Read the weather prose over a frozen set of real forecasts")
    p.add_argument("--version", action=VersionAction)
    sub = p.add_subparsers(dest="action")
    f = sub.add_parser("fetch", help="fetch today's forecasts and freeze them as a set",
                       formatter_class=formatter_class())
    f.add_argument("--set", dest="set_name", metavar="NAME", default=None,
                   help="name the set (default: today's date)")
    sub.add_parser("sets", help="list the frozen sets", formatter_class=formatter_class())
    s = sub.add_parser("show", help="print the prose for a set (the default)",
                       formatter_class=formatter_class())
    s.add_argument("--set", dest="set_name", metavar="NAME", default=None,
                   help="which set (default: the latest)")
    s.add_argument("--lang", metavar="CODES", default=None,
                   help="comma-separated language codes, regional variants "
                        "such as fr-CA included, or all (default: English "
                        "and the configured language)")
    s.add_argument("--place", metavar="NAME", action="append", default=[],
                   help="only places whose name contains NAME; repeatable")
    s.add_argument("--data", action="store_true", help="the hours and days under each place")
    s.add_argument("--trace", action="store_true",
                   help="every candidate sentence with its salience, * if it was chosen")
    s.add_argument("--width", type=int, default=None, help="wrap width (default: the terminal's)")
    s.add_argument("--save", metavar="FILE", default=None, help="write the paragraphs as JSON")
    s.add_argument("--diff", metavar="FILE", default=None,
                   help="print only paragraphs that differ from a saved FILE, instead of the set")
    return p


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0].startswith("-") and argv[0] not in ("-h", "--help", "--version"):
        argv.insert(0, "show")
    args = prose_parser().parse_args(argv)

    if args.action == "fetch":
        name = args.set_name or datetime.now().strftime("%Y-%m-%d")
        count = fetch_set(name)
        print(f"{count} places frozen as {name} in {sets_root() / name}")
        return
    if args.action == "sets":
        for name in list_sets():
            print(name)
        return

    names = list_sets()
    if not names:
        raise SystemExit("linecast prose: no sets yet; run `linecast prose fetch`")
    name = args.set_name or names[-1]
    if name not in names:
        raise SystemExit(f"linecast prose: no set named {name}; have {', '.join(names)}")
    records = load_set(name)
    if args.place:
        wanted = [p.lower() for p in args.place]
        records = [r for r in records if any(w in r["name"].lower() for w in wanted)]
    langs = languages(args.lang)
    width = args.width
    if width is None:
        from linecast._graphics import get_terminal_size
        width = min(100, get_terminal_size()[0])

    if args.diff:
        before = json.loads(open(args.diff).read())
        from io import StringIO
        said = show(records, langs, width, out=StringIO())
        lines = diff_lines(before.get("paragraphs", before), said)
        print("\n".join(lines) if lines else "no change")
        return

    said = show(records, langs, width, data=args.data, trace=args.trace)
    if args.save:
        with open(args.save, "w") as f:
            json.dump({"set": name, "languages": langs, "paragraphs": said}, f,
                      ensure_ascii=False, indent=1)
        print(f"saved {args.save}", file=sys.stderr)


if __name__ == "__main__":
    main()
