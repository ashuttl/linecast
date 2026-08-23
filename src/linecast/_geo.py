"""Shared geospatial helpers."""

import math


def wrap_lon(lon):
    """`lon` folded into [-180, 180] by one turn of the planet.

    One step either way, not a modulo: the callers hand over a
    longitude at most a turn out of range, and 180.0 stays 180.0.
    """
    if lon > 180.0:
        return lon - 360.0
    if lon < -180.0:
        return lon + 360.0
    return lon


def haversine_nm(lat1, lon1, lat2, lon2):
    """Distance in nautical miles between two points."""
    earth_radius_nm = 3440.065
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return earth_radius_nm * 2 * math.asin(math.sqrt(a))
