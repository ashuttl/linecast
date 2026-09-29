"""Tides localization strings."""

from linecast._i18n import LocaleTable, lang_of, lookup

_TIDES_STRINGS = LocaleTable("TIDES")



def _ts(key, runtime, **kwargs):
    """Look up a tides-specific localized string."""
    return lookup(_TIDES_STRINGS, key, lang_of(runtime), **kwargs)
