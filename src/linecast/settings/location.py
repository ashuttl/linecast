"""Show or set a fixed location that overrides IP geolocation.

Usage: linecast location [show]
       linecast location [set] <place | lat,lng>
       linecast location auto
       linecast location search <query>

Precedence for every command: --location flag > WEATHER_LOCATION env >
saved location (this command) > IP geolocation.
"""

import sys

from linecast._commands import formatter_class, parser_class
from linecast._parsers import VersionAction
from linecast._config import saved_location
from linecast._log import UserError, exits_on_user_error
from linecast.settings._command import forget, remember


def _parse_latlng(text):
    """Parse 'lat,lng' into floats, or return None if it isn't one."""
    from linecast._location import parse_latlng
    return parse_latlng(text)


def _cmd_show():
    loc = saved_location()
    if loc is None:
        print("auto (IP geolocation)")
        return
    label = loc.get("label") or f"{loc['lat']:.4f},{loc['lng']:.4f}"
    print(f"{label}  ({loc['lat']:.4f},{loc['lng']:.4f})  [fixed]")
    print("Run 'linecast location auto' to return to IP geolocation.")


def _cmd_set(query):
    from linecast._geocode import (
        GeocoderUnavailable, geocode, result_label, reverse_geocode,
    )

    latlng = _parse_latlng(query)
    if latlng is not None:
        lat, lng = latlng
        name, country, _addr = reverse_geocode(lat, lng)
        label = name or f"{lat:.4f},{lng:.4f}"
        lang = ""   # Nominatim's name in the place's own language
    else:
        try:
            results = geocode(query)
        except GeocoderUnavailable as exc:
            raise UserError(f"Search failed: {exc}") from exc
        if not results:
            from linecast._location import not_found
            raise UserError(not_found(query))
        r = results[0]
        lat, lng = r.get("latitude", 0), r.get("longitude", 0)
        label = result_label(r)
        country = (r.get("country_code") or "").upper()
        lang = "en"

    remember("location", {"lat": lat, "lng": lng, "label": label, "country": country,
                          "lang": lang})
    print(f"Location set to {label} ({lat:.4f},{lng:.4f})")


def _cmd_auto():
    forget("location")
    print("Location set to auto (IP geolocation)")


def _cmd_search(query):
    from linecast._geocode import print_search

    print_search(query)


_ACTIONS = ("show", "set", "auto", "search")


@exits_on_user_error
def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    # A place by itself is a place to set, as `linecast units metric`
    # sets the units: `linecast location Kyoto` was an error.
    if argv and argv[0] not in _ACTIONS and (not argv[0].startswith("-")
                                             or _parse_latlng(argv[0])):
        argv.insert(0, "set")
    parser = parser_class()(
        prog="linecast location",
        usage="%(prog)s [show | [set] PLACE | auto | search QUERY]",
        description="Show or set a fixed location that overrides IP geolocation",
        formatter_class=formatter_class(),
    )
    parser.add_argument("--version", action=VersionAction)
    sub = parser.add_subparsers(dest="action")
    sub.add_parser("show", help="show the current location setting (default)")
    p_set = sub.add_parser("set", help="save a fixed location")
    # the words of a name unquoted are the name: set Portland Maine
    p_set.add_argument("query", metavar="PLACE", nargs="+", help="place name or 'lat,lng'")
    sub.add_parser("auto", help="clear the fixed location and use IP geolocation")
    p_search = sub.add_parser("search", help="list places matching a query")
    p_search.add_argument("query", metavar="QUERY", nargs="+", help="part of a place name")
    args = parser.parse_args(argv)

    if args.action == "set":
        _cmd_set(" ".join(args.query))
    elif args.action == "auto":
        _cmd_auto()
    elif args.action == "search":
        _cmd_search(" ".join(args.query))
    else:
        _cmd_show()


if __name__ == "__main__":
    main()
