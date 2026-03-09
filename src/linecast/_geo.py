"""Shared geospatial helpers."""

import math


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
