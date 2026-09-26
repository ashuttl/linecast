"""Localized UI strings for the radar view."""

from linecast._i18n import LocaleTable, lookup

_STRINGS = LocaleTable("RADAR")


def rs(key, lang, **kwargs):
    """Radar UI string for `lang`, falling back to English."""
    return lookup(_STRINGS, key, lang, **kwargs)
