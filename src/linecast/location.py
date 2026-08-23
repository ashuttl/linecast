"""Show or set a fixed location that overrides IP geolocation.

Usage: linecast location [show]
       linecast location set <place | lat,lng>
       linecast location auto
       linecast location search <query>

Precedence for every command: --location flag > WEATHER_LOCATION env >
saved location (this command) > IP geolocation.
"""

import argparse
import sys

from linecast._runtime import VersionAction
from linecast._config import read_config, write_config, saved_location


def _parse_latlng(text):
    """Parse 'lat,lng' into floats, or return None if it isn't one."""
    parts = text.split(",")
    if len(parts) != 2:
        return None
    try:
        return float(parts[0]), float(parts[1])
    except ValueError:
        return None


def _cmd_show():
    loc = saved_location()
    if loc is None:
        print("auto (IP geolocation)")
        return
    label = loc.get("label") or f"{loc['lat']:.4f},{loc['lng']:.4f}"
    print(f"{label}  ({loc['lat']:.4f},{loc['lng']:.4f})  [fixed]")
    print("Run 'linecast location auto' to return to IP geolocation.")


def _cmd_set(query):
    from linecast._weather_sources import _geocode_query, _reverse_geocode

    latlng = _parse_latlng(query)
    if latlng is not None:
        lat, lng = latlng
        name, country, _addr = _reverse_geocode(lat, lng)
        label = name or f"{lat:.4f},{lng:.4f}"
    else:
        results = _geocode_query(query)
        if not results:
            print(f'No locations matching "{query}".', file=sys.stderr)
            sys.exit(1)
        r = results[0]
        lat, lng = r.get("latitude", 0), r.get("longitude", 0)
        parts = [r.get("name", "")]
        if r.get("admin1"):
            parts.append(r["admin1"])
        if r.get("country"):
            parts.append(r["country"])
        label = ", ".join(parts)
        country = (r.get("country_code") or "").upper()

    config = read_config()
    config["location"] = {"lat": lat, "lng": lng, "label": label, "country": country}
    write_config(config)
    print(f"Location set to {label} ({lat:.4f},{lng:.4f})")


def _cmd_auto():
    config = read_config()
    if config.pop("location", None) is not None:
        write_config(config)
    print("Location set to auto (IP geolocation)")


def _cmd_search(query):
    from linecast._weather_sources import _search_locations

    _search_locations(query)


def main():
    parser = argparse.ArgumentParser(
        prog="linecast location",
        description="Show or set a fixed location that overrides IP geolocation",
    )
    parser.add_argument("--version", action=VersionAction)
    sub = parser.add_subparsers(dest="action")
    sub.add_parser("show", help="show the current location setting (default)")
    p_set = sub.add_parser("set", help="save a fixed location")
    p_set.add_argument("query", help="place name or 'lat,lng'")
    sub.add_parser("auto", help="clear the fixed location and use IP geolocation")
    p_search = sub.add_parser("search", help="list places matching a query")
    p_search.add_argument("query")
    args = parser.parse_args()

    if args.action == "set":
        _cmd_set(args.query)
    elif args.action == "auto":
        _cmd_auto()
    elif args.action == "search":
        _cmd_search(args.query)
    else:
        _cmd_show()


if __name__ == "__main__":
    main()
