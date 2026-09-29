"""Localized UI strings for the radar view."""

from linecast._geo import octant
from linecast._i18n import LocaleTable, lookup

_STRINGS = LocaleTable("RADAR")


def rs(key, lang, **kwargs):
    """Radar UI string for `lang`, falling back to English."""
    return lookup(_STRINGS, key, lang, **kwargs)


def compass_point(bearing, lang):
    """The nearest of the eight compass points to *bearing*, as the
    language abbreviates it: N, NE, E, ... in English, 北, 北東 ... in
    Japanese.  The words are radar's table's; the sky, the moon and the
    tides' swell name directions by them too."""
    return rs("compass", lang).split()[octant(bearing)]
