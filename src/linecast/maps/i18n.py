"""Localized UI strings for the maps view.

Every key is present in every language, in the same order, so a missing
translation shows up as a diff rather than as an English word on a
French screen.  `ms()` still falls back per key, which means a partial
table degrades instead of crashing.

Two things are deliberately never translated: placenames (the data's
own, per the existing policy) and unit symbols (`m km ft mi`, and the
`h`/`m` of a duration) — matching the elevation readout.  Attribution
strings are proper names and data credits, so they live in the modules
that own the data, not here.
"""

from linecast._i18n import LocaleTable, lookup

_STRINGS = LocaleTable("MAPS")


def ms(key, lang, **kwargs):
    """Maps UI string for `lang`, falling back to English."""
    return lookup(_STRINGS, key, lang, **kwargs)
